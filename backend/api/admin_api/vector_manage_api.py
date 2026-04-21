"""向量构建记录管理（vectors 表）；向量文件仍在数据集目录 bge_ingestion / colqwen_ingestion。"""
from __future__ import annotations

import os
from datetime import datetime

from flask import Blueprint, jsonify

from backend.auth.jwt_handler import backoffice_required
from backend.storage import vector_storage
from config.app_config import DEFAULT_DATASET
from config.paths import get_dataset_dir

bp = Blueprint("vector_manage", __name__, url_prefix="/api/admin/vectors")


def _fmt_dt(v: datetime | None) -> str:
    if not v:
        return ""
    try:
        return v.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(v)


@bp.route("/list", methods=["GET"])
@backoffice_required
def list_vectors():
    vectors = vector_storage.list_all()
    rows = []
    for v in vectors:
        rows.append(
            {
                "id": v.id,
                "vector_type": v.vector_type,
                "dataset": getattr(v, "dataset", "") or "",
                "status": v.status,
                "progress": int(getattr(v, "progress", 0) or 0),
                "file_path": (v.file_path or "")[:512],
                "error_msg": getattr(v, "error_msg", None) or "",
                "pdf_id": v.pdf_id,
                "created_at": _fmt_dt(getattr(v, "created_at", None)),
                "updated_at": _fmt_dt(getattr(v, "updated_at", None)),
            }
        )
    # 库中无记录时，与旧版一致：展示磁盘上 .node 数量，便于排查
    if not rows:
        ds_dir = get_dataset_dir(DEFAULT_DATASET)
        bge_dir = os.path.join(ds_dir, "bge_ingestion")
        colqwen_dir = os.path.join(ds_dir, "colqwen_ingestion")
        bge_count = len([f for f in os.listdir(bge_dir) if f.endswith(".node")]) if os.path.isdir(bge_dir) else 0
        colqwen_count = len([f for f in os.listdir(colqwen_dir) if f.endswith(".node")]) if os.path.isdir(colqwen_dir) else 0
        if bge_count:
            rows.append(
                {
                    "id": "-",
                    "vector_type": "bge(node)",
                    "dataset": DEFAULT_DATASET,
                    "status": f"磁盘约 {bge_count} 个节点",
                    "progress": 0,
                    "file_path": bge_dir,
                    "error_msg": "",
                    "pdf_id": None,
                    "created_at": "",
                    "updated_at": "",
                }
            )
        if colqwen_count:
            rows.append(
                {
                    "id": "-",
                    "vector_type": "colqwen(node)",
                    "dataset": DEFAULT_DATASET,
                    "status": f"磁盘约 {colqwen_count} 个节点",
                    "progress": 0,
                    "file_path": colqwen_dir,
                    "error_msg": "",
                    "pdf_id": None,
                    "created_at": "",
                    "updated_at": "",
                }
            )
    return jsonify({"code": 0, "message": "ok", "data": rows})


@bp.route("/status", methods=["GET"])
@backoffice_required
def status():
    return jsonify({"code": 0, "message": "ok", "data": {"status": "ok"}})
