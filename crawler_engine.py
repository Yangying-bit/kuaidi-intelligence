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

# 🌟 新增：多套浏览器伪装，防止高频搜索被封 IP
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36"
]

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
    """时间过滤器：扩大到过去 7 天"""
    if pub_time_str == "未知时间":
        return False
        
    try:
        pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.utcnow() + timedelta(hours=8)
        if timedelta(0) <= (now - pub_time) <= timedelta(days=7):
            return True
        return False
    except ValueError:
        recent_keywords = ['刚刚', '分钟', '小时', '今天', '昨天', '天前']
        if any(keyword in pub_time_str for keyword in recent_keywords):
            return True
        # 处理部分引擎只返回如 "2026-10-01" 格式的短日期
        if len(pub_time_str) == 10 and pub_time_str.count('-') == 2:
            try:
                pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d")
                now = datetime.now()
                if timedelta(0) <= (now - pub_time) <= timedelta(days=7):
                    return True
            except: pass
        return False

def clean_text_for_markdown(text):
    """清理抓取到的文本，防止特殊字符破坏 Markdown 渲染（解决无法跳转的问题）"""
    if not text:
        return ""
    text = text.replace('\n', ' ').replace('\r', '').strip()
    text = text.replace('[', '【').replace(']', '】')  # 防止破坏 markdown 超链接格式
    return text[:200]

