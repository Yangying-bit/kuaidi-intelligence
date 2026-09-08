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

st.title("👁️‍🗨️ 寄件API与SaaS竞对情报 - DeepSeek 驱动")

if df.empty:
    st.info("系统正在收集中... 请确保后台 crawler_engine.py 正在运行，并已正确配置 DeepSeek API Key。")
else:
    # --- 顶栏指标 ---
    now = datetime.now()
    two_hours_ago = now - timedelta(hours=2)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    new_last_2h = df[df['crawl_timestamp'] >= two_hours_ago].shape[0]
    new_today = df[df['crawl_timestamp'] >= today_start].shape[0]
    high_threats = df[df['ai_score'] >= 7].shape[0]  # AI 评估大于等于7分的定为高危

    col1, col2, col3 = st.columns(3)
    col1.metric("🔥 过去2小时新增", f"{new_last_2h} 条")
    col2.metric("📅 今日累计抓取", f"{new_today} 条")
    col3.metric("🚨 历史高危预警 (AI评估>7分)", f"{high_threats} 条")

    st.markdown("---")

    # --- 过滤器 ---
    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        date_list = sorted(df['crawl_timestamp'].dt.date.unique(), reverse=True)
        selected_date = st.selectbox("📅 查看日期", date_list)
    with col_filter2:
        comp_list = df['competitor'].unique().tolist()
        selected_comp = st.multiselect("🎯 筛选竞对", comp_list, default=comp_list)

    filtered_df = df[
        (df['crawl_timestamp'].dt.date == selected_date) &
        (df['competitor'].isin(selected_comp))
        ]

    # --- 呈现实时情报流 ---
    st.subheader(f"情报动态 ({len(filtered_df)} 条)")

    for index, row in filtered_df.iterrows():
        # 根据 AI 打分决定卡片的颜色提示
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

            # 使用折叠面板展示 AI 深度分析，保持页面清爽
            with st.expander("🤖 查看 DeepSeek 深度分析与应对策略"):
                st.markdown(f"**原资讯摘要：** {row['snippet']}")
                st.markdown(f"**🧠 业务影响分析：** {row['ai_analysis']}")
                st.markdown(f"**💡 应对建议：** {row['ai_suggestion']}")