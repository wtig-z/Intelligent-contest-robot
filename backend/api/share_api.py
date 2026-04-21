"""分享：登录用户生成链接；公开读取落地页数据"""
import json
from typing import Optional
from urllib.parse import quote

from flask import Blueprint, request, jsonify

from config.app_config import DEFAULT_DATASET
from backend.auth.jwt_handler import login_required, get_current_user
from backend.storage import question_storage, share_storage

bp = Blueprint("share", __name__, url_prefix="/api/share")


def _base_url() -> str:
    return (request.url_root or "").rstrip("/")


def _preview_image_url(question) -> Optional[str]:
    """从 answer_basis 取首张依据图 URL（与前端 /api/img 一致，无需登录）。"""
    base = _base_url()
    try:
        ab = json.loads(question.answer_basis or "{}")
        vr = ab.get("vidorag") or {}
        refs = vr.get("page_refs") or []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            u = ref.get("url")
            if u:
                return u if str(u).startswith("http") else base + str(u)
            f = ref.get("file")
            if f:
                fn = str(f).replace("\\", "/").split("/")[-1]
                ds = quote(str(DEFAULT_DATASET), safe="")
                return f"{base}/api/img/{ds}/{quote(fn, safe='')}"
    except Exception:
        pass
    return None


@bp.route("", methods=["POST"])
@login_required
def create_share():
    """生成或复用分享 ID，返回落地链接与预览图。"""
    data = request.get_json() or {}
    try:
        qid = int(data.get("question_id"))
    except (TypeError, ValueError):
        return jsonify({"code": 400, "message": "question_id 无效"}), 400

    user = get_current_user()
    q = question_storage.get_by_id(qid)
    if not q or q.user_id != user["sub"]:
        return jsonify({"code": 404, "message": "记录不存在"}), 404

    sl, _created = share_storage.create_for_question(user_id=user["sub"], question_id=qid)
    base = _base_url()
    share_url = f"{base}/s/{sl.share_id}"
    preview = _preview_image_url(q)
    return jsonify({
        "code": 0,
        "data": {
            "share_id": sl.share_id,
            "url": share_url,
            "preview_image": preview,
        },
    })


@bp.route("/<share_id>", methods=["GET"])
def get_share_public(share_id):
    """公开：无需登录，仅返回问题与回答（落地页用）。"""
    sid = (share_id or "").strip()
    sl = share_storage.get_by_share_id(sid)
    if not sl:
        return jsonify({"code": 404, "message": "分享不存在或已失效"}), 404
    q = question_storage.get_by_id(sl.question_id)
    if not q:
        return jsonify({"code": 404, "message": "内容不存在"}), 404
    preview = _preview_image_url(q)
    return jsonify({
        "code": 0,
        "data": {
            "question": q.content or "",
            "answer": q.answer or "",
            "preview_image": preview,
        },
    })
