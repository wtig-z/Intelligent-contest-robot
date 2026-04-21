"""分享链接 CRUD"""
import uuid
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError

from backend.storage.db import db
from backend.models.share_link_model import ShareLink


def get_by_share_id(share_id: str) -> Optional[ShareLink]:
    if not share_id:
        return None
    return ShareLink.query.filter_by(share_id=str(share_id).strip()).first()


def get_by_question_id(question_id: int) -> Optional[ShareLink]:
    return ShareLink.query.filter_by(question_id=question_id).first()


def create_for_question(user_id: int, question_id: int) -> Tuple[ShareLink, bool]:
    """
    每条问答记录最多一条分享映射：已存在则返回已有记录，否则新建。
    返回 (记录, 是否新创建)。
    """
    existing = get_by_question_id(question_id)
    if existing:
        return existing, False
    sl = ShareLink(
        share_id=str(uuid.uuid4()),
        question_id=question_id,
        user_id=user_id,
    )
    db.session.add(sl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = get_by_question_id(question_id)
        if existing:
            return existing, False
        raise
    return sl, True
