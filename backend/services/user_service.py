"""用户服务"""
from backend.storage import user_storage, password_reset_request_storage
from backend.auth.password_utils import hash_password, verify_password


def register(username: str, password: str, phone: str = None) -> tuple:
    """注册，返回 (user, error_msg)。手机号必填。"""
    if not username or not password:
        return None, "用户名和密码不能为空"
    phone = (phone or "").strip()
    if not phone:
        return None, "请填写手机号"
    if not phone.isdigit() or len(phone) != 11:
        return None, "请填写有效的11位手机号"
    if len(username) < 2:
        return None, "用户名至少 2 位"
    if len(password) < 6:
        return None, "密码至少 6 位"
    if user_storage.get_by_username(username):
        return None, "用户名已存在"
    if user_storage.get_by_phone(phone):
        return None, "该手机号已被注册"
    try:
        u = user_storage.create(username, hash_password(password), phone=phone)
    except ValueError as e:
        return None, str(e)
    return u, None


def login(username: str, password: str) -> tuple:
    """登录，返回 (user, error_msg)"""
    u = user_storage.get_by_username(username)
    if not u or not verify_password(password, u.password_hash):
        return None, "用户名或密码错误"
    return u, None


def request_forgot_password(phone: str) -> tuple:
    """用户忘记密码：提交手机号，创建一条待处理申请。不暴露该手机是否已注册。返回 (True, None) 或 (False, error_msg)。"""
    phone = (phone or "").strip()
    if not phone or not phone.isdigit() or len(phone) != 11:
        return False, "请填写有效的11位手机号"
    try:
        password_reset_request_storage.create(phone=phone)
    except Exception:
        return False, "提交失败，请稍后重试"
    return True, None


def change_password(user_id: int, old_password: str, new_password: str) -> tuple:
    """已登录用户修改密码。校验旧密码后更新为新密码并清除 need_change_password。返回 (True, None) 或 (False, error_msg)。"""
    u = user_storage.get_by_id(user_id)
    if not u:
        return False, "用户不存在"
    if not verify_password(old_password, u.password_hash):
        return False, "原密码错误"
    if not new_password or len(new_password) < 6:
        return False, "新密码至少 6 位"
    user_storage.update_password(user_id, hash_password(new_password))
    user_storage.clear_need_change_password(user_id)
    return True, None
