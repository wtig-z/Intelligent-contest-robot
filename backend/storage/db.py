"""数据库连接"""
import os
import sqlite3
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# 数据库连接字符串（也称数据库 URL）就是告诉你的程序如何连上某个数据库的“接口地址”，
# 可以理解成是数据库和程序进行数据交互的一个“门牌号”或“网络地址”——里面包含了用什么协议、在哪个主机、用哪个数据库类型、文件、账号等信息。
# 程序只要知道这个字符串，就能按照这个“路线”去找到并访问指定的数据库。
#
# get_db_url() 这个函数就是为了生成这样的数据库连接字符串：
# 1. 优先使用环境变量 DATABASE_URL（你可以自定义，比如指定 PostgreSQL/MySQL 地址等）；
# 2. 如果没有设，就用默认的 SQLite 文件数据库（存在项目根目录下的 data/contest_robot.db）；
# 3. 如果用的是 SQLite 的相对路径，还会自动把路径变成绝对路径，并自动创建存储目录，保证无论怎么启动项目都能用到同一个数据库文件；
# 4. 最后返回能被 SQLAlchemy 正确识别的连接字符串（如 sqlite:////绝对路径）。
def get_db_url() -> str:
    """
    生成数据库连接字符串（URL）。

    数据库连接字符串就是数据库和程序之间通信的“地址信息”，包括数据库类型、文件路径或服务器、用户名、密码等。
    程序通过它和数据库建立连接，实现数据的读写。

    本函数优先使用环境变量 DATABASE_URL（如果有指定），否则用默认的 SQLite 数据库（data/contest_robot.db），
    并自动把相对路径转换为项目根目录下的绝对路径、确保相关目录存在，避免因启动目录不同导致路径出错。
    """
    url = os.getenv("DATABASE_URL") or "sqlite:///data/contest_robot.db"

    # 仅处理如 sqlite:///foo.db 这类相对路径的 SQLite 文件
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        rel = url[len("sqlite:///"):]
        # 跳过内存数据库
        if rel != ":memory:":
            here = os.path.dirname(os.path.abspath(__file__))  # .../backend/storage
            project_root = os.path.dirname(os.path.dirname(here))  # .../ContestRobot_web
            path = rel
            if not os.path.isabs(path):
                path = os.path.join(project_root, path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            url = "sqlite:////" + path.lstrip("/")

    return url


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = get_db_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        from backend.models import (  # noqa: F401
            User,
            PDF,
            Vector,
            Question,
            ShareLink,
            change_pwd,
            CompetitionStruct,
            Event,
        )
        db.create_all()
        _migrate_remove_operator_role()
        _migrate_events_notice_pdf()


def _migrate_remove_operator_role() -> None:
    """operator 角色已废弃：库中一律改为 viewer（需上传/改配置请使用 admin）。"""
    try:
        from backend.models.user_model import User

        n = (
            User.query.filter(User.role == "operator")
            .update({"role": "viewer"}, synchronize_session=False)
        )
        if n:
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _migrate_events_notice_pdf() -> None:
    """
    SQLite 迁移：为 events 表补 notice_pdf 列。
    说明：SQLAlchemy 的 create_all 不会为已存在表自动加列。
    """
    url = get_db_url()
    if not url.startswith("sqlite:"):
        return
    # sqlite:////abs/path.db 或 sqlite:///rel/path.db（已在 get_db_url 里规范成绝对）
    path = url.replace("sqlite:////", "/").replace("sqlite:///", "")
    if not path or path == ":memory:":
        return
    conn = None
    try:
        # 给 SQLite 一点等待时间，避免其他进程短暂占用导致启动直接失败
        conn = sqlite3.connect(path, timeout=8)
        try:
            conn.execute("PRAGMA busy_timeout=8000")
        except Exception:
            pass
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
        if cur.fetchone() is None:
            return
        cur.execute("PRAGMA table_info(events)")
        cols = [r[1] for r in cur.fetchall() if len(r) >= 2]
        if "notice_pdf" not in cols:
            try:
                cur.execute("ALTER TABLE events ADD COLUMN notice_pdf VARCHAR(256)")
                conn.commit()
            except sqlite3.OperationalError as e:
                # 数据库被占用时不应阻塞服务启动；可稍后运行 scripts/migrate_events.py 手动迁移
                if "locked" in str(e).lower():
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    return
                raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
