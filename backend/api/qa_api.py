"""问答接口：多轮对话、赛事列表、按赛事检索、回答引用图片服务"""
import json
import logging
import os
import time
import uuid
from flask import Blueprint, request, jsonify, send_from_directory

from config.app_config import DEFAULT_DATASET
from config.paths import get_pdf_dir, get_img_dir
from backend.services.qa_service import chat as qa_chat
from backend.auth.jwt_handler import get_current_user
from backend.storage import question_storage, user_storage
from collections import defaultdict

from backend.models.pdf_model import PDF
from backend.models.competition_struct_model import CompetitionStruct
from backend.services.cancel_registry import CancelledError, cancel as cancel_request
from backend.services import task_registry

bp = Blueprint('qa', __name__, url_prefix='/api')
logger = logging.getLogger("contest_robot.qa_api")

_cancelled_request_ids = set()


def _category_display_label(key: str) -> str:
    k = (key or "").strip() or "其他"
    return {
        "AI竞赛": "人工智能 / AI 竞赛",
        "数学建模": "数学建模",
        "其他": "综合 / 其他",
    }.get(k, k)


@bp.route('/contests', methods=['GET'])
def list_contests():
    """列出当前可选的赛事；含结构化库中的赛事类别，供前端级联选择。"""
    dataset = request.args.get('dataset') or DEFAULT_DATASET
    pdfs = PDF.query.filter_by(dataset=dataset).filter(
        PDF.status.in_(['processed', 'pending'])
    ).order_by(PDF.created_at.desc()).all()
    contests = []
    by_cat: dict[str, list[str]] = defaultdict(list)
    for p in pdfs:
        doc_id = p.filename[:-4] if p.filename.lower().endswith('.pdf') else p.filename
        row = CompetitionStruct.query.filter_by(dataset=dataset, competition_id=doc_id).first()
        cat = (row.competition_category if row else None) or "其他"
        by_cat[cat].append(doc_id)
        contests.append({
            'id': doc_id,
            'name': p.contest_name or doc_id,
            'pdf_name': p.filename,
            'category': cat,
        })
    _cat_order = {"AI竞赛": 0, "数学建模": 1, "其他": 99}
    categories = []
    for key in sorted(by_cat.keys(), key=lambda x: (_cat_order.get(x, 50), str(x))):
        ids = sorted(by_cat[key], key=str)
        categories.append({
            'key': key,
            'label': _category_display_label(key),
            'contest_ids': ids,
        })
    return jsonify({'contests': contests, 'categories': categories})


def _ordered_contests_from_db(dataset: str):
    """与 list_contests 相同顺序：created_at 降序（新入库在前）。"""
    pdfs = PDF.query.filter_by(dataset=dataset).filter(
        PDF.status.in_(['processed', 'pending'])
    ).order_by(PDF.created_at.desc()).all()
    out = []
    for p in pdfs:
        doc_id = p.filename[:-4] if p.filename.lower().endswith('.pdf') else p.filename
        out.append({'id': doc_id, 'name': p.contest_name or doc_id})
    return out


@bp.route('/contests/hot', methods=['GET'])
def list_hot_contests():
    """首页热门标签：先按近 N 天全站提问次数取前若干（最多 50 名候选），再按数据库顺序补满 limit 条。
    无提问数据时等价于数据库列表前 limit 条。仅返回 id/name（次数仅管理端可查）。"""
    try:
        days = int(request.args.get('days', 7))
    except (TypeError, ValueError):
        days = 7
    try:
        limit = int(request.args.get('limit', 6))
    except (TypeError, ValueError):
        limit = 6
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 20))
    dataset = request.args.get('dataset') or DEFAULT_DATASET
    db_contests = _ordered_contests_from_db(dataset)
    db_ids = {c['id'] for c in db_contests}
    hot_rows = question_storage.top_competitions_by_count_since(days, 50)
    seen = set()
    contests = []
    for cid, _cnt in hot_rows:
        if len(contests) >= limit:
            break
        if cid not in db_ids or cid in seen:
            continue
        seen.add(cid)
        name = next((c['name'] for c in db_contests if c['id'] == cid), cid)
        contests.append({'id': cid, 'name': name})
    for c in db_contests:
        if len(contests) >= limit:
            break
        if c['id'] in seen:
            continue
        seen.add(c['id'])
        contests.append({'id': c['id'], 'name': c['name']})
    return jsonify({'contests': contests, 'days': days, 'limit': limit})


