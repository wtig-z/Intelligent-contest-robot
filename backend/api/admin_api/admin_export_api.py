"""数据导出：对话、赛事文档清单、简单运行报表。"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
import os

from flask import Blueprint, Response, jsonify, request

from backend.auth.jwt_handler import admin_required
from backend.storage import pdf_storage, question_storage
from backend.services.doc_pipeline import pipeline_status_for_pdf
from config.app_config import DEFAULT_DATASET
from config.paths import get_bge_ingestion_dir

bp = Blueprint("admin_export", __name__, url_prefix="/api/admin/export")


@bp.route("/conversations.csv", methods=["GET"])
@admin_required
def export_conversations_csv():
    limit = min(int(request.args.get("limit", "5000")), 20000)
    items = question_storage.list_for_admin(limit=limit, offset=0)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "user_id", "content", "answer", "engine_source", "query_type", "competition_id", "created_at"])
    for q in items:
        w.writerow([
            q.id,
            q.user_id,
            (q.content or "").replace("\n", " ")[:2000],
            (q.answer or "").replace("\n", " ")[:4000],
            getattr(q, "engine_source", ""),
            getattr(q, "query_type", ""),
            getattr(q, "competition_id", ""),
            q.created_at.isoformat() if q.created_at else "",
        ])
    name = f"conversations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        buf.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@bp.route("/documents_manifest.json", methods=["GET"])
@admin_required
def export_manifest():
    dataset = (request.args.get("dataset") or DEFAULT_DATASET).strip()
    pdfs = pdf_storage.list_all(dataset)
    rows = []
    for p in pdfs:
        pipe = pipeline_status_for_pdf(dataset, p.filename)
        rows.append({
            "id": p.id,
            "filename": p.filename,
            "contest_name": p.contest_name,
            "status": p.status,
            "pipeline": pipe,
        })
    payload = {"dataset": dataset, "generated_at": datetime.now().isoformat(), "documents": rows}
    name = f"documents_manifest_{dataset}.json"
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@bp.route("/graphrag_entities_relationships.json", methods=["GET"])
@admin_required
def export_graphrag_entities_relationships():
    """全量导出 GraphRAG entities + relationships（自 storage 读表）。可选 contest_id；默认不含 embedding 列。"""
    from backend.graphrag import GraphRAGService

    dataset = (request.args.get("dataset") or DEFAULT_DATASET).strip()
    contest_id = (request.args.get("contest_id") or "").strip() or None
    include_emb = request.args.get("include_embeddings", "").lower() in ("1", "true", "yes")

    g = GraphRAGService(dataset=dataset)
    payload = g.export_entities_relationships(contest_id, include_embeddings=include_emb)
    payload["generated_at"] = datetime.now().isoformat()

    if not payload.get("available"):
        return jsonify({
            "code": 404,
            "message": payload.get("error") or "GraphRAG 数据不可用",
            "data": payload,
        }), 404

    name = f"graphrag_entities_relationships_{dataset}.json"
    return Response(
        json.dumps(payload, ensure_ascii=False),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@bp.route("/report.json", methods=["GET"])
@admin_required
def simple_report():
    from backend.graphrag import GraphRAGService
    from backend.services import task_registry

    dataset = (request.args.get("dataset") or DEFAULT_DATASET).strip()
    g = GraphRAGService(dataset=dataset)
    stats = g.get_stats(None)
    pdfs = pdf_storage.list_all(dataset)
    pdf_count = len(pdfs)
    q_total = question_storage.count_all()

    # OCR/文本/图片管线概览（与 /api/admin/indexes/summary 口径一致）
    pipe_rows = [pipeline_status_for_pdf(dataset, p.filename) for p in pdfs]
    documents_missing_text = [p.filename for p, s in zip(pdfs, pipe_rows) if p.filename and not s.get("text_extracted")]
    ocr_done = sum(1 for s in pipe_rows if s.get("ocr_complete"))
    text_done = sum(1 for s in pipe_rows if s.get("text_extracted"))
    img_done = sum(1 for s in pipe_rows if (s.get("image_pages") or 0) > 0)
    total_img_pages = sum(int(s.get("image_pages") or 0) for s in pipe_rows)

    # ViDoRAG 向量产物（.node 文件数量 + 最近更新时间）
    bge_dir = get_bge_ingestion_dir(dataset)
    node_count = len([f for f in os.listdir(bge_dir) if f.endswith(".node")]) if os.path.isdir(bge_dir) else 0
    mtime = None
    if os.path.isdir(bge_dir):
        try:
            mt = max((os.path.getmtime(os.path.join(bge_dir, f)) for f in os.listdir(bge_dir)), default=None)
            if mt:
                mtime = datetime.fromtimestamp(mt).isoformat()
        except Exception:
            mtime = None

    rep = {
        "generated_at": datetime.now().isoformat(),
        "dataset": dataset,
        "pdf_count": pdf_count,
        "question_total": q_total,
        "graphrag": stats,
        "vidorag_vectors": {
            "bge_node_files": node_count,
            "bge_dir_mtime": mtime,
        },
        "pipeline_stats": {
            "ocr_complete_pdfs": ocr_done,
            "text_extracted_pdfs": text_done,
            "images_ready_pdfs": img_done,
            "image_pages_total": total_img_pages,
        },
        "documents_missing_text": documents_missing_text[:100],
        "qa_concurrency": {
            "max": task_registry.max_concurrent(),
            "running": len(task_registry.list_running()),
        },
    }
    return jsonify({"code": 0, "message": "ok", "data": rep})
