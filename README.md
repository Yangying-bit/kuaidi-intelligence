# 物流行业竞对情报 AI 监控大盘 (Logistics CI Dashboard)

> 基于 Python + DeepSeek + GitHub Actions 的全自动化竞对情报监控系统，用于监测竞对是否会对业务带来影响。

## 项目亮点

* **AI 深度洞察**：接入 DeepSeek 模型（Flash版本），自动对长篇新闻进行“摘要提取”、“业务威胁打分（1-10分）”与“高危预警”。
* **“零浪费”防重机制**：基于 SQLite 数据库的 `UNIQUE` 约束，抓取前秒级查重，完美避免重复调用大模型造成的 API 额度浪费。
* **黄金时段防漏策略**：GitHub Actions 定时任务采用“避峰运行（每2小时避开整点运行）” + “4小时动态兜底抓取”策略，确保情报无遗漏且稳定。
* **智能反爬伪装**：内置随机请求延迟（Random Sleep）机制，模拟真实人类操作，保障云端 IP 长期稳定抓取不被封禁。
* **轻量级可视化**：使用 Streamlit 搭建极简交互式大盘，核心指标（近期新增、历史高危）一目了然。

## 核心目录结构

```text
├── .github/workflows/
│   └── run_crawler.yml      # GitHub Actions 自动化定时任务配置
├── app.py                   # Streamlit 可视化大盘网页入口
├── crawler_engine.py        # 爬虫抓取与 DeepSeek AI 分析核心引擎
├── intelligence.db          # SQLite 本地/云端情报数据库
└── requirements.txt         # Python 依赖包清单
