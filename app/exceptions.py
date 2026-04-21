"""自定义异常"""


class AppException(Exception):
    """应用基础异常"""
    code = 500
    message = "服务器内部错误"

    def __init__(self, message: str = None, code: int = None):
        self._message = message or self.message
        self._code = code or self.code
        super().__init__(self._message)

    @property
    def data(self):
        return {"error": self._message, "code": self._code}


class PDFUploadException(AppException):
    """PDF 上传失败"""
    code = 400
    message = "PDF 上传失败"


class PDFParseException(AppException):
    """PDF 解析失败"""
    code = 400
    message = "PDF 解析失败"


class VectorGenerationException(AppException):
    """向量生成失败"""
    code = 500
    message = "向量生成失败"


class AuthException(AppException):
    """认证异常"""
    code = 401
    message = "认证失败"


class PermissionException(AppException):
    """权限异常"""
    code = 403
    message = "无权限"


class MailSendException(AppException):
    """邮件发送失败（如 SMTP 连接/认证/发送异常）"""
    code = 500
    message = "邮件发送失败"
