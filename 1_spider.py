import os
import re
import time
import random
import urllib.parse
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import feedparser
from supabase import create_client, Client

# ==========================================
# 🌟 初始化 Supabase (带清洗防雷达)
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
    return re.sub(r'<[^>]+>', '', str(text)).replace('\n', ' ').strip()[:200]

# ==========================================
# 引擎 1：官网爬取 (爬竞对官网和开放平台)
# ==========================================
def fetch_official_html(domain, keyword):
    results = []
    # 使用 site: 语法，强制搜索引擎只在指定的竞对官网内寻找最新内容
    search_query = f"site:{domain} {keyword}"
    encoded_term = urllib.parse.quote(search_query)
    headers = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "zh-CN,zh;q=0.9"}
    
    # 使用 Bing 网页搜索，qdr=w 代表只搜过去 7 天内官网发生的变更
    url = f"https://cn.bing.com/search?q={encoded_term}&qdr=w" 
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        
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
                "time": "近期官网动态", "snippet": snippet
            })
    except Exception as e:
        print(f"官网爬取 ({domain}): {e}")
    return results

# ==========================================
# 引擎 2：全网 RSS 雷达 (搜索大盘新闻)
# ==========================================
def fetch_broad_rss(comp, keywords):
    results = []
    search_query = f"{comp} 快递"
    encoded_term = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_term}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]:
            title = clean_text(entry.title)
            snippet = clean_text(entry.get('summary', title))
            
            if "快递100" in title: continue

            # 判定是否命中我们关心的业务关键词
            matched_biz = "行业动态"
            for kw in keywords:
                if kw in title or kw in snippet:
                    matched_biz = kw
                    break

            pub_time_str = "最新抓取"
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_time_obj = datetime(*entry.published_parsed[:6])
                if datetime.utcnow() - pub_time_obj > timedelta(days=7):
                    continue
                pub_time_str = (pub_time_obj + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

            results.append({
                "title": title, "link": entry.link, "time": pub_time_str, 
                "snippet": snippet, "business": matched_biz
            })
    except Exception as e:
        print(f"RSS官网爬取 ({comp}): {e}")
    return results

# ==========================================
# 🌟 主控调度逻辑
# ==========================================
def run_spider():
    # 核心竞对及官方域名矩阵
    OFFICIAL_DOMAINS = {
        "顺丰":"sf-express.com","open.sf-express.com",
        "菜鸟":"cainiao.com","open.cainiao.com",
        "京东物流":"jdwl.com","open.jdl.com",
        "中通":"zto.com","open.zto.cn",
        "快递鸟":"kdniao.com",
        "申通":"sto.cn","open.sto.cn",
        "韵达":"yundaex.com","open.yundaex.com",
        "圆通":"yto.net.cn","open.yto.net.cn",
        "极兔":"jtexpress.cn","open.jtexpress.cn"
    }
    
    BROAD_COMPETITORS = list(OFFICIAL_DOMAINS.keys())
    API_KEYWORDS =  ["API", "接口", "开放平台", "涨价", "降价", "规则", "同城急送", 
                "大件","同城急送 API", "上门取件 接口", "国际寄件", "大件快运",
                "快递价格", "电商退货寄件","电商退货","多地址发货","二手闲置交易",
                "开放平台寄件", "商家发货","个人寄件", "商家寄件", "企业寄件",
                "线上支付","线下支付","智选运力","预充值","快递单价","快递价格",
                "快递行业","API价格","API服务]

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 启动混合双擎数据流水线...")
    new_count = 0

    # ---------------------------------------------------------
    # 动作 1：强搜竞对官网及开放平台 (精准打靶)
    # ---------------------------------------------------------
    print("\n🎯 开始潜入竞对官网及开放平台扫描...")
    for comp, domain in OFFICIAL_DOMAINS.items():
        target_kws = random.sample( ["API", "接口", "开放平台", "涨价", "降价", "规则", "同城急送", 
                "大件","同城急送 API", "上门取件 接口", "国际寄件", "大件快运",
                "快递价格", "电商退货 寄件",电商退货","多地址发货","二手闲置交易",
                "开放平台 寄件", "商家发货","个人寄件", "商家寄件", "企业寄件",
                "线上支付", "线下支付","智选运力","预充值" ,"快递单价", "快递价格",
                "快递行业","API价格","API服务], 2)
        for kw in target_kws:
            print(f"   -> 正在探测 {comp} 官网 ({domain}) : {kw}")
            items = fetch_official_html(domain, kw)
            for item in items:
                try:
                    supabase.table("news_v2").insert({
                        "publish_time": item['time'], "competitor": f"{comp}(官方网站)", "business": kw,
                        "title": item['title'], "snippet": item['snippet'], "url": item['link'],
                        "process_status": 0
                    }).execute()
                    new_count += 1
                    print(f"      ✅ [官网捕获] {item['title'][:20]}...")
                except: pass
            time.sleep(random.uniform(2.0, 4.0)) # 随机停顿防屏蔽

    # ---------------------------------------------------------
    # 动作 2：RSS 聚合搜刮全网行业大盘 (无视拦截)
    # ---------------------------------------------------------
    print("\n🌐 开始全网 RSS 订阅流扫描...")
    for comp in BROAD_COMPETITORS:
        print(f"   -> 正在拉取 {comp} 全网相关动态...")
        items = fetch_broad_rss(comp, API_KEYWORDS)
        for item in items:
            try:
                supabase.table("news_v2").insert({
                    "publish_time": item['time'], "competitor": comp, "business": item['business'],
                    "title": item['title'], "snippet": item['snippet'], "url": item['link'],
                    "process_status": 0
                }).execute()
                new_count += 1
                print(f"      ✅ [RSS捕获] {item['title'][:20]}...")
            except: pass
        time.sleep(1)

    print(f"\n✅ 混合双擎提取完毕！本次共斩获 {new_count} 条有效情报，已推送至云端待 AI 分析。")

if __name__ == "__main__":
    run_spider()
