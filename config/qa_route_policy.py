"""
问答路由策略（结构化知识库捷径 vs ViDoRAG/GraphRAG）

架构（两层）
---------
1) **策略层（本模块）** — `route_answer_strategy` / `deterministic_structured_kb_allowed`
   决定「是否允许」走结构化捷径：确定性 Golden 模板、curated-first LLM、选 PDF 单行、
   STRUCTURED 段、RAG 后的 structured 融合等（见 `backend.services.qa_service`）。

2) **模板层（`curated_database_query.route_curated_query`）** — 仅当策略层为 structured 时生效，
   在 stat（枚举/计数模板）与 basic（单字段事实模板）之间分流；返回 open 则不做确定性模板，
   主流程继续走 RAG。

相关模块：`config.qa_intent_keywords`（全量召回条数、与「有哪些」类无关）、`config.golden_kb`（数据源，不含路由）。

对外优先使用：`route_answer_strategy`；`deterministic_structured_kb_allowed` 为兼容旧代码的布尔封装。
"""

from __future__ import annotations

from typing import Final, Literal

AnswerStrategy = Literal["structured", "rag"]

# ---------------------------------------------------------------------------
# 关键词常量（单一数据源，供子串匹配；均配合 normalize_query_for_route）
# ---------------------------------------------------------------------------

WHITE_LIST_STRUCT_KW: Final[tuple[str, ...]] = (
    "全部赛事对比表",
    "赛事一览表",
    "全部比赛对比表",
    "比赛一览表",
    "赛事对比表格",
    "全部赛事表格",
)

MULTI_ENTITY_KW: Final[tuple[str, ...]] = (
    "对比",
    "比较",
    "区别",
    "差异",
    "不同",
    "相同",
    "全部",
    "所有",
    "汇总",
    "一览表",
    "分别",
    "种类",
    "各有",
    "怎么选",
    "优缺点",
    "总结",
)

COMPLEX_KW: Final[tuple[str, ...]] = (
    "介绍",
    "详解",
    "说明",
    "要求",
    "赛制",
    "含金量",
    "如何参赛",
    "准备",
    "怎么准备",
    "评审标准",
    "评分",
    "意义",
    "好处",
    "为什么",
    "流程",
    "章程",
    "规则",
    "概述",
    # 与 curated_database_query._OPEN_HINTS 对齐，避免宽泛 “有什么” 误进枚举
    "技巧",
    "建议",
    "心得",
)

SIMPLE_ENUM_KW: Final[tuple[str, ...]] = (
    "有哪些",
    "有哪些比赛",
    "有哪些赛事",
    "包含哪些",
    "分别是",
    "有什么",
    "都有什么",
    "哪几类",
    "哪一些",
    "多少",
    "几项",
    "几个",
    "多少项",
    "总数",
    "数量",
    "统计",
    "列出",
    "清单",
    "分别是哪些",
    "包括哪些",
    "都有哪些",
)

SIMPLE_FACT_KW: Final[tuple[str, ...]] = (
    "报名时间",
    "报名",
    "比赛时间",
    "竞赛时间",
    "发布时间",
    "费用",
    "竞赛费",
    "报名费",
    "地点",
    "主办单位",
    "组织单位",
    "承办",
    "主办",
    "参赛对象",
    "资格",
    "组别",
    "赛道",
    "赛项",
    "组队",
    "几人",
    "官网",
    "网址",
    "网站",
    "链接",
    "备注",
)

# Golden basic 模板路由补充词（易问法里不含上表完整短语，但仍属单点事实）
BASIC_TEMPLATE_EXTRA_KW: Final[tuple[str, ...]] = (
    "时间",
    "什么时候",
    "何时",
    "截止",
    "在哪",
    "发布",
    "赛期",
    "举办",
    "层级",
    "赛事类别",
    "对象是",
    "谁举办",
)


def normalize_query_for_route(query: str) -> str:
    """与全文件关键词判断一致的规范化（去首尾空白、去空格）。"""
    return (query or "").strip().replace(" ", "")


def is_white_list_struct(query: str) -> bool:
    """窄白名单：明确要求对比表 / 一览表 → 强制 structured（表格输出）。"""
    q = normalize_query_for_route(query)
    return any(kw in q for kw in WHITE_LIST_STRUCT_KW)


def is_multi_entity_query(query: str) -> bool:
    """跨赛事、对比、归纳类 → RAG（白名单优先于本规则）。"""
    q = normalize_query_for_route(query)
    return any(kw in q for kw in MULTI_ENTITY_KW)


def is_complex_query(query: str) -> bool:
    """综述、规程解读、备赛主观类 → RAG。"""
    q = normalize_query_for_route(query)
    return any(kw in q for kw in COMPLEX_KW)


def is_simple_enum_query(query: str) -> bool:
    """简单枚举 / 计数问法 → structured（统计模板）。"""
    q = normalize_query_for_route(query)
    return any(kw in q for kw in SIMPLE_ENUM_KW)


def _composite_multi_aspect_fact_query(q: str) -> bool:
    """同句多问多个事实维度 → RAG，避免只答一个字段。"""
    if q.count("？") + q.count("?") >= 2:
        return True
    if "、" in q:
        hits = sum(
            1
            for w in (
                "时间",
                "地点",
                "费用",
                "报名",
                "组队",
                "官网",
                "对象",
                "主办",
            )
            if w in q
        )
        if hits >= 2:
            return True
    if "分别" in q and any(
        x in q for x in ("时间", "地点", "费用", "报名", "官网", "组队", "什么")
    ):
        return True
    return False


def route_answer_strategy(query: str) -> AnswerStrategy:
    """
    structured：允许 Golden 确定性模板、curated-first、选 PDF 单行、STRUCTURED、融合阶段等。
    rag：主走 ViDoRAG / GraphRAG。
    """
    q = normalize_query_for_route(query)
    if not q:
        return "rag"

    if is_white_list_struct(query):
        return "structured"

    if _composite_multi_aspect_fact_query(q):
        return "rag"

    if is_multi_entity_query(query):
        return "rag"

    if is_complex_query(query):
        return "rag"

    if is_simple_enum_query(query):
        return "structured"

    if any(kw in q for kw in SIMPLE_FACT_KW):
        return "structured"

    return "rag"


def deterministic_structured_kb_allowed(query: str) -> bool:
    """True 表示允许结构化知识库「捷径」（与 route_answer_strategy==structured 等价）。"""
    return route_answer_strategy(query) == "structured"


def is_basic_template_route(query: str) -> bool:
    """
    模板层用：在已通过策略层 structured 的前提下，是否像「单字段 basic」问法。
    须在 is_simple_enum_query 之后判断（枚举优先 stat）。
    """
    q = normalize_query_for_route(query)
    return any(kw in q for kw in SIMPLE_FACT_KW) or any(kw in q for kw in BASIC_TEMPLATE_EXTRA_KW)


__all__ = (
    "AnswerStrategy",
    "BASIC_TEMPLATE_EXTRA_KW",
    "COMPLEX_KW",
    "MULTI_ENTITY_KW",
    "SIMPLE_ENUM_KW",
    "SIMPLE_FACT_KW",
    "WHITE_LIST_STRUCT_KW",
    "deterministic_structured_kb_allowed",
    "is_basic_template_route",
    "is_complex_query",
    "is_multi_entity_query",
    "is_simple_enum_query",
    "is_white_list_struct",
    "normalize_query_for_route",
    "route_answer_strategy",
)
