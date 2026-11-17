"""Streamlit dashboard: full-dataset filtering for industry intelligence."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import Client, create_client

st.set_page_config(page_title="行业竞对情报监控", layout="wide", page_icon="🛰️")
CN_TZ = ZoneInfo("Asia/Shanghai")
PAGE_SIZE = 1000
RESULTS_PER_PAGE = 30

# -----------------------------------------------------------------------------
# Supabase connection
# -----------------------------------------------------------------------------
try:
    supabase_url = (os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")).strip().strip("'\"").rstrip("/")
    supabase_key = (os.getenv("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")).strip().strip("'\"")
    if not supabase_url or not supabase_key:
        raise RuntimeError("未配置 SUPABASE_URL / SUPABASE_KEY")
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as exc:
    st.error(f"Supabase 连接配置异常：{exc}")
    st.stop()

COLUMNS = (
    "id,competitor,business,title,snippet,raw_snippet,page_content,url,canonical_url,"
    "publish_time,published_at,crawl_timestamp,source_type,source_name,source_domain,"
    "ai_score,ai_analysis,ai_suggestion,ai_summary,is_relevant,competitor_confirmed,"
    "relevance_score,ai_confidence,event_type,evidence,process_status,retry_count,last_error"
)


@st.cache_data(ttl=90, show_spinner="正在从 Supabase 分页加载全部已分析情报…")
def load_processed_data() -> pd.DataFrame:
    """逐页读取全部 process_status=1 记录，避免 REST 单次行数上限造成遗漏。"""
    rows: list[dict] = []
    start = 0
    while True:
        response = (
            supabase.table("news_v2")
            .select(COLUMNS)
            .eq("process_status", 1)
            .order("crawl_timestamp", desc=True)
            .order("id", desc=True)
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Supabase 时间统一转换为中国时区；无效时间保留为空，不让单条坏数据导致整表加载失败。
    for source_col, target_col in (("crawl_timestamp", "crawl_dt"), ("published_at", "published_dt")):
        parsed = pd.to_datetime(df[source_col], utc=True, errors="coerce")
        df[target_col] = parsed.dt.tz_convert(CN_TZ).dt.tz_localize(None)

    df["ai_score"] = pd.to_numeric(df["ai_score"], errors="coerce").fillna(0).clip(0, 10).astype(int)
    df["relevance_score"] = pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0).clip(0, 100).astype(int)
    df["ai_confidence"] = pd.to_numeric(df["ai_confidence"], errors="coerce")

    for col, fallback in (("business", "待AI识别"), ("competitor", "未知竞对"),
                          ("source_name", ""), ("source_domain", ""), ("source_type", ""),
                          ("event_type", "待识别")):
        if col not in df.columns:
            df[col] = fallback
        df[col] = df[col].fillna(fallback).astype(str).replace({"": fallback})

    # 保留“待确认”状态，不把数据库 NULL 粗暴转换成 True。
    def relevance_label(value: object) -> str:
        if pd.isna(value):
            return "待确认"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return "高相关"
            if normalized in {"false", "0", "no", "n"}:
                return "低相关"
            return "待确认"
        return "高相关" if bool(value) else "低相关"

    df["relevance_label"] = df["is_relevant"].map(relevance_label)
    df["real_date"] = df["crawl_dt"].dt.strftime("%Y-%m-%d")
    df = df.sort_values(["crawl_dt", "id"], ascending=[False, False], na_position="last").reset_index(drop=True)
    return df


def count_by_status(status: int) -> int:
    try:
        response = supabase.table("news_v2").select("id", count="exact", head=True).eq("process_status", status).execute()
        return int(response.count or 0)
    except Exception:
        return -1


def hide_news(record_id: int | str) -> None:
    try:
        supabase.table("news_v2").update({"process_status": -1}).eq("id", record_id).execute()
        load_processed_data.clear()
        st.toast("已从看板隐藏该条情报")
        st.rerun()
    except Exception as exc:
        st.error(f"隐藏失败：{exc}")


def safe_options(series: pd.Series) -> list[str]:
    values = series.dropna().astype(str).str.strip()
    return sorted(v for v in values.unique().tolist() if v)


def apply_filters(data: pd.DataFrame, *, date_start: date | None, date_end: date | None,
                  selected_competitors: list[str], selected_businesses: list[str],
                  selected_events: list[str], selected_sources: list[str],
                  relevance_scope: str, selected_risks: list[str], keyword: str) -> pd.DataFrame:
    """所有条件统一作用于完整数据集；各统计、列表和复盘共用同一个结果。"""
    result = data.copy()

    if date_start is not None:
        result = result[result["crawl_dt"].notna() & (result["crawl_dt"].dt.date >= date_start)]
    if date_end is not None:
        result = result[result["crawl_dt"].notna() & (result["crawl_dt"].dt.date <= date_end)]

    # 多选条件：未选择任何项时返回空集，避免用户清空筛选后反而看到全部数据。
    result = result[result["competitor"].isin(selected_competitors)]
    result = result[result["business"].isin(selected_businesses)]
    result = result[result["event_type"].isin(selected_events)]
    result = result[result["source_filter"].isin(selected_sources)]

    if relevance_scope == "仅高相关":
        result = result[result["relevance_label"] == "高相关"]
    elif relevance_scope == "仅低相关/待确认":
        result = result[result["relevance_label"].isin(["低相关", "待确认"])]

    score = result["ai_score"]
    allowed_scores: list[int] = []
    if "重大影响（8-10分）" in selected_risks:
        allowed_scores.extend([8, 9, 10])
    if "值得关注（5-7分）" in selected_risks:
        allowed_scores.extend([5, 6, 7])
    if "影响较小（0-4分）" in selected_risks:
        allowed_scores.extend([0, 1, 2, 3, 4])
    result = result[score.isin(allowed_scores)]

    query = keyword.strip()
    if query:
        searchable_columns = [
            "title", "snippet", "raw_snippet", "page_content", "ai_summary",
            "ai_analysis", "ai_suggestion", "evidence", "competitor", "business",
            "event_type", "source_name", "source_domain",
        ]
        mask = pd.Series(False, index=result.index)
        for col in searchable_columns:
            if col in result.columns:
                mask |= result[col].fillna("").astype(str).str.contains(query, case=False, regex=False)
        result = result[mask]

    return result.sort_values(["crawl_dt", "id"], ascending=[False, False], na_position="last")


def render_news_card(row: pd.Series, prefix: str = "all") -> None:
    score = int(row.get("ai_score", 0) or 0)
    relevance = int(row.get("relevance_score", 0) or 0)
    risk = "🔴 重大影响" if score >= 8 else "🟡 值得关注" if score >= 5 else "🟢 影响较小"
    title = str(row.get("title") or "无标题")
    url = str(row.get("url") or row.get("canonical_url") or "")
    record_id = row.get("id")

    with st.container(border=True):
        left, right = st.columns([0.88, 0.12])
        with left:
            st.markdown(f"**【{row.get('competitor', '未知竞对')} · {row.get('business', '待AI识别')}】**")
            if url.startswith(("http://", "https://")):
                st.markdown(f"[{title}]({url})")
            else:
                st.markdown(f"**{title}**")
            crawl_time = row.get("crawl_dt")
            crawl_text = crawl_time.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(crawl_time) else "采集时间未知"
            publish_time = row.get("publish_time") or "发布时间未知"
            source = row.get("source_name") or row.get("source_domain") or row.get("source_type") or "未知来源"
            st.caption(f"发布时间：{publish_time} · 采集时间：{crawl_text} · 来源：{source}")
            st.caption(f"{risk}（{score}/10） · 相关性 {relevance}/100 · {row.get('relevance_label', '待确认')} · 事件：{row.get('event_type') or '待识别'}")
        with right:
            st.button("隐藏", key=f"hide_{prefix}_{record_id}", on_click=hide_news, args=(record_id,), use_container_width=True)
        with st.expander("查看原文摘要、AI判断与应对建议"):
            st.markdown(f"**AI情报总结：** {row.get('ai_summary') or '暂无总结'}")
            st.markdown(f"**原始来源摘要：** {row.get('raw_snippet') or row.get('snippet') or '暂无摘要'}")
            st.markdown(f"**主体确认：** {'已确认' if row.get('competitor_confirmed') else '未确认/存疑'}")
            st.markdown(f"**业务影响分析：** {row.get('ai_analysis') or '暂无分析'}")
            st.markdown(f"**建议动作：** {row.get('ai_suggestion') or '暂无建议'}")
            st.markdown(f"**判断依据：** {row.get('evidence') or '暂无明确证据'}")
            if row.get("page_content"):
                with st.expander("网页正文摘录"):
                    st.write(str(row["page_content"])[:5000])


# -----------------------------------------------------------------------------
# Page header and pipeline health
# -----------------------------------------------------------------------------
st.title("🛰️ 行业竞对情报监控")
st.caption("面向快递100寄件 API、开放平台、同城寄递、大件、国际寄递及企业寄件业务的竞争情报看板")

refresh_col, status_col = st.columns([0.18, 0.82])
with refresh_col:
    if st.button("↻ 刷新数据", use_container_width=True):
        load_processed_data.clear()
        st.rerun()
with status_col:
    pending_count = count_by_status(0)
    processing_count = count_by_status(2)
    failed_count = count_by_status(3)
    st.caption(
        f"流水线状态：待分析 {pending_count if pending_count >= 0 else '—'} 条 · "
        f"正在处理 {processing_count if processing_count >= 0 else '—'} 条 · "
        f"失败待重试/待排查 {failed_count if failed_count >= 0 else '—'} 条"
    )

df = load_processed_data()
if df.empty:
    st.info("目前没有已完成分析的情报。请检查 GitHub Actions 采集任务、AI 分析任务和 Supabase 数据库迁移。")
    st.stop()

# Build a stable source display field for the source filter.
df["source_filter"] = df.apply(
    lambda row: str(row.get("source_name") or row.get("source_domain") or row.get("source_type") or "未知来源"), axis=1
)

now_cn = datetime.now(CN_TZ).replace(tzinfo=None)
two_hours_ago = now_cn - timedelta(hours=2)
today_start = now_cn.replace(hour=0, minute=0, second=0, microsecond=0)
new_last_2h = int((df["crawl_dt"] >= two_hours_ago).sum())
new_today = int((df["crawl_dt"] >= today_start).sum())
all_high_threats = int(((df["relevance_label"] == "高相关") & (df["ai_score"] >= 7)).sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("近 2 小时新增", f"{new_last_2h} 条")
m2.metric("今日采集并分析", f"{new_today} 条")
m3.metric("高相关高影响情报", f"{all_high_threats} 条")
m4.metric("已分析情报总量", f"{len(df):,} 条")

st.divider()
st.subheader("全量情报筛选")
st.caption("默认覆盖数据库中全部已分析情报和全部历史日期。下面的筛选条件会同步作用于情报列表、统计图表和近 7 天复盘。")

# Date presets are explicit so users can return to the entire historical range at any time.
date_values = pd.to_datetime(df["real_date"], errors="coerce").dropna()
min_data_date = date_values.min().date() if not date_values.empty else date.today()
max_data_date = date_values.max().date() if not date_values.empty else date.today()

with st.container(border=True):
    f1, f2, f3 = st.columns([1.05, 1.25, 1.7])
    with f1:
        date_mode = st.selectbox("时间范围", ["全部日期", "最近 7 天", "最近 30 天", "最近 90 天", "自定义日期"], index=0, key="filter_date_mode")
    with f2:
        relevance_scope = st.selectbox("情报范围", ["全部情报", "仅高相关", "仅低相关/待确认"], index=0, key="filter_relevance")
    with f3:
        keyword = st.text_input("全文关键词", placeholder="可搜索标题、摘要、正文、AI分析、建议、证据等", key="filter_keyword")

    custom_start: date | None = None
    custom_end: date | None = None
    if date_mode == "自定义日期":
        d1, d2 = st.columns(2)
        with d1:
            custom_start = st.date_input("开始日期", value=min_data_date, min_value=min_data_date, max_value=max_data_date, key="filter_start_date")
        with d2:
            custom_end = st.date_input("结束日期", value=max_data_date, min_value=min_data_date, max_value=max_data_date, key="filter_end_date")
        if custom_start > custom_end:
            st.warning("开始日期不能晚于结束日期，本次将自动交换日期范围。")
            custom_start, custom_end = custom_end, custom_start

    all_competitors = safe_options(df["competitor"])
    all_businesses = safe_options(df["business"])
    all_events = safe_options(df["event_type"])
    all_sources = safe_options(df["source_filter"])

    f4, f5 = st.columns(2)
    with f4:
        selected_competitors = st.multiselect("监控对象 / 竞对", all_competitors, default=all_competitors, key="filter_competitors")
    with f5:
        selected_businesses = st.multiselect("业务模块", all_businesses, default=all_businesses, key="filter_businesses")

    f6, f7 = st.columns(2)
    with f6:
        selected_events = st.multiselect("事件类型", all_events, default=all_events, key="filter_events")
    with f7:
        selected_sources = st.multiselect("情报来源", all_sources, default=all_sources, key="filter_sources")

    all_risks = ["重大影响（8-10分）", "值得关注（5-7分）", "影响较小（0-4分）"]
    selected_risks = st.multiselect("潜在影响程度", all_risks, default=all_risks, key="filter_risks")

# Resolve date range.
if date_mode == "最近 7 天":
    date_start, date_end = (now_cn - timedelta(days=6)).date(), now_cn.date()
elif date_mode == "最近 30 天":
    date_start, date_end = (now_cn - timedelta(days=29)).date(), now_cn.date()
elif date_mode == "最近 90 天":
    date_start, date_end = (now_cn - timedelta(days=89)).date(), now_cn.date()
elif date_mode == "自定义日期":
    date_start, date_end = custom_start, custom_end
else:
    date_start, date_end = None, None

filtered = apply_filters(
    df,
    date_start=date_start,
    date_end=date_end,
    selected_competitors=selected_competitors,
    selected_businesses=selected_businesses,
    selected_events=selected_events,
    selected_sources=selected_sources,
    relevance_scope=relevance_scope,
    selected_risks=selected_risks,
    keyword=keyword,
)

st.caption(f"全库 {len(df):,} 条 · 当前筛选结果 {len(filtered):,} 条 · 当前范围：{date_mode} / {relevance_scope}")

# Reset pagination whenever any filter changes, including date scope and keyword.
filter_signature = (
    date_mode, date_start, date_end, relevance_scope, keyword.strip(),
    tuple(selected_competitors), tuple(selected_businesses), tuple(selected_events),
    tuple(selected_sources), tuple(selected_risks),
)
if st.session_state.get("_last_filter_signature") != filter_signature:
    st.session_state["_last_filter_signature"] = filter_signature
    st.session_state["all_news_page"] = 1

# -----------------------------------------------------------------------------
# All summaries, charts, export, review and list use the same filtered dataframe.
# -----------------------------------------------------------------------------
st.divider()
st.subheader("筛选结果概览")
if filtered.empty:
    st.info("没有符合当前筛选条件的情报。请扩大时间范围，或取消部分竞对、业务、事件、来源及影响程度筛选。")
else:
    high_count = int((filtered["ai_score"] >= 8).sum())
    medium_count = int(((filtered["ai_score"] >= 5) & (filtered["ai_score"] < 8)).sum())
    low_count = int((filtered["ai_score"] < 5).sum())
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("筛选后情报", f"{len(filtered):,} 条")
    s2.metric("重大影响", f"{high_count:,} 条")
    s3.metric("值得关注", f"{medium_count:,} 条")
    s4.metric("影响较小", f"{low_count:,} 条")

    chart1, chart2 = st.columns(2)
    with chart1:
        comp_counts = filtered["competitor"].value_counts().rename_axis("竞对").reset_index(name="情报数量")
        fig = px.bar(comp_counts, x="竞对", y="情报数量", text="情报数量", title="筛选结果 · 竞对分布")
        fig.update_layout(height=340, margin=dict(t=55, l=10, r=10, b=25), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with chart2:
        biz_counts = filtered["business"].value_counts().rename_axis("业务模块").reset_index(name="情报数量")
        fig = px.treemap(biz_counts, path=["业务模块"], values="情报数量", title="筛选结果 · 业务主题分布", color="情报数量", color_continuous_scale="Blues")
        fig.update_layout(height=340, margin=dict(t=55, l=5, r=5, b=5))
        fig.update_coloraxes(showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("📚 全量情报列表")
    st.caption("此列表展示全部符合筛选条件的历史情报，不再默认限定为最新一天或最近 7 天。")
    export_df = filtered.copy()
    export_columns = [c for c in [
        "competitor", "business", "event_type", "title", "url", "publish_time",
        "crawl_timestamp", "source_name", "source_domain", "ai_score",
        "relevance_score", "relevance_label", "ai_summary", "ai_analysis",
        "ai_suggestion", "evidence",
    ] if c in export_df.columns]
    csv_bytes = export_df[export_columns].to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "下载当前筛选的全部情报（CSV）", data=csv_bytes,
        file_name=f"行业情报筛选结果_{datetime.now(CN_TZ).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv", key="download_filtered_news",
    )
    total_pages = max(1, (len(filtered) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page_col, info_col = st.columns([0.25, 0.75])
    with page_col:
        if "all_news_page" not in st.session_state or int(st.session_state["all_news_page"]) > total_pages:
            st.session_state["all_news_page"] = 1
        page = st.number_input("结果页码", min_value=1, max_value=total_pages, step=1, key="all_news_page")
    with info_col:
        st.caption(f"共 {total_pages} 页，每页 {RESULTS_PER_PAGE} 条；筛选条件变化时会自动返回第 1 页。")
    page_df = filtered.iloc[(int(page) - 1) * RESULTS_PER_PAGE:int(page) * RESULTS_PER_PAGE]
    for _, row in page_df.iterrows():
        render_news_card(row, "all")

    st.divider()
    st.subheader("近 7 天情报复盘（遵循当前筛选条件）")
    seven_days_ago = (now_cn - timedelta(days=6)).date()
    recent = filtered[filtered["crawl_dt"].notna() & (filtered["crawl_dt"].dt.date >= seven_days_ago)].copy()
    if recent.empty:
        st.info("当前筛选条件下，近 7 天没有情报。")
    else:
        recent["review_date"] = recent["crawl_dt"].dt.strftime("%Y-%m-%d")
        for idx, (day_text, group) in enumerate(recent.groupby("review_date", dropna=False, sort=True)):
            with st.expander(f"{day_text} · {len(group)} 条", expanded=(idx == 0)):
                display_cols = ["competitor", "business", "event_type", "title", "ai_score", "relevance_score"]
                st.dataframe(group[display_cols], use_container_width=True, hide_index=True)
