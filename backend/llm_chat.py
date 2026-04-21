"""
多轮对话 LLM 服务（统一使用 Qwen）：归一化/截断历史，Agent 将多轮总结为单轮查询后交给 RAG 检索。
"""
import os
import logging
from typing import Optional
import json

from config.typo_fixes import COMMON_QUERY_TYPO_FIXES

from config.app_config import (
    CHAT_LLM_MODEL,
    MAX_HISTORY_TURNS,
    MAX_HISTORY_CHARS,

)
from backend.vidorag.agent.prompts import (
    SUMMARIZE_SYSTEM_PROMPT,
    HISTORY_LINK_SYSTEM_PROMPT,
    CHITCHAT_ANSWER_SYSTEM_PROMPT,
)
from backend.llm_utils import call_qwen
from backend.intent_router import (
    classify_query_type,
    classify_visual_need,
    classify_chitchat_need,
    classify_structured_intent,
    extract_structured_request,
)



logger = logging.getLogger("contest_robot.llm_chat")

def _fix_common_typos(text: str) -> str:
    """轻量纠错：只做少量高置信替换，避免误伤语义。"""
    t = (text or "").strip()
    if not t:
        return ""
    for k, v in (COMMON_QUERY_TYPO_FIXES or {}).items():
        if k in t:
            t = t.replace(k, v)
    return t


def _normalize_history(history: Optional[list]) -> list:
    """归一化历史：仅保留 user/assistant，content 转为 str。"""
    if not history or not isinstance(history, list):
        return []
    out = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = (item.get('role') or '').strip().lower()
        if role not in ('user', 'assistant'):
            continue
        content = item.get('content')
        if content is None:
            content = ''
        if not isinstance(content, str):
            content = str(content)
        out.append({'role': role, 'content': content.strip()})
    return out


def _truncate_history(history: list, max_turns: int, max_chars: int) -> list:
    """截断历史：优先保留最近 max_turns 轮，且总字符数不超过 max_chars。"""
    if not history:
        return []
    # 一轮 = user + assistant，按顺序保留最近的若干轮
    out = history[-max_turns * 2:] if len(history) > max_turns * 2 else list(history)
    total = sum(len(m['content']) for m in out)
    while total > max_chars and len(out) >= 2:
        out.pop(0)
        out.pop(0)
        total = sum(len(m['content']) for m in out)
    if total > max_chars and out:
        # 最后一条可截断
        last = out[-1]
        if len(last['content']) > max_chars:
            out = out[:-1]
            out.append({'role': last['role'], 'content': last['content'][-max_chars:]})
    return out


def _build_messages(system_prompt: str, history: list, user_request: str) -> list:
    """构建 API 消息列表：system + 多轮历史 + 本轮用户输入。"""
    messages = [{'role': 'system', 'content': system_prompt}]
    for m in history:
        messages.append({'role': m['role'], 'content': m['content']})
    messages.append({'role': 'user', 'content': user_request})
    return messages


def _call_qwen(messages: list) -> str:
    """统一使用 Qwen（DashScope）文本模型。"""
    return call_qwen(messages)


def _format_history_for_link(history: list) -> str:
    """将多轮历史压成可读文本，供关联性判断使用。"""
    lines = []
    for m in history:
        role = "用户" if (m.get("role") or "").lower() == "user" else "助手"
        c = (m.get("content") or "")[:4000]
        lines.append(f"{role}: {c}")
    return "\n".join(lines)


def _parse_history_linked(raw: str) -> Optional[bool]:
    """解析 {\"linked\": true/false}；失败返回 None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        from backend.vidorag.utils.parse_tool import extract_json

        j = extract_json(raw)
        if isinstance(j, dict) and "linked" in j:
            v = j["linked"]
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                s = v.strip().lower()
                if s in ("true", "1", "yes", "是"):
                    return True
                if s in ("false", "0", "no", "否"):
                    return False
    except Exception:
        pass
    compact = raw.replace(" ", "").lower()
    if '"linked":false' in compact or "'linked':false" in compact:
        return False
    if '"linked":true' in compact or "'linked':true" in compact:
        return True
    return None


def history_links_current_query(history: list, user_request: str) -> bool:
    """
    判断本轮输入是否与上文在同一检索话题链上延续。
    True：可多轮合并为单条检索句；False：仅使用本轮（以最新 query 为主）。
    解析失败时返回 False，宁可不合并历史、以本轮为准。
    """
    user_request = (user_request or "").strip()
    if not history or not user_request:
        return True
    blob = _format_history_for_link(history)
    messages = [
        {"role": "system", "content": HISTORY_LINK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"【对话历史】\n{blob}\n\n【本轮用户输入】\n{user_request}",
        },
    ]
    raw = _call_qwen(messages)
    linked = _parse_history_linked(raw)
    if linked is None:
        logger.warning(
            "历史关联解析失败，回退为 linked=false（不合并历史）: raw=%s",
            (raw or "")[:300],
        )
        return False
    logger.info("历史关联判定: linked=%s", linked)
    return linked


_IE_EXTRACT_SYSTEM_PROMPT = """你是专业的“赛事信息结构化抽取”助手。你将从用户提供的 PDF 文本/OCR 内容中抽取结构化字段。你必须严格按 JSON 输出，不添加任何解释性文字。

