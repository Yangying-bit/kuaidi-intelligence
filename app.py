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
    st.subheader("描述统计")
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.markdown("**🎯 竞对活跃度排行**")
        comp_counts = df['competitor'].value_counts()
        # 🌟 统一左侧高度：强制设为 380 像素
        st.bar_chart(comp_counts, height=380)

    # 🌟 1. 记忆胶囊：初始化状态变量
    if 'selected_biz' not in st.session_state:
        st.session_state.selected_biz = None

    with col_chart2:
        # ==========================================
        # 状态 A：全局热力大盘
        # ==========================================
        if st.session_state.selected_biz is None:
            st.markdown("**🏷️ 业务焦点热力分布 (🖱️点击色块进入专场)**")
            
            biz_df = df['business'].value_counts().reset_index()
            biz_df.columns = ['业务模块', '频次']
            
            if not biz_df.empty:
                import plotly.express as px
                fig = px.treemap(
                    biz_df, path=['业务模块'], values='频次', color='频次', color_continuous_scale='Blues'
                )
                
                fig.update_layout(
                    height=380, 
                    margin=dict(t=0, l=0, r=0, b=0),
                    paper_bgcolor='#FFFFFF',        
                    plot_bgcolor='#FFFFFF',         
                )
                fig.update_coloraxes(showscale=False)
                fig.update_traces(tiling=dict(pad=0), marker=dict(line=dict(color='white', width=2)))
                
                event = st.plotly_chart(
                    fig, use_container_width=True, theme=None, on_select="rerun", selection_mode="points", key="treemap_chart"
                )
                
                # 🌟 治愈卡顿核心：防重复刷新锁
                if isinstance(event, dict) and "selection" in event:
                    points = event["selection"].get("points", [])
                    if points:
                        new_biz = points[0].get("label")
                        # 只有当确实点了一个新的色块时，才允许系统刷新
                        if st.session_state.selected_biz != new_biz:
                            st.session_state.selected_biz = new_biz
                            st.rerun() 
            else:
                st.info("暂无业务数据构成热力图")

        # ==========================================
        # 状态 B：原位翻转专属柱状图
        # ==========================================
        else:
            selected = st.session_state.selected_biz
            
            # 微型导航栏
            col_title, col_btn = st.columns([0.8, 0.2])
            with col_title:
                st.markdown(f"🎯 **【{selected}】** 竞对火力分布")
            with col_btn:
                if st.button("🔙 返回", use_container_width=True):
                    st.session_state.selected_biz = None 
                    st.rerun() 
                    
            sub_df = df[df['business'] == selected]['competitor'].value_counts().reset_index()
            sub_df.columns = ['竞对', '数量']
            
            if not sub_df.empty:
                import plotly.express as px
                fig_bar = px.bar(sub_df, x='竞对', y='数量', text='数量')
                
                # 🌟 修复文字腰斩问题
                fig_bar.update_layout(
                    height=325,
                    # 把底部边距 (b) 从 10 猛增到 40，让文字完全露出来
                    margin=dict(t=20, l=10, r=10, b=40), 
                    paper_bgcolor='#9FC5E8', 
                    plot_bgcolor='#9FC5E8',
                    xaxis=dict(
                        showgrid=False, 
                        title=None, 
                        # 字体加大加粗，看着更清晰
                        tickfont=dict(color='#0B3C6A', size=15, weight='bold')
                    ),
                    yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.4)', title=None, showticklabels=False)
                )
                
                # 🌟 解决巨无霸粗柱子问题：智能瘦身
                # 如果只有 1 家竞对，强制柱子宽度缩减到 0.3；如果有两家以上，宽度设为 0.5
                bar_width = 0.3 if len(sub_df) == 1 else 0.5
                
                fig_bar.update_traces(
                    marker_color='#0B3C6A',
                    textposition='outside', 
                    textfont=dict(color='#0B3C6A', size=16, weight='bold'),
                    width=bar_width  # 强制生效瘦身比例
                )
                
                st.plotly_chart(fig_bar, use_container_width=True, theme=None)
            else:
                st.info("暂无明细数据")
            
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
