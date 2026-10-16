import os
import urllib.parse
import random
import time
import re
from datetime import datetime, timedelta
import feedparser
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ==========================================
# 🌟 初始化云数据库 Supabase
# ==========================================
raw_url = os.environ.get("SUPABASE_URL", "")
raw_key = os.environ.get("SUPABASE_KEY", "")
clean_url = raw_url.strip().strip('\'"').rstrip('/')
clean_key = raw_key.strip().strip('\'"')
supabase: Client = create_client(clean_url, clean_key)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).replace('[', '【').replace(']', '】').strip()[:200]

# ==========================================
# 引擎 1：广度雷达 (RSS 免疫反爬，抓取全网行业动态)
# ==========================================
def fetch_broad_rss(search_term):
    results = []
    encoded_term = urllib.parse.quote(search_term)
    # GitHub 服务器在海外，Bing News RSS 极其稳定
    rss_url = f"https://www.bing.com/news/search?q={encoded_term}&format=rss"
    
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:6]:
            pub_time_str = "最新抓取"
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_time_obj = datetime(*entry.published_parsed[:6])
                # 过滤掉 7 天前的新闻
                if datetime.utcnow() - pub_time_obj > timedelta(days=7):
                    continue
                pub_time_str = (pub_time_obj + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
                
            raw_summary = entry.get('summary', entry.title)
            snippet = re.sub('<[^<]+>', '', raw_summary).strip()
            results.append({
                "title": clean_text(entry.title), "link": entry.link,
                "time": pub_time_str, "snippet": clean_text(snippet)
            })
    except Exception as e:
        print(f"⚠️ RSS 雷达异常: {e}")
    return results

# ==========================================
# 引擎 2：深度狙击 (HTML 爬虫，专攻指定竞对官网/开放平台)
# ==========================================
def fetch_official_html(domain, keyword):
    results = []
    # 使用语法 site:domain keyword 强制搜索引擎只在指定官网内查找
    search_query = f"site:{domain} {keyword}"
    encoded_term = urllib.parse.quote(search_query)
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "zh-CN,zh;q=0.9"}
    
    # 使用 Bing Web 网页搜索，它对 GitHub Actions 的机房 IP 比百度宽容得多
    url = f"https://cn.bing.com/search?q={encoded_term}&qdr=w" # qdr=w 表示只搜过去一周
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 解析 Bing 网页结构
        for item in soup.find_all('li', class_='b_algo')[:5]:
            h2_tag = item.find('h2')
            if not h2_tag or not h2_tag.find('a'): continue
            
            a_tag = h2_tag.find('a')
            title = clean_text(a_tag.text)
            link = a_tag.get('href')
            
            p_tag = item.find('p')
            snippet = clean_text(p_tag.text if p_tag else title)
            
            results.append({
                "title": title, "link": link,
                "time": "近期动态", "snippet": snippet
            })
    except Exception as e:
        print(f"⚠️ 官网狙击异常 ({domain}): {e}")
    return results

# ==========================================
# 🌟 主控调度逻辑
# ==========================================
def run_spider():
    # 明确你的核心监控目标及其官方域名
    COMPETITOR_INFO = {
        "顺丰": "sf-express.com",    # 顺丰官网及开放平台通常在此域名下
        "菜鸟": "cainiao.com",
        "京东物流": "jdwl.com",
        "中通": "zto.com"
    }
    
    BROAD_COMPETITORS = list(COMPETITOR_INFO.keys()) + ["极兔", "圆通", "快递鸟"]
    API_KEYWORDS = ["API", "接口", "开放平台", "计费规则", "运费调整", "同城急送"]

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 启动混合双擎情报抓取...")
    new_count = 0

    # --- 阶段 1：深度狙击（专攻竞对官网最新变更） ---
    print("\n🎯 开始扫描官方开放平台动态...")
    for comp, domain in COMPETITOR_INFO.items():
        # 针对每个竞对，随机挑选核心词去官网搜刮
        target_kws = random.sample(["API", "接口", "公告", "价格"], 2)
        for kw in target_kws:
            print(f"   -> 正在潜入 {comp} 官网 ({domain}) 探查: {kw}")
            items = fetch_official_html(domain, kw)
            for item in items:
                try:
                    supabase.table("news_v2").insert({
                        "publish_time": item['time'], "competitor": f"{comp}(官方公告)", "business": kw,
                        "title": item['title'], "snippet": item['snippet'], "url": item['link'],
                        "process_status": 0
                    }).execute()
                    new_count += 1
                except: pass
            time.sleep(random.uniform(2.0, 4.0))

    # --- 阶段 2：广度雷达（捕捉全网行业新闻） ---
    print("\n🌐 开始全网行业新闻雷达扫描...")
    for comp in BROAD_COMPETITORS:
        sampled_kws = random.sample(API_KEYWORDS, 2)
        for kw in sampled_kws:
            search_term = f'"{comp}" "{kw}"'
            items = fetch_broad_rss(search_term)
            for item in items:
                if "快递100" in item['title']: continue # 物理过滤自家公关稿
                
                try:
                    supabase.table("news_v2").insert({
                        "publish_time": item['time'], "competitor": comp, "business": kw,
                        "title": item['title'], "snippet": item['snippet'], "url": item['link'],
                        "process_status": 0
                    }).execute()
                    new_count += 1
                except: pass
            time.sleep(random.uniform(1.0, 2.0))

    print(f"\n✅ 混合双擎抓取完毕！本次共捕获 {new_count} 条核心情报待 AI 分析。")

if __name__ == "__main__":
    run_spider()
