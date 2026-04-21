"""
结构化知识库：确定性路由 + 查表回答（基础信息 / 统计分析）。

路由分两层：
1) **策略层** `config.qa_route_policy`：决定能否使用本模块的确定性模板（否则主流程已走 RAG）。
2) **模板层** `route_curated_query`：在允许结构化时，划分为 stat（枚举/计数）或 basic（单字段事实）；
   返回 open 表示本模块不产出模板答案，但外层仍可能走 curated LLM 等（由 qa_service 决定）。

- stat/basic：不调答案 LLM，仅匹配与字段拼接。
- open：返回 None，交由 qa_service 继续 ViDoRAG/GraphRAG。

数据源优先级：
1) config.golden_kb.GOLDEN_COMPETITION_KB
2) config.curated_competitions.COMPETITION_DATABASE（TSV）
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from config import golden_kb
from config.qa_route_policy import (
    deterministic_structured_kb_allowed,
    is_basic_template_route,
    is_simple_enum_query,
    normalize_query_for_route,
)

CuratedRoute = Literal["basic", "stat", "open"]


def structured_kb_table() -> list[dict]:
    """返回当前生效的结构化知识库行列表（Golden 优先）。"""
    try:
        rows = getattr(golden_kb, "GOLDEN_COMPETITION_KB", None) or []
        if rows:
            return list(rows)
    except Exception:
        pass
    try:
        from config.curated_competitions import COMPETITION_DATABASE  # noqa: WPS433

        return list(COMPETITION_DATABASE or [])
    except Exception:
        return []

# 策略层未覆盖的「主观 / 体验」词：双保险，仍不进确定性模板（与 qa_route_policy.COMPLEX_KW 部分重叠）
_OPEN_HINTS = (
    "如何准备", "怎么准备", "怎样准备", "要注意", "注意事项", "注意什么",
    "凭什么", "好不好", "难不难", "累不累",
)


def route_curated_query(question: str) -> CuratedRoute:
    """
    在 structured 策略允许时，划分 stat / basic。
    若为「对比表/一览表」白名单等无枚举、无单字段提示的问法，返回 open（不做 Golden 字符串模板，
    由 qa_service 的 curated-first 等路径输出表格）。
    """
    q_raw = (question or "").strip()
    if not q_raw:
        return "open"
    if not deterministic_structured_kb_allowed(q_raw):
        return "open"
    qn = normalize_query_for_route(q_raw)
    if any(h in qn for h in _OPEN_HINTS):
        return "open"
    if is_simple_enum_query(q_raw):
        return "stat"
    if is_basic_template_route(q_raw):
        return "basic"
    return "open"


def _norm(s: str) -> str:
    """保留中文、字母数字，去掉标点空白，便于子串匹配。"""
    t = (s or "").lower()
    return re.sub(r"[^\w\u4e00-\u9fff]", "", t, flags=re.UNICODE)


def _full_display_name(row: dict) -> str:
    comp = str(row.get("竞赛名称") or "").strip()
    track = str(row.get("赛道") or "").strip()
    if not comp:
        return track or ""
    if not track or track in ("/", "无"):
        return comp
    return f"{comp}{track}"


def _category_tokens(row: dict) -> list[str]:
    cat = str(row.get("赛事类别") or "").strip()
    parts = [p.strip() for p in re.split(r"[/、，,]+", cat) if p.strip() and p.strip() != "无"]
    return parts


def _score_row(query: str, row: dict) -> int:
    q = _norm(query)
    if not q:
        return 0
    score = 0
    for key in ("竞赛名称", "赛道"):
        s = _norm(str(row.get(key) or ""))
        if len(s) >= 4 and s in q:
            score += len(s)
        elif len(s) >= 2 and s in q:
            score += 1
    for tag in row.get("标签") or []:
        t = _norm(str(tag))
        if len(t) >= 2 and t in q:
            score += len(t)
    for t in _category_tokens(row):
        tn = _norm(t)
        if len(tn) >= 2 and tn in q:
            score += len(tn)
    cat_all = _norm(str(row.get("赛事类别") or ""))
    if len(cat_all) >= 4 and cat_all in q:
        score += min(len(cat_all), 12)
    for al in row.get("别名") or []:
        a = _norm(str(al))
        if len(a) >= 2 and a in q:
            score += len(a) if len(a) >= 4 else 2
    return score


def _pick_rows(query: str, db: list[dict]) -> list[dict]:
    ranked = sorted(((-_score_row(query, r), i, r) for i, r in enumerate(db)), key=lambda x: (x[0], x[1]))
    best = -ranked[0][0] if ranked else 0
    if best <= 0:
        return []
    out = [r for neg_s, _, r in ranked if -neg_s == best]
    return out


def _detect_basic_field(question: str) -> Optional[str]:
    q = question or ""
    # 评审 / 规程类不在结构化单行字段中，勿误匹配「赛道」等
    if any(k in q for k in ("评审标准", "评分标准", "评分细则", "章程")):
        return None
    if any(k in q for k in ("备注", "说明", "几人", "收费")) and "准备" not in q:
        return "备注"
    if any(k in q for k in ("赛事类别", "什么类别", "哪类赛道", "属于哪类")):
        return "赛事类别"
    if any(k in q for k in ("层级", "级别", "全国还是")):
        return "赛事层级"
    if any(k in q for k in ("报名", "何时报名", "报名时间", "截止", "截止日期")):
        return "报名时间"
    if any(k in q for k in ("竞赛时间", "比赛时间", "开赛", "正式比赛", "赛程")) and "报名" not in q:
        return "竞赛时间"
    if "发布" in q and ("时间" in q or "日期" in q):
        return "发布时间"
    if any(k in q for k in ("官网", "网址", "网站", "链接")):
        return "官网"
    if any(k in q for k in ("组织", "主办", "承办", "谁举办")):
        return "组织单位"
    # 赛事名常含「专项赛」，但问「评审标准是什么」勿当成问赛道
    if ("赛道" in q or "赛项" in q) and any(k in q for k in ("什么", "哪", "哪个")):
        return "赛道"
    if any(k in q for k in ("参赛对象", "资格", "谁能报", "谁能参加")):
        return "参赛对象"
    if any(k in q for k in ("举办时间", "赛期", "何时举办", "什么时候办")):
        return "举办时间"
    if "什么时候" in q or "何时" in q:
        # 未明确：有“比赛/赛”倾向则竞赛时间，否则报名时间
        if any(k in q for k in ("比赛", "竞赛", "开赛", "作品提交")):
            return "竞赛时间"
        return "报名时间"
    return None


def _format_time_answer(full_name: str, field_cn: str, value: str) -> str:
    v = (value or "").strip()
    if not v or v == "无":
        return f"{full_name}的{field_cn}未在清单中收录。"
    if field_cn == "报名时间" and ("到" in v or "-" in v or "—" in v):
        v2 = v.replace("—", "-").replace("－", "-")
        return f"{full_name}的报名时间是{v2}。"
    return f"{full_name}的{field_cn}是{v}。"


def try_answer_basic(question: str, db: list[dict], *, single_row: Optional[dict] = None) -> Optional[str]:
    """
    基础信息：匹配 0～1 条主记录 + 字段，模板输出。
    single_row：若已选赛事且可映射为清单行，直接对该行回答（避免问句中无赛名）。
    """
    if single_row is not None:
        rows = [single_row]
    else:
        rows = _pick_rows(question, db)
        if not rows:
            return None
        if len(rows) > 1:
            # 多行同分：取第一条并提示或简短并列 —— 企业场景可改为澄清问
            rows = rows[:1]

    field = _detect_basic_field(question)
    if not field:
        return None

    row = rows[0]
    full = _full_display_name(row)
    val = str(row.get(field) or "").strip()
    if field == "举办时间" and (not val or val == "无"):
        val = str(row.get("竞赛时间") or "").strip()

    if field in ("报名时间", "发布时间", "竞赛时间"):
        out = _format_time_answer(full, field, val)
        if field == "竞赛时间" and "未在清单" in out:
            val2 = str(row.get("举办时间") or "").strip()
            if val2 and val2 != "无":
                return _format_time_answer(full, "举办时间", val2)
        return out
    if field == "赛道":
        tv = str(row.get("赛道") or "").strip()
        if not tv or tv == "无":
            return f"{str(row.get('竞赛名称') or '').strip()}无单独赛道字段或未在清单中单列赛道。"
        return f"{full}的赛道是{tv}。"
    if not val or val == "无":
        return f"{full}的{field}未在清单中收录。"
    return f"{full}的{field}是{val}。"


def _stat_filter_rows(question: str, db: list[dict]) -> list[dict]:
    """Golden KB：同义词 → 标准「赛事类别」精确过滤；否则 TSV 等走子串 blob。"""
    try:
        hit = golden_kb.stat_filter_rows_from_question(question, db)
        if hit is not None:
            return hit
    except Exception:
        pass

    q = question or ""
    tags_tokens = []
    for t in ("人工智能", "数学建模", "数据挖掘", "机器人", "智能车", "创新创业", "青少年", "大学生", "研究生", "电子信息"):
        if t in q:
            tags_tokens.append(t)

    if not tags_tokens:
        return list(db)

    def match(r: dict) -> bool:
        blob = f"{r.get('竞赛名称','')}{r.get('赛道','')}{r.get('赛事类别','')}"
        blob += "".join(str(x) for x in (r.get("标签") or []))
        blob += "".join(str(x) for x in (r.get("别名") or []))
        return any(tok in blob for tok in tags_tokens)

    return [r for r in db if match(r)]


def try_answer_stat(question: str, db: list[dict]) -> Optional[str]:
    rows = _stat_filter_rows(question, db)
    if not rows:
        return "清单中未找到与条件匹配的赛事条目。"

    q = question or ""
    want_count = any(k in q for k in ("多少", "几项", "几个", "多少项", "总数", "数量", "统计"))

    if want_count:
        dom = ""
        try:
            st = golden_kb.match_standard_category_from_text(q)
            if st:
                dom = golden_kb.count_answer_domain_label(st)
        except Exception:
            pass
        if not dom:
            for t in ("人工智能", "数学建模", "数据挖掘"):
                if t in q:
                    dom = t
                    break
        if dom:
            return f"{dom}相关竞赛共有 {len(rows)} 项。"
        return f"符合条件的竞赛共有 {len(rows)} 项。"

    # 列举
    names = []
    seen = set()
    for r in rows:
        fn = _full_display_name(r)
        if fn and fn not in seen:
            seen.add(fn)
            names.append(fn)
    if not names:
        return "清单中无可用赛事名称。"
    return "相关竞赛包括：" + "、".join(names) + "。"


def try_curated_deterministic(
    question: str,
    kind: CuratedRoute,
    db: list[dict],
    *,
    single_row: Optional[dict] = None,
) -> Optional[str]:
    if kind == "open":
        return None
    if kind == "basic":
        return try_answer_basic(question, db, single_row=single_row)
    return try_answer_stat(question, db)


def legacy_row_to_enterprise(it: dict) -> dict:
    """将 curated_structured 行转为 COMPETITION_DATABASE 形（供已选 PDF 路径）。"""
    tags: list[str] = []
    cat = str(it.get("category") or "")
    for part in re.split(r"[/、，,]+", cat):
        p = part.strip()
        if p and p not in ("无",) and len(p) >= 2:
            tags.append(p)
    blob = f"{it.get('competition_name','')}{cat}"
    for kw in ("人工智能", "数学建模", "数据挖掘", "机器人", "青少年", "大学生", "研究生"):
        if kw in blob and kw not in tags:
            tags.append(kw)
    track = str(it.get("track") or "").strip()
    if track in ("/", "无"):
        track = ""
    aliases = list(it.get("aliases") or []) if isinstance(it.get("aliases"), list) else []
    held = str(it.get("held_time") or "无")
    return {
        "id": it.get("id"),
        "竞赛名称": str(it.get("competition_name") or ""),
        "赛道": track,
        "发布时间": str(it.get("publish_time") or "无"),
        "报名时间": str(it.get("registration_time") or "无"),
        "组织单位": str(it.get("organizer") or "无"),
        "官网": str(it.get("official_website") or "无"),
        "举办时间": held,
        "竞赛时间": held,
        "赛事类别": cat or "无",
        "赛事层级": str(it.get("level") or "无"),
        "参赛对象": str(it.get("eligibility") or "无"),
        "备注": str(it.get("notes") or it.get("remark") or "无"),
        "标签": tags,
        "别名": aliases,
    }