def analyze_with_deepseek(competitor, title, snippet):
    """调用 DeepSeek 接口，进行深度业务情报分析"""
    prompt = f"""
    你是一个资深的物流行业商业情报分析师。请阅读以下竞对动态，并评估其对【快递100】业务的潜在威胁或机会。
    重点评估领域：寄件服务接口、上门取件API、企业快递管理SaaS、智选运力、同城急送、寄大件、国际寄件、线上支付、线下支付、商家寄件
    请敏锐捕捉：竞对在API接口升级、快递公司单价降价、企业大客户案例、价格补贴战、新接口发布、新解决方案发布等方面的动作。

    监控目标: {competitor}
    动态标题: {title}
    内容摘要: {snippet}

    请严格以 JSON 格式输出，必须且只能包含以下四个字段：
    1. "summary": AI资讯总结 (对内容摘要进行准确无误的提炼总结，消除网页乱码或冗余字眼，50字以内，语言精练)。
    2. "score": 影响程度打分 (整数，1-10分。1-4分为常规动态，5-7分为值得警惕，8-10分为严重威胁或重大商机)。
    3. "analysis": 简要分析竞对此举会如何影响我们的客户获客、激活、留存、API调用毛利或市场份额（100字以内，语义到位）。
    4. "suggestion": 给业务团队的实操建议（言简意赅，给出精细到具体动作的建议。例如降价应对、推出新方案或跟进新功能等）。
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
    """核心抓取引擎：三合一全网搜刮 (百度 + 必应 + 搜狗微信) - 已加入高级防封禁"""
    results = []
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    encoded_term = urllib.parse.quote(search_term)

    # 1. 百度新闻
    try:
        baidu_headers = headers.copy()
        baidu_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.baidu.com/"
        })
        resp = requests.get(f"https://www.baidu.com/s?rtt=4&bsst=1&cl=2&tn=news&word={encoded_term}", headers=baidu_headers, timeout=15)
        
        if "wappass.baidu.com" in resp.url or "安全验证" in resp.text:
            print(f" ⚠️ 百度触发安全验证拦截 [{search_term[:15]}...]，自动交由必应引擎处理")
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.find_all('h3')[:8]:
                a_tag = item.find('a')
                if a_tag:
                    title = clean_text_for_markdown(a_tag.text)
                    link = a_tag.get('href')
                    parent_div = item.parent
                    time_span = parent_div.find('span', class_='c-color-gray2') if parent_div else None
                    pub_time = time_span.text.strip() if time_span else "未知时间" 
                    snippet = parent_div.text.strip().replace(title, '')[:150] if parent_div else title
                    snippet = clean_text_for_markdown(snippet)
                    results.append({"title": title, "link": link, "time": pub_time, "snippet": snippet, "source": "百度"})
    except requests.exceptions.Timeout:
        pass
    except Exception as e:
        pass

    # 2. 必应新闻
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
                snippet = snippet_tag.text.strip() if snippet_tag else title
                snippet = clean_text_for_markdown(snippet)
                results.append({"title": title, "link": link, "time": pub_time, "snippet": snippet, "source": "必应"})
    except requests.exceptions.Timeout:
        pass
    except Exception as e:
        pass

    # 3. 搜狗微信
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
                snippet = snippet_tag.text.strip() if snippet_tag else title
                snippet = clean_text_for_markdown(snippet)
                results.append({"title": title, "link": link, "time": "今天", "snippet": snippet, "source": "微信公众号"})
    except requests.exceptions.Timeout:
        pass
    except Exception as e:
        pass

    return results


def run_crawler():
    """主控调度逻辑"""

    # 🌟 终极升级：同时绑定“官网域名”与“官方微信公众号名称”
    COMPETITOR_INFO = {
        "菜鸟": {"domain": "cainiao.com", "wechat": "菜鸟网络"},
        "快递鸟": {"domain": "kdniao.com", "wechat": "快递鸟"},
        "顺丰": {"domain": "sf-express.com", "wechat": "顺丰速运"},
        "京东物流": {"domain": "jdwl.com", "wechat": "京东物流"},
        "德邦": {"domain": "deppon.com", "wechat": "德邦快递"},
        "中通": {"domain": "zto.com", "wechat": "中通快递"},
        "圆通": {"domain": "yto.net.cn", "wechat": "圆通速递"},
        "韵达": {"domain": "yundaex.com", "wechat": "韵达速递"},
        "申通": {"domain": "sto.cn", "wechat": "申通快递"},
        "极兔": {"domain": "jtexpress.com.cn", "wechat": "极兔速递"}
    }
    
    COMPETITORS = list(COMPETITOR_INFO.keys()) + ["京东快递", "邮政"]
    
    SCENARIOS = ["同城急送", "同城配送", "同城急送","上门取件", "国际寄件", "大件快运", "寄大件","免开发寄件组件","寄件组件"]
    API_SYNONYMS = ["API", "接口", "对接", "开放平台"]
    INDEPENDENT_WORDS = [
        "电商退货","多地址发货","二手闲置交易","开放平台 寄件", "商家发货",
        "个人寄件", "商家寄件", "企业寄件", "线上支付", "线下支付","智选运力",
        "预充值" ,"快递单价", "快递价格", "快递行业","API","API价格","API服务",
    ]

    KEYWORDS = [f"{scene} {syn}" for scene in SCENARIOS for syn in API_SYNONYMS] + INDEPENDENT_WORDS

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 情报搜集中...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    new_count = 0

    # ==========================================
    # 模块 A：精准狙击 —— 官网 + 官方微信公众号
    # ==========================================
    for comp, info in COMPETITOR_INFO.items():
        print(f"\n📡 正在构建 [{comp}] 的精准检索矩阵...")
        
        domain = info["domain"]
        wechat = info["wechat"]
        
        # 前两个给百度/必应查官网，后一个专门给微信引擎查公众号文章！
        official_queries = [
            f"site:{domain} 接口 OR 开放平台 OR 服务",
            f"site:{domain} 新闻 OR 公告 OR 动态",
            f"{wechat} 接口 OR 新功能 OR 发布" # 🌟 新增：没有 site:，微信引擎能完美抓取官方公众号推文
        ]
        
        for q in official_queries:
            scraped_items = fetch_multi_engine(q)
            for item in scraped_items:
                if not is_recent_news(item['time']):
                    continue
                    
                cursor.execute("SELECT id FROM news_v2 WHERE url=?", (item['link'],))
                if cursor.fetchone() is None:
                    print(f"👉 [官方狙击] 捕获: {item['title'][:20]}... 交给AI")
                    ai_summary, score, analysis, suggestion = analyze_with_deepseek(f"{comp}(官方动向)", item['title'], item['snippet'])
                    cursor.execute('''
                        INSERT INTO news_v2 (publish_time, competitor, business, title, snippet, url, ai_score, ai_analysis, ai_suggestion)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (item['time'], comp, "官方动向", item['title'], ai_summary, item['link'], score, analysis, suggestion))
                    new_count += 1
                    conn.commit()
            time.sleep(random.uniform(2.0, 4.0))


    # ==========================================
    # 模块 B：执行全网舆情多引擎搜索循环 (含微信生态舆情)
    # ==========================================
    print("\n🌐 开始全网舆情多引擎矩阵扫描...")
    for comp in COMPETITORS:
        sampled_keywords = random.sample(KEYWORDS, 3) 
        for kw in sampled_keywords:
            search_term = f"{comp} {kw} -快递100"
            scraped_items = fetch_multi_engine(search_term)

            for item in scraped_items:
                if not is_recent_news(item['time']):
                    continue

                if item['link'] and item['link'].startswith("http") and "快递100" not in item['title']:
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
                        
            time.sleep(random.uniform(2.0, 4.0))

    conn.commit()
    conn.close()
    print(f"\n✅ 本轮抓取结束！双擎驱动共斩获 {new_count} 条核心情报。")

if __name__ == "__main__":
    init_db()
    
    print("=====================================================")
    print("🤖 GitHub Actions 触发：开始执行单次扫描任务")
    print("=====================================================")

    try:
        run_crawler()
        print("✅ 本次扫描任务顺利完成，自动退出程序。")
    except Exception as e:
        print(f"❌ 运行过程中发生全局崩溃: {e}")
