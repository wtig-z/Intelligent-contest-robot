"""向量库 + GraphRAG 统一概览、异常提示、重建入口。"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from flask import Blueprint, jsonify, request

from backend.auth.jwt_handler import admin_required, backoffice_required, uploader_required
from backend.graphrag import GraphRAGService
from backend.storage import pdf_storage, vector_storage
from backend.services.doc_pipeline import pipeline_status_for_pdf
from config.app_config import DEFAULT_DATASET
from config.paths import (
    get_bge_ingestion_dir,
    get_graphrag_dir,
    get_project_root,
    get_scripts_dir,
)

bp = Blueprint("admin_indexes", __name__, url_prefix="/api/admin/indexes")

_graphrag = GraphRAGService()


def _bge_stats(dataset: str) -> dict:
    bge_dir = get_bge_ingestion_dir(dataset)
    node_count = 0
    if os.path.isdir(bge_dir):
        node_count = len([f for f in os.listdir(bge_dir) if f.endswith(".node")])
    mtime = None
    if os.path.isdir(bge_dir):
        try:
            mt = max((os.path.getmtime(os.path.join(bge_dir, f)) for f in os.listdir(bge_dir)), default=None)
            if mt:
                mtime = datetime.fromtimestamp(mt).isoformat()
        except Exception:
            mtime = None
    return {"bge_node_files": node_count, "bge_dir_mtime": mtime}


@bp.route("/summary", methods=["GET"])
@backoffice_required
def summary():
    dataset = (request.args.get("dataset") or DEFAULT_DATASET).strip()
    pdfs = pdf_storage.list_all(dataset)
    pipe_rows = [pipeline_status_for_pdf(dataset, p.filename) for p in pdfs]
    empty_text = [p.filename for p, s in zip(pdfs, pipe_rows) if p.filename and not s.get("text_extracted")]
    graph_stats = _graphrag.get_stats(None)
    vectors_db = len(vector_storage.list_all())

    graphrag_dir = get_graphrag_dir(dataset)
    output_ready = os.path.isdir(os.path.join(graphrag_dir, "output"))
    anomalies = []
    for p, s in zip(pdfs, pipe_rows):
        if s.get("issues"):
            anomalies.append({"filename": p.filename, "issues": s["issues"], "pipeline": s})
    if graph_stats.get("available") and graph_stats.get("entities") == 0:
        anomalies.append({"scope": "graphrag", "issues": ["zero_entities"]})
    if graph_stats.get("available") and graph_stats.get("relationships") == 0:
        anomalies.append({"scope": "graphrag", "issues": ["zero_relationships"]})

    bge = _bge_stats(dataset)

    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "dataset": dataset,
            "pdf_count": len(pdfs),
            "vector_rows_in_db": vectors_db,
            "vidorag_vectors": bge,
            "graphrag": {
                **graph_stats,
                "output_dir_ready": output_ready,
            },
            "triple_like_count": graph_stats.get("relationships") if isinstance(graph_stats, dict) else None,
            "anomalies": anomalies[:200],
            "documents_missing_text": empty_text[:100],
        },
    })


@bp.route("/rebuild_vectors", methods=["POST"])
@uploader_required
def rebuild_vectors():
    """触发 update_knowledge（OCR + 向量入库）。"""
    data = request.get_json(silent=True) or {}
    dataset = (data.get("dataset") or DEFAULT_DATASET).strip()
    script_path = os.path.join(get_scripts_dir(), "update_knowledge.py")
    if not os.path.isfile(script_path):
        return jsonify({"code": 500, "message": "更新脚本不存在"}), 500
    try:
        subprocess.Popen(
            [sys.executable or "python", script_path, "--dataset", dataset],
            cwd=get_project_root(),
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)}), 500
    return jsonify({"code": 0, "message": "已触发向量与管线重建任务", "data": {"dataset": dataset}})


@bp.route("/rebuild_graph", methods=["POST"])
@admin_required
def rebuild_graph():
    """全量 GraphRAG 构建：复用 graphrag_manage 逻辑，由前端也可直接调 /api/admin/graphrag/build。"""
    from backend.api.admin_api import graphrag_manage_api as gmod

    if gmod._build_status.get("running"):
        return jsonify({"code": 409, "message": "构建任务正在进行中"}), 409
    data = request.get_json(silent=True) or {}
    contest_id = data.get("contest_id") or None
    method = data.get("method", "standard")

    def _do():
        gmod._build_status["running"] = True
        try:
            result = _graphrag.build_index(contest_id, method=method)
            gmod._build_status["last_result"] = result
        except Exception as e:
            gmod._build_status["last_result"] = {"status": "error", "error": str(e)}
        finally:
            gmod._build_status["running"] = False

    import threading
    threading.Thread(target=_do, daemon=True).start()
    return jsonify({"code": 0, "message": "GraphRAG 全量构建已启动", "data": {"contest_id": contest_id, "method": method}})