@bp.route('/img/<dataset>/<path:filename>', methods=['GET'])
def serve_image(dataset, filename):
    """返回数据集 img 目录下的图片"""
    base = os.path.basename(filename)
    if not base or base != filename or ".." in filename:
        return jsonify({'code': 400, 'message': 'invalid path'}), 400
    img_dir = get_img_dir(dataset)
    path = os.path.join(img_dir, base)
    if not os.path.isfile(path):
        return jsonify({'code': 404, 'message': 'not found'}), 404
    return send_from_directory(img_dir, base, as_attachment=False)


@bp.route('/chat/cancel', methods=['POST'])
def chat_cancel():
    """仅中断当前用户自己的进行中的问答（不发送新问题）。与 cancel_registry 联动。"""
    data = request.get_json() or {}
    rid = (data.get('request_id') or '').strip()
    if not rid:
        return jsonify({'code': 400, 'message': '缺少 request_id', 'data': None}), 400
    user = get_current_user()
    if not user:
        return jsonify({'code': 401, 'message': '请先登录', 'data': None}), 401
    if user.get('role') == 'viewer':
        return jsonify({'code': 403, 'message': '访客不可使用问答', 'data': None}), 403
    ok = task_registry.user_cancel_own_request(rid, user.get('sub'))
    if not ok:
        return jsonify({'code': 404, 'message': '任务不存在或已结束', 'data': None}), 404
    return jsonify({'code': 0, 'message': 'ok', 'data': None})


