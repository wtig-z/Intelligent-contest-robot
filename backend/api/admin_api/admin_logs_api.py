"""日志中心：内存缓冲、按天文件检索、列表归档。"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List

from flask import Blueprint, jsonify, request, send_file

from backend.auth.jwt_handler import admin_required, backoffice_required
from app.logger import get_logs
from config.logger_config import LOGS_DIR, PROJECT_NAME

bp = Blueprint("admin_logs", __name__, url_prefix="/api/admin/logs")

_MAIN_RE = re.compile(rf"^{re.escape(PROJECT_NAME)}_(\d{{4}}-\d{{2}}-\d{{2}})\.log$")


@bp.route("/buffer", methods=["GET"])
@backoffice_required
def log_buffer():
    """与 logger 单例环形缓冲一致。"""
    raw = get_logs()
    level = (request.args.get("level") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()
    out = []
    for row in raw:
        msg = (row.get("m") or "")
        if q and q not in msg.lower():
            continue
        if level:
            if f"[{level}]" not in msg.upper():
                continue
        out.append(row)
    tail = int(request.args.get("tail", "500"))
    tail = max(1, min(tail, 5000))
    return jsonify({"code": 0, "message": "ok", "data": out[-tail:]})


def _main_log_path(date_str: str | None) -> str:
    ds = (date_str or datetime.now().strftime("%Y-%m-%d")).strip()
    return os.path.join(LOGS_DIR, f"{PROJECT_NAME}_{ds}.log")


@bp.route("/file", methods=["GET"])
@backoffice_required
def log_file():
    """按天读取主日志，支持关键词过滤与 tail。"""
    date_str = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    path = _main_log_path(date_str)
    if not os.path.isfile(path):
        return jsonify({"code": 0, "message": "ok", "data": {"lines": [], "path": path}})
    q = (request.args.get("q") or "").strip()
    tail_n = int(request.args.get("tail", "2000"))
    tail_n = max(1, min(tail_n, 50000))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)}), 500
    if q:
        lines = [ln for ln in lines if q in ln]
    lines = lines[-tail_n:]
    return jsonify({"code": 0, "message": "ok", "data": {"lines": lines, "path": path, "count": len(lines)}})


@bp.route("/archives", methods=["GET"])
@backoffice_required
def archives():
    names: List[str] = []
    if os.path.isdir(LOGS_DIR):
        for name in sorted(os.listdir(LOGS_DIR), reverse=True):
            m = _MAIN_RE.match(name)
            if m:
                names.append(m.group(1))
    return jsonify({"code": 0, "message": "ok", "data": {"dates": names[:90]}})


@bp.route("/download", methods=["GET"])
@admin_required
def download():
    """按天下载主日志文本。"""
    date_str = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    path = _main_log_path(date_str)
    if not os.path.isfile(path):
        return jsonify({"code": 404, "message": "文件不存在"}), 404
    return send_file(
        path,
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=f"{PROJECT_NAME}_{date_str}.log",
    )
