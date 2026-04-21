"""赛事管理（后台）"""
from __future__ import annotations

from datetime import datetime

import os
from flask import Blueprint, jsonify, request

from backend.auth.jwt_handler import admin_required, backoffice_required
from backend.storage.db import db
from backend.models import Event

bp = Blueprint("admin_events", __name__, url_prefix="/api/admin/events")


def _events_pdf_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # backend/
    project_root = os.path.dirname(here)
    out = os.path.join(project_root, "data", "events", "pdfs")
    os.makedirs(out, exist_ok=True)
    return out


def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


@bp.route("/list", methods=["GET"])
@backoffice_required
def list_events_admin():
    include_deleted = str(request.args.get("include_deleted") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    q = Event.query
    if not include_deleted:
        q = q.filter_by(is_deleted=False)
    rows = q.order_by(Event.event_date.desc(), Event.id.desc()).all()
    items = []
    for e in rows:
        items.append(
            {
                "id": e.id,
                "title": e.title,
                "event_date": e.event_date.isoformat(),
                "official_url": e.official_url or "",
                "signup_desc": e.signup_desc or "",
                "has_notice_pdf": bool(getattr(e, "notice_pdf", None)),
                "is_deleted": bool(e.is_deleted),
            }
        )
    return jsonify({"code": 0, "message": "ok", "data": {"items": items}})


@bp.route("", methods=["POST"])
@admin_required
def create_event():
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    event_date = _parse_date(data.get("event_date") or "")
    official_url = (data.get("official_url") or "").strip() or None
    signup_desc = (data.get("signup_desc") or "").strip() or None
    if not title:
        return jsonify({"code": 400, "message": "赛事名称不能为空", "data": None}), 400
    if not event_date:
        return jsonify({"code": 400, "message": "赛事日期无效", "data": None}), 400
    e = Event(title=title, event_date=event_date, official_url=official_url, signup_desc=signup_desc)
    db.session.add(e)
    db.session.commit()
    return jsonify({"code": 0, "message": "ok", "data": {"id": e.id}})


@bp.route("/<int:event_id>", methods=["PUT"])
@admin_required
def update_event(event_id: int):
    e = Event.query.get(event_id)
    if not e:
        return jsonify({"code": 404, "message": "赛事不存在", "data": None}), 404
    data = request.get_json() or {}
    if "title" in data:
        t = (data.get("title") or "").strip()
        if not t:
            return jsonify({"code": 400, "message": "赛事名称不能为空", "data": None}), 400
        e.title = t
    if "event_date" in data:
        d = _parse_date(data.get("event_date") or "")
        if not d:
            return jsonify({"code": 400, "message": "赛事日期无效", "data": None}), 400
        e.event_date = d
    if "official_url" in data:
        e.official_url = (data.get("official_url") or "").strip() or None
    if "signup_desc" in data:
        e.signup_desc = (data.get("signup_desc") or "").strip() or None
    if "is_deleted" in data:
        e.is_deleted = bool(data.get("is_deleted"))
    db.session.commit()
    return jsonify({"code": 0, "message": "ok", "data": {"id": e.id}})


@bp.route("/<int:event_id>", methods=["DELETE"])
@admin_required
def delete_event(event_id: int):
    """软删除：前端不再展示。"""
    e = Event.query.get(event_id)
    if not e:
        return jsonify({"code": 404, "message": "赛事不存在", "data": None}), 404
    e.is_deleted = True
    db.session.commit()
    return jsonify({"code": 0, "message": "ok", "data": {"id": e.id}})


@bp.route("/<int:event_id>/notice_pdf", methods=["POST"])
@admin_required
def upload_notice_pdf(event_id: int):
    """上传赛事通知 PDF（multipart/form-data, field=file）。"""
    e = Event.query.get(event_id)
    if not e:
        return jsonify({"code": 404, "message": "赛事不存在", "data": None}), 404
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        return jsonify({"code": 400, "message": "缺少文件", "data": None}), 400
    name = os.path.basename(str(f.filename))
    if not name.lower().endswith(".pdf"):
        return jsonify({"code": 400, "message": "仅支持 PDF 文件", "data": None}), 400
    # 统一命名，避免冲突与路径问题
    safe = f"event_{e.id}.pdf"
    out_dir = _events_pdf_dir()
    out_path = os.path.join(out_dir, safe)
    f.save(out_path)
    e.notice_pdf = safe
    db.session.commit()
    return jsonify({"code": 0, "message": "ok", "data": {"id": e.id, "notice_pdf": safe}})

