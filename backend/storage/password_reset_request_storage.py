"""忘记密码申请 CRUD（基于 change_pwd 模型）"""
from datetime import datetime
from backend.storage.db import db
from backend.models.change_pwd import change_pwd


def create(phone: str, user_id: int = None) -> change_pwd:
    """用户提交忘记密码/修改密码申请，创建一条 pending 记录。若传入 user_id 则关联；否则按手机号查用户并关联。"""
    from backend.storage import user_storage
    phone = (phone or "").strip()
    if not user_id:
        u = user_storage.get_by_phone(phone)
        user_id = u.id if u else None
    req = change_pwd(phone=phone, status="pending", user_id=user_id)
    db.session.add(req)
    db.session.commit()
    return req


def get_pending_list(limit: int = 100):
    """管理员查看待处理的申请列表，按创建时间倒序。"""
    return (
        change_pwd.query.filter_by(status="pending")
        .order_by(change_pwd.created_at.desc())
        .limit(limit)
        .all()
    )


def get_by_id(req_id: int) -> change_pwd:
    return change_pwd.query.get(req_id)


def mark_done(req_id: int, processed_by: int) -> bool:
    """标记申请已处理。"""
    req = change_pwd.query.get(req_id)
    if not req:
        return False
    req.status = "done"
    req.processed_at = datetime.utcnow()
    req.processed_by = processed_by
    db.session.commit()
    return True


def mark_rejected(req_id: int, processed_by: int) -> bool:
    """标记申请已拒绝。"""
    req = change_pwd.query.get(req_id)
    if not req:
        return False
    req.status = "rejected"
    req.processed_at = datetime.utcnow()
    req.processed_by = processed_by
    db.session.commit()
    return True
