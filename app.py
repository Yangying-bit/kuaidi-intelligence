import streamlit as st
import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="寄件业务情报与AI分析大盘", layout="wide")

current_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(current_dir, "intelligence.db")


@st.cache_data(ttl=60)
def load_data():
    if not os.path.exists(db_path): return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    # 读取包含 AI 分析结果的新表 news_v2
    df = pd.read_sql_query("SELECT * FROM news_v2 ORDER BY crawl_timestamp DESC", conn)
    conn.close()
    if not df.empty:
        df['crawl_timestamp'] = pd.to_datetime(df['crawl_timestamp'])
    return df


df = load_data()

# 按照时间倒序排列（最新时间排在最上面）
if not df.empty:
    # 🌟 修复时间倒置 Bug：用正则强行提取标题里的业务真实日期 (如 2026-02-06)
    df['real_date'] = df['title'].str.extract(r'(\d{4}-\d{2}-\d{2})')[0]
    
    # 如果有的新闻标题没写日期，就用系统的抓取时间兜底
    df['real_date'] = df['real_date'].fillna(df['crawl_timestamp'].dt.strftime('%Y-%m-%d'))
    
    # 双重排序魔法：先按【真实日期】倒序，如果同一天，再按【抓取时间】倒序
    df = df.sort_values(by=['real_date', 'crawl_timestamp'], ascending=[False, False]).reset_index(drop=True)

st.title("👁️‍🗨️行业竞对情报——DeepSeek驱动分析")

if df.empty:
    st.info("系统正在收集中... 请确保后台 crawler_engine.py 正在运行，并已正确配置 DeepSeek API Key。")
