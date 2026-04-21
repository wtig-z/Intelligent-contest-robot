"""登录/注册/注销"""
from flask import Blueprint, request, jsonify, make_response

from backend.services import user_service
from backend.storage import user_storage
from backend.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    login_required,
)

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip() or None
    user, err = user_service.register(username, password, phone=phone)
    if err:
        return jsonify({"code": 400, "message": err, "data": None}), 400
    token = create_access_token(user.id, user.username, user.role)
    resp = make_response(jsonify({
        "code": 0,
        "message": "ok",
        "data": {"token": token, "username": user.username, "role": user.role},
    }))
    # 同步写 cookie，供页面路由（如 /admin）使用
    resp.set_cookie(
        "token",
        token,
        httponly=False,
        samesite="Lax",
        path="/",
    )
    return resp


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user, err = user_service.login(username, password)
    if err:
        return jsonify({"code": 401, "message": err, "data": None}), 401
    token = create_access_token(user.id, user.username, user.role)
    need_change = getattr(user, "need_change_password", False)
    resp = make_response(jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "token": token,
            "username": user.username,
            "role": user.role,
            "need_change_password": bool(need_change),
        },
    }))
    # 同步写 cookie，供页面路由（如 /admin）使用
    resp.set_cookie(
        "token",
        token,
        httponly=False,
        samesite="Lax",
        path="/",
    )
    return resp


@bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    """用户忘记密码：提交手机号，创建重置申请。管理员处理后会发短信通知默认密码。"""
    data = request.get_json() or {}
    phone = (data.get("phone") or "").strip()
    ok, err = user_service.request_forgot_password(phone)
    if not ok:
        return jsonify({"code": 400, "message": err or "提交失败", "data": None}), 400
    return jsonify({
        "code": 0,
        "message": "已提交，请等待管理员处理，将通过短信通知您新密码。",
        "data": None,
    })


@bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    """已登录用户修改密码（含管理员重置后首次登录的强制修改）。"""
    data = request.get_json() or {}
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""
    user = get_current_user()
    if not user:
        return jsonify({"code": 401, "message": "请先登录", "data": None}), 401
    ok, err = user_service.change_password(user["sub"], old_password, new_password)
    if not ok:
        return jsonify({"code": 400, "message": err or "修改失败", "data": None}), 400
    return jsonify({"code": 0, "message": "密码已修改", "data": None})


@bp.route("/me", methods=["GET"])
def me():
    user = get_current_user()
    if not user:
        return jsonify({"code": 401, "message": "未登录", "data": None}), 401
    u = user_storage.get_by_id(user["sub"])
    need_change = getattr(u, "need_change_password", False) if u else False
    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "id": user["sub"],
            "username": user["username"],
            "role": user["role"],
            "need_change_password": bool(need_change),
        },
    })


@bp.route("/refresh", methods=["POST"])
def refresh():
    data = request.get_json() or {}
    token = data.get("refresh_token")
    payload = decode_token(token) if token else None
    if not payload or payload.get("type") != "refresh":
        return jsonify({"code": 401, "message": "无效的 refresh token", "data": None}), 401
    from backend.storage import user_storage
    # refresh token 的 sub 在 JWT 里是 string（create_refresh_token 里写入），需要转回 int
    try:
        uid = int(payload.get("sub"))
    except Exception:
        uid = None
    if uid is None:
        return jsonify({"code": 401, "message": "无效的 refresh token", "data": None}), 401
    u = user_storage.get_by_id(uid)
    if not u:
        return jsonify({"code": 401, "message": "用户不存在", "data": None}), 401
    new_token = create_access_token(u.id, u.username, u.role)
    return jsonify({"code": 0, "message": "ok", "data": {"token": new_token}})
