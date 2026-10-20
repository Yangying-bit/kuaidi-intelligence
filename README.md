# 物流 B2B 竞对情报自动化监控系统

## 项目简介
本项目是一个专为物流与快递 API 行业设计的竞对情报自动化监控与分析系统。系统采用解耦的 ETL（提取、转换、加载）架构，结合双模数据抓取策略与大语言模型（LLM）分析，实现对主流快递企业官网、开放平台及全网行业动态的 24 小时自动化监控、分析与可视化展示。

## 核心架构与数据流

系统分为三个核心模块，通过 Supabase 云数据库进行状态解耦：

1. **数据采集引擎 (`1_spider.py`)**
   - **双模抓取策略**：
     - **定向抓取**：利用搜索引擎的 `site:` 语法，精准监控顺丰、菜鸟、京东物流等竞对的官网及开放平台，重点提取 API 接口变更、价格调整、业务规则等高价值公告。
     - **全网聚合**：通过 Google News 等标准 RSS 源，无视反爬限制，广泛捕获行业大盘资讯。
   - **状态管理**：抓取到的原始数据存入 Supabase 数据库，标记为 `process_status = 0`（待处理）。

2. **AI 异步分析队列 (`2_ai_worker.py`)**
   - 作为消费者，定期从数据库拉取 `process_status = 0` 的增量数据。
   - 调用 DeepSeek API 对每条情报进行结构化分析，提取关键业务信息、评估情报重要程度并生成简报。
   - 分析完成后，将结果写回数据库，更新标记为 `process_status = 1`（已处理）。

3. **数据可视化看板 (`app.py`)**
   - 基于 Streamlit 构建的前端交互看板。
   - 实时读取数据库中已处理 (`process_status = 1`) 的情报数据，进行图表统计与卡片式展示。
   - 包含时区处理机制与软删除功能，确保数据展示的准确性与系统的易用性。

## 技术栈
- **后端脚本**：Python 3.10+
- **数据采集**：`requests`, `BeautifulSoup4`, `feedparser`
- **AI 引擎**：DeepSeek API (通过 `openai` Python SDK 调用)
- **数据库**：Supabase (PostgreSQL 托管服务)
- **前端框架**：Streamlit, Pandas
- **自动化部署**：GitHub Actions, Streamlit Community Cloud

## 监控目标矩阵
系统默认配置监控以下企业的核心域名及开放平台：
- 顺丰 (`sf-express.com`, `open.sf-express.com`)
- 菜鸟 (`cainiao.com`, `open.cainiao.com`)
- 京东物流 (`jdwl.com`, `open.jdl.com`)
- 中通、圆通、申通、韵达、极兔及快递鸟等。

**核心业务关键词**：API、接口、开放平台、运费调整、同城急送、电商退货等。

## 环境配置与部署

### 1. 环境变量配置 (Secrets)
无论是在本地运行还是在云端部署，均需要配置以下三个环境变量：

```toml
# Supabase 配置
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_KEY = "your-supabase-anon-key"

# DeepSeek 大模型配置
DEEPSEEK_API_KEY = "sk-your-deepseek-api-key"
```

### 2. 自动化流水线 (GitHub Actions)
项目内置了 `.github/workflows/main.yml` 配置文件。
- **触发机制**：每 2 小时定时自动运行，或通过 Actions 面板手动触发（`workflow_dispatch`）。
- **运行逻辑**：依次执行 `1_spider.py` 和 `2_ai_worker.py`，实现无人值守的情报更新。
- **配置要求**：需在 GitHub 仓库的 `Settings > Secrets and variables > Actions` 中填入上述三个环境变量。

### 3. 前端看板部署 (Streamlit Cloud)
- 将本项目推送到 GitHub。
- 在 Streamlit Community Cloud 关联该仓库，将启动文件设置为 `app.py`。
- 在应用的 `Settings > Secrets` 面板中，按照 TOML 格式填入上述三个环境变量。

## 数据库表结构参考 (`news_v2`)
系统依赖 Supabase 中的 `news_v2` 表，需包含以下核心字段：
- `id`: UUID (主键)
- `publish_time`: 字符串或时间戳
- `competitor`: 字符串 (如 "顺丰(官方网站)")
- `business`: 字符串 (业务分类)
- `title`: 字符串 (情报标题)
- `snippet`: 文本 (情报摘要)
- `url`: 字符串 (原文链接，需设置为 Unique 避免重复录入)
- `process_status`: 整数 (0: 未处理, 1: 已处理, -1: 已拉黑/删除)
- `ai_score`: 整数 (AI 评分)
- `ai_analysis`: 文本 (AI 深度分析结果)
- `crawl_timestamp`: 时间戳 (抓取入库时间)
