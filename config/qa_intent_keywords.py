"""
问答侧意图关键词（非 prompt 文案）：全量列表/对比类、视觉问句兜底等。
供 backend.services.qa_service 等模块引用，便于集中维护。
"""

from __future__ import annotations

# 全量列表 / 对比类问法：命中则 curated 结构化知识库上下文按「全量匹配条 + 仅关键字段」召回（仍受调用方硬上限约束）
INTENT_KEYWORDS_ALL_COMPARISON: frozenset[str] = frozenset(
    {
        "全部",
        "所有",
        "各个",
        "各项",
        "分别",
        "对比",
        "比较",
        "一览表",
        "清单",
        "汇总",
        "总结",
        "区别",
        "差异",
        "有哪些",
        "分别是什么",
        "分别介绍",
        "都有什么",
        "全部比赛",
        "所有比赛",
        "全部赛事",
        "所有赛事",
        "赛事对比",
        "比赛对比",
        "赛事汇总",
        "比赛汇总",
        "全部介绍",
        "所有介绍",
        "全部说明",
        "所有说明",
    }
)

# 兼容旧名（与 INTENT_KEYWORDS_ALL_COMPARISON 相同）
INTENT_KEYWORDS_ALL_SUMMARY: frozenset[str] = INTENT_KEYWORDS_ALL_COMPARISON

# classify_visual_need 异常时的关键词兜底（中英）
VISUAL_QUERY_KEYWORDS_FALLBACK: frozenset[str] = frozenset(
    {
        "图",
        "图片",
        "图表",
        "表格",
        "示意图",
        "流程图",
        "结构图",
        "截图",
        "页码",
        "第几页",
        "figure",
        "diagram",
        "chart",
        "table",
        "image",
        "screenshot",
        "page",
    }
)


def is_query_require_all(query: str) -> bool:
    """是否需要按全量（在调用方硬上限内）召回匹配赛事条目，仅关键字段拼上下文。"""
    q = (query or "").replace(" ", "").strip()
    if not q:
        return False
    return any(kw in q for kw in INTENT_KEYWORDS_ALL_COMPARISON)
