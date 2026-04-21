"""
短信发送：用于验证码、重置密码等。默认使用虚拟接口（仅打日志），后续可配置真实阿里云。
- SMS_PROVIDER=mock 或未配置：虚拟接口，日志输出，返回 True
- SMS_PROVIDER=aliyun 且配置完整：走阿里云 dysms
"""
import os
import json
import logging

logger = logging.getLogger("contest_robot.sms")


def _normalize_phone(phone: str) -> str:
    """去掉空格与常见前缀，保留 11 位数字。"""
    s = (phone or "").strip().replace(" ", "").replace("-", "")
    if s.startswith("+86"):
        s = s[3:].lstrip()
    return s if s.isdigit() and len(s) == 11 else ""


def _mock_send(phone: str, scene: str, **kwargs) -> bool:
    """虚拟短信接口：仅写日志，不真实发送。返回 True 便于联调。"""
    logger.info("[虚拟短信] 手机=%s 场景=%s 内容=%s", phone, scene, kwargs)
    return True


def send_reset_password_sms(phone: str, username: str, new_password: str) -> bool:
    """
    发送「密码已重置」短信到用户手机。
    返回 True 表示发送成功，False 表示手机号无效等。
    """
    phone = _normalize_phone(phone)
    if not phone:
        return False
    provider = (os.getenv("SMS_PROVIDER") or "mock").strip().lower()
    if provider == "aliyun" and _aliyun_configured():
        return _send_aliyun_reset_sms(phone, username, new_password)
    # 默认或 mock / virtual：走虚拟接口
    return _mock_send(phone, "reset_password", username=username, password=new_password)


def send_verify_code_sms(phone: str, code: str, expire_minutes: int = 5) -> bool:
    """
    发送验证码短信（如登录/注册验证）。默认走虚拟接口，后续可接阿里云等。
    """
    phone = _normalize_phone(phone)
    if not phone:
        return False
    provider = (os.getenv("SMS_PROVIDER") or "mock").strip().lower()
    if provider == "aliyun" and _aliyun_configured():
        return _send_aliyun_verify_code(phone, code, expire_minutes)
    return _mock_send(phone, "verify_code", code=code, expire_minutes=expire_minutes)


def _aliyun_configured() -> bool:
    ak = (os.getenv("ALIYUN_ACCESS_KEY_ID") or os.getenv("SMS_ACCESS_KEY_ID") or "").strip()
    sk = (os.getenv("ALIYUN_ACCESS_KEY_SECRET") or os.getenv("SMS_ACCESS_KEY_SECRET") or "").strip()
    sign = (os.getenv("SMS_SIGN_NAME") or "").strip()
    return bool(ak and sk and sign)


def _send_aliyun_verify_code(phone: str, code: str, expire_minutes: int) -> bool:
    """阿里云发送验证码短信（可选，需配置验证码模板）。"""
    template_code = (os.getenv("SMS_TEMPLATE_CODE_VERIFY") or "").strip()
    if not template_code:
        return _mock_send(phone, "verify_code", code=code, expire_minutes=expire_minutes)
    try:
        from aliyun_python_sdk_core.client import AcsClient
        from aliyun_python_sdk_dysmsapi.request.v20170525.SendSmsRequest import SendSmsRequest
    except ImportError:
        return _mock_send(phone, "verify_code", code=code)
    access_key = (os.getenv("ALIYUN_ACCESS_KEY_ID") or os.getenv("SMS_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("ALIYUN_ACCESS_KEY_SECRET") or os.getenv("SMS_ACCESS_KEY_SECRET") or "").strip()
    sign_name = (os.getenv("SMS_SIGN_NAME") or "").strip()
    client = AcsClient(access_key, secret, "cn-hangzhou")
    req = SendSmsRequest()
    req.set_accept_format("json")
    req.set_domain("dysmsapi.aliyuncs.com")
    req.set_method("POST")
    req.set_version("2017-05-25")
    req.set_action_name("SendSms")
    req.set_PhoneNumbers(phone)
    req.set_SignName(sign_name)
    req.set_TemplateCode(template_code)
    req.set_TemplateParam(json.dumps({"code": code}))
    try:
        resp = client.do_action_with_exception(req)
        return json.loads(resp).get("Code") == "OK"
    except Exception:
        return False


def _send_aliyun_reset_sms(phone: str, username: str, new_password: str) -> bool:
    """阿里云 dysms 发送重置密码短信。需配置签名、模板（模板变量含 username、password）。"""
    template_code = (os.getenv("SMS_TEMPLATE_CODE_RESET_PASSWORD") or "").strip()
    if not template_code:
        return _mock_send(phone, "reset_password", username=username, password=new_password)
    try:
        from aliyun_python_sdk_core.client import AcsClient
        from aliyun_python_sdk_dysmsapi.request.v20170525.SendSmsRequest import SendSmsRequest
    except ImportError:
        return _mock_send(phone, "reset_password", username=username, password=new_password)
    access_key = (os.getenv("ALIYUN_ACCESS_KEY_ID") or os.getenv("SMS_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("ALIYUN_ACCESS_KEY_SECRET") or os.getenv("SMS_ACCESS_KEY_SECRET") or "").strip()
    sign_name = (os.getenv("SMS_SIGN_NAME") or "").strip()
    if not access_key or not secret or not sign_name:
        return _mock_send(phone, "reset_password", username=username, password=new_password)
    client = AcsClient(access_key, secret, "cn-hangzhou")
    req = SendSmsRequest()
    req.set_accept_format("json")
    req.set_domain("dysmsapi.aliyuncs.com")
    req.set_method("POST")
    req.set_version("2017-05-25")
    req.set_action_name("SendSms")
    req.set_PhoneNumbers(phone)
    req.set_SignName(sign_name)
    req.set_TemplateCode(template_code)
    # 模板变量：阿里云控制台申请的模板占位符，如 username、password 或仅 code
    style = (os.getenv("SMS_TEMPLATE_PARAM_STYLE") or "default").strip().lower()
    if style == "code":
        param = {"code": new_password}
    else:
        param = {"username": username, "password": new_password}
    req.set_TemplateParam(json.dumps(param))
    try:
        resp = client.do_action_with_exception(req)
        data = json.loads(resp)
        return data.get("Code") == "OK"
    except Exception:
        return False
