#!/usr/bin/env python3
"""
SQLite 迁移：创建 events 表；为已存在的 events 表补 notice_pdf 列。

说明：
- 本系统默认数据库为 data/contest_robot.db，可通过环境变量 DATABASE_URL 覆盖。
- SQLite 下 SQLAlchemy 的 create_all 不会为已有表自动加列，因此需要这个脚本兜底。
"""
from __future__ import annotations

import os
import sqlite3


def _db_path_from_env() -> str:
    url = os.getenv("DATABASE_URL") or "sqlite:///data/contest_robot.db"
    if not url.startswith("sqlite:///"):
        raise SystemExit("当前脚本仅支持 SQLite（DATABASE_URL 需以 sqlite:/// 开头）")
    rel = url[len("sqlite:///") :]
    # sqlite:////abs/path.db
    if rel.startswith("/"):
        return rel
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    return os.path.join(project_root, rel)


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def _column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    for row in cur.fetchall():
        # row: cid, name, type, notnull, dflt_value, pk
        if len(row) >= 2 and row[1] == col:
            return True
    return False


def main() -> None:
    db_path = _db_path_from_env()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "events"):
            cur.execute(
                """
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(256) NOT NULL,
                    event_date DATE NOT NULL,
                    official_url VARCHAR(512),
                    signup_desc TEXT,
                    notice_pdf VARCHAR(256),
                    is_deleted BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS ix_events_event_date ON events(event_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_events_is_deleted ON events(is_deleted)")
            conn.commit()
            print("已创建 events 表与索引。")
        else:
            changed = False
            if not _column_exists(cur, "events", "notice_pdf"):
                cur.execute("ALTER TABLE events ADD COLUMN notice_pdf VARCHAR(256)")
                changed = True
            if changed:
                conn.commit()
                print("已为 events 表补齐缺失列。")
            else:
                print("events 表已存在且字段齐全，无需迁移。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

