#!/usr/bin/env python3
"""
把 competition_structs 从旧语义迁移为新语义：

- 旧表字段：competition_name(赛系或赛系+赛道拼接)、tracks_json(JSON数组)
- 新表字段：competition_system(赛系)、competition_name(赛名/赛道单值)

迁移方式（SQLite 安全做法）：
1) 新建临时表 competition_structs__new
2) 把旧表数据拷贝过去（赛名取 tracks_json[0]，缺失则 "/"）
3) DROP 旧表；ALTER TABLE 重命名为 competition_structs
4) 创建中文视图 competition_structs_cn

该脚本可重复执行：如果检测到新字段已存在，则只会刷新视图并退出。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from flask import Flask
    from backend.storage.db import init_db, db

    app = Flask(__name__)
    init_db(app)
    with app.app_context():
        # 是否已是新 schema？
        cols = db.session.execute(db.text("PRAGMA table_info(competition_structs)")).fetchall()
        names = {str(r[1]) for r in cols}  # (cid, name, type, notnull, dflt, pk)
        if "competition_system" in names and "tracks_json" not in names:
            # refresh view and exit
            _create_views(db)
            print("schema already migrated; views refreshed")
            return 0

        # 旧表必须存在
        if not cols:
            print("competition_structs not found; nothing to migrate")
            return 0

        # 创建新表（字段保留旧表大部分，不引入 tracks_json）
        db.session.execute(
            db.text(
                """
                CREATE TABLE IF NOT EXISTS competition_structs__new (
                  id INTEGER PRIMARY KEY,
                  dataset VARCHAR(64) NOT NULL,
                  competition_id VARCHAR(256) NOT NULL,
                  competition_system VARCHAR(512) NOT NULL DEFAULT '',
                  competition_name VARCHAR(512) NOT NULL DEFAULT '/',
                  organizer VARCHAR(512) NOT NULL DEFAULT '',
                  official_website VARCHAR(512) NOT NULL DEFAULT '',
                  registration_time VARCHAR(256) NOT NULL DEFAULT '',
                  competition_category VARCHAR(32) NOT NULL DEFAULT '其他',
                  session VARCHAR(64) NOT NULL DEFAULT '',
                  evidence_pages VARCHAR(128) NOT NULL DEFAULT '',
                  raw_extract_json TEXT NOT NULL DEFAULT '{}',
                  source_hash VARCHAR(64) NOT NULL DEFAULT '',
                  created_at DATETIME,
                  updated_at DATETIME,
                  UNIQUE(dataset, competition_id)
                );
                """
            )
        )

        # 拷贝数据：赛系=旧 competition_name；赛名=tracks_json[0] or "/"
        # 若 tracks_json 不存在或为空，则直接 "/"。
        has_tracks = "tracks_json" in names
        if has_tracks:
            insert_sql = """
            INSERT OR REPLACE INTO competition_structs__new (
              id, dataset, competition_id,
              competition_system, competition_name,
              organizer, official_website, registration_time, competition_category, session,
              evidence_pages, raw_extract_json, source_hash,
              created_at, updated_at
            )
            SELECT
              id, dataset, competition_id,
              COALESCE(NULLIF(TRIM(competition_name), ''), ''),
              COALESCE(NULLIF(json_extract(tracks_json, '$[0]'), ''), '/'),
              organizer, official_website, registration_time, competition_category, session,
              evidence_pages, raw_extract_json, source_hash,
              created_at, updated_at
            FROM competition_structs;
            """
        else:
            # 极端情况：没有 tracks_json，只能把赛名置 "/"
            insert_sql = """
            INSERT OR REPLACE INTO competition_structs__new (
              id, dataset, competition_id,
              competition_system, competition_name,
              organizer, official_website, registration_time, competition_category, session,
              evidence_pages, raw_extract_json, source_hash,
              created_at, updated_at
            )
            SELECT
              id, dataset, competition_id,
              COALESCE(NULLIF(TRIM(competition_name), ''), ''),
              '/',
              organizer, official_website, registration_time, competition_category, session,
              evidence_pages, raw_extract_json, source_hash,
              created_at, updated_at
            FROM competition_structs;
            """

        db.session.execute(db.text(insert_sql))
        db.session.commit()

        # 替换表（重命名）
        db.session.execute(db.text("DROP TABLE competition_structs"))
        db.session.execute(db.text("ALTER TABLE competition_structs__new RENAME TO competition_structs"))
        db.session.commit()

        _create_views(db)
        print("migration done")
        return 0


def _create_views(db) -> None:
    sql = """
    DROP VIEW IF EXISTS competition_structs_cn;
    CREATE VIEW competition_structs_cn AS
    SELECT
      id AS id,
      dataset AS 数据集,
      competition_id AS competition_id,
      competition_system AS 赛系,
      competition_name AS "赛名/赛道",
      competition_category AS 赛事类别,
      session AS 发布时间,
      registration_time AS 报名时间,
      organizer AS 组织单位,
      official_website AS 官网,
      created_at AS 创建时间,
      updated_at AS 更新时间
    FROM competition_structs;
    """
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        db.session.execute(db.text(stmt))
    db.session.commit()


if __name__ == "__main__":
    raise SystemExit(main())

