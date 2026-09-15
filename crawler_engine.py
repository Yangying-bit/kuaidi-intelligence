import os
import time
import random
import urllib.parse
import sqlite3
import json
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

current_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(current_dir, "intelligence.db")

def init_db():
    """初始化轻量级数据库，新增 AI 评估字段"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS news_v2
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       publish_time TEXT,
                       competitor TEXT,
                       business TEXT,
                       title TEXT,
                       snippet TEXT,
                       url TEXT UNIQUE,
                       ai_score INTEGER,
                       ai_analysis TEXT,
                       ai_suggestion TEXT,
                       crawl_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                   )
                   ''')
    conn.commit()
    conn.close()

def is_recent_news(pub_time_str):
    """时间过滤器：扩大到 24 小时兜底"""
    try:
        pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.utcnow() + timedelta(hours=8)
        if timedelta(0) <= (now - pub_time) <= timedelta(hours=24):
            return True
        return False
    except ValueError:
        recent_keywords = ['刚刚', '分钟', '小时', '今天', '昨天']
        if any(keyword in pub_time_str for keyword in recent_keywords):
            return True
        return False

def analyze_with_deepseek(competitor, title, snippet):
    """调用 DeepSeek 接口，进行深度业务情报分析"""
    prompt = f"""
    你是一个资深的物流行业商业情报分析师。请阅读以下竞对动态，并评估其对【快递100】业务的潜在威胁或机会。
    重点评估领域：寄件API、企业快递管理SaaS、智选运力、同城急送、上门取件、寄大件、国际寄件
    请敏锐捕捉：竞对在API单价、企业大客户争夺、价格补贴战、新接口发布等方面的动作。

    监控目标: {competitor}
    动态标题: {title}
    内容摘要: {snippet}

    请严格以 JSON 格式输出，必须且只能包含以下四个字段：
    1. "summary": AI资讯总结 (对内容摘要进行准确无误的提炼总结，消除网页乱码或冗余字眼，50字以内，语言精练)。
    2. "score": 影响程度打分 (整数，1-10分。1-4分为常规动态，5-7分为值得警惕，8-10分为严重威胁或重大商机)。
    3. "analysis": 简要分析竞对此举会如何影响我们的客户留存、API调用利润或SaaS市场份额（100字以内，一针见血）。
    4. "suggestion": 给业务团队的实操建议（一句话，例如降价应对、推出组合拳或跟进新功能）。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("summary", snippet), result.get("score", 0), result.get("analysis", ""), result.get("suggestion", "")
    except Exception as e:
        print(f"⚠️ AI 分析遭遇波动: {e}")
        return snippet, 0, "AI分析暂时失败，稍后可手动重试", "无"

