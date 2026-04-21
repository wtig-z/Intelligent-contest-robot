"""
问答服务：Vidorag + GraphRAG 双引擎串行融合。
流程：多轮时先判定「本轮与历史是否同一检索话题」→ 相关才多轮→单轮合并，否则以本轮为准 → 查询分类 → Vidorag → GraphRAG → 动态路由

结构化知识库（Golden / curated）原则：
- 单条 / 类属追问：先检索，仅取少量关键字段再进 LLM（见 qa_curated_helpers.CURATED_ROWS_FOR_LLM）。
- 命中 is_query_require_all：全量召回（仅关键字段），上限见 qa_curated_helpers.CURATED_FULL_LIST_HARD_CAP。
- 绝不把原始 PDF 全文或无关大段拼进 prompt。

模块分层：
- `config.qa_route_policy`：结构化捷径 vs RAG 的**策略层**（`deterministic_structured_kb_allowed`）。
- `curated_database_query`：Golden/TSV **模板层**（stat/basic 确定性拼接，见 `route_curated_query`）。
- `qa_curated_helpers`：`curated_structured` 检索、关键字段排版、与 RAG 融合 LLM。
- `config.qa_intent_keywords`：全量召回条数（`is_query_require_all`）、视觉问句兜底词（与路由策略独立）。
- 本文件：多轮总结、闲聊、chat 主流程（ViDoRAG / GraphRAG / 缓存 / 取消）。
"""

import json
import logging
import hashlib
import os
import re
from typing import List, Optional, Tuple

from config.app_config import DEFAULT_DATASET
from config.qa_intent_keywords import (
    VISUAL_QUERY_KEYWORDS_FALLBACK,
    is_query_require_all,
)
from config.qa_route_policy import deterministic_structured_kb_allowed
from config.math_modeling_undergrad_kb import (
    STANDARD_ANSWER_UNDERGRADUATE_MATH_MODELING,
    is_undergraduate_math_modeling_list_query,
)
from backend.llm_chat import (
    summarize_multi_turn_to_single,
    answer_chitchat,
)
from backend.intent_router import (
    classify_query_type,
    classify_visual_need,
    classify_chitchat_need,
    classify_structured_intent,
    extract_structured_request,
    rewrite_structured_query,
)
from backend.llm_utils import call_qwen, compress_graphrag_answer
from backend.vidorag.agent.prompts import (
    STRUCTURED_ANSWER_SYSTEM_PROMPT,
    SELECTED_PDF_CURATED_ANSWER_SYSTEM_PROMPT,
)
from backend.vidorag import ViDoRAGService
from backend.graphrag import GraphRAGService
from backend.services.oss_service import upload_images_to_oss
from backend.vidorag.utils.page_visual_detector import check_pdf_page
from backend.services.cancel_registry import raise_if_cancelled, CancelledError
from backend.storage import competition_struct_storage
from backend.vidorag.service import ViDoRAGModelNotReadyError
from backend.services.curated_database_query import (
    route_curated_query,
    try_curated_deterministic,
    legacy_row_to_enterprise,
    structured_kb_table,
)
from backend.services.qa_curated_helpers import (
    CURATED_ROWS_FOR_LLM,
    compose_with_curated,
    curated_facts_for_llm,
    curated_hit_for_selected_pdf,
    curated_match_rows,
    selected_pdf_hint,
)

_vidorag = ViDoRAGService()
_graphrag = GraphRAGService()
logger = logging.getLogger("contest_robot.qa_service")
_answer_cache: dict = {}

