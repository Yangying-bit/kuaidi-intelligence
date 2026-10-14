import os
import time
import random
import urllib.parse
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# 初始化云数据库
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]

def is_recent_news(pub_time_str):
    if pub_time_str == "未知时间": return False
    try:
        pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.utcnow() + timedelta(hours=8)
        return timedelta(0) <= (now - pub_time) <= timedelta(days=7)
    except ValueError:
        if any(kw in pub_time_str for kw in ['刚刚', '分钟', '小时', '今天', '昨天', '天前']): return True
        if len(pub_time_str) == 10 and pub_time_str.count('-') == 2:
            try:
                pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d")
                return timedelta(0) <= (datetime.now() - pub_time) <= timedelta(days=7)
            except: pass
        return False

def clean_text_for_markdown(text):
    if not text: return ""
    return text.replace('\n', ' ').replace('\r', '').replace('[', '【').replace(']', '】').strip()[:200]

def fetch_multi_engine(search_term):
    results = []
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    encoded_term = urllib.parse.quote(search_term)

    # 必应新闻
    try:
        resp = requests.get(f"https://cn.bing.com/news/search?q={encoded_term}&qft=interval%3d%227%22", headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.find_all('div', class_='news-card')[:8]:
            a_tag = item.find('a', class_='title')
            if a_tag:
                title = clean_text_for_markdown(a_tag.text)
                link = a_tag.get('href')
                time_span = item.find('span', tabindex="0")
                pub_time = time_span.text.strip() if time_span else "未知时间"
                snippet_tag = item.find('div', class_='snippet')
                snippet = clean_text_for_markdown(snippet_tag.text if snippet_tag else title)
                results.append({"title": title, "link": link, "time": pub_time, "snippet": snippet, "source": "必应"})
    except: pass

    # 搜狗微信
    try:
        resp = requests.get(f"https://weixin.sogou.com/weixin?type=2&query={encoded_term}&tsn=2", headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.find_all('div', class_='txt-box')[:8]:
            a_tag = item.find('h3').find('a')
            if a_tag:
                title = clean_text_for_markdown(a_tag.text)
                href = a_tag.get('href')
                link = "https://weixin.sogou.com" + href if href.startswith('/') else href
                snippet_tag = item.find('p', class_='txt-info')
                snippet = clean_text_for_markdown(snippet_tag.text if snippet_tag else title)
                results.append({"title": title, "link": link, "time": "今天", "snippet": snippet, "source": "微信公众号"})
    except: pass
    return results

def run_spider():
    COMPETITOR_INFO = {
        "菜鸟": {"domain": "cainiao.com", "wechat": "菜鸟网络"},
        "顺丰": {"domain": "sf-express.com", "wechat": "顺丰速运"},
        "京东物流": {"domain": "jdwl.com", "wechat": "京东物流"},
        "中通": {"domain": "zto.com", "wechat": "中通快递"},
        "圆通": {"domain": "yto.net.cn", "wechat": "圆通速递"}
    }
    
    COMPETITORS = list(COMPETITOR_INFO.keys()) + ["极兔", "邮政"]
    KEYWORDS = ["同城急送 API", "上门取件 接口", "国际寄件", "大件快运", "快递价格", "电商退货 寄件"]

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 极速情报搜集中...")
    new_count = 0

    # 1. 官方矩阵搜刮
    for comp, info in COMPETITOR_INFO.items():
        queries = [
            f"site:{info['domain']} 新闻 OR 公告",
            f"{info['wechat']} 接口 OR 新功能"
        ]
        for q in queries:
            for item in fetch_multi_engine(q):
                if not is_recent_news(item['time']): continue
                try:
                    supabase.table("news_v2").insert({
                        "publish_time": item['time'], "competitor": comp, "business": "官方动向",
                        "title": item['title'], "snippet": item['snippet'], "url": item['link'],
                        "process_status": 0 # 0代表待处理
                    }).execute()
                    new_count += 1
                except: pass # 报错说明URL已存在，自动忽略去重
            time.sleep(2)

    # 2. 行业关键词搜刮
    for comp in COMPETITORS:
        for kw in random.sample(KEYWORDS, 2):
            for item in fetch_multi_engine(f"{comp} {kw} -快递100"):
                if not is_recent_news(item['time']): continue
                if "快递100" in item['title'] or "快递100" in item['snippet'][:30]: continue
                
                try:
                    supabase.table("news_v2").insert({
                        "publish_time": item['time'], "competitor": comp, "business": kw,
                        "title": item['title'], "snippet": item['snippet'], "url": item['link'],
                        "process_status": 0
                    }).execute()
                    new_count += 1
                except: pass
            time.sleep(2)

    print(f"✅ 抓取完毕！共推送 {new_count} 条原始情报入库待分析。")

if __name__ == "__main__":
    run_spider()
