"""登录注册配置"""
import os

# 密码加密（bcrypt rounds）
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# JWT 配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))  # 1 小时
JWT_REFRESH_TOKEN_EXPIRES = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 86400 * 7))  # 7 天

# 角色
ROLE_USER = "user"
ROLE_ADMIN = "admin"

# 管理员重置密码时使用的默认密码（用户收到短信后首次登录用，登录后需强制修改）
DEFAULT_RESET_PASSWORD = os.getenv("DEFAULT_RESET_PASSWORD", "Reset@123")
