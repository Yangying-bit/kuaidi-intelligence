import os
import urllib.parse
from datetime import datetime, timedelta
import feedparser
from supabase import create_client, Client

# ==========================================
# 🌟 初始化 Supabase
# ==========================================
raw_url = os.environ.get("SUPABASE_URL", "")
raw_key = os.environ.get("SUPABASE_KEY", "")
clean_url = raw_url.strip().strip('\'"').rstrip('/')
clean_key = raw_key.strip().strip('\'"')
supabase: Client = create_client(clean_url, clean_key)

# ==========================================
# 🌟 核心引擎：RSS 聚合解析器
# ==========================================
def fetch_rss_feed(search_term):
    """通过官方原生 RSS 接口直接拉取数据，免疫所有验证码反爬虫"""
    results = []
    encoded_term = urllib.parse.quote(search_term)
    
    # 引擎 1：Google News 中文 RSS (GitHub 服务器在海外，这是最强的免反爬源)
    google_rss_url = f"https://news.google.com/rss/search?q={encoded_term}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    
    # 引擎 2：Bing News RSS
    bing_rss_url = f"https://www.bing.com/news/search?q={encoded_term}&format=rss"

    sources = [
        {"name": "Google新闻", "url": google_rss_url},
        {"name": "Bing新闻", "url": bing_rss_url}
    ]

    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:10]:  # 每个引擎取前10条
                pub_time_obj = None
                
                # 尝试解析标准 RSS 时间
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time_obj = datetime(*entry.published_parsed[:6])
                
                # 如果超过 7 天则跳过
                if pub_time_obj:
                    now = datetime.utcnow()
                    if now - pub_time_obj > timedelta(days=7):
                        continue
                    pub_time_str = (pub_time_obj + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S") # 转北京时间
                else:
                    pub_time_str = "最新抓取"

                # 清洗摘要内容 (去除 RSS 自带的 HTML 标签)
                raw_summary = entry.get('summary', entry.title)
                import re
                clean_snippet = re.sub('<[^<]+>', '', raw_summary).strip()[:150]

                results.append({
                    "title": entry.title,
                    "link": entry.link,
                    "time": pub_time_str,
                    "snippet": clean_snippet,
                    "source": source["name"]
                })
        except Exception as e:
            print(f"⚠️ {source['name']} RSS源拉取异常: {e}")
            
    return results

# ==========================================
# 🌟 主调度逻辑
# ==========================================
def run_spider():
    COMPETITOR_INFO = {
        "菜鸟": "菜鸟网络", "顺丰": "顺丰速运", "京东物流": "京东物流",
        "中通": "中通快递", "圆通": "圆通速递", "极兔": "极兔速递"
    }
    
    KEYWORDS = ["接口", "API", "同城急送", "大件快运", "运费调整", "电商退货"]

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 启动企业级 RSS 聚合抓取...")
    new_count = 0

    # 交叉组合生成高价值商业搜索词
    for comp in COMPETITOR_INFO.keys():
        # 每次随机挑 2 个关键词组合，避免词汇量过大导致单次任务耗时过长
        import random
        sampled_kws = random.sample(KEYWORDS, 2)
        
        for kw in sampled_kws:
            search_term = f'"{comp}" AND "{kw}"'  # 使用严格的布尔搜索语法
            print(f"📡 正在拉取订阅流: {search_term}")
            
            scraped_items = fetch_rss_feed(search_term)
            
            for item in scraped_items:
                # 物理过滤自家新闻
                if "快递100" in item['title']: 
                    continue
                
                try:
                    supabase.table("news_v2").insert({
                        "publish_time": item['time'],
                        "competitor": comp,
                        "business": kw,
                        "title": item['title'],
                        "snippet": item['snippet'],
                        "url": item['link'],
                        "process_status": 0 # 0代表待AI处理
                    }).execute()
                    new_count += 1
                except Exception:
                    pass  # URL 重复会导致唯一键冲突报错，直接跳过即可，实现天然去重

    print(f"✅ RSS 订阅源同步完毕！本次共发现 {new_count} 条全新情报。")

if __name__ == "__main__":
    run_spider()
