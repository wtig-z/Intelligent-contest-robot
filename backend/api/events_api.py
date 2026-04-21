"""公开赛事日历 API（游客可访问）"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import os
from flask import Blueprint, jsonify, request, send_from_directory

from backend.models import Event

bp = Blueprint("events", __name__, url_prefix="/api/events")


def _parse_month(s: str) -> Optional[tuple[int, int]]:
    """YYYY-MM -> (year, month)"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m")
        return dt.year, dt.month
    except Exception:
        return None


@bp.route("", methods=["GET"])
def list_events():
    """公开列表：默认仅返回未来赛事；支持 month=YYYY-MM 过滤；include_past=1 可包含历史。"""
    month = _parse_month(request.args.get("month") or "")
    include_past = str(request.args.get("include_past") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    q = Event.query.filter_by(is_deleted=False)
    if not include_past:
        q = q.filter(Event.event_date >= date.today())
    if month:
        y, m = month
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1)
        else:
            end = date(y, m + 1, 1)
        q = q.filter(Event.event_date >= start).filter(Event.event_date < end)
    rows = q.order_by(Event.event_date.asc(), Event.id.asc()).all()
    items = []
    for e in rows:
        has_pdf = bool(getattr(e, "notice_pdf", None))
        items.append(
            {
                "id": e.id,
                "title": e.title,
                "event_date": e.event_date.isoformat(),
                "official_url": e.official_url or "",
                "signup_desc": e.signup_desc or "",
                "notice_pdf_url": f"/api/events/{e.id}/notice.pdf" if has_pdf else "",
            }
        )
    return jsonify({"code": 0, "message": "ok", "data": {"items": items}})


@bp.route("/<int:event_id>/notice.pdf", methods=["GET"])
def download_notice_pdf(event_id: int):
    """下载赛事通知 PDF（如存在）。"""
    e = Event.query.get(event_id)
    if not e or e.is_deleted:
        return jsonify({"code": 404, "message": "赛事不存在", "data": None}), 404
    fn = (getattr(e, "notice_pdf", None) or "").strip()
    if not fn:
        return jsonify({"code": 404, "message": "该赛事暂无通知 PDF", "data": None}), 404
    # 防止目录穿越
    base = os.path.basename(fn)
    if not base or base != fn or ".." in fn or "/" in fn or "\\" in fn:
        return jsonify({"code": 400, "message": "文件名无效", "data": None}), 400
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    project_root = os.path.dirname(here)  # repo root
    pdf_dir = os.path.join(project_root, "data", "events", "pdfs")
    if not os.path.exists(os.path.join(pdf_dir, base)):
        return jsonify({"code": 404, "message": "文件不存在", "data": None}), 404
    return send_from_directory(pdf_dir, base, as_attachment=True, download_name=base)

