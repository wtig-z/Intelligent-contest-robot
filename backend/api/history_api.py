"""用户问答历史接口：查询、筛选、重查"""
import json
from typing import Any, Dict, Optional
from urllib.parse import quote

from flask import Blueprint, request, jsonify

from config.app_config import DEFAULT_DATASET
from backend.auth.jwt_handler import login_required, get_current_user
from backend.storage import question_storage

bp = Blueprint('history', __name__, url_prefix='/api/history')


def _history_list_thumb_url(answer_basis_raw: Optional[str]) -> Optional[str]:
    """
    列表卡片用小图：优先用户提问附图，其次资料插图，再 ViDoRAG 页图。
    返回绝对 URL（http/https）或与站点同源的 /api/img/... 路径。
    """
    if not answer_basis_raw or not str(answer_basis_raw).strip():
        return None
    try:
        data: Dict[str, Any] = json.loads(answer_basis_raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    def _pick(u: str) -> str:
        u = (u or "").strip()
        if not u:
            return ""
        if u.startswith(("http://", "https://", "/")):
            return u
        return u

    iu = data.get("image_urls")
    if isinstance(iu, list):
        for x in iu:
            s = _pick(str(x))
            if s:
                return s

    refs = data.get("references")
    if isinstance(refs, list):
        for r in refs:
            if isinstance(r, dict):
                s = _pick(str(r.get("related_image") or ""))
                if s:
                    return s

    vr = data.get("vidorag")
    if isinstance(vr, dict):
        pr = vr.get("page_refs")
        if isinstance(pr, list):
            ds = str(data.get("image_dataset") or DEFAULT_DATASET or "CompetitionDataset").strip() or "CompetitionDataset"
            for ref in pr:
                if not isinstance(ref, dict):
                    continue
                s = _pick(str(ref.get("url") or ""))
                if s:
                    return s
                fn = str(ref.get("file") or "").strip()
                if fn:
                    fn = fn.replace("\\", "/").split("/")[-1]
                    return f"/api/img/{quote(ds, safe='')}/{quote(fn, safe='')}"
    return None


@bp.route('', methods=['GET'])
@login_required
def list_history():
    """
    查询当前用户的问答历史
    参数: limit, offset, competition_id, keyword, engine_source, query_type
    """
    user = get_current_user()
    limit = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))
    competition_id = request.args.get('competition_id') or None
    keyword = request.args.get('keyword') or None
    engine_source = request.args.get('engine_source') or None
    query_type = request.args.get('query_type') or None

    items = question_storage.list_by_user(
        user_id=user['sub'],
        limit=limit,
        offset=offset,
        competition_id=competition_id,
        keyword=keyword,
        engine_source=engine_source,
        query_type=query_type,
    )
    total = question_storage.count_by_user(
        user_id=user['sub'],
        competition_id=competition_id,
        keyword=keyword,
        engine_source=engine_source,
        query_type=query_type,
    )

    return jsonify({
        'code': 0,
        'data': {
            'items': [
                {
                    'id': q.id,
                    'content': q.content,
                    'answer': q.answer,
                    'rewritten': q.rewritten,
                    'query_type': q.query_type,
                    'competition_id': q.competition_id,
                    'engine_source': q.engine_source,
                    'seeker_rounds': q.seeker_rounds,
                    'cache_key': q.cache_key,
                    'created_at': q.created_at.isoformat() if q.created_at else None,
                    'list_thumb_url': _history_list_thumb_url(q.answer_basis),
                }
                for q in items
            ],
            'total': total,
            'limit': limit,
            'offset': offset,
        }
    })


@bp.route('/<int:question_id>', methods=['GET'])
@login_required
def get_detail(question_id):
    """获取单条历史记录详情"""
    user = get_current_user()
    q = question_storage.get_by_id(question_id)
    if not q or q.user_id != user['sub']:
        return jsonify({'code': 404, 'message': '记录不存在'}), 404

    return jsonify({
        'code': 0,
        'data': {
            'id': q.id,
            'content': q.content,
            'answer': q.answer,
            'rewritten': q.rewritten,
            'query_type': q.query_type,
            'competition_id': q.competition_id,
            'answer_basis': q.answer_basis,
            'engine_source': q.engine_source,
            'seeker_rounds': q.seeker_rounds,
            'cache_key': q.cache_key,
            'created_at': q.created_at.isoformat() if q.created_at else None,
            'updated_at': q.updated_at.isoformat() if q.updated_at else None,
        }
    })


@bp.route('/requery', methods=['POST'])
@login_required
def requery():
    """一键重查：复用原赛事ID和检索参数"""
    data = request.get_json() or {}
    question_id = data.get('question_id')
    new_query = data.get('query')

    if not question_id:
        return jsonify({'code': 400, 'message': '请提供原记录ID'}), 400

    user = get_current_user()
    q = question_storage.get_by_id(question_id)
    if not q or q.user_id != user['sub']:
        return jsonify({'code': 404, 'message': '记录不存在'}), 404

    image_urls = []
    route = ''
    try:
        if q.answer_basis:
            basis = json.loads(q.answer_basis)
            if isinstance(basis, dict):
                route = str(basis.get('route') or '')
                raw_iu = basis.get('image_urls')
                if isinstance(raw_iu, list):
                    for u in raw_iu[:8]:
                        s = str(u).strip()
                        if s:
                            image_urls.append(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        image_urls = []
        route = ''

    is_volc_kb = 'volc_kb' in route.lower() or (q.engine_source or '') == 'volc_kb'

    return jsonify({
        'code': 0,
        'data': {
            'query': new_query or q.content,
            'competition_id': q.competition_id,
            'cache_key': q.cache_key,
            'engine_source': q.engine_source or '',
            'image_urls': image_urls,
            'is_volc_kb': is_volc_kb,
        }
    })