【输出 JSON（必须全部字段都输出，缺失填“无”，tracks 例外：无则 []）】
{
  "competition_name": "主赛事名称（尽量是总赛事名/主赛事名，不要把赛道/专项赛拼进来）",
  "tracks": ["赛道/专项赛/赛项名（数组，可多项）"],
  "organizer": "组织单位/主办单位（原文完整表述）",
  "official_website": "官网URL（必须是原文出现的完整 URL；若出现多个，优先选择主站/权威主域名那个）",
  "registration_time": "报名时间范围（如 2024年4月15日-5月15日；尽量抽取完整起止范围）",
  "publish_time": "发布时间/发布日期（如 2024年4月；无则填“无”）",
  "competition_category": "赛事分类（AI竞赛/数学建模/其他，严格三选一）",
  "session": "届次（如 第七届/第12届/第二十一届；无则填“无”）",
  "pdf_page": "证据页码（如果文本中带【第X页】或出现“第X页”，填对应；否则填“无”）"
}

【关键抽取规则（用于对齐业务正确答案）】
1) 主赛事名 vs 赛道拆分：
   - 如果文本同时包含“主赛事名（如：第七届全国青少年人工智能创新挑战赛）”和“某某专项赛/赛道/赛项名”，
     那么 competition_name 填主赛事名，tracks 把专项赛/赛道名填进去（不要把两者拼成一个长名字）。
   - 如果文档本身就是某个专项赛文件名/通知，但能识别其所属主赛事，仍按上面规则拆分。
2) 官网：
   - 只能输出原文出现的 URL，不要自行拼接。
   - 若出现多个 URL：优先选择“主站/权威域名”（例如比子域名更通用的官网入口）。
3) 时间：
   - registration_time 优先输出完整起止范围；连接符统一用 "-"（如原文是 “–/—” 也按原文提取后保留含义）。
4) 不得臆测：任何字段若原文没有出现，必须填“无”（tracks 例外填 []）。

【输出要求】
- 仅输出单行 JSON，不要输出任何额外文本。
"""


def extract_competition_structured(pdf_ocr_content: str) -> dict:
    """把 PDF/OCR 文本抽取成结构化 JSON（供结构化库、GraphRAG/ViDoRAG 元数据使用）。"""
    text = (pdf_ocr_content or "").strip()
    if not text:
        raise ValueError("PDF_OCR_CONTENT 为空")
    messages = [
        {"role": "system", "content": _IE_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    out = _call_qwen(messages)
    try:
        obj = json.loads(out)
    except Exception as e:
        raise RuntimeError(f"结构化抽取未返回有效 JSON: {e}; raw={out[:200]}")

    # 补齐字段，避免后续入库失败
    if not isinstance(obj, dict):
        raise RuntimeError("结构化抽取 JSON 不是 dict")
    obj.setdefault("competition_name", "无")
    if not isinstance(obj.get("tracks"), list):
        obj["tracks"] = []
    obj.setdefault("organizer", "无")
    obj.setdefault("official_website", "无")
    obj.setdefault("registration_time", "无")
    obj.setdefault("publish_time", "无")
    cat = str(obj.get("competition_category") or "其他").strip() or "其他"
    if cat not in ("AI竞赛", "数学建模", "其他"):
        cat = "其他"
    obj["competition_category"] = cat
    obj.setdefault("session", "无")
    obj.setdefault("pdf_page", "无")
    return obj


# NOTE: 意图识别已迁移至 backend.intent_router（本文件仅保留多轮总结/闲聊回答/抽取等能力）。


def answer_chitchat(query: str, history: Optional[list] = None) -> str:
    """闲聊直接回复：不走 RAG 检索。"""
    query = (query or "").strip()
    if not query:
        return ""
    hist = _truncate_history(_normalize_history(history), MAX_HISTORY_TURNS, MAX_HISTORY_CHARS)
    messages = _build_messages(CHITCHAT_ANSWER_SYSTEM_PROMPT, hist, query)
    return (_call_qwen(messages) or "").strip()


def summarize_multi_turn_to_single(
    history: Optional[list] = None,
    user_request: str = '',
) -> str:
    """
    Agent（Qwen）将多轮对话总结为一条单轮检索查询，供 RAG 使用。
    若无历史或仅一条当前输入，直接返回当前输入（去首尾空）。
    若有多轮历史：先判定本轮与历史是否同一检索话题；无关则**不合并**，直接以本轮为准。
    """
    user_request = _fix_common_typos((user_request or '').strip())
    if not user_request:
        return ''

    norm = _normalize_history(history)
    truncated = _truncate_history(norm, MAX_HISTORY_TURNS, MAX_HISTORY_CHARS)
    logger.info(
        "多轮→单轮: 原始历史条数=%s, 截断后条数=%s, 本轮输入长度=%s",
        len(norm), len(truncated), len(user_request),
    )

    if not truncated:
        logger.info("无多轮历史，直接使用本轮输入作为检索查询")
        return user_request

    if not history_links_current_query(truncated, user_request):
        logger.info("历史与本轮检索意图无关联，跳过多轮合并，以本轮输入为检索查询")
        return user_request

    messages = _build_messages(SUMMARIZE_SYSTEM_PROMPT, truncated, user_request)
    
    logger.info("发给 Qwen 的 messages 条数=%s, 最后一条(本轮)=%s", len(messages), (user_request[:100] + "..." if len(user_request) > 100 else user_request))
    single_query = _call_qwen(messages)
    single_query = _fix_common_typos((single_query or '').strip())
    logger.info("Agent 输出单轮检索查询: %s", single_query[:200] + "..." if len(single_query) > 200 else single_query)
    return single_query if single_query else user_request

