import os
import logging
from datetime import datetime, timedelta, date
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
import plotly.express as px
from supabase import create_client, Client


# ============================================================
# 页面与日志
# ============================================================
st.set_page_config(page_title="寄件业务情报与AI分析大盘", layout="wide")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("industry_intel_dashboard")


# ============================================================
# Supabase 配置
# 兼容 Streamlit Cloud Secrets 和环境变量
# ============================================================
def read_config(name: str, default: str = "") -> str:
    value = ""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        pass

    if not value:
        try:
            nested = st.secrets.get("supabase", {})
            if isinstance(nested, dict):
                nested_key = {
                    "SUPABASE_URL": "url",
                    "SUPABASE_KEY": "key",
                    "SUPABASE_SERVICE_ROLE_KEY": "service_role_key",
                    "SUPABASE_ANON_KEY": "anon_key",
                }.get(name, name.lower())
                value = nested.get(nested_key, "")
        except Exception:
            pass

    if not value:
        value = os.environ.get(name, "")

    return str(value or default).strip().strip("'\"")


@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    url = read_config("SUPABASE_URL")
    # 优先沿用原项目中的 SUPABASE_KEY；也兼容常见的其他命名
    key = (
        read_config("SUPABASE_KEY")
        or read_config("SUPABASE_SERVICE_ROLE_KEY")
        or read_config("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "缺少 Supabase 配置。请在 Streamlit Cloud → Settings → Secrets 中配置 "
            "SUPABASE_URL 和 SUPABASE_KEY（或 SUPABASE_SERVICE_ROLE_KEY）。"
        )
    return create_client(url.rstrip("/"), key)


try:
    supabase: Client = get_supabase()
except Exception as exc:
    logger.exception("Supabase 客户端初始化失败")
    st.error("Supabase 初始化失败，请检查 Streamlit Cloud 的 Secrets 配置。")
    with st.expander("查看诊断信息"):
        st.code(f"{type(exc).__name__}: {exc}")
    st.stop()


# ============================================================
# 数据加载
# 通过 range 分页，避免 Supabase 单次返回条数上限导致历史情报缺失
# ============================================================
@st.cache_data(ttl=60, show_spinner="正在从 Supabase 加载全部已分析情报…")
def load_data() -> pd.DataFrame:
    page_size = 500
    start = 0
    all_rows: List[Dict[str, Any]] = []
    max_pages = 200  # 防止异常情况下出现无限循环；最多读取 100,000 条

    try:
        for _ in range(max_pages):
            response = (
                supabase.table("news_v2")
                .select("*")
                .eq("process_status", 1)
                .range(start, start + page_size - 1)
                .execute()
            )
            batch = response.data or []
            all_rows.extend(batch)

            if len(batch) < page_size:
                break
            start += page_size
        else:
            logger.warning("情报读取达到分页安全上限，已读取 %s 条", len(all_rows))

        df = pd.DataFrame(all_rows)
        if df.empty:
            return df

        # 兼容旧数据中可能缺少的字段，避免看板因单列缺失直接崩溃
        defaults = {
            "id": None,
            "competitor": "未分类竞对",
            "business": "未分类业务",
            "title": "无标题",
            "url": "",
            "publish_time": "",
            "snippet": "",
            "ai_score": None,
            "ai_analysis": "",
            "ai_suggestion": "",
            "crawl_timestamp": None,
        }
        for col, default_value in defaults.items():
            if col not in df.columns:
                df[col] = default_value

        # 统一评分类型
        df["ai_score"] = pd.to_numeric(df["ai_score"], errors="coerce")

        # 优先使用 crawl_timestamp；缺失时尝试从 publish_time 解析
        crawl_ts = pd.to_datetime(df["crawl_timestamp"], errors="coerce", utc=True)
        publish_ts = pd.to_datetime(df["publish_time"], errors="coerce", utc=True)
        crawl_ts = crawl_ts.fillna(publish_ts)
        df["crawl_timestamp"] = crawl_ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)

        # 标题中带日期时优先使用标题日期；否则使用时间字段
        title_date = df["title"].astype(str).str.extract(r"(\d{4}-\d{2}-\d{2})", expand=False)
        timestamp_date = df["crawl_timestamp"].dt.strftime("%Y-%m-%d")
        df["real_date"] = title_date.fillna(timestamp_date)
        df["real_date"] = pd.to_datetime(df["real_date"], errors="coerce").dt.date

        df["competitor"] = df["competitor"].fillna("未分类竞对").astype(str)
        df["business"] = df["business"].fillna("未分类业务").astype(str)
        df["title"] = df["title"].fillna("无标题").astype(str)

        df = df.sort_values(
            by=["real_date", "crawl_timestamp"],
            ascending=[False, False],
            na_position="last",
        ).reset_index(drop=True)
        return df

    except Exception as exc:
        logger.exception("读取 Supabase news_v2 表失败")
        # 不要把数据库错误伪装成“没有情报”，明确提示真实错误位置
        st.error("读取 Supabase 情报数据失败。当前错误发生在数据库查询阶段，不是筛选控件导致的。")
        with st.expander("展开 Supabase 错误详情（排查时请复制给开发者）", expanded=True):
            st.code(f"{type(exc).__name__}: {exc}")
            st.markdown(
                "请重点检查：`news_v2` 表是否存在、`process_status` 字段是否存在、"
                "当前 API Key 是否有 SELECT 权限，以及 Supabase 项目是否可访问。"
            )
        return pd.DataFrame()


