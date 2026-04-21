#!/usr/bin/env python3
"""
把人工维护的结构化知识库（data/curated_competitions.tsv → config/curated_structured.py）同步进数据库 competition_structs 表。

目标：
- competition_structs 的核心字段（名称/赛道/官网/报名时间/组织单位/类别）以 TSV 为准
- competition_id 以数据库 pdfs 表中的 doc_id 为准（filename 去掉 .pdf）

用法：
  python scripts/build_curated_structured.py --input data/curated_competitions.tsv --output config/curated_structured.py
  python scripts/sync_competition_structs_from_curated.py --dataset CompetitionDataset
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

from flask import Flask

from config.app_config import DEFAULT_DATASET
from backend.storage.db import init_db
from backend.models.pdf_model import PDF
from backend.storage import competition_struct_storage


def _doc_id_from_pdf_filename(fn: str) -> str:
    s = (fn or "").strip()
    return s[:-4] if s.lower().endswith(".pdf") else s


def _norm(s: Any) -> str:
    v = ("" if s is None else str(s)).strip()
    return "" if v in ("无", "/") else v


def _match_curated_row(doc_id: str, curated_rows: list[dict[str, object]]) -> dict[str, object] | None:
    """用 doc_id（通常含赛道名/别名）匹配一条结构化知识库记录。"""
    t = (doc_id or "").strip().lower()
    if not t:
        return None
    for it in curated_rows:
        comp = str(it.get("competition_name") or "").strip()
        track = str(it.get("track") or "").strip()
        aliases = it.get("aliases") or []
        hay = [comp, track] + [str(a) for a in (aliases if isinstance(aliases, list) else [])]
        for x in hay:
            xx = (x or "").strip().lower()
            if not xx:
                continue
            if xx in t or t in xx:
                return it
    return None


def _payload_from_curated(it: dict[str, object]) -> dict[str, Any]:
    comp = str(it.get("competition_name") or "").strip()
    track = str(it.get("track") or "/").strip() or "/"
    if track in ("无", "／", ""):
        track = "/"
    payload = {
        "competition_system": comp,
        "competition_name": track,
        "organizer": _norm(it.get("organizer")),
        "official_website": _norm(it.get("official_website")),
        "registration_time": _norm(it.get("registration_time")),
        "competition_category": _norm(it.get("category")) or "其他",
        "session": _norm(it.get("publish_time")),
        "evidence_pages": "",
        "source": "curated_tsv",
        "curated_id": it.get("id"),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.getenv("VIDORAG_DATASET", DEFAULT_DATASET))
    ap.add_argument("--limit", type=int, default=0, help="仅同步前 N 条（调试用）")
    ap.add_argument("--rebuild", action="store_true", help="先清空目标表该 dataset 的行，再重灌")
    args = ap.parse_args(argv)

    dataset = (args.dataset or DEFAULT_DATASET).strip()
    limit = max(0, int(args.limit or 0))
    rebuild = bool(getattr(args, "rebuild", False))

    try:
        from config.curated_structured import CURATED_COMPETITIONS
    except Exception as e:
        raise SystemExit(f"无法导入 config/curated_structured.py，请先运行 build_curated_structured.py：{e}")

    curated_rows: list[dict[str, object]] = list(CURATED_COMPETITIONS or [])
    if not curated_rows:
        raise SystemExit("CURATED_COMPETITIONS 为空")

    app = Flask(__name__)
    init_db(app)
    with app.app_context():
        if rebuild:
            try:
                from backend.storage.db import db
                from backend.models.competition_struct_model import CompetitionStruct
                deleted = CompetitionStruct.query.filter_by(dataset=dataset).delete()
                db.session.commit()
                print(f"rebuild: cleared competition_structs dataset={dataset} rows={deleted}")
            except Exception as e:
                print(f"warn: rebuild clear competition_structs failed: {e}")

        pdfs = PDF.query.filter_by(dataset=dataset).all()
        targets = []
        for p in pdfs:
            doc_id = _doc_id_from_pdf_filename(p.filename)
            targets.append((p, doc_id))

        ok = 0
        miss = 0
        for i, (_p, doc_id) in enumerate(targets, 1):
            if limit and ok >= limit:
                break
            it = _match_curated_row(doc_id, curated_rows)
            if not it:
                miss += 1
                continue
            payload = _payload_from_curated(it)
            src = f"curated_id={it.get('id')}|{payload.get('competition_system')}|{payload.get('competition_name')}|{payload.get('official_website')}|{payload.get('registration_time')}"
            competition_struct_storage.upsert(
                dataset=dataset,
                competition_id=doc_id,
                payload=payload,
                source_text=src,
            )
            ok += 1

        # 刷新中文视图（由迁移脚本创建；这里容错执行一遍）
        try:
            from backend.storage.db import db
            sql = """
            DROP VIEW IF EXISTS competition_structs_cn;
            CREATE VIEW competition_structs_cn AS
            SELECT
              id AS id,
              dataset AS 数据集,
              competition_id AS competition_id,
              competition_system AS 赛系,
              competition_name AS "赛名/赛道",
              competition_category AS 赛事类别,
              session AS 发布时间,
              registration_time AS 报名时间,
              organizer AS 组织单位,
              official_website AS 官网,
              created_at AS 创建时间,
              updated_at AS 更新时间
            FROM competition_structs;
            """
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                db.session.execute(db.text(stmt))
            db.session.commit()
        except Exception:
            pass

        print(f"done dataset={dataset} pdfs={len(targets)} ok={ok} miss={miss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

