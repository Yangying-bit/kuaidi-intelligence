import os
import json
import traceback
from openai import OpenAI
from supabase import create_client, Client

# ==========================================
# 🌟 初始化：复用强力清洗逻辑
# ==========================================
raw_url = os.environ.get("SUPABASE_URL", "")
raw_key = os.environ.get("SUPABASE_KEY", "")
clean_url = raw_url.strip().strip('\'"').rstrip('/')
clean_key = raw_key.strip().strip('\'"')
supabase: Client = create_client(clean_url, clean_key)

client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

def analyze_with_deepseek(competitor, title, snippet):
    prompt = f"""
    你是一个资深且冷酷的物流行业商业情报分析师，专门为【快递100】公司服务。
    【强制规则】你必须死死盯住【{competitor}】的主体动作！哪怕文章提到快递100，也不能把快递100当主角分析。如果是自家公关稿或无效放假通知，直接给0分。

    监控目标竞对: {competitor}
    动态标题: {title}
    内容摘要: {snippet}

    请严格以单纯的 JSON 格式输出四个字段，绝对不要带任何 Markdown 代码块标记：
    {{
        "summary": "AI资讯总结 (提炼具体动作，50字内)",
        "score": 8,
        "analysis": "简要分析对快递100客户或API调用量的影响 (100字内)",
        "suggestion": "实操应对建议"
    }}
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            timeout=30
        )
        
        raw_content = response.choices[0].message.content.strip()
        
        # 🌟 核心防线：暴力扒掉大模型自带的 Markdown JSON 格式外衣
        if raw_content.startswith("```json"):
            raw_content = raw_content.replace("```json", "", 1)
        elif raw_content.startswith("```"):
            raw_content = raw_content.replace("```", "", 1)
            
        if raw_content.endswith("```"):
            raw_content = raw_content.rsplit("```", 1)[0]
            
        res = json.loads(raw_content.strip())
        return res.get("summary", snippet), res.get("score", 0), res.get("analysis", ""), res.get("suggestion", ""), True
        
    except Exception as e:
        print(f"⚠️ AI 接口分析崩溃，报错原因: {str(e)}")
        # 确保打印出错误时大模型到底吐出了什么乱码
        if 'raw_content' in locals():
            print(f"⚠️ 大模型原始返回值: {raw_content}")
        return snippet, 0, f"AI分析暂时失败: {str(e)}", "无", False

def run_ai_worker():
    print("🧠 启动大模型异步分析流水线...")
    response = supabase.table("news_v2").select("*").eq("process_status", 0).limit(1000).execute()
    pending_news = response.data
    
    if not pending_news:
        print("📭 当前数据库中没有待分析的情报。")
        return
        
    for news in pending_news:
        print(f"🤖 正在分析: {news['title'][:20]}...")
        
        try:
            summary, score, analysis, suggestion, is_success = analyze_with_deepseek(news['competitor'], news['title'], news['snippet'])
            
            if is_success:
                # 只有真正成功解析了 JSON，才打回数据库并赋予最高通行状态 process_status = 1
                supabase.table("news_v2").update({
                    "ai_score": score,
                    "ai_analysis": analysis,
                    "ai_suggestion": suggestion,
                    "snippet": summary,
                    "process_status": 1
                }).eq("id", news['id']).execute()
                print(f"   ✅ 分析成功并入库，打分：{score} 分")
            else:
                # 失败数据打上 -1 标记，防止它永远卡在 0 状态造成死循环，同时阻断它进入前端展示
                supabase.table("news_v2").update({
                    "process_status": -1,
                    "ai_analysis": "大模型处理异常，已强制跳过"
                }).eq("id", news['id']).execute()
                print(f"   ❌ 该条数据分析失败，已标记为受损状态 (-1)。")
                
        except Exception as e:
            print(f"   ❌ 更新数据库时发生致命崩溃：")
            traceback.print_exc()

    print("✅ 本轮 AI 处理流水线执行完毕！")

if __name__ == "__main__":
    run_ai_worker()
