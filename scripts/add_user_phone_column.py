#!/usr/bin/env python3
"""为已有数据库的 users 表添加 phone 列与手机号唯一索引（若不存在）。原邮箱已改为手机号，本脚本用于迁移。仅 SQLite。"""
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv()

from backend.storage.db import get_db_url

# SQLAlchemy 对 unique=True 列默认生成的索引名
PHONE_UNIQUE_INDEX = "ix_users_phone"


def main():
    url = get_db_url()
    if not url.startswith("sqlite"):
        print("当前仅支持 SQLite。其他库请手动: ALTER TABLE users ADD COLUMN phone VARCHAR(20); CREATE UNIQUE INDEX ix_users_phone ON users(phone);")
        sys.exit(0)
    import sqlite3
    path = url.replace("sqlite:///", "").lstrip("/")
    if not os.path.isabs(path):
        path = os.path.join(_project_root, path)
    if not os.path.exists(path):
        print("数据库文件不存在，无需加列。")
        return
    conn = sqlite3.connect(path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in cur.fetchall()]
    if "phone" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
        conn.commit()
        print("已为 users 表添加 phone 列。")
    else:
        print("users 表已有 phone 列，跳过加列。")

    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users' AND name=?", (PHONE_UNIQUE_INDEX,))
    if cur.fetchone():
        print("手机号唯一索引已存在，跳过。")
    else:
        cur.execute("CREATE UNIQUE INDEX ix_users_phone ON users(phone)")
        conn.commit()
        print("已创建手机号唯一索引 ix_users_phone。")

    conn.close()


if __name__ == "__main__":
    main()
