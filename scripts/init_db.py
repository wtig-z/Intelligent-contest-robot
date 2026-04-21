#!/usr/bin/env python3
"""初始化数据库并创建管理员账号（不依赖 ViDoRAG 等重依赖）"""
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from backend.storage.db import init_db, db
from backend.auth.password_utils import hash_password


def main():
    app = Flask(__name__)
    init_db(app)
    with app.app_context():
        from backend.models import User
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        admin_phone = (os.getenv("ADMIN_PHONE") or "").strip() or "13800000000"
        if not User.query.filter_by(username=admin_username).first():
            from backend.storage import user_storage
            user_storage.create(admin_username, hash_password(admin_password), "admin", phone=admin_phone)
            print(f"已创建管理员账号: {admin_username}，手机: {admin_phone}")
        else:
            print(f"管理员账号 {admin_username} 已存在，跳过")


if __name__ == "__main__":
    main()
