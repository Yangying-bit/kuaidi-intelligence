import os
import json
from openai import OpenAI
from supabase import create_client, Client

supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

def analyze_with_deepseek(competitor, title, snippet):
    prompt = f"""
    你是一个资深且冷酷的物流行业商业情报分析师，专门为【快递100】公司服务。
    【强制规则】你必须死死盯住【{competitor}】的主体动作！哪怕文章提到快递100，也不能把快递100当主角分析。如果是自家公关稿或无效放假通知，直接给0分。

    监控目标竞对: {competitor}
    动态标题: {title}
    内容摘要: {snippet}

    请以 JSON 格式输出四个字段：
    1. "summary": AI资讯总结 (提炼具体动作，50字内)。
    2. "score": 影响打分 (1-10分，无效填0)。
    3. "analysis": 简要分析对快递100客户或API调用量的影响 (100字内)。
    4. "suggestion": 实操应对建议。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        res = json.loads(response.choices[0].message.content)
        return res.get("summary", snippet), res.get("score", 0), res.get("analysis", ""), res.get("suggestion", "")
    except Exception as e:
        print(f"⚠️ AI 波动: {e}")
        return snippet, 0, "AI分析暂时失败，稍后重试", "无"

def run_ai_worker():
    print("🧠 启动大模型异步分析流水线...")
    # 每次最多捞取 20 条没处理的数据
    response = supabase.table("news_v2").select("*").eq("process_status", 0).limit(20).execute()
    pending_news = response.data
    
    if not pending_news:
        print("📭 当前数据库中没有待分析的情报。")
        return
        
    for news in pending_news:
        print(f"🤖 正在分析: {news['title'][:20]}...")
        summary, score, analysis, suggestion = analyze_with_deepseek(news['competitor'], news['title'], news['snippet'])
        
        # 分析完打回数据库，状态改为 1 (完成)
        supabase.table("news_v2").update({
            "ai_score": score,
            "ai_analysis": analysis,
            "ai_suggestion": suggestion,
            "snippet": summary,
            "process_status": 1
        }).eq("id", news['id']).execute()
        
    print("✅ 本轮 AI 处理流水线执行完毕！")

if __name__ == "__main__":
    run_ai_worker()
