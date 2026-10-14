import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from supabase import create_client, Client

st.set_page_config(page_title="寄件业务情报与AI分析大盘", layout="wide")

# ==========================================
# 🌟 初始化 Supabase 云数据库连接
# ==========================================
# 注意：部署到 Streamlit Cloud 时，需在后台 Secrets 填入这两个环境变量
try:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("⚠️ 未检测到 Supabase 环境变量，请在部署平台配置 SUPABASE_URL 和 SUPABASE_KEY。")
    st.stop()

# ==========================================
# 🌟 数据加载与操作逻辑 (直连云端)
# ==========================================
@st.cache_data(ttl=60)
def load_data():
    """只读取 AI 已经分析完毕 (process_status=1) 且未被拉黑的数据"""
    try:
        response = supabase.table("news_v2").select("*").eq("process_status", 1).order("crawl_timestamp", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['crawl_timestamp'] = pd.to_datetime(df['crawl_timestamp'])
        return df
    except Exception as e:
        st.error(f"数据库连接异常: {e}")
        return pd.DataFrame()

def delete_news(record_id):
    """软删除：将数据的处理状态设为 -1 (拉黑隐藏)"""
    try:
        supabase.table("news_v2").update({"process_status": -1}).eq("id", record_id).execute()
        load_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"删除失败: {e}")

df = load_data()

# 按照时间倒序排列（最新时间排在最上面）
if not df.empty:
    df['real_date'] = df['title'].str.extract(r'(\d{4}-\d{2}-\d{2})')[0]
    df['real_date'] = df['real_date'].fillna(df['crawl_timestamp'].dt.strftime('%Y-%m-%d'))
    df = df.sort_values(by=['real_date', 'crawl_timestamp'], ascending=[False, False]).reset_index(drop=True)

st.title("👁️‍🗨️行业竞对情报——DeepSeek驱动分析")

if df.empty:
    st.info("系统正在收集中... 或所有数据正处于待分析队列。请确保后台 GitHub Actions 任务正常运行。")