@bp.route('/chat', methods=['POST'])
def chat():
    """
    POST /api/chat
    body: { message, history, request_id, cancel_request_id, pdf_name, contest }
    返回: { answer, images, rewritten, history, engine_source, query_type, answer_basis }
    """
    data = request.get_json() or {}
    message = (data.get('message') or data.get('user_request') or '').strip()
    if not message:
        return jsonify({'code': 400, 'message': 'message 不能为空', 'data': None}), 400
    history = data.get('history')
    if history is not None and not isinstance(history, list):
        history = None
    request_id = data.get('request_id')
    if request_id is not None:
        request_id = str(request_id).strip() or None
    if not request_id:
        request_id = str(uuid.uuid4())
    cancel_request_id = data.get('cancel_request_id')
    if cancel_request_id is not None:
        cancel_request_id = str(cancel_request_id).strip() or None
    if cancel_request_id:
        _cancelled_request_ids.add(cancel_request_id)
        # 标记取消（用于正在运行的旧请求尽快退出）
        cancel_request(cancel_request_id)

    pdf_name = (data.get('pdf_name') or data.get('contest') or '').strip() or None
    raw_ids = data.get('contest_ids')
    contest_ids = None
    if isinstance(raw_ids, list):
        contest_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        if not contest_ids:
            contest_ids = None
    if contest_ids is not None:
        pdf_name = None

    user = get_current_user()
    if not user:
        # 未登录不允许调用核心问答，避免触发模型加载与产生无归属的对话记录
        return jsonify({'code': 401, 'message': '请先登录再使用', 'data': None}), 401
    if user.get("role") == "viewer":
        return jsonify({"code": 403, "message": "访客账号仅可浏览管理后台，不可使用问答", "data": None}), 403
    user_prefs = {}
    if user:
        u = user_storage.get_by_id(user['sub'])
        if u:
            user_prefs = {
                'topk': u.pref_topk,
                'answer_format': u.pref_answer_format,
                'gmm_sensitivity': u.pref_gmm_sensitivity,
            }

    # 前端“深度思考”开关：决定是否启用 GraphRAG（更慢但覆盖多实体/全局归纳更强）
    deep_think_raw = data.get('deep_think')
    deep_think = False
    if deep_think_raw is not None:
        s = str(deep_think_raw).strip().lower()
        deep_think = s in ("1", "true", "yes", "on")
    user_prefs["deep_think"] = deep_think

    wait_sec = float(os.getenv("QA_QUEUE_WAIT_SEC", "120"))
    if not task_registry.acquire_qa_slot(blocking=True, timeout=wait_sec):
        return jsonify({
            "code": 503,
            "message": "当前问答并发已满，请稍后重试",
            "data": {"request_id": request_id},
        }), 503

    acquired = True
    scope_preview = pdf_name or (",".join(contest_ids) if contest_ids else None)
    task_registry.register_running(
        request_id,
        user_id=user.get("sub"),
        username=user.get("username"),
        message_preview=message,
        pdf_name=scope_preview,
        phase="qa",
    )
    t0 = time.time()
    result = None
    try:
        result = qa_chat(
            message=message,
            history=history,
            request_id=request_id,
            pdf_name=pdf_name,
            contest_ids=contest_ids,
            user_prefs=user_prefs,
        )
    except CancelledError:
        # 请求中断（Abort）是正常路径，不是错误：不打 ERROR、不返回 5xx
        dur_ms = (time.time() - t0) * 1000.0
        logger.info(
            "request cancelled (正常中断): request_id=%s duration_ms=%.2f",
            request_id,
            dur_ms,
        )
        task_registry.finish_running(
            request_id,
            status="cancelled",
            interrupted=True,
            duration_ms=dur_ms,
            engine_source="none",
        )
        payload = {
            "code": 200,
            "message": "ok",
            "answer": "已中断上一轮回答",
            "status": "cancelled",
            "images": [],
            "image_refs": [],
            "image_dataset": DEFAULT_DATASET,
            "rewritten": "",
            "history": list(history or []) + [{"role": "user", "content": message}],
            "engine_source": "none",
            "query_type": "text",
            "answer_basis": json.dumps({"route": "request_cancelled"}, ensure_ascii=False),
            "seeker_rounds": 0,
            "competition_id": (",".join(contest_ids) if contest_ids else (pdf_name or "")),
            "cache_key": "",
            "request_id": request_id,
        }
        return jsonify(payload), 200
    except Exception as e:
        dur_ms = (time.time() - t0) * 1000.0
        # 关键：保留 traceback，便于定位 500 根因
        logger.exception("qa_chat exception request_id=%s pdf_name=%s", request_id, pdf_name)
        task_registry.finish_running(
            request_id,
            status="error",
            error=str(e),
            duration_ms=dur_ms,
            engine_source="none",
        )
        logger.info("qa_done request_id=%s status=error engine=none duration_ms=%.2f", request_id, dur_ms)
        return jsonify({"code": 500, "message": str(e), "data": {"request_id": request_id}}), 500
    finally:
        if acquired:
            task_registry.release_qa_slot()

    if not isinstance(result, dict):
        dur_ms = (time.time() - t0) * 1000.0
        task_registry.finish_running(
            request_id,
            status="error",
            error="invalid_result",
            duration_ms=dur_ms,
        )
        logger.info("qa_done request_id=%s status=error engine=? duration_ms=%.2f", request_id, dur_ms)
        return jsonify({"code": 500, "message": "内部错误", "data": None}), 500

    result["request_id"] = request_id

    if user:
        cancelled = (request_id and request_id in _cancelled_request_ids) or (result.get("status") == "cancelled")
        if cancelled:
            _cancelled_request_ids.discard(request_id)
        if not cancelled:
            q_row = question_storage.create(
                user_id=user['sub'],
                content=message,
                answer=result.get('answer'),
                rewritten=result.get('rewritten'),
                query_type=result.get('query_type', 'text'),
                competition_id=result.get('competition_id', ''),
                answer_basis=result.get('answer_basis', ''),
                engine_source=result.get('engine_source', 'vidorag'),
                seeker_rounds=result.get('seeker_rounds', 0),
                cache_key=result.get('cache_key', ''),
            )
            result["question_id"] = q_row.id
        dur_ms = (time.time() - t0) * 1000.0
        es = result.get("engine_source") or "none"
        if cancelled:
            task_registry.finish_running(
                request_id,
                status="cancelled",
                interrupted=True,
                duration_ms=dur_ms,
                engine_source=es,
            )
            logger.info("qa_done request_id=%s status=cancelled engine=%s duration_ms=%.2f", request_id, es, dur_ms)
        else:
            task_registry.finish_running(
                request_id,
                status="success",
                duration_ms=dur_ms,
                engine_source=es,
            )
            logger.info("qa_done request_id=%s status=success engine=%s duration_ms=%.2f", request_id, es, dur_ms)

    return jsonify(result)
