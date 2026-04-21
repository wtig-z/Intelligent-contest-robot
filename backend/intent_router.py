"""
意图识别/路由（独立模块，可脚本运行）。

包含：
- chitchat / visual / query_type（basic/local/global）
- STRUCTURED：LLM 意图路由 + LLM 信息抽取
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.llm_utils import classify_yes_no, extract_json
from backend.vidorag.agent.prompts import (
    CHITCHAT_SYSTEM_PROMPT,
    VISUAL_NEED_SYSTEM_PROMPT,
    CLASSIFY_SYSTEM_PROMPT,
    STRUCTURED_ROUTE_SYSTEM_PROMPT,
    STRUCTURED_EXTRACT_SYSTEM_PROMPT,
    STRUCTURED_REWRITE_SYSTEM_PROMPT,
)

logger = logging.getLogger("contest_robot.intent_router")


def rewrite_structured_query(query: str) -> str:
    """STRUCTURED 专用问句改写：提升后续结构化抽取稳定性。失败则回退原句。"""
    q = (query or "").strip()
    if not q:
        return ""
    try:
        from backend.llm_utils import call_qwen

        messages = [
            {"role": "system", "content": STRUCTURED_REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": q},
        ]
        out = (call_qwen(messages) or "").strip()
        # 防御：有些模型会加引号/多行说明，这里做轻度清理
        out = out.strip().strip('"').strip("'").strip()
        if not out:
            return q
        # 过长则回退，避免把问句改写成大段总结
        if len(out) > 300:
            return q
        return out
    except Exception as e:
        logger.warning("STRUCTURED 问句改写失败，回退原句: %s", e)
        return q


def classify_visual_need(query: str) -> bool:
    query = (query or "").strip()
    if not query:
        return False
    try:
        v = classify_yes_no(VISUAL_NEED_SYSTEM_PROMPT, query)
        return bool(v)
    except Exception as e:
        logger.warning("视觉意图判断失败，降级为 False: %s", e)
        return False


def classify_chitchat_need(query: str) -> bool:
    query = (query or "").strip()
    if not query:
        return False
    try:
        v = classify_yes_no(CHITCHAT_SYSTEM_PROMPT, query)
        return bool(v)
    except Exception as e:
        logger.warning("闲聊意图判断失败，降级为 False: %s", e)
        return False


def classify_query_type(query: str) -> str:
    """用轻量 LLM 判断查询属于 basic/local/global 哪一类。"""
    q = (query or "").strip()
    if not q:
        return "basic"
    try:
        messages = [
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": q},
        ]
        from backend.llm_utils import call_qwen  # 避免循环 import

        result = (call_qwen(messages) or "").strip().lower()
        if result in ("basic", "local", "global"):
            logger.info("查询分类: %s → %s", q[:60], result)
            return result
        if "global" in result:
            return "global"
        if "local" in result:
            return "local"
        return "basic"
    except Exception as e:
        logger.warning("查询分类失败，默认 basic: %s", e)
        return "basic"


def classify_structured_intent(query: str) -> bool:
    """LLM 意图路由：是否归为 STRUCTURED（列表/统计/固定字段枚举）。"""
    q = (query or "").strip()
    if not q:
        return False
    try:
        v = classify_yes_no(STRUCTURED_ROUTE_SYSTEM_PROMPT, q)
        return bool(v)
    except Exception as e:
        logger.warning("STRUCTURED 意图路由失败，降级为规则兜底: %s", e)
        # 规则兜底：覆盖“改写成陈述句”的情况
        keys = (
            "列出",
            "枚举",
            "分别",
            "有哪些",
            "有什么",
            "都有什么",
            "名单",
            "清单",
            "多少",
            "总数",
            "数量",
            "统计",
            "官网",
            "主办",
            "报名",
            "赛道",
            "赛项",
            "名称",
            "名字",
            "全称",
            "包括",
            "包含",
            "均为",
        )
        return any(k in q for k in keys) and any(k in q for k in ("赛事", "竞赛", "比赛"))


def extract_structured_request(query: str) -> dict:
    """LLM 信息抽取：把 STRUCTURED 问题抽取为可执行参数。失败返回 unknown。"""
    q = (query or "").strip()
    if not q:
        return {
            "intent": "unknown",
            "fields": [],
            "scope": "all",
            "competition_name_contains": "",
            "track_contains": "",
            "prefer_single": False,
            "wants_enumeration": False,
            "notes": "empty_query",
        }
    try:
        obj = extract_json(STRUCTURED_EXTRACT_SYSTEM_PROMPT, q)
        intent = str(obj.get("intent") or "unknown").strip().lower()
        if intent not in ("list", "count", "fields", "unknown"):
            intent = "unknown"

        fields = obj.get("fields") or []
        if not isinstance(fields, list):
            fields = []
        allowed = {
            "name",
            "official_website",
            "organizer",
            "registration_time",
            "tracks",
            "session",
            "competition_category",
        }
        norm_fields: list[str] = []
        for f in fields:
            fs = str(f or "").strip()
            if fs in allowed and fs not in norm_fields:
                norm_fields.append(fs)

        scope = str(obj.get("scope") or "all").strip().lower()
        if scope not in ("all", "ai"):
            scope = "all"

        competition_name_contains = str(obj.get("competition_name_contains") or "").strip()
        track_contains = str(obj.get("track_contains") or "").strip()
        prefer_single = bool(obj.get("prefer_single")) if obj.get("prefer_single") is not None else False

        wants_enum = bool(obj.get("wants_enumeration")) if obj.get("wants_enumeration") is not None else False
        notes = str(obj.get("notes") or "").strip()
        req = {
            "intent": intent,
            "fields": norm_fields,
            "scope": scope,
            "competition_name_contains": competition_name_contains,
            "track_contains": track_contains,
            "prefer_single": prefer_single,
            "wants_enumeration": wants_enum,
            "notes": notes,
        }
        # NOTE: 不在这里做规则兜底/强制改写；STRUCTURED 路线以 LLM 抽取 + 结构化知识库为准。
        return req
    except Exception as e:
        logger.warning("STRUCTURED 信息抽取失败，回退 unknown: %s", e)
        return {
            "intent": "unknown",
            "fields": [],
            "scope": "ai" if ("人工智能" in q or "AI" in q) else "all",
            "competition_name_contains": "",
            "track_contains": "",
            "prefer_single": False,
            "wants_enumeration": any(
                k in q for k in ("列出", "枚举", "分别", "有哪些", "有什么", "都有什么", "清单", "名单", "包括", "包含", "均为")
            ),
            "notes": f"extract_failed: {e}",
        }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Intent router (LLM-based).")
    parser.add_argument("query", nargs="?", default="", help="user query text")
    args = parser.parse_args(argv)
    q = (args.query or "").strip()
    out = {
        "query": q,
        "chitchat": classify_chitchat_need(q),
        "visual": classify_visual_need(q),
        "query_type": classify_query_type(q),
        "structured": classify_structured_intent(q),
        "structured_req": extract_structured_request(q) if q else {},
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

