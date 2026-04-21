"""JWT 生成/验证"""
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import request
import jwt

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_EXP = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))
REFRESH_EXP = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 86400 * 7))


def create_access_token(user_id: int, username: str, role: str) -> str:
    payload = {
        # PyJWT 对标准声明 sub(subject) 有校验：必须是 string
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(seconds=ACCESS_EXP),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(seconds=REFRESH_EXP),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None


def get_current_user():
    """
    从 request 获取当前用户。

    支持两种来源：
    - Authorization: Bearer <token>（API 调用）
    - Cookie: token=<token>（页面路由，如 /admin 访问）
    """
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        bearer = auth[7:].strip()
        if bearer:
            payload = decode_token(bearer)
            if payload and payload.get("type") == "access":
                # 将 sub 统一转换回 int，兼容数据库查询
                try:
                    payload["sub"] = int(payload.get("sub"))
                except Exception:
                    return None
                if payload.get("role") == "operator":
                    payload["role"] = "viewer"
                return payload
            # Bearer 存在但无效/过期时，回退读取 cookie（避免旧 token 影响当前会话）

    cookie_token = request.cookies.get("token")
    if not cookie_token:
        return None
    payload = decode_token(cookie_token)
    if not payload or payload.get("type") != "access":
        return None
    try:
        payload["sub"] = int(payload.get("sub"))
    except Exception:
        return None
    if payload.get("role") == "operator":
        payload["role"] = "viewer"
    return payload


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        from flask import jsonify
        user = get_current_user()
        if not user:
            return jsonify({"code": 401, "message": "请先登录", "data": None}), 401
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        from flask import jsonify
        user = get_current_user()
        if not user:
            return jsonify({"code": 401, "message": "请先登录", "data": None}), 401
        if user.get("role") != "admin":
            return jsonify({"code": 403, "message": "需要管理员权限", "data": None}), 403
        return f(*args, **kwargs)
    return wrapped


# 管理后台可访问角色：管理员 / 访客（只读）；上传与索引构建仅 admin
BACKOFFICE_ROLES = frozenset({"admin", "viewer"})
UPLOADER_ROLES = frozenset({"admin"})


def backoffice_required(f):
    """已登录且为后台账号（admin | viewer）。"""

    @wraps(f)
    def wrapped(*args, **kwargs):
        from flask import jsonify

        user = get_current_user()
        if not user:
            return jsonify({"code": 401, "message": "请先登录", "data": None}), 401
        if user.get("role") not in BACKOFFICE_ROLES:
            return jsonify({"code": 403, "message": "无后台访问权限", "data": None}), 403
        return f(*args, **kwargs)

    return wrapped


def uploader_required(f):
    """可上传文档、触发知识库更新（仅 admin）。"""

    @wraps(f)
    def wrapped(*args, **kwargs):
        from flask import jsonify

        user = get_current_user()
        if not user:
            return jsonify({"code": 401, "message": "请先登录", "data": None}), 401
        if user.get("role") not in UPLOADER_ROLES:
            return jsonify({"code": 403, "message": "需要管理员权限", "data": None}), 403
        return f(*args, **kwargs)

    return wrapped
