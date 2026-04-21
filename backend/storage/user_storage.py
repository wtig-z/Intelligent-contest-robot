"""用户 CRUD"""
from sqlalchemy.exc import IntegrityError
from backend.storage.db import db
from backend.models.user_model import User


def get_by_username(username: str) -> User:
    return User.query.filter_by(username=username).first()


def get_by_phone(phone: str) -> User:
    """按手机号查询，用于唯一性校验。空字符串视为 None 不查。"""
    phone = (phone or "").strip()
    if not phone:
        return None
    return User.query.filter_by(phone=phone).first()


def get_by_id(user_id: int) -> User:
    return User.query.get(user_id)


def create(username: str, password_hash: str, role: str = "user", phone: str = None) -> User:
    phone = (phone or "").strip() or None
    if phone and get_by_phone(phone):
        raise ValueError("该手机号已被注册")
    u = User(username=username, password_hash=password_hash, role=role, phone=phone)
    db.session.add(u)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("用户名或手机号已被占用")
    return u


def update_password(user_id: int, password_hash: str) -> bool:
    """按用户 id 更新密码哈希，返回是否找到并更新。"""
    u = User.query.get(user_id)
    if not u:
        return False
    u.password_hash = password_hash
    db.session.commit()
    return True


def update_password_by_username(username: str, password_hash: str) -> bool:
    """按用户名更新密码哈希，返回是否找到并更新。"""
    u = User.query.filter_by(username=username).first()
    if not u:
        return False
    u.password_hash = password_hash
    db.session.commit()
    return True


def set_need_change_password(user_id: int, value: bool = True) -> bool:
    """设置用户是否需要强制修改密码（管理员重置后为 True）。"""
    u = User.query.get(user_id)
    if not u:
        return False
    u.need_change_password = bool(value)
    db.session.commit()
    return True


def clear_need_change_password(user_id: int) -> bool:
    """用户修改密码后清除强制修改标志。"""
    return set_need_change_password(user_id, False)


def get_by_username_for_reset(username: str):
    """按用户名获取用户（含 phone），用于重置密码时发短信。"""
    return User.query.filter_by(username=username).first()


def update_profile(user_id: int, **kwargs) -> bool:
    """更新用户个人资料，支持字段：username, phone, avatar, default_contest 等"""
    u = User.query.get(user_id)
    if not u:
        return False
    allowed = {
        'username', 'phone', 'avatar', 'default_contest',
        'pref_topk', 'pref_answer_format', 'pref_gmm_sensitivity',
        'pref_kmeans_clusters', 'privacy_anonymous',
    }
    for key, val in kwargs.items():
        if key in allowed and val is not None:
            setattr(u, key, val)
    db.session.commit()
    return True


def update_preferences(user_id: int, prefs: dict) -> bool:
    """更新用户检索偏好设置"""
    u = User.query.get(user_id)
    if not u:
        return False
    if 'default_contest' in prefs:
        u.default_contest = prefs['default_contest']
    if 'topk' in prefs:
        val = max(5, min(20, int(prefs['topk'])))
        u.pref_topk = val
    if 'answer_format' in prefs:
        if prefs['answer_format'] in ('brief', 'detailed'):
            u.pref_answer_format = prefs['answer_format']
    if 'gmm_sensitivity' in prefs:
        val = max(0.0, min(1.0, float(prefs['gmm_sensitivity'])))
        u.pref_gmm_sensitivity = val
    if 'kmeans_clusters' in prefs and u.role == 'admin':
        u.pref_kmeans_clusters = int(prefs['kmeans_clusters'])
    if 'privacy_anonymous' in prefs:
        u.privacy_anonymous = bool(prefs['privacy_anonymous'])
    db.session.commit()
    return True


def set_role(user_id: int, role: str) -> bool:
    allowed = frozenset({"user", "admin", "viewer"})
    if role not in allowed:
        return False
    u = User.query.get(user_id)
    if not u:
        return False
    u.role = role
    db.session.commit()
    return True


def get_all_users(limit: int = 100, offset: int = 0):
    return User.query.order_by(User.created_at.desc()).limit(limit).offset(offset).all()


def count_all_users() -> int:
    return User.query.count()
