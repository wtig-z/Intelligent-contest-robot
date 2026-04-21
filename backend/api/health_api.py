"""健康检查与日志"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Dict

from flask import Blueprint, jsonify, request

from app.logger import get_logs
from backend.auth.jwt_handler import get_current_user
from config.logger_config import FRONTEND_LOGGER_NAME

bp = Blueprint('health', __name__, url_prefix='/api')


@bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'ContestRobot-web'})


@bp.route('/logs', methods=['GET'])
def logs():
    """返回缓冲区中的日志（用于 Web/API 展示/调试）"""
    return jsonify({'logs': get_logs()})


@bp.route('/log/report', methods=['POST'])
def report_frontend_logs():
    """
    接收前端 sendBeacon 批量日志，写入独立前端日志文件。

    body: JSON array of log objects
    """
    raw = request.get_data(as_text=True) or ""
    logs: List[Dict[str, Any]] = []
    if raw.strip():
        try:
            logs = json.loads(raw)
        except Exception:
            logs = []
    if not isinstance(logs, list):
        logs = []

    user = get_current_user() or {}
    user_id = user.get("sub")
    is_admin = (user.get("role") == "admin") if user else False

    logger = logging.getLogger(FRONTEND_LOGGER_NAME)

    for item in logs:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "info").lower()
        msg = str(item.get("message") or "").strip() or "(empty)"
        ctx = item.get("context")

        # 服务端兜底补齐关键字段（避免前端缺失）
        item.setdefault("user_id", user_id if user_id is not None else "unlogin")
        item.setdefault("is_admin", bool(is_admin))
        item.setdefault("server_ts", None)
        item["server_ts"] = item.get("server_ts") or None

        final = f"[FRONTEND] {msg} | ctx={json.dumps(ctx, ensure_ascii=False, separators=(',', ':')) if ctx is not None else 'null'} | payload={json.dumps(item, ensure_ascii=False, separators=(',', ':'))}"

        if level == "error":
            logger.error(final)
        elif level in ("warn", "warning"):
            logger.warning(final)
        else:
            logger.info(final)

    return jsonify({"code": 0, "message": "ok", "data": None})
