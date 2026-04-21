"""
数据库迁移脚本：为现有数据库添加新字段
适用于从旧版本升级到 Vidorag-GraphRAG 双引擎版本
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import get_project_root


def get_db_path():
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        rel = url[len("sqlite:///"):]
        if not rel.startswith("/"):
            return os.path.join(get_project_root(), rel)
        return rel
    return os.path.join(get_project_root(), "data", "contest_robot.db")


def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}")
        print("请先运行 scripts/init_db.py 初始化数据库")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"连接数据库: {db_path}")
    print("开始迁移...")

    # Question 表新字段
    question_fields = [
        ("query_type", "VARCHAR(16) DEFAULT 'text'"),
        ("competition_id", "VARCHAR(256)"),
        ("answer_basis", "TEXT"),
        ("engine_source", "VARCHAR(16) DEFAULT 'vidorag'"),
        ("seeker_rounds", "INTEGER DEFAULT 0"),
        ("cache_key", "VARCHAR(128)"),
    ]
    for col, dtype in question_fields:
        if not column_exists(cursor, "questions", col):
            cursor.execute(f"ALTER TABLE questions ADD COLUMN {col} {dtype}")
            print(f"  + questions.{col}")
        else:
            print(f"  = questions.{col} (已存在)")

    # User 表新字段
    user_fields = [
        ("avatar", "VARCHAR(256)"),
        ("default_contest", "VARCHAR(128)"),
        ("pref_topk", "INTEGER DEFAULT 10"),
        ("pref_answer_format", "VARCHAR(16) DEFAULT 'detailed'"),
        ("pref_gmm_sensitivity", "FLOAT DEFAULT 0.5"),
        ("pref_kmeans_clusters", "INTEGER"),
        ("privacy_anonymous", "BOOLEAN DEFAULT 0"),
    ]
    for col, dtype in user_fields:
        if not column_exists(cursor, "users", col):
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
            print(f"  + users.{col}")
        else:
            print(f"  = users.{col} (已存在)")

    # PDF 表新字段
    pdf_fields = [
        ("contest_name", "VARCHAR(256)"),
    ]
    for col, dtype in pdf_fields:
        if not column_exists(cursor, "pdfs", col):
            cursor.execute(f"ALTER TABLE pdfs ADD COLUMN {col} {dtype}")
            print(f"  + pdfs.{col}")
        else:
            print(f"  = pdfs.{col} (已存在)")

    # 为 cache_key 创建索引
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_questions_cache_key'")
    if not cursor.fetchone():
        cursor.execute("CREATE INDEX ix_questions_cache_key ON questions(cache_key)")
        print("  + 索引 ix_questions_cache_key")

    conn.commit()
    conn.close()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