def _ensure_text(v) -> str:
    """
    确保写库/返回给前端的 answer 一定是字符串，避免 sqlite 绑定 dict 报错。

    约定：如果上游返回结构化 dict/list，这里要转换成“最终可读的 Markdown 排版内容”，
    而不是把 JSON 原样塞给用户或用代码块包起来。
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v

    def _md_from_obj(obj, level: int = 2) -> str:
        h = "#" * max(2, min(level, 4))
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj.strip()
        if isinstance(obj, (int, float, bool)):
            return str(obj)
        if isinstance(obj, list):
            lines = []
            for item in obj:
                t = _md_from_obj(item, level=level + 1).strip()
                if not t:
                    continue
                # 避免多行破坏列表缩进：把多行缩进到下一行
                t = t.replace("\n", "\n  ")
                lines.append(f"- {t}")
            return "\n".join(lines).strip()
        if isinstance(obj, dict):
            # 常见：{answer: "..."} 或 {通用路线:[...], 专项补强:{...}}
            if isinstance(obj.get("answer"), str) and obj.get("answer").strip():
                return obj.get("answer").strip()
            parts = []
            for k, val in obj.items():
                key = str(k).strip()
                if not key:
                    continue
                body = _md_from_obj(val, level=level + 1).strip()
                if not body:
                    continue
                if isinstance(val, (list, dict)):
                    parts.append(f"{h} {key}\n{body}")
                else:
                    parts.append(f"- {key}：{body}")
            return "\n\n".join(parts).strip()
        return str(obj)

    # 常见：VLM/Agent 返回结构化 dict/list
    if isinstance(v, dict):
        return _md_from_obj(v)
    if isinstance(v, (list, tuple)):
        return _md_from_obj(list(v))
    return str(v)

def _curated_answer_for_selected_pdf(req: dict, pdf_name: Optional[str]) -> str:
    """
    当用户已选择 pdf_name 且 LLM 抽取到了结构化 fields 时，用 pdf_name 做定向结构化知识库查询并回答。
    重要：这里不做任何关键词规则匹配，完全以 req.fields 为准。
    """
    if not pdf_name:
        return ""
    if not isinstance(req, dict):
        return ""
    row = curated_hit_for_selected_pdf(str(pdf_name))
    if not row:
        return ""

    def pick(field: str, default: str = "未找到") -> str:
        v = (row.get(field) or "").strip()
        return v if v and v != "无" else default

    req_fields = req.get("fields") or []
    if not isinstance(req_fields, list):
        req_fields = []

    comp = (row.get("competition_name") or "").strip()
    track = (row.get("track") or "/").strip()
    obj = comp + (("" if track in ("", "/") else track))

    # === 让 LLM 基于「结构化知识库单行记录」做语义去重与通顺整理（主路径）===
    try:
        hint = selected_pdf_hint(str(pdf_name)).strip()
        facts_lines = [
            "赛系\t赛名/赛道\t赛事类别\t发布时间\t报名时间\t组织单位\t官网\tid",
            "\t".join(
                [
                    str(row.get("competition_name") or ""),
                    str(row.get("track") or "/"),
                    str(row.get("category") or "无"),
                    str(row.get("publish_time") or "无"),
                    str(row.get("registration_time") or "无"),
                    str(row.get("organizer") or "无"),
                    str(row.get("official_website") or "无"),
                    str(row.get("id") or ""),
                ]
            ),
        ]
        facts = "\n".join(facts_lines)
        user = (
            f"用户问题：{str(req.get('_original_query') or '').strip()}\n"
            f"抽取字段：{json.dumps(req_fields, ensure_ascii=False)}\n"
            f"{(hint + chr(10)) if hint else ''}"
            f"结构化知识库（一行）：\n{facts}\n"
        ).strip()
        out = (call_qwen([{"role": "system", "content": SELECTED_PDF_CURATED_ANSWER_SYSTEM_PROMPT},
                          {"role": "user", "content": user}]) or "").strip()
        if out:
            return out
    except Exception:
        pass

    # === 兜底：将抽取字段映射为知识库行字段（模板拼接，仅在 LLM 失败时使用）===
    fields: list[tuple[str, str]] = []
    for f in req_fields:
        ff = str(f or "").strip()
        if not ff:
            continue
        if ff == "name":
            fields.append(("名称", obj or "未找到"))
        elif ff == "official_website":
            fields.append(("官网", pick("official_website")))
        elif ff == "organizer":
            fields.append(("组织单位", pick("organizer")))
        elif ff == "registration_time":
            fields.append(("报名时间", pick("registration_time")))
        elif ff == "session":
            fields.append(("发布时间", pick("publish_time")))
        elif ff == "competition_category":
            fields.append(("赛事类别", pick("category")))
        elif ff == "tracks":
            # 赛道：定向场景下就是当前 track
            fields.append(("赛名/赛道", (track if track else "/")))

    if not fields:
        return ""
    if len(fields) == 1:
        k, v = fields[0]
        if k == "名称":
            return v
        return f"{obj}的{k}是{v}。"
    # 多字段：用表格
    lines = ["| 赛事 | 字段 | 值 |", "|---|---|---|"]
    for k, v in fields:
        lines.append(f"| {obj} | {k} | {v} |")
    return "\n".join(lines).strip()


_GRAPHRAG_DEV_MARKER_RE = re.compile(
    r"\s*\[Data:\s*[^\]]*\]\s*",
    re.IGNORECASE,
)


def _clean_graphrag_answer(text: str) -> str:
    """
    GraphRAG 的提示词示例里会要求模型在句末输出形如：
      [Data: Sources (...), Reports (...), Date_Range (...)]
    这对普通用户无意义且可能动态变化，属于开发者调试/溯源标记，统一从最终回答中移除。
    """
    t = (text or "").strip()
    if not t:
        return ""
    # 1) 移除中括号 Data: ... 标记（可能出现在句中或独立一行）
    t = _GRAPHRAG_DEV_MARKER_RE.sub(" ", t)
    # 2) 清理多余空白
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _infer_competition_id(pdf_name: Optional[str], images: List[str]) -> str:
    """
    当用户未在前端显式选择赛事（pdf_name 为空），但检索结果已经明显落在某一赛事 PDF 上时，
    尝试从图片路径中推断出 competition_id，便于历史检索按“赛事”维度过滤。

    约定：图片文件名形如：
      07_1_竞技机器人专项赛_1.jpg
    则 competition_id 推断为：
      07_1_竞技机器人专项赛
    """
    if pdf_name:
        return str(pdf_name).strip()
    for p in images or []:
        base = os.path.basename(p)
        stem = base.rsplit(".", 1)[0] if "." in base else base
        parts = stem.split("_")
        # 末尾带页码的情况：xxx_12
        if len(parts) >= 2 and parts[-1].isdigit():
            return "_".join(parts[:-1])
        if stem:
            return stem
    return ""


def _image_path_to_ref(path: str, oss_url: str = None) -> dict:
    """将图片路径转为前端可用的 { url, file, page }。oss_url 由上传后获得。"""
    base = os.path.basename(path)
    stem = base.rsplit(".", 1)[0] if "." in base else base
    parts = stem.split("_")
    page = 1
    if len(parts) >= 2 and parts[-1].isdigit():
        try:
            page = int(parts[-1])
        except ValueError:
            pass
    ref = {"file": base, "page": page}
    if oss_url:
        ref["url"] = oss_url
    return ref


def _has_visual_content(images: List[str]) -> bool:
    """
    判断召回页面是否存在“需要视觉证据”的内容（表格/图片）。

    注意：不要用“只要有图片就算视觉”的粗规则，因为 HybridSearchEngine 天生返回 ImageNode，
    这会导致几乎所有问题都被误标为 visual。
    """
    if not images:
        return False
    # 抽样检测前几页，避免每次都对大量页面做 OpenCV 分析造成开销。
    for img_path in images[:8]:
        try:
            flags = check_pdf_page(img_path)
            if flags.get("has_table") or flags.get("has_image"):
                return True
        except Exception:
            continue
    return False


def _is_visual_query(query: str) -> bool:
    """判断用户问题是否明确需要视觉证据（优先用 Qwen 判断，失败再关键词兜底）。"""
    try:
        return bool(classify_visual_need(query))
    except Exception:
        q = (query or "").strip().lower()
        if not q:
            return False
        return any(k in q for k in VISUAL_QUERY_KEYWORDS_FALLBACK)


def _compute_cache_key(
    query: str,
    contest_id: Optional[str],
    *,
    deep_think: bool = False,
    answer_format: str = "detailed",
) -> str:
    """问答缓存键：须包含会影响最终答案产出的偏好（深度思考 / 详略），否则会错误复用上一模式的结果。"""
    af = (answer_format or "detailed").strip() or "detailed"
    raw = f"{query}||{contest_id or ''}||dt={int(bool(deep_think))}||af={af}"
    return hashlib.md5(raw.encode()).hexdigest()


def _normalize_contest_scope(
    pdf_name: Optional[str],
    contest_ids: Optional[List[str]],
) -> Tuple[Optional[List[str]], str]:
    """解析前端传入的赛事范围：单 id、contest_ids 列表或全库（空）。"""
    if contest_ids is not None:
        scope = [str(x).strip() for x in contest_ids if str(x).strip()]
        if not scope:
            scope = None
    elif pdf_name and str(pdf_name).strip():
        scope = [str(pdf_name).strip()]
    else:
        scope = None
    cache_seg = ",".join(sorted(scope)) if scope else ""
    return scope, cache_seg


def chat(
    message: str,
    history: Optional[List[dict]] = None,
    request_id: Optional[str] = None,
    pdf_name: Optional[str] = None,
    contest_ids: Optional[List[str]] = None,
    user_prefs: Optional[dict] = None,
) -> dict:
    """
    双引擎融合流程（智能路由版）：
    1. 多轮→单轮总结
    2. LLM 分类查询类型 → basic/local/global
    3. Vidorag 全流程检索 + Agent 推理
    4. GraphRAG 精准单级检索（按分类结果，不再三级全跑）
    5. 动态答案路由：视觉内容→Vidorag，纯文本→GraphRAG
    """
    user_prefs = user_prefs or {}
    deep_think = bool(user_prefs.get("deep_think"))
    answer_format_pref = str(user_prefs.get("answer_format") or "detailed").strip() or "detailed"
    contest_scope, contest_cache_seg = _normalize_contest_scope(pdf_name, contest_ids)
    pdf_name = contest_scope[0] if contest_scope and len(contest_scope) == 1 else None
    multi_contest_scope = contest_scope if contest_scope and len(contest_scope) > 1 else None
    competition_id_out = ",".join(contest_scope) if contest_scope else ""
    logger.info(
        "chat 入参: message长度=%s, history条数=%s, contest_scope=%s",
        len(message),
        len(history or []),
        contest_scope or "<all>",
    )
    current_query = (message or "").strip()
    # 若该 request 已被后续请求取消，直接快速返回
    try:
        raise_if_cancelled(request_id)
    except CancelledError:
        return {
            # 取消语义：丢弃中间结果，仅返回 cancelled 状态，不产生副作用
            "answer": "",
            "images": [],
            "image_refs": [],
            "image_dataset": DEFAULT_DATASET,
            "rewritten": "",
            "history": list(history or []) + [{'role': 'user', 'content': message}],
            "engine_source": "none",
            "query_type": "text",
            "answer_basis": "",
            "seeker_rounds": 0,
            "competition_id": competition_id_out,
            "cache_key": "",
            "status": "cancelled",
        }

    # === 缓存 key（问句 + 赛事 + 深度思考 + 详略；避免切换开关仍命中旧答案）===
    cache_key = _compute_cache_key(
        current_query,
        contest_cache_seg or None,
        deep_think=deep_think,
        answer_format=answer_format_pref,
    )

    # 注：原先这里有“谢谢/你是谁”类的关键词秒回短路。
    # 现在统一交给 LLM 的闲聊识别与回答链路处理，避免堆叠规则与提示词体系冲突。

    # === 前置：闲聊识别仅看本轮原句（避免 history 改写影响） ===
    try:
        if classify_chitchat_need(current_query):
            final_answer = _ensure_text(answer_chitchat(message, history=history))
            if not final_answer:
                final_answer = "你好呀，有什么我可以帮你的？"
            new_history = list(history or [])
            new_history.append({'role': 'user', 'content': message})
            new_history.append({'role': 'assistant', 'content': final_answer})
            result = {
                'answer': final_answer,
                'images': [],
                'image_refs': [],
                'image_dataset': DEFAULT_DATASET,
                'rewritten': current_query,
                'history': new_history,
                'engine_source': 'llm',
                'query_type': 'chitchat',
                'answer_basis': json.dumps({'route': 'chitchat_llm_current_query'}, ensure_ascii=False),
                'seeker_rounds': 0,
                'competition_id': competition_id_out,
                'cache_key': cache_key,
            }
            _answer_cache[cache_key] = {k: v for k, v in result.items() if k != 'history'}
            return result
    except Exception:
        pass

    # === 结构化知识库：基础信息 / 统计分析 — 确定性查表，不经答案 LLM ===
    # 综合类问法在 route_curated_query 内已统一拦截为 open
    try:
        cr_kind = route_curated_query(current_query)
        single_ent = None
        if pdf_name and cr_kind == "basic":
            hit_pdf = curated_hit_for_selected_pdf(str(pdf_name))
            if hit_pdf:
                single_ent = legacy_row_to_enterprise(hit_pdf)
        det_ans = try_curated_deterministic(
            current_query,
            cr_kind,
            structured_kb_table(),
            single_row=single_ent,
        )
        if det_ans:
            new_history = list(history or [])
            new_history.append({"role": "user", "content": message})
            new_history.append({"role": "assistant", "content": det_ans})
            result = {
                "answer": det_ans,
                "images": [],
                "image_refs": [],
                "image_dataset": DEFAULT_DATASET,
                "rewritten": current_query,
                "history": new_history,
                "engine_source": "structured_kb",
                "query_type": "text",
                "answer_basis": json.dumps(
                    {"route": "structured_knowledge_base", "kind": cr_kind},
                    ensure_ascii=False,
                ),
                "seeker_rounds": 0,
                "competition_id": competition_id_out,
                "cache_key": cache_key,
            }
            _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
            return result
    except Exception as e:
        logger.warning("structured_knowledge_base 确定性查询失败（忽略，走后续流程）: %s", e, exc_info=True)

    # === STRUCTURED（企业解耦版）：路由/抽取仅看“本轮用户原始问句” ===
    # 注意：不使用 history，不使用改写后的 single_query，彻底切断 history 对结构化路由的干扰。
    # 已选赛事的“定向结构化回答”不再用关键词判断，而是等 LLM 抽取 req 后再决定是否可直接用知识库行回答。

    try:
        is_structured = classify_structured_intent(current_query)
    except Exception:
        is_structured = False

    # === CURATED-FIRST：在跑 ViDoRAG/GraphRAG 之前，优先用结构化知识库直接回答 ===
    # 目的：让“领域类列表/对比”问题（如：数学建模类竞赛有哪些）稳定输出，不被单个 PDF 的 RAG 结果带偏。
    # 原则：只要能从结构化知识库生成非“未找到”的答案，就直接返回；否则再走后续 RAG。
    # 综合/综述类问法不走本分支（避免残缺答）。
    if deterministic_structured_kb_allowed(current_query):
        try:
            _full_cat = is_query_require_all(current_query)
            curated_pre_hits = curated_match_rows(current_query, full_catalog=_full_cat)
            if curated_pre_hits:
                facts = curated_facts_for_llm(curated_pre_hits, full_catalog=_full_cat)
                # 用抽取器辅助判断是否更像“结构化字段/列表/枚举”，避免把长文本规则题提前截断
                req_pre = {}
                try:
                    structured_query_pre = rewrite_structured_query(current_query)
                    req_pre = extract_structured_request((structured_query_pre or current_query).strip())
                except Exception:
                    req_pre = {}

                intent_pre = str((req_pre or {}).get("intent") or "").strip().lower()
                wants_enum_pre = bool((req_pre or {}).get("wants_enumeration"))
                fields_pre = (req_pre or {}).get("fields") or []
                if not isinstance(fields_pre, list):
                    fields_pre = []

                # 仅当抽取器认为是 list/fields/count 或 wants_enumeration，才走 curated-first，
                # 避免把“规则条款/流程/评审”类长文本问题误判为可结构化回答。
                if intent_pre in ("list", "fields", "count") or wants_enum_pre or bool(is_structured):
                    system = STRUCTURED_ANSWER_SYSTEM_PROMPT
                    user = f"用户问题：{current_query}\n\n答案来源：\n{facts}"
                    ans0 = (call_qwen([{"role": "system", "content": system}, {"role": "user", "content": user}]) or "").strip()
                    ans0_norm = (ans0 or "").strip()
                    if ans0_norm and ans0_norm not in (
                        "未找到该信息",
                        "未找到该信息。",
                        "未在结构化知识库中找到该信息",
                        "未在结构化知识库中找到该信息。",
                    ):
                        new_history = list(history or [])
                        new_history.append({"role": "user", "content": message})
                        new_history.append({"role": "assistant", "content": ans0_norm})
                        result = {
                            "answer": ans0_norm,
                            "images": [],
                            "image_refs": [],
                            "image_dataset": DEFAULT_DATASET,
                            "rewritten": current_query,
                            "history": new_history,
                            "engine_source": "structured",
                            "query_type": "text",
                            "answer_basis": json.dumps(
                                {
                                    "structured": {
                                        "route": "curated_first",
                                        "matched": len(curated_pre_hits),
                                        "req": req_pre,
                                        "route_query": current_query,
                                    }
                                },
                                ensure_ascii=False,
                            ),
                            "seeker_rounds": 0,
                            # 若用户在前端已选择赛事范围（单赛事/多赛事），必须写入历史，便于“历史记录”页展示与筛选
                            "competition_id": competition_id_out,
                            "cache_key": cache_key,
                        }
                        _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
                        return result
        except Exception as e:
            logger.warning("CURATED-FIRST 失败（忽略，回退到后续 RAG/STRUCTURED 流程）: %s", e, exc_info=True)

    # 若已选择赛事（pdf_name），先让 LLM 抽取字段意图，然后尝试用“该赛事对应的知识库行”定向回答。
    if pdf_name and deterministic_structured_kb_allowed(current_query):
        try:
            structured_query = rewrite_structured_query(current_query)
            # 关键：把“已选赛事”的 competition_id + (赛系/赛名) 显式提供给抽取器，
            # 让 LLM 稳定理解“这/这个比赛/它”指的是当前选中赛事。
            req_input0 = (structured_query or current_query).strip()
            hint0 = selected_pdf_hint(str(pdf_name)).strip()
            if hint0:
                req_input0 = req_input0 + "\n\n" + hint0
            req0 = extract_structured_request(req_input0)
            # 让定向回答器能拿到原始问句做语义理解（不影响抽取 schema）
            try:
                if isinstance(req0, dict) and "_original_query" not in req0:
                    req0["_original_query"] = current_query
            except Exception:
                pass
            fields0 = req0.get("fields") or []
            if not isinstance(fields0, list):
                fields0 = []
            if req0.get("intent") in ("fields", "list") or fields0:
                # 用 pdf_name -> DB -> curated_id 精确定位知识库行
                row = curated_hit_for_selected_pdf(str(pdf_name))
                if row:
                    # 把 fields 交给“定向回答器”去出答案；若 fields 空，则按原逻辑返回空继续走 RAG
                    # 这里直接复用 _curated_answer_for_selected_pdf 的输出格式（Markdown/句子）
                    ans = (_curated_answer_for_selected_pdf(req0, pdf_name) or "").strip()
                    if ans:
                        new_history = list(history or [])
                        new_history.append({"role": "user", "content": message})
                        new_history.append({"role": "assistant", "content": ans})
                        result = {
                            "answer": ans,
                            "images": [],
                            "image_refs": [],
                            "image_dataset": DEFAULT_DATASET,
                            "rewritten": structured_query or current_query,
                            "history": new_history,
                            "engine_source": "structured",
                            "query_type": "text",
                            "answer_basis": json.dumps(
                                {"structured": {"route": "selected_pdf_curated_llm", "pdf_name": pdf_name, "req": req0, "route_query": current_query}},
                                ensure_ascii=False,
                            ),
                            "seeker_rounds": 0,
                            "competition_id": competition_id_out,
                            "cache_key": cache_key,
                        }
                        _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
                        return result
        except Exception:
            pass

    if is_structured and deterministic_structured_kb_allowed(current_query):
        try:
            # STRUCTURED：先把问句改写成更利于抽取的标准格式（失败则回退原句）
            structured_query = rewrite_structured_query(current_query)
            req_input = (structured_query or current_query).strip()
            # 若用户选了赛事但仍走 STRUCTURED（例如“报名时间分别是什么”），同样把选中赛事提示给抽取器
            if pdf_name:
                hint = selected_pdf_hint(str(pdf_name)).strip()
                if hint:
                    req_input = req_input + "\n\n" + hint
            req = extract_structured_request(req_input)
            scope = (req.get("scope") or "all").strip().lower()
            full_struct = is_query_require_all(current_query)
            curated_rows = curated_match_rows(current_query, full_catalog=full_struct)
            if scope == "ai":
                curated_rows = [
                    it
                    for it in curated_rows
                    if "人工智能" in str(it.get("category") or "") + str(it.get("competition_name") or "")
                ]
            facts = curated_facts_for_llm(curated_rows, full_catalog=full_struct)

            system = STRUCTURED_ANSWER_SYSTEM_PROMPT
            user = f"用户问题：{current_query}\n\n（可参考改写问句：{structured_query or ''}）\n\n答案来源：\n{facts}"
            final_answer = (call_qwen([{"role": "system", "content": system}, {"role": "user", "content": user}]) or "").strip()

            rows_all = curated_rows
            rows = curated_rows

            if final_answer:
                ans = final_answer
            else:
                ans = "未在结构化知识库中找到该信息。"

            # 若 STRUCTURED 回答不了，则不要直接返回，继续走 RAG 兜底（直到能回答为止）
            ans_norm = (ans or "").strip()
            if ans_norm in (
                "未找到该信息",
                "未找到该信息。",
                "未在结构化知识库中找到该信息",
                "未在结构化知识库中找到该信息。",
            ):
                logger.info("STRUCTURED 未命中，转 RAG 兜底: %s", current_query[:80])
            else:
                final_answer = ans_norm
                new_history = list(history or [])
                new_history.append({"role": "user", "content": message})
                new_history.append({"role": "assistant", "content": final_answer})
                result = {
                    "answer": final_answer,
                    "images": [],
                    "image_refs": [],
                    "image_dataset": DEFAULT_DATASET,
                    "rewritten": structured_query or current_query,
                    "history": new_history,
                    "engine_source": "structured",
                    "query_type": "text",
                    "answer_basis": json.dumps(
                        {
                            "structured": {
                                "rows": len(rows_all),
                                "matched": len(rows),
                                "req": req,
                                "route_query": current_query,
                                "rewrite_query": structured_query or "",
                                "source": "curated_structured",
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "seeker_rounds": 0,
                    # structured 回答可能覆盖全库；但若用户显式选择了赛事范围，也应写入历史用于展示/筛选
                    "competition_id": competition_id_out,
                    "cache_key": cache_key,
                }
                _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
                return result
        except Exception as e:
            logger.warning("STRUCTURED 执行失败，回退到 RAG: %s", e, exc_info=True)

    # === 缓存命中检查 ===
    if cache_key in _answer_cache:
        logger.info("命中缓存: %s", cache_key)
        cached = _answer_cache[cache_key]
        new_history = list(history or [])
        new_history.append({'role': 'user', 'content': message})
        new_history.append({'role': 'assistant', 'content': cached['answer']})
        cached_result = dict(cached)
        cached_result['history'] = new_history
        cached_result['from_cache'] = True
        return cached_result

    # 被取消请求不写入缓存（确保“丢弃所有中间结果”）
    raise_if_cancelled(request_id)

    # === 阶段0: 多轮→单轮（仅用于 RAG 检索，不反向影响路由）===
    single_query = summarize_multi_turn_to_single(history=history, user_request=message)
    logger.info("单轮查询: %s", single_query[:150])
    raise_if_cancelled(request_id)

    # === 阶段1: 闲聊短路（是闲聊则直接 LLM 回复，不走检索） ===
    is_chitchat = classify_chitchat_need(single_query)
    logger.info("闲聊识别结果: %s", "是" if is_chitchat else "否")
    raise_if_cancelled(request_id)
    if is_chitchat:
        final_answer = _ensure_text(answer_chitchat(message, history=history))
        if not final_answer:
            final_answer = "你好呀，有什么我可以帮你的？"
        new_history = list(history or [])
        new_history.append({'role': 'user', 'content': message})
        new_history.append({'role': 'assistant', 'content': final_answer})
        result = {
            'answer': final_answer,
            'images': [],
            'image_refs': [],
            'image_dataset': DEFAULT_DATASET,
            'rewritten': single_query,
            'history': new_history,
            'engine_source': 'llm',
            'query_type': 'chitchat',
            'answer_basis': json.dumps({'route': 'chitchat_llm'}, ensure_ascii=False),
            'seeker_rounds': 0,
            'competition_id': competition_id_out,
            'cache_key': cache_key,
        }
        _answer_cache[cache_key] = {k: v for k, v in result.items() if k != 'history'}
        return result

    # === 本科生数学建模类列举：白名单标准答，不走 ViDoRAG/GraphRAG（防止泰迪杯等混入） ===
    if is_undergraduate_math_modeling_list_query(single_query):
        final_answer = STANDARD_ANSWER_UNDERGRADUATE_MATH_MODELING.strip()
        new_history = list(history or [])
        new_history.append({"role": "user", "content": message})
        new_history.append({"role": "assistant", "content": final_answer})
        result = {
            "answer": final_answer,
            "images": [],
            "image_refs": [],
            "image_dataset": DEFAULT_DATASET,
            "rewritten": single_query,
            "history": new_history,
            "engine_source": "structured",
            "query_type": "text",
            "answer_basis": json.dumps(
                {"route": "undergraduate_math_modeling_whitelist", "kb": "math_modeling_undergrad_kb"},
                ensure_ascii=False,
            ),
            "seeker_rounds": 0,
            "competition_id": competition_id_out,
            "cache_key": cache_key,
        }
        _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
        logger.info("本科生数学建模白名单短路，跳过双引擎")
        return result

    # === 阶段2: 查询类型分类（极轻量，几乎无开销） ===
    graphrag_mode = classify_query_type(single_query)
    logger.info("查询分类结果: %s", graphrag_mode)
    raise_if_cancelled(request_id)

    # === 阶段3: Vidorag 全流程检索 ===
    try:
        vidorag_result = _vidorag.chat(
            single_query,
            contest_filter=pdf_name,
            contest_filters=multi_contest_scope,
            request_id=request_id,
        )
    except ViDoRAGModelNotReadyError as e:
        # 不降级：明确告知离线缺缓存，直接返回，不继续跑 GraphRAG/其他检索
        final_answer = _ensure_text(str(e)).strip() or "ViDoRAG 模型未就绪。"
        new_history = list(history or [])
        new_history.append({'role': 'user', 'content': message})
        new_history.append({'role': 'assistant', 'content': final_answer})
        result = {
            "answer": final_answer,
            "images": [],
            "image_refs": [],
            "image_dataset": DEFAULT_DATASET,
            "rewritten": single_query,
            "history": new_history,
            "engine_source": "error",
            "query_type": "text",
            "answer_basis": json.dumps(
                {"error": {"type": "vidorag_model_not_ready", "message": final_answer}},
                ensure_ascii=False,
            ),
            "seeker_rounds": 0,
            "competition_id": competition_id_out,
            "cache_key": cache_key,
            "status": "error",
        }
        _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
        return result
    except CancelledError:
        # 丢弃所有中间结果：不缓存、不上传、不落库（由上层判断）
        return {
            "answer": "",
            "images": [],
            "image_refs": [],
            "image_dataset": DEFAULT_DATASET,
            "rewritten": single_query,
            "history": list(history or []) + [{'role': 'user', 'content': message}],
            "engine_source": "none",
            "query_type": "text",
            "answer_basis": "",
            "seeker_rounds": 0,
            "competition_id": competition_id_out,
            "cache_key": "",
            "status": "cancelled",
        }
    except Exception as e:
        # 不降级：明确报错并停止（避免在离线/初始化失败时继续跑其他引擎造成更混乱的表现）
        final_answer = f"ViDoRAG 初始化或检索失败：{str(e)}"
        new_history = list(history or [])
        new_history.append({'role': 'user', 'content': message})
        new_history.append({'role': 'assistant', 'content': final_answer})
        result = {
            "answer": final_answer,
            "images": [],
            "image_refs": [],
            "image_dataset": DEFAULT_DATASET,
            "rewritten": single_query,
            "history": new_history,
            "engine_source": "error",
            "query_type": "text",
            "answer_basis": json.dumps(
                {"error": {"type": "vidorag_failed", "message": str(e)}},
                ensure_ascii=False,
            ),
            "seeker_rounds": 0,
            "competition_id": competition_id_out,
            "cache_key": cache_key,
            "status": "error",
        }
        _answer_cache[cache_key] = {k: v for k, v in result.items() if k != "history"}
        return result

    vidorag_answer = _ensure_text(vidorag_result.get('answer'))
    vidorag_images = vidorag_result.get('images') or []
    seeker_rounds = vidorag_result.get('seeker_rounds', 0)
    logger.info("ViDoRAG: answer长度=%s, images数=%s, seeker轮次=%s",
                len(vidorag_answer), len(vidorag_images), seeker_rounds)
    raise_if_cancelled(request_id)

    # === 阶段4: GraphRAG 精准单级检索 ===
    graphrag_result = {"answer": "", "mode": "none", "status": "skipped"}
    if deep_think:
        gr_contest = None if multi_contest_scope else pdf_name
        if _graphrag.is_available(gr_contest):
            graphrag_result = _graphrag.search(single_query, contest_id=gr_contest, mode=graphrag_mode)
            logger.info("GraphRAG（深度思考）[%s]: status=%s, answer长度=%s",
                        graphrag_mode, graphrag_result.get('status'),
                        len(graphrag_result.get('answer', '')))
        else:
            logger.info("GraphRAG（深度思考）索引不可用 contest_id=%s，跳过", gr_contest or "<dataset>")
    else:
        logger.info("GraphRAG 已跳过（未开启深度思考）")
    raise_if_cancelled(request_id)

    # === 阶段5: 动态答案路由 ===
    graphrag_answer = _clean_graphrag_answer(_ensure_text(graphrag_result.get('answer', '')))
    graphrag_second_pass_compressed = False
    if graphrag_answer and graphrag_result.get('status') == 'success':
        raise_if_cancelled(request_id)
        _before_compress = graphrag_answer
        graphrag_answer = compress_graphrag_answer(single_query, graphrag_answer)
        graphrag_second_pass_compressed = True
        logger.info(
            "GraphRAG 二次精简: len %s -> %s",
            len(_before_compress),
            len(graphrag_answer or ""),
        )
    has_visual = _has_visual_content(vidorag_images)
    visual_query = _is_visual_query(single_query)

    # global 问题优先 GraphRAG：跨文档/全局归纳更适合图谱社区报告等结构化索引
    if graphrag_mode == 'global' and graphrag_answer and graphrag_result.get('status') == 'success':
        final_answer = graphrag_answer
        engine_source = 'graphrag'
        query_type = 'text'
        # Vidorag 仅做页码/图片引用补充
        if vidorag_images:
            engine_source = 'hybrid'
            final_answer += "\n\n---\n**相关页码参考（视觉检索）**：见下方引用页缩略图。"
    # 仅当“问题本身有明确视觉诉求”或页面检测确实发现表格/图片时，才把 Vidorag 放主位并标 visual。
    elif (visual_query or has_visual) and vidorag_answer:
        final_answer = vidorag_answer
        engine_source = 'vidorag'
        query_type = 'visual'
        if graphrag_answer:
            final_answer += f"\n\n---\n**知识图谱补充参考：**\n{graphrag_answer}"
    elif graphrag_answer and graphrag_result.get('status') == 'success':
        final_answer = graphrag_answer
        engine_source = 'graphrag'
        query_type = 'text'
        if vidorag_images:
            engine_source = 'hybrid'
    elif vidorag_answer:
        final_answer = vidorag_answer
        engine_source = 'vidorag'
        query_type = 'visual' if (visual_query or has_visual) else 'text'
    else:
        final_answer = "未检索到相关文档，请换一种方式描述您的问题。"
        engine_source = 'none'
        query_type = 'text'

    # === 阶段6: 注入人工校对事实，收敛回答风格（仅在命中结构化知识库条目时触发） ===
    if deterministic_structured_kb_allowed(current_query):
        try:
            _full_fuse = is_query_require_all(current_query)
            curated_hits = curated_match_rows(current_query, full_catalog=_full_fuse)
            # 若用户已选择具体赛事（pdf_name），则用 “pdf_name -> DB -> curated_id/赛系赛名” 精确定位知识库行
            # 并强制注入到融合提示，避免短问句时命中错误赛事。
            if pdf_name:
                hit = curated_hit_for_selected_pdf(str(pdf_name))
                if hit:
                    seen = set()
                    merged: list[dict] = []
                    for it in [hit] + list(curated_hits or []):
                        cid = str(it.get("id") or "")
                        key = cid or (str(it.get("competition_name") or "") + "|" + str(it.get("track") or ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        merged.append(it)
                    curated_hits = merged
            # 未选 PDF：仅使用问句命中的少量知识库行参与融合，禁止注入全表

            if curated_hits and final_answer and engine_source in ("graphrag", "vidorag", "hybrid"):
                fused = compose_with_curated(
                    user_query=current_query,
                    curated_rows=curated_hits,
                    graphrag_answer=graphrag_answer,
                    vidorag_answer=vidorag_answer,
                    mode=str(graphrag_mode or ""),
                )
                if fused:
                    final_answer = fused
        except Exception as e:
            logger.warning("CURATED 融合失败（忽略，沿用原始回答）: %s", e, exc_info=True)

    answer_format = answer_format_pref
    if answer_format == 'brief' and len(final_answer) > 500:
        final_answer = final_answer[:500] + '...'
    final_answer = _ensure_text(final_answer)

    new_history = list(history or [])
    new_history.append({'role': 'user', 'content': message})
    new_history.append({'role': 'assistant', 'content': final_answer})

    # 图片上传到 OSS，前端通过 URL 直接访问
    # 若已取消，不进行 OSS 上传等副作用
    raise_if_cancelled(request_id)
    oss_map = upload_images_to_oss(vidorag_images)
    image_refs = [_image_path_to_ref(p, oss_map.get(p)) for p in vidorag_images]

    answer_basis = {
        'vidorag': {
            'images': [os.path.basename(p) for p in vidorag_images],
            'page_refs': image_refs,
        },
        'graphrag': {
            'mode': graphrag_result.get('mode', 'none'),
            'status': graphrag_result.get('status', 'skipped'),
            'second_pass_compress': graphrag_second_pass_compressed,
        },
    }

    competition_id_val = competition_id_out or _infer_competition_id(pdf_name, vidorag_images)

    result = {
        'answer': final_answer,
        'images': vidorag_images,
        'image_refs': image_refs,
        'image_dataset': DEFAULT_DATASET,
        'rewritten': single_query,
        'history': new_history,
        'engine_source': engine_source,
        'query_type': query_type,
        'answer_basis': json.dumps(answer_basis, ensure_ascii=False),
        'seeker_rounds': seeker_rounds,
        'competition_id': competition_id_val,
        'cache_key': cache_key,
    }

    _answer_cache[cache_key] = {k: v for k, v in result.items() if k != 'history'}
    if len(_answer_cache) > 500:
        oldest = list(_answer_cache.keys())[:100]
        for k in oldest:
            _answer_cache.pop(k, None)

    return result
