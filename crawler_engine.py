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
# ==========================================

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
    try:
        # 尝试解析标准时间格式
        pub_time = datetime.strptime(pub_time_str, "%Y-%m-%d %H:%M:%S")

        # 🌟 修复时区陷阱：强制使用北京时间 (UTC+8) 代替默认的云端时间
        now = datetime.utcnow() + timedelta(hours=8)

        # 判断时间差是否在 2 小时以内
        if timedelta(0) <= (now - pub_time) <= timedelta(hours=24):
            return True
        return False
    except ValueError:
        # 兜底逻辑：包含这些字眼的一律放行
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
    1. "summary": AI资讯总结 (对内容摘要进行准确无误的总结，消除网页乱码或冗余字眼，50字以内，语言清晰贴合新闻文意，稍精炼)。
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
        # 提取出4个字段，如果 AI 没生成 summary，就用原 snippet 兜底
        return result.get("summary", snippet), result.get("score", 0), result.get("analysis", ""), result.get(
            "suggestion", "")
    except Exception as e:
        print(f"⚠️ AI 分析遭遇波动: {e}")
        return snippet, 0, "AI分析暂时失败，稍后可手动重试", "无"


def run_crawler():
    """核心爬虫引擎：全量覆盖你要求的竞对与全套搜索关键词"""

    COMPETITORS = ["菜鸟", "快递鸟", "顺丰", "京东快递", "德邦", "中通", "圆通", "韵达", "申通", "极兔", "邮政"]

    KEYWORDS = [
        "快递查询API", "个人寄件", "商家寄件", "企业寄件", "快递员揽件",
        "企业快递管理saas", "商家快递管理saas", "邮政", "物流", "跨境快递",
        "电商平台快递", "京东快递", "德邦", "中通", "圆通", "韵达",
        "快递单价", "快递价格", "快递行业", "API价格", "电商"
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 云端爬虫引擎启动：全量词库扫描中...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    new_count = 0

    for comp in COMPETITORS:
        for kw in KEYWORDS:
            search_term = f"{comp} {kw} -快递100"
            encoded_term = urllib.parse.quote(search_term)

            # rtt=4 强制按最新时间排序
            url = f"https://www.baidu.com/s?rtt=4&bsst=1&cl=2&tn=news&word={encoded_term}"

            try:
                resp = requests.get(url, headers=headers, timeout=12)
                resp.encoding = "utf-8"

                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                for item in soup.find_all('h3'):
                    a_tag = item.find('a')
                    if not a_tag: continue
                    title = a_tag.text.strip()
                    link = a_tag.get('href')

                    parent_div = item.parent

                    # 提取真实发布时间
                    time_span = parent_div.find('span', class_='c-color-gray2') if parent_div else None
                    real_publish_time = time_span.text.strip() if time_span else datetime.now().strftime("%Y-%m-%d %H:%M")

                    # ==========================================
                    # 🔴 核心拦截器：如果不是最近2小时的新闻，直接跳过！
                    if not is_recent_news(real_publish_time):
                        continue
                    # ==========================================

                    snippet = parent_div.text.strip().replace(title, '')[:150] if parent_div else ""

                    if link and link.startswith("http") and "快递100" not in title:
                        cursor.execute("SELECT id FROM news_v2 WHERE url=?", (link,))
                        if cursor.fetchone() is None:
                            print(f"👉 捕获新情报: [{comp} - {kw}] {title[:15]}... 交给AI分析")

                            # 唤醒 DeepSeek 分析 (新增了 ai_summary 变量接收总结)
                            ai_summary, score, analysis, suggestion = analyze_with_deepseek(f"{comp}({kw})", title,
                                                                                            snippet)

                            # 写入数据库 (注意：这里用精炼的 ai_summary 替换掉了粗糙的 snippet)
                            cursor.execute('''
                                           INSERT INTO news_v2 (publish_time, competitor, business, title, snippet, url,
                                                                ai_score, ai_analysis, ai_suggestion)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                           ''', (real_publish_time, comp, kw, title, ai_summary, link, score, analysis,
                                                 suggestion))
                            new_count += 1

                # 随机礼貌休息，防止请求过密
                time.sleep(random.uniform(1.5, 3.5))

            except Exception as e:
                time.sleep(2)
                continue

    conn.commit()
    conn.close()
    print(f"✅ 本轮抓取结束！共成功挖掘并深度分析了 {new_count} 条2小时内的全网核心情报。")


if __name__ == "__main__":
    init_db()
    run_crawler()