def delete_news(record_id: Any) -> None:
    """软删除：将 process_status 设置为 -1。"""
    try:
        supabase.table("news_v2").update({"process_status": -1}).eq("id", record_id).execute()
        load_data.clear()
        st.success("该条情报已从看板隐藏。")
        st.rerun()
    except Exception as exc:
        logger.exception("删除情报失败，record_id=%s", record_id)
        st.error("删除失败，请检查数据库更新权限。")
        with st.expander("查看删除错误详情"):
            st.code(f"{type(exc).__name__}: {exc}")


# ============================================================
# 读取全量已分析数据
# ============================================================
df = load_data()
st.title("👁️‍🗨️ 行业竞对情报——DeepSeek 驱动分析")
st.caption("数据范围：Supabase news_v2 表中 process_status = 1 的已分析情报；列表支持跨分页全量筛选。")

if df.empty:
    st.info("目前没有读取到已分析情报。若数据库中确认已有数据，请展开上方错误详情检查 Supabase 查询权限、字段和连接配置。")
    st.stop()


# ============================================================
# 全量筛选区：所有图表、指标和情报列表统一使用 filtered_df
# ============================================================
st.subheader("🔎 全量情报筛选")

competitor_options = sorted(df["competitor"].dropna().unique().tolist())
business_options = sorted(df["business"].dropna().unique().tolist())

filter_row1_col1, filter_row1_col2, filter_row1_col3 = st.columns([1.1, 1.2, 1.2])
with filter_row1_col1:
    date_mode = st.selectbox(
        "📅 时间范围",
        ["全部日期", "今天", "近7天", "近30天", "近90天", "自定义"],
        index=0,
        key="filter_date_mode",
    )
with filter_row1_col2:
    selected_competitors = st.multiselect(
        "🎯 监控竞对",
        options=competitor_options,
        default=competitor_options,
        key="filter_competitors",
        placeholder="选择一个或多个竞对",
    )
with filter_row1_col3:
    selected_businesses = st.multiselect(
        "📦 业务模块",
        options=business_options,
        default=business_options,
        key="filter_businesses",
        placeholder="选择一个或多个业务模块",
    )

filter_row2_col1, filter_row2_col2 = st.columns([1.25, 2.0])
with filter_row2_col1:
    risk_options = [
        "🔴 重大影响（8–10分）",
        "🟡 值得关注（5–7分）",
        "🟢 影响较小（0–4分）",
        "⚪ 未评分",
    ]
    selected_risks = st.multiselect(
        "⚠️ 影响程度",
        options=risk_options,
        default=risk_options,
        key="filter_risks",
    )
with filter_row2_col2:
    keyword = st.text_input(
        "🔍 全文搜索",
        placeholder="输入产品名称、关键词或内容；搜索标题、摘要、正文、AI分析和建议",
        key="filter_keyword",
    )

custom_start = None
custom_end = None
if date_mode == "自定义":
    valid_dates = df["real_date"].dropna()
    min_date = valid_dates.min() if not valid_dates.empty else date.today()
    max_date = valid_dates.max() if not valid_dates.empty else date.today()
    date_col1, date_col2 = st.columns(2)
    with date_col1:
        custom_start = st.date_input("开始日期", value=min_date, min_value=min_date, max_value=max_date, key="filter_start_date")
    with date_col2:
        custom_end = st.date_input("结束日期", value=max_date, min_value=min_date, max_value=max_date, key="filter_end_date")

