"""对话历史管理：筛选列表。"""
from datetime import datetime

from flask import Blueprint, request, jsonify

from backend.auth.jwt_handler import backoffice_required
from backend.storage import question_storage
from backend.models import User

bp = Blueprint("question_manage", __name__, url_prefix="/api/admin/questions")


def _parse_dt(s: str | None):
    if not s:
        return None
    s = str(s).strip()
    try:
        if len(s) <= 10:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


@bp.route("/list", methods=["GET"])
@backoffice_required
def list_questions():
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))
    user_id = request.args.get("user_id")
    uid = int(user_id) if user_id and str(user_id).isdigit() else None
    competition_id = (request.args.get("competition_id") or "").strip() or None
    keyword = (request.args.get("keyword") or "").strip() or None
    df = _parse_dt(request.args.get("date_from"))
    dt = _parse_dt(request.args.get("date_to"))

    items = question_storage.list_for_admin(
        limit=limit,
        offset=offset,
        user_id=uid,
        competition_id=competition_id,
        date_from=df,
        date_to=dt,
        keyword=keyword,
    )
    total = question_storage.count_for_admin(
        user_id=uid,
        competition_id=competition_id,
        date_from=df,
        date_to=dt,
        keyword=keyword,
    )
    user_ids = {q.user_id for q in items if getattr(q, "user_id", None) is not None}
    users = User.query.filter(User.id.in_(user_ids)).all() if user_ids else []
    user_map = {u.id: u.username for u in users}
    return jsonify({
        "code": 0,
        "message": "ok",
        "data": {
            "items": [
                {
                    "id": q.id,
                    "content": q.content[:500] if q.content else "",
                    "answer": (q.answer or "")[:800] if q.answer else None,
                    "user_id": q.user_id,
                    "username": user_map.get(q.user_id, None),
                    "query_type": getattr(q, "query_type", "text"),
                    "competition_id": getattr(q, "competition_id", ""),
                    "answer_basis": (getattr(q, "answer_basis", "") or "")[:1200],
                    "engine_source": getattr(q, "engine_source", "vidorag"),
                    "seeker_rounds": getattr(q, "seeker_rounds", 0),
                    "cache_key": getattr(q, "cache_key", ""),
                    "created_at": q.created_at.isoformat() if q.created_at else None,
                }
                for q in items
            ],
            "total": total,
        },
    })