else:
    # --- 顶栏指标 ---
    now = datetime.now()
    two_hours_ago = now - timedelta(hours=2)  # 如果你之前把 GitHub Actions 改成了3小时，这里也可以改成3
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    new_last_2h = df[df['crawl_timestamp'] >= two_hours_ago].shape[0]
    new_today = df[df['crawl_timestamp'] >= today_start].shape[0]
    high_threats = df[df['ai_score'] >= 7].shape[0]  # AI 评估大于等于7分的定为高危
    total_count = df.shape[0]  # 历史总数据量

    # 🌟 修改点 1：扩展为 4 列，加上历史总数
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔥 过去2小时新增", f"{new_last_2h} 条")
    col2.metric("📅 今日累计抓取", f"{new_today} 条")
    col3.metric("🚨 历史高危预警 (AI评估>7分)", f"{high_threats} 条")
    col4.metric("📚 历史情报总库", f"{total_count} 条")

    st.markdown("---")

    # 🌟 修改点 2：新增数据量化统计图表模块
    # =====================================================================
    # 状态机初始化：用于控制右侧图表的“下钻 (Drill-down)”状态
    # =====================================================================
    if 'drilldown_keyword' not in st.session_state:
        st.session_state.drilldown_keyword = None

    # 提前拦截 Plotly 的原生点击事件，实现 0 延迟无缝翻转
    if "treemap_selection" in st.session_state:
        pts = st.session_state["treemap_selection"].get("selection", {}).get("points", [])
        if pts:
            # 捕获用户点击的关键词
            clicked_keyword = pts[0].get("label")
            # 只有点击了不同关键词才更新状态
            if st.session_state.drilldown_keyword != clicked_keyword:
                st.session_state.drilldown_keyword = clicked_keyword

    # 布局：左右两列
    st.subheader("描述统计")
    col_chart1, col_chart2 = st.columns(2)

    # =====================================================================
    # 左侧：🎯 竞对活跃度排行 (保持全局统一样式)
    # =====================================================================
    with col_chart1:
        st.markdown("**🎯 竞对活跃度排行**")
        comp_counts = df['competitor'].value_counts().reset_index()
        comp_counts.columns = ['竞对', '活跃度']
        
        if not comp_counts.empty:
            import plotly.express as px
            # 为了联动视觉，左侧也统一使用 Plotly 渲染并采用同样的商务蓝
            fig_left = px.bar(comp_counts, x='竞对', y='活跃度', text='活跃度')
            fig_left.update_layout(
                height=380,  # 统一绝对高度
                margin=dict(t=20, l=10, r=10, b=30),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, title=None, tickfont=dict(color='#333333', size=13)),
                yaxis=dict(showgrid=True, gridcolor='#F0F2F6', title=None, showticklabels=False)
            )
            fig_left.update_traces(
                marker_color='#1E88E5', # 统一的科技商务蓝
                textposition='outside', 
                textfont=dict(color='#1E88E5', size=13, weight='bold'),
                width=0.4
            )
            st.plotly_chart(fig_left, use_container_width=True, theme=None)
        else:
            st.info("暂无竞对活跃度数据")

    # =====================================================================
    # 右侧：热力图 与 下钻柱状图 的平滑切换逻辑
    # =====================================================================
    with col_chart2:
        
        # -----------------------------------------------------------
        # 状态 A：默认总览状态 (显示业务焦点热力图)
        # -----------------------------------------------------------
        if st.session_state.drilldown_keyword is None:
            # 标题 + 弱提示
            st.markdown(
                "**🏷️ 业务焦点热力分布** <span style='font-size:12px; color:#888888; font-weight:normal; margin-left:8px;'>点击关键词查看竞对分布 →</span>", 
                unsafe_allow_html=True
            )
            
            biz_df = df['business'].value_counts().reset_index()
            biz_df.columns = ['业务模块', '频次']
            
            if not biz_df.empty:
                import plotly.express as px
                fig_tree = px.treemap(
                    biz_df, 
                    path=['业务模块'], 
                    values='频次', 
                    color='频次', 
                    color_continuous_scale='Blues' # 保持蓝色主题
                )
                fig_tree.update_layout(
                    height=380,  # 与左侧严格对齐
                    margin=dict(t=10, l=0, r=0, b=0),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)'
                )
                fig_tree.update_coloraxes(showscale=False)
                fig_tree.update_traces(
                    tiling=dict(pad=0), 
                    marker=dict(line=dict(color='#FFFFFF', width=2))
                )
                
                # 绑定 key 用于捕获点击事件
                st.plotly_chart(
                    fig_tree, 
                    use_container_width=True, 
                    theme=None, 
                    on_select="rerun", 
                    selection_mode="points", 
                    key="treemap_selection"
                )
            else:
                st.info("暂无业务数据构成热力图")

        # -----------------------------------------------------------
        # 状态 B：下钻状态 (显示该关键词的竞对分布)
        # -----------------------------------------------------------
        else:
            keyword = st.session_state.drilldown_keyword
            
            # 使用列布局实现轻量级的返回按钮与标题同行
            c_back, c_title = st.columns([0.25, 0.75])
            with c_back:
                # 轻量级返回按钮
                if st.button("← 返回热力图", use_container_width=True):
                    st.session_state.drilldown_keyword = None
                    st.rerun() # 瞬间复原
            with c_title:
                st.markdown(
                    f"<div style='padding-top:4px;'><b>{keyword} · 竞对分布</b> <span style='font-size:12px; color:#888888; font-weight:normal; margin-left:8px;'>关键词关联竞对排行</span></div>", 
                    unsafe_allow_html=True
                )
                
            # 获取当前关键词对应的数据
            sub_df = df[df['business'] == keyword]['competitor'].value_counts().reset_index()
            sub_df.columns = ['竞对', '数量']
            
            if not sub_df.empty:
                # 注意：Plotly 的水平柱状图是从下往上画的，所以要升序排列，这样最多的在最上面
                sub_df = sub_df.sort_values('数量', ascending=True) 
                
                import plotly.express as px
                # 核心设计：智能继承颜色。利用 color='数量' 和 color_continuous_scale='Blues'，
                # 自动根据数值生成深蓝->浅蓝的渐变层次，摒弃杂乱色彩，保持极简商务风。
                fig_bar_h = px.bar(
                    sub_df, 
                    x='数量', 
                    y='竞对', 
                    orientation='h', # 水平柱状图
                    text='数量',
                    color='数量', 
                    color_continuous_scale='Blues'
                )
                
                # 为了与左图 380px 高度完美对齐，需减去上方按钮/标题占据的大约 45px
                fig_bar_h.update_layout(
                    height=335, 
                    margin=dict(t=10, l=10, r=30, b=10),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(showgrid=False, showticklabels=False, title=None), # 隐藏X轴，保持干净
                    yaxis=dict(showgrid=False, title=None, tickfont=dict(color='#333333', size=13, weight='bold'))
                )
                fig_bar_h.update_coloraxes(showscale=False) # 隐藏右侧多余的渐变色条
                
                # 调整柱子数值标签位置与柱子粗细
                bar_width = 0.4 if len(sub_df) < 3 else 0.6
                fig_bar_h.update_traces(
                    textposition='outside', 
                    textfont=dict(size=13, weight='bold', color='#1E88E5'),
                    width=bar_width
                )
                
                st.plotly_chart(fig_bar_h, use_container_width=True, theme=None)
            else:
                st.info(f"暂无【{keyword}】相关的竞对数据")
            
    st.markdown("---")

    # --- 过滤器 (扩展为三列，新增影响程度筛选) ---
    col_filter1, col_filter2, col_filter3 = st.columns(3)
    with col_filter1:
        date_list = sorted(df['crawl_timestamp'].dt.date.unique(), reverse=True)
        # 加上容错处理，防止 date_list 为空时报错
        selected_date = st.selectbox("📅 查看日期", date_list) if date_list else None
    with col_filter2:
        comp_list = df['competitor'].unique().tolist()
        selected_comp = st.multiselect("🎯 筛选竞对", comp_list, default=comp_list)
    with col_filter3:
        # 新增：与下方 UI 匹配的标签筛选器
        risk_labels = ["🔴 重大影响 (8-10分)", "🟡 值得关注 (5-7分)", "🟢 影响较小 (1-4分)"]
        selected_risks = st.multiselect("⚠️ 影响程度筛选", risk_labels, default=risk_labels)

    # --- 动态构建分数过滤逻辑 ---
    allowed_scores = []
    if "🔴 重大影响 (8-10分)" in selected_risks:
        allowed_scores.extend([8, 9, 10])
    if "🟡 值得关注 (5-7分)" in selected_risks:
        allowed_scores.extend([5, 6, 7])
    if "🟢 影响较小 (1-4分)" in selected_risks:
        allowed_scores.extend([0, 1, 2, 3, 4])  # 包含0分(兜底解析失败的)

    # 组合多重过滤条件
    if selected_date:
        filtered_df = df[
            (df['crawl_timestamp'].dt.date == selected_date) &
            (df['competitor'].isin(selected_comp)) &
            (df['ai_score'].isin(allowed_scores))
        ]
    else:
        filtered_df = pd.DataFrame()

    # ==========================================
    # 🌟 核心修改区：封装卡片渲染函数
    # ==========================================
    def render_news_card(row):
        """将单条新闻渲染为 UI 卡片"""
        score = row.get('ai_score', 0)
        if score >= 8:
            status = "🔴 重大影响"
        elif score >= 5:
            status = "🟡 值得关注"
        else:
            status = "🟢 影响较小"

        with st.container(border=True):
            st.markdown(f"**【{row['competitor']} - {row['business']}】** [{row['title']}]({row['url']})")
            st.caption(f"发现时间: {row['publish_time']} | 影响评估: {status} ({score}/10)")

            with st.expander("查看 DeepSeek 深度分析与应对策略"):
                st.markdown(f"**AI资讯总结：** {row['snippet']}")
                st.markdown(f"**🧠 业务影响分析：** {row['ai_analysis']}")
                st.markdown(f"**💡 应对建议：** {row['ai_suggestion']}")

    # ==========================================
    # 🌟 核心修改区：Tabs 标签页布局
    # ==========================================
    st.markdown("### 📡 实时情报")
    
    if not filtered_df.empty:
        # 数据分离：划分为“快递鸟”和“其他竞对”
        kdniao_df = filtered_df[filtered_df['competitor'] == '快递鸟']
        other_df = filtered_df[filtered_df['competitor'] != '快递鸟']

        # 构建并排的标签页
        tab1, tab2 = st.tabs([
            f"🦅 快递鸟相关情报 ({len(kdniao_df)} 条)", 
            f"🌐 行业综合情报 ({len(other_df)} 条)"
        ])

        # 渲染快递鸟专属板块
        with tab1:
            if kdniao_df.empty:
                st.info("在当前筛选条件下，暂无快递鸟的情报。")
            else:
                for index, row in kdniao_df.iterrows():
                    render_news_card(row)

        # 渲染其他竞对综合板块
        with tab2:
            if other_df.empty:
                st.info("在当前筛选条件下，暂无其他同行的情报。")
            else:
                for index, row in other_df.iterrows():
                    render_news_card(row)
    else:
        st.warning("当前筛选条件下无数据，请尝试调整上方的日期或影响程度过滤器。")