# 逐项筛选，保证所有模块复用同一个结果集
filtered_df = df.copy()
now_cn = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
today = now_cn.date()

if date_mode == "今天":
    filtered_df = filtered_df[filtered_df["real_date"] == today]
elif date_mode in ("近7天", "近30天", "近90天"):
    days = {"近7天": 7, "近30天": 30, "近90天": 90}[date_mode]
    start_day = today - timedelta(days=days - 1)
    filtered_df = filtered_df[filtered_df["real_date"].apply(lambda x: pd.notna(x) and x >= start_day)]
elif date_mode == "自定义" and custom_start and custom_end:
    if custom_start > custom_end:
        st.warning("开始日期不能晚于结束日期。")
        filtered_df = filtered_df.iloc[0:0]
    else:
        filtered_df = filtered_df[
            filtered_df["real_date"].apply(
                lambda x: pd.notna(x) and custom_start <= x <= custom_end
            )
        ]

if selected_competitors:
    filtered_df = filtered_df[filtered_df["competitor"].isin(selected_competitors)]
else:
    filtered_df = filtered_df.iloc[0:0]

if selected_businesses:
    filtered_df = filtered_df[filtered_df["business"].isin(selected_businesses)]
else:
    filtered_df = filtered_df.iloc[0:0]

score = filtered_df["ai_score"]
allowed_mask = pd.Series(False, index=filtered_df.index)
if "🔴 重大影响（8–10分）" in selected_risks:
    allowed_mask |= score.between(8, 10, inclusive="both")
if "🟡 值得关注（5–7分）" in selected_risks:
    allowed_mask |= score.between(5, 7, inclusive="both")
if "🟢 影响较小（0–4分）" in selected_risks:
    allowed_mask |= score.between(0, 4, inclusive="both")
if "⚪ 未评分" in selected_risks:
    allowed_mask |= score.isna()
filtered_df = filtered_df[allowed_mask]

if keyword.strip():
    search_columns = [
        "title", "competitor", "business", "snippet", "ai_analysis", "ai_suggestion", "url"
    ]
    search_text = filtered_df[search_columns].fillna("").astype(str).agg(" ".join, axis=1)
    filtered_df = filtered_df[search_text.str.contains(keyword.strip(), case=False, regex=False)]

filtered_df = filtered_df.sort_values(
    by=["real_date", "crawl_timestamp"], ascending=[False, False], na_position="last"
).reset_index(drop=True)

metric_cols = st.columns(4)
metric_cols[0].metric("📚 全部有效情报", f"{len(df):,} 条")
metric_cols[1].metric("🔎 当前筛选命中", f"{len(filtered_df):,} 条")
metric_cols[2].metric("🚨 当前筛选高影响", f"{int(filtered_df['ai_score'].ge(8).sum()):,} 条")
recent_24h = now_cn - pd.Timedelta(hours=24)
metric_cols[3].metric(
    "🕒 当前筛选近24小时",
    f"{int(filtered_df['crawl_timestamp'].ge(recent_24h).sum()):,} 条",
)
st.caption("提示：默认时间范围为‘全部日期’，默认选中全部竞对、业务模块和影响程度。取消某个选项即可缩小范围。")
st.markdown("---")


# ============================================================
# 描述统计：统一使用 filtered_df
# ============================================================
st.subheader("📊 描述统计（随筛选条件联动）")
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.markdown("**🎯 竞对活跃度排行**")
    comp_counts = filtered_df["competitor"].value_counts().rename_axis("竞对").reset_index(name="情报数量")
    if comp_counts.empty:
        st.info("当前筛选条件下没有可统计的数据。")
    else:
        fig_left = px.bar(comp_counts, x="竞对", y="情报数量", text="情报数量")
        fig_left.update_layout(
            height=380,
            margin=dict(t=20, l=10, r=10, b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, title=None, tickfont=dict(color="#333333", size=13)),
            yaxis=dict(showgrid=True, gridcolor="#F0F2F6", title=None, showticklabels=False),
        )
        fig_left.update_traces(
            marker_color="#1E88E5",
            textposition="outside",
            textfont=dict(color="#1E88E5", size=13, weight="bold"),
            width=0.4,
        )
        st.plotly_chart(fig_left, use_container_width=True, theme=None)

