"""用户个人资料接口：基础信息、检索偏好、安全隐私、数据统计"""
from flask import Blueprint, request, jsonify

from backend.auth.jwt_handler import login_required, get_current_user
from backend.storage import user_storage, question_storage

bp = Blueprint('profile', __name__, url_prefix='/api/profile')


@bp.route('', methods=['GET'])
@login_required
def get_profile():
    """获取当前用户个人资料"""
    user = get_current_user()
    u = user_storage.get_by_id(user['sub'])
    if not u:
        return jsonify({'code': 404, 'message': '用户不存在'}), 404

    stats = question_storage.get_user_stats(u.id)

    return jsonify({
        'code': 0,
        'data': {
            'id': u.id,
            'username': u.username,
            'phone': u.phone,
            'role': u.role,
            'avatar': u.avatar,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'preferences': {
                'default_contest': u.default_contest,
                'topk': u.pref_topk,
                'answer_format': u.pref_answer_format,
                'gmm_sensitivity': u.pref_gmm_sensitivity,
                'kmeans_clusters': u.pref_kmeans_clusters if u.role == 'admin' else None,
                'privacy_anonymous': u.privacy_anonymous,
            },
            'stats': stats,
        }
    })


@bp.route('', methods=['PUT'])
@login_required
def update_profile():
    """更新基础信息：username, phone, avatar"""
    user = get_current_user()
    data = request.get_json() or {}
    allowed = {}
    if 'username' in data:
        name = data['username'].strip()
        if len(name) < 2:
            return jsonify({'code': 400, 'message': '用户名至少2位'}), 400
        existing = user_storage.get_by_username(name)
        if existing and existing.id != user['sub']:
            return jsonify({'code': 400, 'message': '用户名已存在'}), 400
        allowed['username'] = name
    if 'phone' in data:
        phone = data['phone'].strip()
        if phone and (not phone.isdigit() or len(phone) != 11):
            return jsonify({'code': 400, 'message': '请填写有效的11位手机号'}), 400
        if phone:
            existing = user_storage.get_by_phone(phone)
            if existing and existing.id != user['sub']:
                return jsonify({'code': 400, 'message': '手机号已被占用'}), 400
        allowed['phone'] = phone or None
    if 'avatar' in data:
        allowed['avatar'] = data['avatar']

    if allowed:
        user_storage.update_profile(user['sub'], **allowed)
    return jsonify({'code': 0, 'message': '更新成功'})


@bp.route('/preferences', methods=['PUT'])
@login_required
def update_preferences():
    """更新检索偏好设置"""
    user = get_current_user()
    data = request.get_json() or {}
    ok = user_storage.update_preferences(user['sub'], data)
    if not ok:
        return jsonify({'code': 404, 'message': '用户不存在'}), 404
    return jsonify({'code': 0, 'message': '偏好设置已更新'})


@bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """获取用户数据统计"""
    user = get_current_user()
    stats = question_storage.get_user_stats(user['sub'])
    return jsonify({'code': 0, 'data': stats})
