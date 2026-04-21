import json
import requests
from openai import OpenAI

# ===================== 配置 =====================
account_id = "被我删"
apikey = "e被我删e"
service_id = "被我删"
g_knowledge_base_domain = "被我删m"

model_name = "被我删s"
api_key = "被我删了"

query = "3D编程模型创新设计专项赛选拔赛的评审标准是什么？，？如何参赛，参赛需要做哪些准备工作。"

base_prompt = """
【语言-最高优先级】深度思考（推理链）与最终回答必须全程使用简体中文；不要用英文句子推理（代码、URL、文件名等原文可保留）。
你是面向中国用户的智能竞赛客服机器人，请严格根据下面的参考资料回答问题，准确、简洁、不编造。

# 参考资料
{documents}
"""

# DashScope 无单独「思考语言」API 参数，缀在用户消息后加强约束（与 backend volc_kb_api 一致）
_QWEN_CN_THINK_USER_SUFFIX = (
    "\n\n【本轮附加】请用简体中文完成内部推理与正式回答；推理过程不要用英文整句。"
)

# ===================== 解析知识库返回 =====================
def generate_prompt_and_references(rsp_txt):
    references = []
    if not rsp_txt:
        return "", references

    try:
        rsp = json.loads(rsp_txt)
    except:
        return "", references

    if rsp.get("code") != 0:
        return "", references

    docs_text = ""
    points = rsp.get("data", {}).get("result_list", [])

    for idx, point in enumerate(points):
        content = point.get("content", "").strip()
        if not content:
            continue

        doc_name = point.get("doc_info", {}).get("doc_name", "未知文档")
        img_link = None

        # 只取当前 chunk 对应的图片
        if "chunk_attachment" in point and point["chunk_attachment"]:
            att = point["chunk_attachment"][0]
            if att.get("type") == "image" and att.get("link"):
                img_link = att.get("link")

        # 这条就是“答案来源”的原始资料，直接保留
        references.append({
            "seq": idx + 1,
            "source_pdf": doc_name,
            "related_image": img_link,
            "content_snippet": content  # 给前端展示一小段
        })

        # 拼给模型的提示词
        docs_text += f"【资料{idx+1}】{content}\n---\n"

    final_prompt = base_prompt.format(documents=docs_text)
    return final_prompt, references

# ===================== 火山知识库检索 =====================
def knowledge_service_chat():
    url = f"https://{g_knowledge_base_domain}/api/knowledge/service/chat"
    payload = {
        "service_resource_id": service_id,
        "messages": [{"role": "user", "content": query}],
        "stream": False
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": f"Bearer {apikey}"
    }

    try:
        rsp = requests.post(url, json=payload, headers=headers, timeout=180)
        return rsp.text
    except Exception as e:
        print("检索出错：", e)
        return '{"code":-1,"data":{"result_list":[]}}'

# ===================== 通义千问流式输出 + 思考过程 =====================
def chat_completion(messages):
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    completion = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
        extra_body={"enable_thinking": True},
    )

    reasoning = ""
    answer = ""
    is_answering = False

    print("\n" + "=" * 20 + "🧠 思考过程" + "=" * 20 + "\n")

    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            print(delta.reasoning_content, end="", flush=True)
            reasoning += delta.reasoning_content

        if hasattr(delta, "content") and delta.content:
            if not is_answering:
                print("\n" + "=" * 20 + "✅ 最终回答" + "=" * 20 + "\n")
                is_answering = True
            print(delta.content, end="", flush=True)
            answer += delta.content

    print("\n")
    return reasoning, answer

# ===================== 主流程 =====================
def search_knowledge_and_chat_completion():
    print("🔍 正在检索知识库...")
    rsp_txt = knowledge_service_chat()

    print("🔧 正在解析答案来源资料...")
    prompt, answer_references = generate_prompt_and_references(rsp_txt)

    # ===================== 前端展示区 =====================
    print("\n" + "=" * 20 + "📎 答案来源资料（仅展示用到的）" + "=" * 20 + "\n")
    for ref in answer_references:
        print(f"来源 {ref['seq']}")
        print(f"PDF 文档：{ref['source_pdf']}")
        print(f"关联图片：{ref['related_image'] or '无'}")
        print("-" * 70)

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": query + _QWEN_CN_THINK_USER_SUFFIX},
    ]

    print("\n🤖 正在生成回答...\n")
    chat_completion(messages)

if __name__ == "__main__":
    search_knowledge_and_chat_completion()