"""任务控制台：运行中问答、历史、强制中断、并发配置只读。"""
from flask import Blueprint, jsonify, request

from backend.auth.jwt_handler import admin_required, backoffice_required
from backend.services import task_registry

bp = Blueprint("admin_tasks", __name__, url_prefix="/api/admin/tasks")


@bp.route("/running", methods=["GET"])
@backoffice_required
def running():
    return jsonify({"code": 0, "message": "ok", "data": task_registry.list_running()})


@bp.route("/history", methods=["GET"])
@backoffice_required
def history():
    limit = min(int(request.args.get("limit", "100")), 500)
    return jsonify({"code": 0, "message": "ok", "data": task_registry.list_history(limit)})


@bp.route("/stats", methods=["GET"])
@backoffice_required
def stats():
    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "max_concurrent": task_registry.max_concurrent(),
            "running_count": len(task_registry.list_running()),
            "available_slots": task_registry.available_slots(),
        },
    })


@bp.route("/cancel", methods=["POST"])
@admin_required
def cancel():
    data = request.get_json(silent=True) or {}
    rid = (data.get("request_id") or "").strip()
    if not rid:
        return jsonify({"code": 400, "message": "缺少 request_id"}), 400
    ok = task_registry.admin_cancel(rid)
    return jsonify({"code": 0, "message": "已发送取消信号", "data": {"request_id": rid, "was_running": ok}})
