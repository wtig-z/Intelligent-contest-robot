"""
结构化知识库（config.curated_structured）辅助：检索、关键字段排版、与 GraphRAG/ViDoRAG 答案融合。

仅依赖结构化行与 config，不依赖 qa_service，避免循环引用。
"""

from __future__ import annotations

import json
from typing import Optional

from config.app_config import DEFAULT_DATASET
from config.curated_structured import CURATED_COMPETITIONS
from config.qa_intent_keywords import is_query_require_all
from config.curated_fusion_prompt import CURATED_FUSION_ANSWER_SYSTEM_PROMPT
from backend.llm_utils import call_qwen
from backend.storage import competition_struct_storage

# 注入 LLM 的「普通追问」最多行数
CURATED_ROWS_FOR_LLM = 3
# 全量/对比类问法下的硬上限，防止撑爆上下文
CURATED_FULL_LIST_HARD_CAP = 300


def _row_topic_blob(it: dict) -> str:
    """赛名/赛道/类别/别名拼成一段，供主题词过滤。"""
    parts = [
        str(it.get("competition_name") or ""),
        str(it.get("track") or ""),
        str(it.get("category") or ""),
    ]
    aliases = it.get("aliases") or []
    if isinstance(aliases, list):
        parts.extend(str(a) for a in aliases)
    return " ".join(parts)


def _topic_fallback_rows(base: list[dict], q_raw: str) -> list[dict]:
    """
    问句含「数学建模 / 数据挖掘 …」等主题词时，按类别拉回相关行。
    避免「都有哪些」类问句无法整句子串匹配赛名时，误用整表前若干行（曾把泰迪杯等塞进融合层）。
    """
    q = (q_raw or "").strip()
    if not q:
        return []
    rules: list[tuple[tuple[str, ...], object]] = [
        (("数学建模", "数模"), lambda b: "数学建模" in b or "数模" in b),
        (("数据挖掘", "泰迪杯", "TIPDM", "tipdm"), lambda b: "数据挖掘" in b or "泰迪" in b),
        (("人工智能",), lambda b: "人工智能" in b),
        (("物联网",), lambda b: "物联网" in b),
        (("电子设计", "电赛"), lambda b: "电子设计" in b or "电赛" in b),
    ]
    for keys, pred in rules:
        if not any(k in q for k in keys):
            continue
        out: list[dict] = []
        for it in base:
            try:
                if pred(_row_topic_blob(it)):
                    out.append(it)
            except Exception:
                continue
        return out
    return []


def _key_fields_block(it: dict) -> dict[str, str]:
    """一行 curated → 展示用关键字段（无单独报名费列时用组队信息占位）。"""
    name = str(it.get("competition_name") or "").strip()
    track = str(it.get("track") or "").strip()
    if track and track not in ("/", "无"):
        disp_name = f"{name}（{track}）"
    else:
        disp_name = name
    reg = str(it.get("registration_time") or "无").strip()
    held = str(it.get("held_time") or "无").strip()
    if reg != "无" and held != "无":
        time_s = f"报名 {reg}；赛期 {held}"
    elif reg != "无":
        time_s = f"报名 {reg}"
    elif held != "无":
        time_s = f"赛期 {held}"
    else:
        time_s = "无"
    team = str(it.get("team_size") or "").strip()
    fee_s = team if team and team != "无" else "见赛事说明或官网"
    traits = str(it.get("category") or "无").strip()
    elig = str(it.get("eligibility") or "无").strip()
    return {
        "名称": disp_name,
        "参赛对象": elig,
        "时间": time_s,
        "费用说明": fee_s,
        "特点": traits,
    }


def curated_facts_for_llm(rows: list[dict], *, full_catalog: bool) -> str:
    """拼给 LLM 的结构化知识库上下文：只含关键字段。"""
    if not rows:
        return ""
    if full_catalog:
        lines: list[str] = ["【全部赛事对比】（仅结构化关键字段，非 PDF 全文）"]
        for i, it in enumerate(rows, 1):
            k = _key_fields_block(it)
            lines.append(f"{i}. 赛事名称：{k['名称']}")
            lines.append(f"   参赛对象：{k['参赛对象']}")
            lines.append(f"   时间：{k['时间']}")
            lines.append(f"   费用/组队：{k['费用说明']}")
            lines.append(f"   特点：{k['特点']}")
            lines.append("")
        return "\n".join(lines).strip()
    lines = ["【相关赛事】（Top{}，仅关键字段）".format(CURATED_ROWS_FOR_LLM)]
    for i, it in enumerate(rows[:CURATED_ROWS_FOR_LLM], 1):
        k = _key_fields_block(it)
        lines.append(
            f"{i}. 赛事名称：{k['名称']} | 参赛对象：{k['参赛对象']} | 时间：{k['时间']} | 特点：{k['特点']}"
        )
    return "\n".join(lines).strip()