else:
    # --- 顶栏指标 ---
    now = datetime.now()
    two_hours_ago = now - timedelta(hours=2)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    new_last_2h = df[df['crawl_timestamp'] >= two_hours_ago].shape[0]
    new_today = df[df['crawl_timestamp'] >= today_start].shape[0]
    high_threats = df[df['ai_score'] >= 7].shape[0]
    total_count = df.shape[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔥 过去2小时新增", f"{new_last_2h} 条")
    col2.metric("📅 今日累计分析", f"{new_today} 条")
    col3.metric("🚨 历史高危预警 (AI评估>7分)", f"{high_threats} 条")
    col4.metric("📚 有效情报总库", f"{total_count} 条")

    st.markdown("---")

    # =====================================================================
    # 状态机初始化与图表渲染
    # =====================================================================
    if 'drilldown_keyword' not in st.session_state:
        st.session_state.drilldown_keyword = None

    if "treemap_selection" in st.session_state:
        pts = st.session_state["treemap_selection"].get("selection", {}).get("points", [])
        if pts:
            clicked_keyword = pts[0].get("label")
            if st.session_state.drilldown_keyword != clicked_keyword:
                st.session_state.drilldown_keyword = clicked_keyword

    st.subheader("描述统计")
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.markdown("**🎯 竞对活跃度排行**")
        comp_counts = df['competitor'].value_counts().reset_index()
        comp_counts.columns = ['竞对', '活跃度']
        
        if not comp_counts.empty:
            import plotly.express as px
            fig_left = px.bar(comp_counts, x='竞对', y='活跃度', text='活跃度')
            fig_left.update_layout(
                height=380,  
                margin=dict(t=20, l=10, r=10, b=30),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, title=None, tickfont=dict(color='#333333', size=13)),
                yaxis=dict(showgrid=True, gridcolor='#F0F2F6', title=None, showticklabels=False)
            )
            fig_left.update_traces(
                marker_color='#1E88E5', 
                textposition='outside', 
                textfont=dict(color='#1E88E5', size=13, weight='bold'),
                width=0.4
            )
            st.plotly_chart(fig_left, use_container_width=True, theme=None)

    with col_chart2:
        if st.session_state.drilldown_keyword is None:
            st.markdown(
                "**🏷️ 业务焦点热力分布** <span style='font-size:12px; color:#888888; font-weight:normal; margin-left:8px;'>点击关键词查看竞对分布 →</span>", 
                unsafe_allow_html=True
            )
            
            biz_df = df['business'].value_counts().reset_index()
            biz_df.columns = ['业务模块', '频次']
            
            if not biz_df.empty:
                import plotly.express as px
                fig_tree = px.treemap(
                    biz_df, path=['业务模块'], values='频次', color='频次', color_continuous_scale='Blues' 
                )
                fig_tree.update_layout(height=380, margin=dict(t=10, l=0, r=0, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                fig_tree.update_coloraxes(showscale=False)
                fig_tree.update_traces(tiling=dict(pad=0), marker=dict(line=dict(color='#FFFFFF', width=2)))
                st.plotly_chart(fig_tree, use_container_width=True, theme=None, on_select="rerun", selection_mode="points", key="treemap_selection")
        else:
            keyword = st.session_state.drilldown_keyword
            c_back, c_title = st.columns([0.25, 0.75])
            with c_back:
                if st.button("← 返回热力图", use_container_width=True):
                    st.session_state.drilldown_keyword = None
                    st.rerun() 
            with c_title:
                st.markdown(f"<div style='padding-top:4px;'><b>{keyword} · 竞对分布</b></div>", unsafe_allow_html=True)
                
            sub_df = df[df['business'] == keyword]['competitor'].value_counts().reset_index()
            sub_df.columns = ['竞对', '数量']
            if not sub_df.empty:
                sub_df = sub_df.sort_values('数量', ascending=True) 
                import plotly.express as px
                fig_bar_h = px.bar(sub_df, x='数量', y='竞对', orientation='h', text='数量', color='数量', color_continuous_scale='Blues')
                fig_bar_h.update_layout(height=335, margin=dict(t=10, l=80, r=30, b=10), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(showgrid=False, showticklabels=False, title=None), yaxis=dict(showgrid=False, title=None, automargin=True))
                fig_bar_h.update_coloraxes(showscale=False) 
                fig_bar_h.update_traces(textposition='outside', textfont=dict(size=13, weight='bold', color='#1E88E5'), width=0.4 if len(sub_df) < 3 else 0.6)
                st.plotly_chart(fig_bar_h, use_container_width=True, theme=None)
            
    st.markdown("---")

    # --- 过滤器 ---
    col_filter1, col_filter2, col_filter3 = st.columns(3)
    with col_filter1:
        date_list = sorted(df['crawl_timestamp'].dt.date.unique(), reverse=True)
        selected_date = st.selectbox("📅 查看日期", date_list) if date_list else None
    with col_filter2:
        comp_list = df['competitor'].unique().tolist()
        selected_comp = st.multiselect("🎯 筛选竞对", comp_list, default=comp_list)
    with col_filter3:
        risk_labels = ["🔴 重大影响 (8-10分)", "🟡 值得关注 (5-7分)", "🟢 影响较小 (1-4分)"]
        selected_risks = st.multiselect("⚠️ 影响程度筛选", risk_labels, default=risk_labels)

    allowed_scores = []
    if "🔴 重大影响 (8-10分)" in selected_risks: allowed_scores.extend([8, 9, 10])
    if "🟡 值得关注 (5-7分)" in selected_risks: allowed_scores.extend([5, 6, 7])
    if "🟢 影响较小 (1-4分)" in selected_risks: allowed_scores.extend([0, 1, 2, 3, 4])

    if selected_date:
        filtered_df = df[(df['crawl_timestamp'].dt.date == selected_date) & (df['competitor'].isin(selected_comp)) & (df['ai_score'].isin(allowed_scores))]
    else:
        filtered_df = pd.DataFrame()

    def render_news_card(row, tab_prefix=""):
        score = row.get('ai_score', 0)
        record_id = row['id']  
        
        status = "🔴 重大影响" if score >= 8 else "🟡 值得关注" if score >= 5 else "🟢 影响较小"

        with st.container(border=True):
            c_title, c_action = st.columns([0.85, 0.15])
            with c_title:
                st.markdown(f"**【{row['competitor']} - {row['business']}】** [{row['title']}]({row['url']})")
                st.caption(f"发现时间: {row['publish_time']} | 影响评估: {status} ({score}/10)")
            with c_action:
                if st.button("🗑️ 删除", key=f"del_{record_id}_{tab_prefix}"):
                    delete_news(record_id)

            with st.expander("查看 DeepSeek 深度分析与应对策略"):
                st.markdown(f"**AI资讯总结：** {row['snippet']}")
                st.markdown(f"**🧠 业务影响分析：** {row['ai_analysis']}")
                st.markdown(f"**💡 应对建议：** {row['ai_suggestion']}")

    st.markdown("### 📡 情报大盘视图")
    TECH_PLATFORMS = ["快递鸟", "菜鸟"]
    
    tech_df = filtered_df[filtered_df['competitor'].isin(TECH_PLATFORMS)] if not filtered_df.empty else pd.DataFrame()
    logistics_df = filtered_df[~filtered_df['competitor'].isin(TECH_PLATFORMS)] if not filtered_df.empty else pd.DataFrame()

    tab1, tab2, tab3 = st.tabs([f"🦅 聚合平台 ({len(tech_df)} 条)", f"📦 快递巨头 ({len(logistics_df)} 条)", "📅 全景复盘"])

    with tab1:
        if tech_df.empty: st.info("无相关数据。")
        else:
            for _, row in tech_df.iterrows(): render_news_card(row, "tab1")

    with tab2:
        if logistics_df.empty: st.info("无相关数据。")
        else:
            for _, row in logistics_df.iterrows(): render_news_card(row, "tab2")

    with tab3:
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        recent_7d_df = df[df['real_date'] >= seven_days_ago]
        if recent_7d_df.empty: st.info("无相关数据。")
        else:
            grouped = recent_7d_df.groupby('real_date')
            for i, (date_str, group) in enumerate(sorted(grouped, key=lambda x: x[0], reverse=True)):
                with st.expander(f"🗓️ 【{date_str}】 (共 {len(group)} 条)", expanded=(i == 0)):
                    for _, row in group.iterrows(): render_news_card(row, "tab3")
