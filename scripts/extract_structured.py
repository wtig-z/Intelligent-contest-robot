#!/usr/bin/env python3
"""
从 unified_text/（页级 OCR 融合文本）抽取结构化赛事信息，落库到 data/contest_robot.db 的 competition_structs 表。

用法：
  /data/miniconda/envs/contestrobot_py312/bin/python scripts/extract_structured.py --dataset CompetitionDataset
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
from flask import Flask

from config.app_config import DEFAULT_DATASET
from config.paths import get_unified_text_dir
from backend.storage.db import init_db
from backend.models.pdf_model import PDF
from backend.llm_chat import extract_competition_structured
from backend.storage import competition_struct_storage


def _natural_sort_key(s: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def _group_pages(unified_dir: str) -> Dict[str, List[Tuple[int, str]]]:
    files = [f for f in os.listdir(unified_dir) if f.endswith(".txt")]
    page_re = re.compile(r"^(.+?)_(\d+)\.txt$")
    out: Dict[str, List[Tuple[int, str]]] = {}
    for f in files:
        m = page_re.match(f)
        if not m:
            continue
        cid = m.group(1)
        p = int(m.group(2))
        out.setdefault(cid, []).append((p, f))
    for cid in out:
        out[cid].sort(key=lambda x: x[0])
    return out


def _read_pages(unified_dir: str, pages: List[Tuple[int, str]], max_pages: int = 3) -> str:
    parts: List[str] = []
    for pno, fn in pages[: max(1, max_pages)]:
        path = os.path.join(unified_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                txt = fh.read().strip()
        except Exception:
            txt = ""
        if not txt:
            continue
        parts.append(f"【第{pno}页】\n{txt}")
    return "\n\n".join(parts).strip()


def main() -> None:
    # 允许通过项目根目录 .env 提供 DASHSCOPE_API_KEY 等配置
    try:
        load_dotenv(os.path.join(_ROOT, ".env"))
    except Exception:
        # .env 不存在或解析失败时不阻塞执行（后续会在调用处报缺 key）
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.getenv("VIDORAG_DATASET", DEFAULT_DATASET))
    ap.add_argument("--max-pages", type=int, default=3, help="每个赛事用于抽取的最大页数（默认 3）")
    args = ap.parse_args()

    dataset = (args.dataset or DEFAULT_DATASET).strip()
    unified_dir = get_unified_text_dir(dataset)
    if not os.path.isdir(unified_dir):
        raise SystemExit(f"unified_text 不存在：{unified_dir}（请先跑 merge_ocr.py）")

    groups = _group_pages(unified_dir)
    if not groups:
        raise SystemExit("unified_text 下未找到 *_<page>.txt")

    app = Flask(__name__)
    init_db(app)
    with app.app_context():
        # 仅处理 DB 里存在的 PDF（避免 unified_text 里残留导致误入库）
        pdfs = PDF.query.filter_by(dataset=dataset).all()
        db_cids = set()
        for p in pdfs:
            doc_id = p.filename[:-4] if p.filename.lower().endswith(".pdf") else p.filename
            db_cids.add(doc_id)

        cids = [cid for cid in sorted(groups.keys(), key=_natural_sort_key) if cid in db_cids]
        print(f"dataset={dataset} unified_groups={len(groups)} db_pdfs={len(db_cids)} target={len(cids)}")

        ok = 0
        for i, cid in enumerate(cids, 1):
            pages = groups.get(cid) or []
            src_text = _read_pages(unified_dir, pages, max_pages=max(1, int(args.max_pages)))
            if not src_text:
                continue
            try:
                payload = extract_competition_structured(src_text)
                competition_struct_storage.upsert(
                    dataset=dataset,
                    competition_id=cid,
                    payload=payload,
                    source_text=src_text,
                )
                ok += 1
                print(f"[{i:02d}] OK {cid} name={payload.get('competition_name','')[:30]}")
            except Exception as e:
                print(f"[{i:02d}] FAIL {cid}: {e}")

        print(f"done ok={ok}/{len(cids)}")


if __name__ == "__main__":
    main()

