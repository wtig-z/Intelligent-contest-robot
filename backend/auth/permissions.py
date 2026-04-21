"""权限装饰器"""
from backend.auth.jwt_handler import login_required, admin_required

__all__ = ["login_required", "admin_required"]
