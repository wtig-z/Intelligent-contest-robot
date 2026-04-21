"""用户管理"""
from flask import Blueprint, jsonify, request

from backend.auth.jwt_handler import admin_required, get_current_user
from backend.auth.password_utils import hash_password
from backend.models import User
from backend.storage import user_storage, password_reset_request_storage
from config.auth_config import DEFAULT_RESET_PASSWORD

bp = Blueprint("user_manage", __name__, url_prefix="/api/admin/users")


@bp.route("/role", methods=["POST"])
@admin_required
def set_user_role():
    """设置后台角色：user | admin | viewer"""
    data = request.get_json() or {}
    uid = data.get("user_id")
    role = (data.get("role") or "").strip()
    try:
        uid = int(uid)
    except Exception:
        return jsonify({"code": 400, "message": "无效 user_id"}), 400
    if role not in ("user", "admin", "viewer"):
        return jsonify({"code": 400, "message": "无效 role"}), 400
    if not user_storage.set_role(uid, role):
        return jsonify({"code": 404, "message": "用户不存在"}), 404
    return jsonify({"code": 0, "message": "ok", "data": {"user_id": uid, "role": role}})


@bp.route("/list", methods=["GET"])
@admin_required
def list_users():
    users = User.query.all()
    return jsonify({
        "code": 0,
        "message": "ok",
        "data": [
            {"id": u.id, "username": u.username, "role": u.role, "phone": getattr(u, "phone", None) or ""}
            for u in users
        ],
    })


@bp.route("/reset-password", methods=["POST"])
@admin_required
def reset_password():
    """
    管理员重置用户密码（用户忘记密码时使用）。
    body: {
      "username": "被重置用户的登录名",
      "new_password": "新密码",
      "send_sms": true  可选，若为 true 且该用户已绑定手机号且配置了短信通道，则把新密码发到其手机
    }
    """
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    new_password = data.get("new_password") or ""
    send_sms = data.get("send_sms") is True

    if not username:
        return jsonify({"code": 400, "message": "缺少 username", "data": None}), 400
    if not new_password or len(new_password) < 4:
        return jsonify({"code": 400, "message": "新密码至少 4 位", "data": None}), 400

    u = user_storage.get_by_username_for_reset(username)
    if not u:
        return jsonify({"code": 404, "message": "用户不存在", "data": None}), 404

    user_storage.update_password_by_username(username, hash_password(new_password))

    sms_sent = False
    if send_sms and getattr(u, "phone", None) and (u.phone or "").strip():
        from app.sms_utils import send_reset_password_sms
        sms_sent = send_reset_password_sms((u.phone or "").strip(), username, new_password)

    return jsonify({
        "code": 0,
        "message": "密码已重置",
        "data": {"sms_sent": sms_sent},
    })


@bp.route("/reset-requests/list", methods=["GET"])
@admin_required
def list_reset_requests():
    """管理员查看待处理的忘记密码申请列表。"""
    limit = min(int(request.args.get("limit", 100)), 500)
    requests = password_reset_request_storage.get_pending_list(limit=limit)
    out = []
    for r in requests:
        user = User.query.get(r.user_id) if r.user_id else None
        out.append({
            "id": r.id,
            "phone": r.phone,
            "status": r.status,
            "user_id": r.user_id,
            "username": user.username if user else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return jsonify({"code": 0, "message": "ok", "data": out})


@bp.route("/reset-requests/<int:req_id>/approve", methods=["POST"])
@admin_required
def approve_reset_request(req_id):
    """
    管理员处理忘记密码申请：将对应用户密码重置为默认密码，设置需强制修改密码，发短信通知用户，并标记申请已处理。
    """
    req = password_reset_request_storage.get_by_id(req_id)
    if not req:
        return jsonify({"code": 404, "message": "申请不存在", "data": None}), 404
    if req.status != "pending":
        return jsonify({"code": 400, "message": "该申请已处理", "data": None}), 400

    user = user_storage.get_by_phone(req.phone)
    if not user:
        password_reset_request_storage.mark_rejected(req_id, get_current_user()["sub"])
        return jsonify({"code": 404, "message": "该手机号未注册，无法重置", "data": None}), 404

    new_password = DEFAULT_RESET_PASSWORD
    user_storage.update_password_by_username(user.username, hash_password(new_password))
    user_storage.set_need_change_password(user.id, True)

    sms_sent = False
    if getattr(user, "phone", None) and (user.phone or "").strip():
        try:
            from app.sms_utils import send_reset_password_sms
            sms_sent = send_reset_password_sms((user.phone or "").strip(), user.username, new_password)
        except Exception:
            pass
    password_reset_request_storage.mark_done(req_id, get_current_user()["sub"])

    return jsonify({
        "code": 0,
        "message": "已重置为默认密码并已通知用户",
        "data": {"sms_sent": sms_sent, "username": user.username},
    })
