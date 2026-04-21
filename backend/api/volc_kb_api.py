"""
火山知识库：与 text.py 一致的两段式流程

1) POST https://<domain>/api/knowledge/service/chat（Bearer）
   使用顶级字段 query（本轮文本）、image_query（单图 URL/Base64，可选）、messages（仅文本多轮）；
   解析 data.result_list → 参考资料 + 拼 system 提示词（严格依据资料回答）。

2) 通义千问 DashScope 兼容接口流式生成：思考过程 + 正文（OpenAI SDK）。

环境变量：
  VOLC_KB_API_KEY、VOLC_KB_SERVICE_RESOURCE_ID  必填（检索）
  DASHSCOPE_API_KEY 或 GRAPHRAG_API_KEY        必填（生成）
  VOLC_KB_DOMAIN、VOLC_KB_TIMEOUT              可选
  VOLC_QWEN_MODEL、VOLC_QWEN_VL_MODEL            可选
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from backend.auth.jwt_handler import get_current_user
from backend.services.oss_service import upload_local_file
from backend.storage import competition_struct_storage

logger = logging.getLogger("contest_robot.volc_kb")

bp = Blueprint("volc_kb", __name__, url_prefix="/api/volc_kb")

DEFAULT_VOLC_DOMAIN = "api-knowledgebase.mlp.cn-beijing.volces.com"
VOLC_SERVICE_CHAT_PATH = "/api/knowledge/service/chat"

# 与 text.py 中 base_prompt 一致。说明：DashScope 无「思考语言」独立 API 参数，只能靠提示词约束 reasoning_content。
VOLC_KB_SYSTEM_PROMPT = """【语言-最高优先级】
你的全部内部思考、推理步骤、分析过程，必须**全程只使用简体中文**，**绝对禁止出现任何英文句子、英文标题、英文引导语**。
不允许出现 "Here's a thinking process"、"Analyze"、"Step" 等任何英文。
思考格式必须为：1.xxx 2.xxx 3.xxx，全程中文。

你是面向中国用户的智能竞赛客服机器人，请严格根据下面的参考资料回答问题，准确、简洁、不编造。

