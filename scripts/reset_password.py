#!/usr/bin/env python3
"""命令行重置用户密码（用户忘记密码时可在服务器上执行）"""
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from backend.storage.db import init_db
from backend.auth.password_utils import hash_password
from backend.storage import user_storage


def main():
    if len(sys.argv) < 3:
        print("用法: python scripts/reset_password.py <用户名> <新密码>")
        print("示例: python scripts/reset_password.py zhangsan mynewpass")
        sys.exit(1)
    username = sys.argv[1].strip()
    new_password = sys.argv[2]
    if len(new_password) < 4:
        print("新密码至少 4 位")
        sys.exit(1)

    app = Flask(__name__)
    init_db(app)
    with app.app_context():
        ok = user_storage.update_password_by_username(username, hash_password(new_password))
        if ok:
            print(f"用户 {username} 的密码已重置")
        else:
            print(f"用户 {username} 不存在")
            sys.exit(1)


if __name__ == "__main__":
    main()