def curated_match_rows(
    query: str,
    *,
    full_catalog: bool | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    子串匹配结构化知识库中的行。
    full_catalog=True：收集全部命中直至硬上限；无命中时可回退整表前若干行。
    否则最多 limit 条（默认 CURATED_ROWS_FOR_LLM）。
    """
    q_raw = (query or "").strip()
    q = q_raw.lower()
    if not q:
        return []
    full = is_query_require_all(q_raw) if full_catalog is None else full_catalog
    topn = limit if limit is not None else CURATED_ROWS_FOR_LLM

    base = list(CURATED_COMPETITIONS or [])
    rows: list[dict] = []
    for it in base:
        comp = str(it.get("competition_name") or "").strip()
        track = str(it.get("track") or "").strip()
        aliases = it.get("aliases") or []
        hay = [comp, track] + [str(a) for a in (aliases if isinstance(aliases, list) else [])]
        hit = False
        for s in hay:
            ss = (s or "").strip()
            if not ss:
                continue
            if ss.lower() in q or q in ss.lower():
                hit = True
                break
        if hit:
            rows.append(it)
            if not full and len(rows) >= topn:
                break

    if not rows:
        rows = _topic_fallback_rows(base, q_raw)

    if full:
        if not rows:
            rows = base[:CURATED_FULL_LIST_HARD_CAP]
        elif len(rows) > CURATED_FULL_LIST_HARD_CAP:
            rows = rows[:CURATED_FULL_LIST_HARD_CAP]
    else:
        rows = rows[:topn]
    return rows


def curated_row_by_id(curated_id: int) -> dict | None:
    try:
        cid = int(curated_id)
    except Exception:
        return None
    if cid <= 0:
        return None
    for it in (CURATED_COMPETITIONS or []):
        try:
            if int(it.get("id") or 0) == cid:
                return it
        except Exception:
            continue
    return None


def selected_pdf_hint(pdf_name: str) -> str:
    """给抽取器的已选赛事提示（不改变用户原句语义）。"""
    pid = (pdf_name or "").strip()
    if not pid:
        return ""
    try:
        row = competition_struct_storage.get_by_competition_id(DEFAULT_DATASET, pid)
        if row is None:
            return f"【已选赛事】competition_id={pid}"
        sys_name = (getattr(row, "competition_system", "") or "").strip()
        name = (getattr(row, "competition_name", "") or "").strip()
        parts = [f"competition_id={pid}"]
        if sys_name:
            parts.append(f"赛系={sys_name}")
        if name:
            parts.append(f"赛名/赛道={name}")
        return "【已选赛事】" + "；".join(parts)
    except Exception:
        return f"【已选赛事】competition_id={pid}"


def curated_hit_for_selected_pdf(pdf_name: str) -> dict | None:
    """已选 PDF → 结构化知识库一行：DB curated_id > 赛系+赛道精确 > 模糊 Top1。"""
    t = (pdf_name or "").strip()
    if not t:
        return None
    try:
        row = competition_struct_storage.get_by_competition_id(DEFAULT_DATASET, t)
        curated_id = None
        if row is not None:
            try:
                raw = json.loads(getattr(row, "raw_extract_json", "") or "{}")
                curated_id = raw.get("curated_id")
            except Exception:
                curated_id = None

        if curated_id is not None:
            hit = curated_row_by_id(int(curated_id))
            if hit:
                return hit

        if row is not None:
            sys_name = (getattr(row, "competition_system", "") or "").strip()
            name = (getattr(row, "competition_name", "") or "").strip() or "/"
            if sys_name:
                for it in (CURATED_COMPETITIONS or []):
                    if (str(it.get("competition_name") or "").strip() == sys_name
                            and (str(it.get("track") or "/").strip() or "/") == (name or "/")):
                        return it

        hits = curated_match_rows(t, full_catalog=False, limit=CURATED_ROWS_FOR_LLM)
        return hits[0] if hits else None
    except Exception:
        return None


def compose_with_curated(
    *,
    user_query: str,
    curated_rows: list[dict],
    graphrag_answer: str,
    vidorag_answer: str,
    mode: str,
) -> str:
    """用结构化知识库关键字段 + 双引擎原文，经融合 LLM 生成最终句。"""
    full = is_query_require_all(user_query)
    curated_rows = list(curated_rows or [])
    if not full:
        curated_rows = curated_rows[:CURATED_ROWS_FOR_LLM]
    else:
        curated_rows = curated_rows[:CURATED_FULL_LIST_HARD_CAP]
    facts = curated_facts_for_llm(curated_rows, full_catalog=full)
    system = CURATED_FUSION_ANSWER_SYSTEM_PROMPT
    user = (
        f"用户问题：{(user_query or '').strip()}\n\n"
        f"当前检索模式：{mode}\n\n"
        f"结构化知识库摘要（若为空表示本次未匹配到相关条目）：\n{facts or '（空）'}\n\n"
        f"GraphRAG 原始回答：\n{(graphrag_answer or '').strip() or '（空）'}\n\n"
        f"ViDoRAG 原始回答：\n{(vidorag_answer or '').strip() or '（空）'}\n"
    )
    return (call_qwen([{"role": "system", "content": system}, {"role": "user", "content": user}]) or "").strip()