# 参考资料
{documents}
"""

# 缀在本轮 user 末尾，进一步压低英文思考概率（不写入多轮 history，仅当次请求有效）
_QWEN_CN_THINK_USER_SUFFIX = (
    "\n\n【本轮强制要求】内部思考全过程仅使用简体中文，不得出现任何英文句子。"
)


def _sanitize_reasoning_cn(s: str) -> str:
    """
    thinking 有时会混入英文元话术（如 'Final Check'、'Generating' 等）。
    为保证“推理过程”展示为简体中文，这里过滤掉包含英文字母的行。
    """
    txt = str(s or "")
    if not txt.strip():
        return ""
    lines = txt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: List[str] = []
    for ln in lines:
        if re.search(r"[A-Za-z]", ln):
            continue
        kept.append(ln)
    return "\n".join(kept)


def _is_basic_fact_query(q: str) -> bool:
    """识别“基础事实查询”问法（报名/官网/主办等）。"""
    s = (q or "").strip()
    if not s:
        return False
    # 排除明显的综合/统计/开放性问法，避免误走结构化
    if any(k in s for k in ("对比", "比较", "统计", "汇总", "归纳", "总结", "分析", "如何", "怎么", "建议", "方案")):
        return False
    return any(k in s for k in ("报名", "截止", "官网", "网址", "网站", "链接", "主办", "承办", "组织", "参赛对象", "资格"))


def _structured_basic_answer(message: str, competition_id: str) -> Optional[str]:
    """
    未开启深度思考时：若为基础事实查询且用户选择了具体赛事，则走结构化知识库（competition_structs）直接返回。
    """
    cid = (competition_id or "").strip()
    if not cid:
        return None
    row = competition_struct_storage.get_by_competition_id("CompetitionDataset", cid)
    if not row:
        return None
    full_name = (str(row.competition_system or "") + str(row.competition_name or "")).strip() or cid
    q = message or ""
    if any(k in q for k in ("官网", "网址", "网站", "链接")):
        v = (row.official_website or "").strip()
        return f"{full_name}的官网是{v}。" if v else f"{full_name}的官网未在结构化知识库中收录。"
    if any(k in q for k in ("报名", "截止", "报名时间", "截止时间")) or ("什么时候" in q and "报名" in q):
        v = (row.registration_time or "").strip()
        return f"{full_name}的报名时间是{v}。" if v else f"{full_name}的报名时间未在结构化知识库中收录。"
    if any(k in q for k in ("主办", "承办", "组织", "谁举办")):
        v = (row.organizer or "").strip()
        return f"{full_name}的组织单位是{v}。" if v else f"{full_name}的组织单位未在结构化知识库中收录。"
    if any(k in q for k in ("参赛对象", "资格", "谁能报", "谁能参加")):
        return f"{full_name}的参赛对象信息未在结构化知识库中单列，请在文档规则中查询。"
    return None


def _vl_synthetic_retrieve_reasoning(doc_count: int) -> str:
    """
    qwen-vl 兼容接口无法传 enable_thinking 时，用「检索过程」说明填充推理区，
    doc_count 随本轮 references 条数变化。
    """
    n = max(0, int(doc_count))
    return (
        f"1. 用户问题涉及竞赛规则查询，启动知识库检索\n"
        f"2. 从知识库中命中 {n} 篇相关参考资料\n"
        f"3. 对文档片段进行关键词匹配与内容筛选\n"
        f"4. 提取赛项、任务、规则等核心信息\n"
        f"5. 基于参考资料生成准确、不编造的回答"
    )


def _is_volc_vl_model(model: str) -> bool:
    return "qwen-vl" in (model or "").lower()


def _configured() -> bool:
    k = (os.getenv("VOLC_KB_API_KEY") or "").strip()
    sid = (os.getenv("VOLC_KB_SERVICE_RESOURCE_ID") or "").strip()
    return bool(k and sid)


def _dashscope_configured() -> bool:
    return bool(
        (os.getenv("DASHSCOPE_API_KEY") or os.getenv("GRAPHRAG_API_KEY") or "").strip()
    )


def _dashscope_api_key() -> str:
    return (os.getenv("DASHSCOPE_API_KEY") or os.getenv("GRAPHRAG_API_KEY") or "").strip()


def _qwen_text_model() -> str:
    return (os.getenv("VOLC_QWEN_MODEL") or "qwen3.5-plus").strip()


def _qwen_vision_model() -> str:
    return (os.getenv("VOLC_QWEN_VL_MODEL") or "qwen-vl-plus").strip()


def _service_chat_http_url() -> str:
    host = (os.getenv("VOLC_KB_DOMAIN") or DEFAULT_VOLC_DOMAIN).strip().rstrip("/")
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    return f"https://{host}{VOLC_SERVICE_CHAT_PATH}"


def _sse(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def generate_prompt_and_references_from_volc_data(data: dict) -> Tuple[str, List[dict]]:
    """
    与 text.py 的 generate_prompt_and_references 一致：从 data.result_list
    生成 system 提示词与前端参考资料（全文进模型，snippet 给列表展示）。
    """
    references: List[dict] = []
    docs_text = ""
    points = data.get("result_list") or []
    if not isinstance(points, list):
        points = []

    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            continue
        content = (point.get("content") or "").strip()
        if not content:
            continue
        doc_name = (point.get("doc_info") or {}).get("doc_name") or "未知文档"
        img_link = None
        atts = point.get("chunk_attachment")
        if isinstance(atts, list) and atts:
            att = atts[0]
            if isinstance(att, dict) and att.get("link"):
                img_link = att.get("link")
        seq = len(references) + 1
        references.append(
            {
                "seq": seq,
                "source_pdf": doc_name,
                "related_image": img_link,
                "content_snippet": content[:800],
            }
        )
        docs_text += f"【资料{seq}】{content}\n---\n"

    if not docs_text.strip():
        docs_text = "（当前检索未返回有效文档片段，请结合常识谨慎回答并说明依据不足。）\n"
    system_prompt = VOLC_KB_SYSTEM_PROMPT.format(documents=docs_text)
    return system_prompt, references


def _build_qwen_messages(
    system_prompt: str,
    history: List[Dict[str, Any]],
    message: str,
    image_urls: Optional[List[str]] = None,
    *,
    append_cn_thinking_hint: bool = True,
) -> List[Dict[str, Any]]:
    """多轮 + 本轮 user（可含图），供 DashScope 兼容接口。"""
    out: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for h in history or []:
        if not isinstance(h, dict):
            continue
        role = str(h.get("role", "")).strip().lower()
        if role not in ("user", "assistant"):
            continue
        c = h.get("content")
        if c is None:
            continue
        if isinstance(c, str):
            text = c.strip()
            if text:
                out.append({"role": role, "content": text})
        elif isinstance(c, list):
            out.append({"role": role, "content": c})
    suf = _QWEN_CN_THINK_USER_SUFFIX if append_cn_thinking_hint else ""
    urls = image_urls or []
    if urls:
        parts: List[Dict[str, Any]] = [{"type": "text", "text": message.strip() + suf}]
        for u in urls:
            parts.append({"type": "image_url", "image_url": {"url": u}})
        out.append({"role": "user", "content": parts})
    else:
        out.append({"role": "user", "content": message.strip() + suf})
    return out


def iter_dashscope_chat_stream(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    enable_thinking: bool,
) -> Generator[Tuple[str, str], None, None]:
    """
    流式读取 DashScope 兼容接口。yield ("reasoning", delta) 或 ("content", delta)。
    """
    from openai import OpenAI

    key = _dashscope_api_key()
    if not key:
        return

    client = OpenAI(
        api_key=key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    # qwen-vl-* 兼容接口在开启思考时易触发 thinking_budget 校验 400，故视觉模型不传 extra_body。
    # 纯文本模型仅传 enable_thinking，不传 thinking_budget（避免 0/非法值）。
    mlow = (model or "").lower()
    if enable_thinking and "qwen-vl" not in mlow:
        kwargs["extra_body"] = {"enable_thinking": True}

    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        rc = getattr(delta, "reasoning_content", None)
        if not rc and isinstance(delta, dict):
            rc = delta.get("reasoning_content")
        if rc:
            cleaned = _sanitize_reasoning_cn(str(rc))
            if cleaned:
                yield ("reasoning", cleaned)
        ct = getattr(delta, "content", None)
        if not ct and isinstance(delta, dict):
            ct = delta.get("content")
        if ct:
            yield ("content", str(ct))


def _build_volc_service_messages(
    history: List[Dict[str, Any]],
    message: str,
) -> List[Dict[str, Any]]:
    """仅文本的 messages，供火山 knowledge/service/chat（图片走顶级 image_query，不得放在 content 里）。"""
    out: List[Dict[str, Any]] = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        role = str(h.get("role", "")).strip().lower()
        if role not in ("user", "assistant"):
            continue
        c = h.get("content")
        if c is None:
            continue
        if isinstance(c, str):
            text = c.strip()
            if text:
                out.append({"role": role, "content": text})
        elif isinstance(c, list):
            chunks = []
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text":
                    t = (p.get("text") or "").strip()
                    if t:
                        chunks.append(t)
            if chunks:
                out.append({"role": role, "content": "\n".join(chunks)})

    out.append({"role": "user", "content": (message or "").strip()})
    return out


def _volc_default_query_param() -> Dict[str, Any]:
    raw = (os.getenv("VOLC_KB_QUERY_PARAM") or "").strip()
    if raw:
        try:
            o = json.loads(raw)
            return o if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            logger.warning("VOLC_KB_QUERY_PARAM 不是合法 JSON，已忽略")
    return {"get_attachment_link": True, "rerank_switch": True}


def _call_volc_knowledge_service_chat(
    messages: List[Dict[str, Any]],
    *,
    query: str,
    image_query: Optional[str] = None,
) -> Tuple[Any, Optional[str]]:
    api_key = (os.getenv("VOLC_KB_API_KEY") or "").strip()
    service_id = (os.getenv("VOLC_KB_SERVICE_RESOURCE_ID") or "").strip()
    url = _service_chat_http_url()
    payload: Dict[str, Any] = {
        "service_resource_id": service_id,
        "query": (query or "").strip(),
        "messages": messages,
        "stream": False,
    }
    iq = (image_query or "").strip()
    if iq:
        payload["image_query"] = iq
    qp = _volc_default_query_param()
    if qp:
        payload["query_param"] = qp
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": f"Bearer {api_key}",
    }
    to = float(os.getenv("VOLC_KB_TIMEOUT", "180"))
    rsp = requests.post(url, headers=headers, json=payload, timeout=to)
    if not rsp.ok:
        return None, (rsp.text or "")[:2000]
    try:
        return rsp.json(), None
    except json.JSONDecodeError:
        return None, (rsp.text or "")[:1500]


def _pdf_stem_from_source_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    if s.lower().endswith(".pdf"):
        s = s[:-4]
    return s.strip()


def _first_pdf_stem_from_refs(references: List[dict]) -> str:
    """依据列表顺序，第一条有效 source_pdf 的主文件名（无 .pdf）。"""
    for r in references or []:
        if not isinstance(r, dict):
            continue
        stem = _pdf_stem_from_source_name(str(r.get("source_pdf") or ""))
        if stem:
            return stem
    return ""


def _unique_pdf_stems_from_refs(references: List[dict]) -> List[str]:
    """参考资料里去重后的 PDF 主文件名（无 .pdf），顺序保留。"""
    seen: set[str] = set()
    out: List[str] = []
    for r in references or []:
        if not isinstance(r, dict):
            continue
        stem = _pdf_stem_from_source_name(str(r.get("source_pdf") or ""))
        if not stem:
            continue
        key = stem.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(stem)
    return out


def _norm_cid_key(s: str) -> str:
    t = (s or "").strip()
    if t.lower().endswith(".pdf"):
        t = t[:-4]
    return t.strip().casefold()


def _resolve_volc_competition_for_history(
    client_competition_id: str, references: List[dict]
) -> str:
    """
    写入历史的赛事标签：
    - 有检索依据时，优先用「第一条资料」的 PDF 名（与回答依据顺序一致），避免多 PDF 或所选与命中不一致时出现 '-'。
    - 仅当唯一命中 PDF 与前端所选赛事 id 规范化后一致时，保留前端传入的 competition_id 字符串。
    - 无任何有效 PDF 依据时，回退为前端所选（可为空）。
    """
    cc = (client_competition_id or "").strip()
    stems = _unique_pdf_stems_from_refs(references)
    first = _first_pdf_stem_from_refs(references)
    if not first:
        return cc
    if len(stems) == 1 and cc and _norm_cid_key(cc) == _norm_cid_key(stems[0]):
        return cc
    return first


_VOLC_CHITCHAT_SHORT = re.compile(
    r"^(你好|您好|嗨|哈喽|hi|hello|你是谁|你叫什么|在吗|在不在|谢谢|多谢|辛苦了|不客气|再见|拜拜|"
    r"早上好|晚上好|午安|好的|ok|OK|嗯|嗯嗯|哈哈)[！!。.…\s]*$",
    re.IGNORECASE,
)


def _is_volc_chitchat_for_tagging(message: str) -> bool:
    """后台列表引擎列：闲聊类标 llm（不额外调用 LLM，避免耗时）。"""
    t = (message or "").strip()
    if not t or len(t) > 100:
        return False
    if _VOLC_CHITCHAT_SHORT.match(t):
        return True
    if len(t) <= 18:
        for s in (
            "你好",
            "您好",
            "谢谢",
            "你是谁",
            "在吗",
            "再见",
            "早上好",
            "晚上好",
        ):
            if t == s or t.startswith(s + "！") or t.startswith(s + "!"):
                return True
    return False


_VOLC_CROSS_INTENT = re.compile(
    r"(哪些|多少种|对比|异同|综合|所有赛事|分别|不同点|相同点|区别|跨赛|多个赛事|列举|都有哪些|"
    r"相同之处|不同之处|哪几个|多项)",
)
_VOLC_HARD_INTENT = re.compile(
    r"(分析|归纳|总结|评价|为什么|如何准备|计划|建议|详细说明|深入|难点|挑战)",
)
_VOLC_ENTITY_INTENT = re.compile(
    r"(什么时候|何时|报名时间|评审|标准|规则|赛道|组别|费用|在哪|是否|有没有|叫什么|"
    r"多少分|截止|章程|赛制|主办单位|含金量)",
)


def _classify_volc_engine_for_history(
    message: str, references: List[dict], deep_think: bool
) -> str:
  
    if _is_volc_chitchat_for_tagging(message):
        return "llm"
    stems = _unique_pdf_stems_from_refs(references)
    n = len(stems)
    msg = (message or "").strip()
    if n > 1:
        return "graphrag"
    if n == 0:
        return "llm"
    if _VOLC_CROSS_INTENT.search(msg):
        return "graphrag"
    if deep_think:
        if _VOLC_HARD_INTENT.search(msg) or len(msg) > 220:
            return "hybrid"
        return "vidorag"
    if _VOLC_ENTITY_INTENT.search(msg):
        return "vidorag"
    return "structured"


def _normalize_image_urls(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for u in raw[:8]:
        s = str(u).strip()
        if s and s not in out:
            out.append(s)
    return out


def _volc_history_user_turn(message: str, image_urls: Optional[List[str]]) -> Dict[str, Any]:
    """多轮 history 中的 user 条：带可选附图 URL，供前端展示缩略图。"""
    iu = _normalize_image_urls(image_urls or [])
    turn: Dict[str, Any] = {"role": "user", "content": message}
    if iu:
        turn["image_urls"] = iu
    return turn


def _save_volc_question(
    user_id: int,
    message: str,
    answer: str,
    references: List[dict],
    competition_id: str,
    image_urls: Optional[List[str]] = None,
    reasoning: str = "",
    *,
    deep_think: bool = False,
) -> Optional[int]:
    from backend.storage import question_storage

    resolved_cid = _resolve_volc_competition_for_history(competition_id, references)
    display_engine = _classify_volc_engine_for_history(message, references, deep_think)

    iu = _normalize_image_urls(image_urls or [])
    # 与主站一致：是否带用户上传图 → visual / text，供历史与个人统计展示
    query_type = "visual" if iu else "text"
    basis = {
        "route": "volc_kb_dashscope_after_volc_retrieval",
        "references": references,
        "reasoning": (reasoning or "")[:100000],
        "image_urls": iu,
        "deep_think": bool(deep_think),
        "unique_pdf_count": len(_unique_pdf_stems_from_refs(references)),
        "resolved_competition_id": resolved_cid,
        "display_engine": display_engine,
    }
    try:
        q = question_storage.create(
            user_id=user_id,
            content=message,
            answer=answer,
            rewritten=None,
            query_type=query_type,
            competition_id=resolved_cid,
            answer_basis=json.dumps(basis, ensure_ascii=False),
            engine_source=display_engine,
            seeker_rounds=0,
            cache_key="",
        )
        return q.id
    except Exception:
        logger.exception("volc_kb 写入问答历史失败")
        return None


_ALLOWED_IMAGE_CT = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@bp.route("/upload_image", methods=["POST"])
def volc_kb_upload_image():
    """用户上传图片 → OSS → 公网 URL，供多模态 messages。"""
    user = get_current_user()
    if not user:
        return jsonify({"code": 401, "message": "请先登录"}), 401

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"code": 400, "message": "请选择图片文件"}), 400

    ct = (f.content_type or "").split(";")[0].strip().lower()
    if not ct and f.filename:
        fn = (f.filename or "").lower()
        if fn.endswith(".png"):
            ct = "image/png"
        elif fn.endswith(".webp"):
            ct = "image/webp"
        elif fn.endswith(".gif"):
            ct = "image/gif"
        elif fn.endswith((".jpg", ".jpeg")):
            ct = "image/jpeg"
    if not ct:
        return jsonify(
            {"code": 400, "message": "无法识别图片类型，请使用 jpg / png / webp / gif"}
        ), 400
    if ct not in _ALLOWED_IMAGE_CT:
        return jsonify({"code": 400, "message": f"不支持的图片类型: {ct}"}), 400

    raw = f.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        return jsonify({"code": 400, "message": "图片不能超过 8MB"}), 400
    if len(raw) < 16:
        return jsonify({"code": 400, "message": "文件无效"}), 400

    ext = ".jpg"
    if "png" in ct:
        ext = ".png"
    elif "webp" in ct:
        ext = ".webp"
    elif "gif" in ct:
        ext = ".gif"

    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, "wb") as wf:
            wf.write(raw)
        url = upload_local_file(path)
        if not url:
            return jsonify(
                {"code": 503, "message": "对象存储未配置或上传失败"}
            ), 503
        return jsonify({"code": 0, "message": "ok", "data": {"url": url}})
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


@bp.route("/chat", methods=["POST"])
def volc_kb_chat():
    if os.getenv("VOLC_KB_REQUIRE_AUTH", "1").lower() not in (
        "0",
        "false",
        "no",
    ):
        user = get_current_user()
        if not user:
            return jsonify({"code": 401, "message": "请先登录"}), 401
    else:
        user = get_current_user()

    data = request.get_json() or {}
    message = str(data.get("message", "")).strip()
    if not message:
        return jsonify({"code": 400, "message": "message 不能为空"}), 400

    history = data.get("history") if isinstance(data.get("history"), list) else []
    image_urls = _normalize_image_urls(data.get("image_urls"))
    # 火山检索：图片必须走顶级 image_query（单张 URL/Base64）；与 OpenAI messages 多模态无关
    iq_body = str(data.get("image_query") or "").strip()
    volc_image_query = iq_body or (image_urls[0] if image_urls else "")
    vision_urls = list(image_urls) if image_urls else (
        [volc_image_query] if volc_image_query else []
    )
    image_urls_for_storage = list(image_urls) if image_urls else (
        [volc_image_query] if volc_image_query else []
    )
    competition_id = str(data.get("competition_id") or "").strip()
    deep_think_flag = bool(data.get("deep_think"))

    raw_stream = data.get("stream")
    if raw_stream is None:
        want_sse = False
    elif isinstance(raw_stream, str):
        want_sse = raw_stream.strip().lower() in ("1", "true", "yes")
    else:
        want_sse = bool(raw_stream)
    if not want_sse and "text/event-stream" in (
        request.headers.get("Accept") or ""
    ).lower():
        want_sse = True

    # 闲聊 / 你是谁：不走检索通道，直接本地中文兜底
    if _is_volc_chitchat_for_tagging(message):
        ans = (
            "我是智能竞赛客服机器人，可以帮你查询竞赛规则、报名时间、官网入口等信息，也支持图文问答与多轮追问。"
            "你可以直接告诉我想问的赛事与问题。"
        )
        qid = None
        if user:
            qid = _save_volc_question(
                int(user["sub"]),
                message,
                ans,
                references=[],
                competition_id=competition_id,
                image_urls=image_urls_for_storage,
                reasoning="1. 识别为闲聊/寒暄\n2. 直接生成简短中文回复",
                deep_think=False,
            )
        new_history = list(history)
        new_history.append(_volc_history_user_turn(message, image_urls_for_storage))
        new_history.append({"role": "assistant", "content": ans})
        if len(new_history) > 40:
            new_history = new_history[-40:]
        if want_sse:
            def gen() -> Generator[str, None, None]:
                yield _sse({"type": "content", "delta": ans})
                yield _sse({"type": "done", "history": new_history, "question_id": qid})
            headers = {
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
            }
            return Response(stream_with_context(gen()), headers=headers)
        return jsonify(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "answer": ans,
                    "reasoning": "1. 识别为闲聊/寒暄\n2. 直接生成简短中文回复",
                    "references": [],
                    "history": new_history,
                    "question_id": qid,
                    "vision": bool(vision_urls),
                    "model": "local_chitchat",
                },
            }
        )

    # 基础事实查询：未开启深度思考时优先走结构化知识库（避免不必要的外部检索与生成）
    if not deep_think_flag:
        has_user_images = bool(vision_urls)
        if (not has_user_images) and _is_basic_fact_query(message):
            ans = _structured_basic_answer(message, competition_id)
            if ans:
                qid = None
                if user:
                    qid = _save_volc_question(
                        int(user["sub"]),
                        message,
                        ans,
                        references=[],
                        competition_id=competition_id,
                        image_urls=[],
                        reasoning="1. 识别为基础事实查询\n2. 命中结构化知识库字段\n3. 直接返回确定性结果",
                        deep_think=False,
                    )
                return jsonify(
                    {
                        "code": 0,
                        "message": "ok",
                        "data": {
                            "answer": ans,
                            "reasoning": "1. 识别为基础事实查询\n2. 命中结构化知识库字段\n3. 直接返回确定性结果",
                            "references": [],
                            "history": (history or [])
                            + [_volc_history_user_turn(message, [])]
                            + [{"role": "assistant", "content": ans}],
                            "question_id": qid,
                            "vision": False,
                            "model": "structured_kb",
                        },
                    }
                )

    # 与 text.py 一致：始终开启 enable_thinking，保证思考过程流式输出（deep_think 仍参与后台引擎标签）
    enable_thinking = True

    if not _configured():
        return jsonify(
            {
                "code": 503,
                "message": "未配置 VOLC_KB_API_KEY 或 VOLC_KB_SERVICE_RESOURCE_ID",
            }
        ), 503
    if not _dashscope_configured():
        return jsonify(
            {
                "code": 503,
                "message": "未配置 DASHSCOPE_API_KEY（通义生成回答所需，与 text.py 一致）",
            }
        ), 503

    has_user_images = bool(vision_urls)
    msgs = _build_volc_service_messages(history, message)
    llm_model = _qwen_vision_model() if has_user_images else _qwen_text_model()

    if want_sse:

        def generate_service() -> Generator[str, None, None]:
            with current_app.app_context():
                full_reason = ""
                full_answer = ""
                try:
                    body, err = _call_volc_knowledge_service_chat(
                        msgs,
                        query=message,
                        image_query=volc_image_query or None,
                    )
                    if err:
                        yield _sse(
                            {
                                "type": "error",
                                "message": "火山知识服务请求失败",
                                "detail": err,
                            }
                        )
                        return
                    volc_data = body.get("data") if isinstance(body, dict) else None
                    if not isinstance(volc_data, dict):
                        volc_data = {}
                    system_prompt, references = generate_prompt_and_references_from_volc_data(
                        volc_data
                    )
                    qwen_msgs = _build_qwen_messages(
                        system_prompt,
                        history,
                        message,
                        vision_urls if has_user_images else None,
                    )
                    yield _sse({"type": "references", "references": references})
                    yield _sse(
                        {
                            "type": "meta",
                            "vision": has_user_images,
                            "model": llm_model,
                        }
                    )
                    # VL 无法开启 enable_thinking：流式下发简要检索说明，供前端推理区展示（与深度思考开关无关）
                    if has_user_images and _is_volc_vl_model(llm_model):
                        syn = _vl_synthetic_retrieve_reasoning(len(references))
                        for line in syn.split("\n"):
                            rd = line + "\n"
                            full_reason += rd
                            yield _sse({"type": "reasoning", "delta": rd})
                    for kind, delta in iter_dashscope_chat_stream(
                        qwen_msgs,
                        model=llm_model,
                        enable_thinking=enable_thinking,
                    ):
                        if kind == "reasoning":
                            full_reason += delta
                            yield _sse({"type": "reasoning", "delta": delta})
                        else:
                            full_answer += delta
                            yield _sse({"type": "content", "delta": delta})
                    new_history = list(history)
                    new_history.append(
                        _volc_history_user_turn(message, image_urls_for_storage)
                    )
                    new_history.append({"role": "assistant", "content": full_answer})
                    if len(new_history) > 40:
                        new_history = new_history[-40:]
                    qid = None
                    if user:
                        qid = _save_volc_question(
                            int(user["sub"]),
                            message,
                            full_answer,
                            references,
                            competition_id,
                            image_urls=image_urls_for_storage,
                            reasoning=full_reason,
                            deep_think=deep_think_flag,
                        )
                    yield _sse(
                        {
                            "type": "done",
                            "history": new_history,
                            "question_id": qid,
                        }
                    )
                except Exception as e:
                    logger.exception("volc_kb chat stream")
                    yield _sse({"type": "error", "message": str(e)})

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        }
        # 勿用 direct_passthrough：开发服务器要求 write(bytes)，该选项会跳过 str→bytes 编码导致 AssertionError
        return Response(
            stream_with_context(generate_service()),
            headers=headers,
        )

    try:
        body, err = _call_volc_knowledge_service_chat(
            msgs,
            query=message,
            image_query=volc_image_query or None,
        )
        if err:
            return (
                jsonify(
                    {
                        "code": 502,
                        "message": "火山知识服务请求失败",
                        "data": {"detail": err},
                    }
                ),
                502,
            )
        volc_data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(volc_data, dict):
            volc_data = {}
        system_prompt, references = generate_prompt_and_references_from_volc_data(
            volc_data
        )
        qwen_msgs = _build_qwen_messages(
            system_prompt,
            history,
            message,
            vision_urls if has_user_images else None,
        )
        full_reason = ""
        full_answer = ""
        for kind, delta in iter_dashscope_chat_stream(
            qwen_msgs,
            model=llm_model,
            enable_thinking=enable_thinking,
        ):
            if kind == "reasoning":
                full_reason += delta
            else:
                full_answer += delta
        if (
            has_user_images
            and _is_volc_vl_model(llm_model)
            and not (full_reason or "").strip()
        ):
            full_reason = _vl_synthetic_retrieve_reasoning(len(references))
        new_history = list(history)
        new_history.append(_volc_history_user_turn(message, image_urls_for_storage))
        new_history.append({"role": "assistant", "content": full_answer})
        if len(new_history) > 40:
            new_history = new_history[-40:]
        qid = None
        if user:
            qid = _save_volc_question(
                int(user["sub"]),
                message,
                full_answer,
                references,
                competition_id,
                image_urls=image_urls_for_storage,
                reasoning=full_reason,
                deep_think=deep_think_flag,
            )
        return jsonify(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "answer": full_answer,
                    "reasoning": full_reason,
                    "references": references,
                    "history": new_history,
                    "question_id": qid,
                    "vision": has_user_images,
                    "model": llm_model,
                },
            }
        )
    except Exception as e:
        logger.exception("volc_kb chat")
        return jsonify({"code": 500, "message": str(e)}), 500


@bp.route("/status", methods=["GET"])
def status():
    return jsonify(
        {
            "code": 0,
            "data": {
                "configured": _configured(),
                "dashscope_configured": _dashscope_configured(),
                "domain": (os.getenv("VOLC_KB_DOMAIN") or DEFAULT_VOLC_DOMAIN).strip(),
            },
        }
    )
