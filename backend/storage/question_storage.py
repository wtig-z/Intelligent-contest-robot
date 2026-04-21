"""用户问题 CRUD：增强版（筛选/缓存）"""
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import func, or_

from config.app_config import DEFAULT_DATASET
from backend.storage.db import db
from backend.models.question_model import Question
from backend.models.pdf_model import PDF


def _contest_display_name(competition_id: Optional[str], dataset: str) -> str:
    """与 /api/contests 一致：用 PDF.contest_name（管理员可改）作为展示名，缺省回退 id。"""
    cid = (competition_id or "").strip()
    if not cid:
        return ""
    # 火山等路径：多 PDF 命中或与所选赛事不一致时记为 '-'，无法对应单一 PDF 展示名
    if cid in ("-", "—"):
        return "综合文档"
    stem = cid[:-4] if cid.lower().endswith(".pdf") else cid
    fn_pdf = stem + ".pdf" if not stem.lower().endswith(".pdf") else stem
    p = (
        PDF.query.filter_by(dataset=dataset)
        .filter(or_(PDF.filename == fn_pdf, PDF.filename == stem))
        .first()
    )
    if p and getattr(p, "contest_name", None) and str(p.contest_name).strip():
        return str(p.contest_name).strip()
    return stem


def create(user_id: int, content: str, answer: str = None, rewritten: str = None,
           query_type: str = 'text', competition_id: str = '',
           answer_basis: str = '', engine_source: str = 'vidorag',
           seeker_rounds: int = 0, cache_key: str = '') -> Question:
    # 双保险：理论上上游已把 answer 转成最终 Markdown 字符串；这里仅兜底转 str 防止写库炸
    if answer is not None and not isinstance(answer, str):
        answer = str(answer)
    q = Question(
        user_id=user_id,
        content=content,
        answer=answer,
        rewritten=rewritten,
        query_type=query_type,
        competition_id=competition_id,
        answer_basis=answer_basis,
        engine_source=engine_source,
        seeker_rounds=seeker_rounds,
        cache_key=cache_key,
    )
    db.session.add(q)
    db.session.commit()
    return q


def get_by_id(question_id: int) -> Optional[Question]:
    return Question.query.get(question_id)


def get_by_cache_key(cache_key: str) -> Optional[Question]:
    if not cache_key:
        return None
    return Question.query.filter_by(cache_key=cache_key).first()


def list_all(limit: int = 100, offset: int = 0):
    return Question.query.order_by(Question.created_at.desc()).limit(limit).offset(offset).all()


def list_for_admin(
    limit: int = 100,
    offset: int = 0,
    user_id: Optional[int] = None,
    competition_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    keyword: Optional[str] = None,
):
    """管理端对话列表：多条件筛选。"""
    q = Question.query
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    if competition_id:
        q = q.filter(Question.competition_id.contains(competition_id))
    if date_from is not None:
        q = q.filter(Question.created_at >= date_from)
    if date_to is not None:
        q = q.filter(Question.created_at <= date_to)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Question.content.like(like)) | (Question.answer.like(like)))
    return q.order_by(Question.created_at.desc()).limit(limit).offset(offset).all()


def count_for_admin(
    user_id: Optional[int] = None,
    competition_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    keyword: Optional[str] = None,
) -> int:
    q = Question.query
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    if competition_id:
        q = q.filter(Question.competition_id.contains(competition_id))
    if date_from is not None:
        q = q.filter(Question.created_at >= date_from)
    if date_to is not None:
        q = q.filter(Question.created_at <= date_to)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Question.content.like(like)) | (Question.answer.like(like)))
    return q.count()


def list_by_user(user_id: int, limit: int = 50, offset: int = 0,
                 competition_id: Optional[str] = None,
                 keyword: Optional[str] = None,
                 engine_source: Optional[str] = None,
                 query_type: Optional[str] = None) -> List[Question]:
    """按用户查询历史记录，支持多维度筛选"""
    q = Question.query.filter_by(user_id=user_id)
    if competition_id:
        q = q.filter(Question.competition_id.contains(competition_id))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Question.content.like(like)) | (Question.answer.like(like)))
    if engine_source:
        q = q.filter_by(engine_source=engine_source)
    if query_type:
        q = q.filter_by(query_type=query_type)
    return q.order_by(Question.created_at.desc()).limit(limit).offset(offset).all()


def count_by_user(user_id: int, competition_id: Optional[str] = None,
                  keyword: Optional[str] = None,
                  engine_source: Optional[str] = None,
                  query_type: Optional[str] = None) -> int:
    q = Question.query.filter_by(user_id=user_id)
    if competition_id:
        q = q.filter(Question.competition_id.contains(competition_id))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Question.content.like(like)) | (Question.answer.like(like)))
    if engine_source:
        q = q.filter_by(engine_source=engine_source)
    if query_type:
        q = q.filter_by(query_type=query_type)
    return q.count()


def count_all():
    return Question.query.count()


def top_competitions_by_count_since(days: int = 7, limit: int = 6) -> List[Tuple[str, int]]:
    """全站：自 cutoff 起按 competition_id 聚合提问次数，取前 limit 条（用于首页热门赛事）。"""
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), 50))
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.session.query(Question.competition_id, func.count(Question.id).label("cnt"))
        .filter(Question.created_at >= cutoff)
        .filter(Question.competition_id.isnot(None))
        .filter(Question.competition_id != "")
        .group_by(Question.competition_id)
        .order_by(func.count(Question.id).desc())
        .limit(limit)
        .all()
    )
    return [(str(r.competition_id), int(r.cnt)) for r in rows]


def get_user_stats(user_id: int) -> dict:
    """获取用户问答统计"""
    total = Question.query.filter_by(user_id=user_id).count()
    visual_count = Question.query.filter_by(user_id=user_id, query_type='visual').count()
    text_count = Question.query.filter_by(user_id=user_id, query_type='text').count()

    avg_seeker = db.session.query(func.avg(Question.seeker_rounds)).filter_by(user_id=user_id).scalar() or 0

    top_contests_raw = db.session.query(
        Question.competition_id, func.count(Question.id)
    ).filter(
        Question.user_id == user_id,
        Question.competition_id.isnot(None),
        Question.competition_id != ''
    ).group_by(Question.competition_id).order_by(func.count(Question.id).desc()).limit(5).all()

    ds = DEFAULT_DATASET
    top_contests = [
        {
            'id': c[0],
            'name': _contest_display_name(c[0], ds),
            'count': c[1],
        }
        for c in top_contests_raw
    ]

    return {
        'total': total,
        'visual_count': visual_count,
        'text_count': text_count,
        'visual_ratio': round(visual_count / total * 100, 1) if total > 0 else 0,
        'avg_seeker_rounds': round(float(avg_seeker), 2),
        'top_contests': top_contests,
    }