with chart_col2:
    if "drilldown_keyword" not in st.session_state:
        st.session_state.drilldown_keyword = None

    available_businesses = set(filtered_df["business"].dropna().unique().tolist())
    if st.session_state.drilldown_keyword not in available_businesses:
        st.session_state.drilldown_keyword = None

    if st.session_state.drilldown_keyword is None:
        st.markdown("**🏷️ 业务焦点热力分布** <span style='font-size:12px;color:#888;'>点击业务查看竞对分布</span>", unsafe_allow_html=True)
        biz_counts = filtered_df["business"].value_counts().rename_axis("业务模块").reset_index(name="情报数量")
        if biz_counts.empty:
            st.info("当前筛选条件下没有可统计的数据。")
        else:
            fig_tree = px.treemap(
                biz_counts,
                path=["业务模块"],
                values="情报数量",
                color="情报数量",
                color_continuous_scale="Blues",
            )
            fig_tree.update_layout(
                height=380,
                margin=dict(t=10, l=0, r=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            fig_tree.update_coloraxes(showscale=False)
            fig_tree.update_traces(tiling=dict(pad=0), marker=dict(line=dict(color="#FFFFFF", width=2)))
            selected_tree = st.plotly_chart(
                fig_tree,
                use_container_width=True,
                theme=None,
                on_select="rerun",
                selection_mode="points",
                key="treemap_selection",
            )
            try:
                points = selected_tree.selection.points
                if points:
                    clicked = points[0].get("label")
                    if clicked in available_businesses:
                        st.session_state.drilldown_keyword = clicked
                        st.rerun()
            except Exception:
                pass
    else:
        keyword_business = st.session_state.drilldown_keyword
        back_col, title_col = st.columns([0.25, 0.75])
        with back_col:
            if st.button("← 返回热力图", use_container_width=True):
                st.session_state.drilldown_keyword = None
                st.rerun()
        with title_col:
            st.markdown(f"**{keyword_business} · 竞对分布**")
        sub_df = (
            filtered_df[filtered_df["business"] == keyword_business]["competitor"]
            .value_counts().rename_axis("竞对").reset_index(name="情报数量")
        )
        if not sub_df.empty:
            sub_df = sub_df.sort_values("情报数量", ascending=True)
            fig_bar = px.bar(
                sub_df,
                x="情报数量",
                y="竞对",
                orientation="h",
                text="情报数量",
                color="情报数量",
                color_continuous_scale="Blues",
            )
            fig_bar.update_layout(
                height=335,
                margin=dict(t=10, l=80, r=30, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, showticklabels=False, title=None),
                yaxis=dict(showgrid=False, title=None, automargin=True),
            )
            fig_bar.update_coloraxes(showscale=False)
            fig_bar.update_traces(textposition="outside", textfont=dict(size=13, weight="bold", color="#1E88E5"))
            st.plotly_chart(fig_bar, use_container_width=True, theme=None)

st.markdown("---")


# ============================================================
# 情报卡片与列表
# ============================================================
def safe_text(value: Any, fallback: str = "暂无") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    text_value = str(value).strip()
    return text_value if text_value else fallback


def render_news_card(row: pd.Series, tab_prefix: str = "") -> None:
    score_value = row.get("ai_score")
    score_is_valid = pd.notna(score_value)
    score_value = int(score_value) if score_is_valid else None

    if score_value is None:
        risk_text = "⚪ 未评分"
        score_text = "未评分"
    elif score_value >= 8:
        risk_text = "🔴 重大影响"
        score_text = f"{score_value}/10"
    elif score_value >= 5:
        risk_text = "🟡 值得关注"
        score_text = f"{score_value}/10"
    else:
        risk_text = "🟢 影响较小"
        score_text = f"{score_value}/10"

    record_id = row.get("id")
    competitor = safe_text(row.get("competitor"), "未分类竞对")
    business = safe_text(row.get("business"), "未分类业务")
    title = safe_text(row.get("title"), "无标题")
    url = safe_text(row.get("url"), "")
    publish_time = safe_text(row.get("publish_time"), "时间待确认")

    with st.container(border=True):
        col_title, col_action = st.columns([0.86, 0.14])
        with col_title:
            if url and url != "暂无":
                st.markdown(f"**【{competitor} - {business}】** [{title}]({url})")
            else:
                st.markdown(f"**【{competitor} - {business}】** {title}")
            st.caption(f"发布时间：{publish_time}　|　影响评估：{risk_text}（{score_text}）")
        with col_action:
            if record_id is not None and st.button("🗑️ 删除", key=f"del_{record_id}_{tab_prefix}"):
                delete_news(record_id)

        with st.expander("查看 DeepSeek 深度分析与应对策略"):
            st.markdown(f"**AI资讯总结：** {safe_text(row.get('snippet'))}")
            st.markdown(f"**🧠 业务影响分析：** {safe_text(row.get('ai_analysis'))}")
            st.markdown(f"**💡 应对建议：** {safe_text(row.get('ai_suggestion'))}")


st.subheader("📡 情报大盘视图")
page_size = 30

TECH_PLATFORMS = ("快递鸟", "菜鸟")
competitor_text = filtered_df["competitor"].astype(str)
is_tech = competitor_text.str.contains("快递鸟|菜鸟", regex=True, na=False)
tech_df = filtered_df[is_tech].reset_index(drop=True)
logistics_df = filtered_df[~is_tech].reset_index(drop=True)

# 每个标签独立分页，避免某一类情报较少时被另一类情报占用分页名额
tab1, tab2, tab3 = st.tabs([
    f"🦅 聚合平台（{len(tech_df)} 条）",
    f"📦 快递巨头（{len(logistics_df)} 条）",
    f"📅 全景复盘（{len(filtered_df)} 条）",
])

with tab1:
    if tech_df.empty:
        st.info("当前筛选条件下没有聚合平台情报。")
    else:
        tech_pages = max(1, (len(tech_df) + page_size - 1) // page_size)
        if st.session_state.get("tech_page_number", 1) > tech_pages:
            st.session_state["tech_page_number"] = 1
        tech_page = st.number_input(
            f"聚合平台分页（共 {len(tech_df)} 条）", min_value=1,
            max_value=tech_pages, value=1, step=1, key="tech_page_number"
        )
        tech_start = (int(tech_page) - 1) * page_size
        for _, row in tech_df.iloc[tech_start:tech_start + page_size].iterrows():
            render_news_card(row, "tech")

with tab2:
    if logistics_df.empty:
        st.info("当前筛选条件下没有快递企业情报。")
    else:
        logistics_pages = max(1, (len(logistics_df) + page_size - 1) // page_size)
        if st.session_state.get("logistics_page_number", 1) > logistics_pages:
            st.session_state["logistics_page_number"] = 1
        logistics_page = st.number_input(
            f"快递企业分页（共 {len(logistics_df)} 条）", min_value=1,
            max_value=logistics_pages, value=1, step=1, key="logistics_page_number"
        )
        logistics_start = (int(logistics_page) - 1) * page_size
        for _, row in logistics_df.iloc[logistics_start:logistics_start + page_size].iterrows():
            render_news_card(row, "logistics")

with tab3:
    st.caption("按当前所有筛选条件展示；选择‘全部日期’即可复盘全部历史情报。复盘列表独立分页，不会只显示最新几天。")
    if filtered_df.empty:
        st.info("当前筛选条件下没有可复盘的情报。")
    else:
        review_pages = max(1, (len(filtered_df) + page_size - 1) // page_size)
        if st.session_state.get("review_page_number", 1) > review_pages:
            st.session_state["review_page_number"] = 1
        review_page = st.number_input(
            f"全景复盘分页（共 {len(filtered_df)} 条）", min_value=1,
            max_value=review_pages, value=1, step=1, key="review_page_number"
        )
        review_start = (int(review_page) - 1) * page_size
        review_page_df = filtered_df.iloc[review_start:review_start + page_size]
        grouped = review_page_df.groupby("real_date", dropna=False, sort=False)
        for idx, (date_value, group) in enumerate(grouped):
            date_label = date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else "日期未知"
            with st.expander(f"🗓️【{date_label}】（本页 {len(group)} 条）", expanded=(idx == 0)):
                for _, row in group.iterrows():
                    render_news_card(row, f"review_{date_label}")

st.markdown("---")
st.caption("数据说明：看板读取 news_v2 中 process_status = 1 的记录；被软删除（-1）及待分析（0）的记录不会显示。")
