#!/usr/bin/env python3
"""
由 data/curated_competitions.tsv 生成 config/curated_competitions.py（结构化知识库：中文字段 + 标签）。

维护方式（二选一）：
  - 改 TSV 后运行本脚本，刷新结构化知识库模块；
  - 或直接编辑 config/curated_competitions.py（若取消自动生成，请勿运行覆盖）。

用法：
  python scripts/build_curated_competitions.py \\
    --input data/curated_competitions.tsv \\
    --output config/curated_competitions.py
"""
from __future__ import annotations

import argparse
import csv
import os
import re
from typing import Any


def _read_rows(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.excel_tab if "\t" in sample else csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        rows: list[dict[str, str]] = []
        for r in reader:
            if not r:
                continue
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
        return rows


def _as_int(s: str, default: int = 0) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


def _py_repr(obj: Any) -> str:
    if isinstance(obj, str):
        return repr(obj)
    if isinstance(obj, list):
        return "[" + ", ".join(_py_repr(x) if isinstance(x, str) else repr(x) for x in obj) + "]"
    return repr(obj)


def _derive_tags(
    competition_name: str,
    track: str,
    category: str,
    aliases: list[str],
) -> list[str]:
    tags: list[str] = []
    blob = f"{competition_name} {track} {category}"
    for part in re.split(r"[/、，,\s]+", category):
        p = part.strip()
        if len(p) >= 2 and p not in ("无", "无。") and p not in tags:
            tags.append(p)
    for kw in ("人工智能", "数学建模", "数据挖掘", "机器人", "智能车", "创新创业", "青少年", "大学生", "研究生"):
        if kw in blob and kw not in tags:
            tags.append(kw)
    for a in aliases:
        if len(a) >= 2 and a not in tags:
            tags.append(a)
    return tags[:20]


def _emit(rows: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append('"""')
    lines.append("竞赛结构化知识库（人工维护源：TSV → 本模块；中文字段企业格式）")
    lines.append("")
    lines.append("本文件由 scripts/build_curated_competitions.py 从 data/curated_competitions.tsv 自动生成。")
    lines.append("基础信息/统计分析类问答走确定性查表，不经过答案 LLM；开放类问题走 RAG。")
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("COMPETITION_DATABASE: list[dict[str, object]] = [")

    for r in rows:
        cid = _as_int(r.get("id", "") or r.get("ID", "") or "0", 0)
        comp = (r.get("赛系") or r.get("竞赛名称") or "").strip()
        track_raw = (r.get("赛名/赛道") or r.get("赛道") or "").strip() or "/"
        track = "" if track_raw in ("/", "无") else track_raw
        category = (r.get("赛事类别") or "无").strip() or "无"
        pub = (r.get("发布时间") or "无").strip() or "无"
        reg = (r.get("报名时间") or "无").strip() or "无"
        org = (r.get("组织单位") or "无").strip() or "无"
        web = (r.get("官网") or "无").strip() or "无"
        held = (r.get("举办时间") or "无").strip() or "无"
        eligible = (r.get("参赛对象") or "无").strip() or "无"
        aliases_raw = (r.get("别名") or "").strip()
        aliases = [a.strip() for a in aliases_raw.replace("；", ";").replace("，", ",").split("|") if a.strip()]
        tags = _derive_tags(comp, track, category, aliases)

        lines.append("    {")
        lines.append(f'        "id": {cid},')
        lines.append(f'        "竞赛名称": {_py_repr(comp)},')
        lines.append(f'        "赛道": {_py_repr(track)},')
        lines.append(f'        "发布时间": {_py_repr(pub)},')
        lines.append(f'        "报名时间": {_py_repr(reg)},')
        lines.append(f'        "组织单位": {_py_repr(org)},')
        lines.append(f'        "官网": {_py_repr(web)},')
        lines.append(f'        "举办时间": {_py_repr(held)},')
        lines.append(f'        "参赛对象": {_py_repr(eligible)},')
        lines.append(f'        "标签": {_py_repr(tags)},')
        lines.append(f'        "别名": {_py_repr(aliases)},')
        lines.append("    },")

    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/curated_competitions.tsv")
    ap.add_argument("--output", default="config/curated_competitions.py")
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_path = args.input if os.path.isabs(args.input) else os.path.join(root, args.input)
    out_path = args.output if os.path.isabs(args.output) else os.path.join(root, args.output)

    rows = _read_rows(in_path)
    if not rows:
        raise SystemExit(f"no rows in {in_path}")

    content = _emit(rows)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"OK wrote {out_path} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