def fetch_multi_engine(search_term):
    """核心抓取引擎：三合一全网搜刮 (百度 + 必应 + 搜狗微信)"""
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
    encoded_term = urllib.parse.quote(search_term)

    # 1. 百度新闻
    try:
        resp = requests.get(f"https://www.baidu.com/s?rtt=4&bsst=1&cl=2&tn=news&word={encoded_term}", headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.find_all('h3')[:3]:
            a_tag = item.find('a')
            if a_tag:
                title = a_tag.text.strip()
                link = a_tag.get('href')
                parent_div = item.parent
                time_span = parent_div.find('span', class_='c-color-gray2') if parent_div else None
                pub_time = time_span.text.strip() if time_span else "今天"
                snippet = parent_div.text.strip().replace(title, '')[:150] if parent_div else title
                results.append({"title": title, "link": link, "time": pub_time, "snippet": snippet, "source": "百度"})
    except: pass

    # 2. 必应新闻
    try:
        resp = requests.get(f"https://cn.bing.com/news/search?q={encoded_term}&qft=interval%3d%224%22", headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.find_all('div', class_='news-card')[:3]:
            a_tag = item.find('a', class_='title')
            if a_tag:
                title = a_tag.text.strip()
                link = a_tag.get('href')
                time_span = item.find('span', tabindex="0")
                pub_time = time_span.text.strip() if time_span else "今天"
                snippet_tag = item.find('div', class_='snippet')
                snippet = snippet_tag.text.strip() if snippet_tag else title
                results.append({"title": title, "link": link, "time": pub_time, "snippet": snippet, "source": "必应"})
    except: pass

    # 3. 搜狗微信
    try:
        resp = requests.get(f"https://weixin.sogou.com/weixin?type=2&query={encoded_term}&tsn=1", headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.find_all('div', class_='txt-box')[:3]:
            a_tag = item.find('h3').find('a')
            if a_tag:
                title = a_tag.text.strip()
                href = a_tag.get('href')
                link = "https://weixin.sogou.com" + href if href.startswith('/') else href
                snippet_tag = item.find('p', class_='txt-info')
                snippet = snippet_tag.text.strip() if snippet_tag else title
                results.append({"title": title, "link": link, "time": "今天", "snippet": snippet, "source": "微信公众号"})
    except: pass

    return results

def fetch_kdniao_official():
    """升级版专属探针：多阵地巡回潜入快递鸟官网抓取一手公告"""
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
    
    # 🌟 核心升级：把单点变成了“网址监控池”
    # 你可以随时把在快递鸟官网上发现的各种“更新页面”网址加到这里面
    target_urls = [
        "https://www.kdniao.com/message/category/239",           # 公司新闻动态页
        "https://www.kdniao.com/message/category/80",         # 行业资讯
        "https://www.kdniao.com/message",     # 最新资讯
        "https://www.kdniao.com/message/category/11",  # 物流知识
        "https://www.kdniao.com/doc", # 文档中心
        "https://www.kdniao.com/" # 官网
    ]
    
    print(f"\n🦅 开始潜入快递鸟官网，共布控 {len(target_urls)} 个关键阵地...")
    
    for url in target_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            
            for item in soup.find_all('a'):
                link = item.get('href')
                title = item.text.strip()
                
                if link and len(title) > 6:
                    if link.startswith('/'):
                        link = "https://www.kdniao.com" + link
                        
                    # 放宽链接过滤条件，只要包含以下词根，大概率就是具体的文章或公告页
                    if any(keyword in link.lower() for keyword in ['news', 'article', 'notice', 'detail', 'update', 'log']):
                        results.append({
                            "title": f"【官网发布】{title}",
                            "link": link,
                            "time": "今天",
                            "snippet": f"来自快递鸟官网监测阵地: {url}", # 备注是从哪个阵地抓来的
                            "source": "快递鸟官网"
                        })
                        
            # 随机休息1秒，假装真人浏览，防止把竞对官网搞崩溃或被封IP
            time.sleep(random.uniform(1.0, 2.0))
            
        except Exception as e:
            # 就算这4个网址里有1个失效了，也不会报错，只会安静地去抓下一个
            print(f" ❌ 快递鸟官网阵地 ({url}) 抓取异常: {e}")
            continue
            
    # 全局简单去重（防止不同页面挂了同一篇公告）
    unique_results = []
    seen = set()
    for r in results:
        if r['link'] not in seen:
            seen.add(r['link'])
            unique_results.append(r)
            
    # 因为监控了多个页面，把获取上限从 3 条放宽到 8 条
    print(f" ✅ 快递鸟官网探测完成，共捕获 {len(unique_results[:8])} 条动态")
    return unique_results[:8]



def run_crawler():
    """主控调度逻辑"""

    COMPETITORS = ["菜鸟", "快递鸟", "顺丰", "京东快递", "德邦", "中通", "圆通", "韵达", "申通", "极兔", "邮政"]
    
    # 词槽 A：核心产品
    SCENARIOS = ["同城急送", "上门取件", "国际寄件", "大件快运", "寄大件","免开发 寄件组件"]
    
    # 词槽 B：技术接口同义词 (可以随时在这里补充，比如加上 "SDK" 或 "对接")
    API_SYNONYMS = ["API", "接口", "对接"]
    
    # 词槽 C：不需要组合的、独立的商业监控词
    INDEPENDENT_WORDS = [
        "电商退货","多地址发货","二手闲置交易","开放平台 寄件", "商家发货",
        "个人寄件", "商家寄件", "企业寄件", "线上支付", "线下支付","智选运力",
        "预充值" ,"快递单价", "快递价格", "快递行业","API","API价格","API服务",
    ]

    # 🪄 自动魔法组合 (利用 Python 列表推导式)：
    # 这行代码会自动帮你把场景和同义词拼起来，生成："同城急送 API", "同城急送 接口"...
    KEYWORDS = [f"{scene} {syn}" for scene in SCENARIOS for syn in API_SYNONYMS] + INDEPENDENT_WORDS

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 云端情报系统启动...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    new_count = 0

    # ==========================================
    # 模块 A：执行竞对官网专属探测任务
    # ==========================================
    official_items = fetch_kdniao_official()
    
    official_items.reverse()
    
    for item in official_items:
        cursor.execute("SELECT id FROM news_v2 WHERE url=?", (item['link'],))
        if cursor.fetchone() is None:
            print(f"👉 [{item['source']}] 捕获官网新情报: {item['title'][:20]}... 交给AI")
            ai_summary, score, analysis, suggestion = analyze_with_deepseek("快递鸟(官网更新)", item['title'], item['snippet'])
            cursor.execute('''
                           INSERT INTO news_v2 (publish_time, competitor, business, title, snippet, url, ai_score, ai_analysis, ai_suggestion)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', ("今天", "快递鸟", "官网更新", item['title'], ai_summary, item['link'], score, analysis, suggestion))
            new_count += 1
            conn.commit()
            time.sleep(random.uniform(1.5, 3.0))

    # ==========================================
    # 模块 B：执行全网多引擎搜索循环
    # ==========================================
    print("\n🌐 开始全网多引擎矩阵扫描...")
    for comp in COMPETITORS:
        for kw in KEYWORDS:
            search_term = f"{comp} {kw} -快递100"
            scraped_items = fetch_multi_engine(search_term)

            for item in scraped_items:
                # 时间过滤
                if not is_recent_news(item['time']):
                    continue

                if item['link'] and item['link'].startswith("http") and "快递100" not in item['title']:
                    # 数据库查重拦截
                    cursor.execute("SELECT id FROM news_v2 WHERE url=?", (item['link'],))
                    if cursor.fetchone() is None:
                        print(f"👉 [{item['source']}] 捕获新情报: [{comp} - {kw}] {item['title'][:15]}... 交给AI分析")
                        
                        ai_summary, score, analysis, suggestion = analyze_with_deepseek(f"{comp}({kw})", item['title'], item['snippet'])
                        
                        cursor.execute('''
                                       INSERT INTO news_v2 (publish_time, competitor, business, title, snippet, url, ai_score, ai_analysis, ai_suggestion)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                       ''', (item['time'], comp, kw, item['title'], ai_summary, item['link'], score, analysis, suggestion))
                        new_count += 1
                        conn.commit()
                        
            time.sleep(random.uniform(1.5, 3.0))

    conn.commit()
    conn.close()
    print(f"\n✅ 本轮抓取结束！双擎驱动共斩获 {new_count} 条核心情报。")

if __name__ == "__main__":
    init_db()
    run_crawler()

