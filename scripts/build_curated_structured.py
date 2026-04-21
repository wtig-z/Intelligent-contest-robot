#!/usr/bin/env python3
"""
把人工维护的 TSV/CSV（结构化知识库）转换为 config/curated_structured.py。

用法：
  /data/miniconda/envs/contestrobot_py312/bin/python scripts/build_curated_structured.py \
    --input data/curated_competitions.tsv \
    --output config/curated_structured.py
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
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


def _py_str(s: str) -> str:
    # 用 repr 保留引号/转义
    return repr(s)


def _emit(rows: list[dict[str, str]]) -> str:
    out: list[str] = []
    out.append('"""')
    out.append("结构化知识库赛事数据（人工校对版）")
    out.append("")
    out.append("本文件由 scripts/build_curated_structured.py 自动生成。")
    out.append('"""')
    out.append("")
    out.append("CURATED_COMPETITIONS: list[dict[str, object]] = [")

    for r in rows:
        cid = _as_int(r.get("id", "") or r.get("ID", "") or "0", 0)
        comp = (r.get("赛系") or r.get("竞赛名称") or r.get("competition_name") or "").strip()
        track = (r.get("赛名/赛道") or r.get("赛道") or r.get("track") or "/").strip() or "/"
        category = (r.get("赛事类别") or r.get("category") or "无").strip() or "无"
        pub = (r.get("发布时间") or r.get("publish_time") or "无").strip() or "无"
        reg = (r.get("报名时间") or r.get("registration_time") or "无").strip() or "无"
        org = (r.get("组织单位") or r.get("organizer") or "无").strip() or "无"
        web = (r.get("官网") or r.get("official_website") or "无").strip() or "无"
        held = (r.get("举办时间") or r.get("held_time") or "无").strip() or "无"
        eligible = (r.get("参赛对象") or r.get("eligibility") or "无").strip() or "无"
        team = (r.get("组队人数") or r.get("team_size") or "无").strip() or "无"
        advisor = (r.get("指导教师") or r.get("advisor") or "无").strip() or "无"
        aliases_raw = (r.get("别名") or r.get("aliases") or "").strip()
        aliases = [a.strip() for a in aliases_raw.replace("；", ";").replace("，", ",").split("|") if a and a.strip()]

        out.append("    {")
        out.append(f'        "id": {cid},')
        out.append(f'        "competition_name": {_py_str(comp)},')
        out.append(f'        "track": {_py_str(track)},')
        out.append(f'        "category": {_py_str(category)},')
        out.append(f'        "publish_time": {_py_str(pub)},')
        out.append(f'        "registration_time": {_py_str(reg)},')
        out.append(f'        "organizer": {_py_str(org)},')
        out.append(f'        "official_website": {_py_str(web)},')
        out.append(f'        "held_time": {_py_str(held)},')
        out.append(f'        "eligibility": {_py_str(eligible)},')
        out.append(f'        "team_size": {_py_str(team)},')
        out.append(f'        "advisor": {_py_str(advisor)},')
        out.append(f'        "aliases": {repr(aliases)},')
        out.append("    },")

    out.append("]")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/curated_competitions.tsv")
    ap.add_argument("--output", default="config/curated_structured.py")
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_path = args.input
    out_path = args.output
    if not os.path.isabs(in_path):
        in_path = os.path.join(root, in_path)
    if not os.path.isabs(out_path):
        out_path = os.path.join(root, out_path)

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

