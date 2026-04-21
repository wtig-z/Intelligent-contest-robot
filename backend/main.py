"""Flask 应用入口"""
import os
import sys

from flask import Flask, send_from_directory, redirect, request, Response

# HuggingFace/Transformers 离线模式（只读本地缓存，不做网络 HEAD/GET 探测）
# 用法：启动服务前设置 HF_OFFLINE=1
if os.getenv("HF_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on"):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    # 避免无用的遥测
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# 确保项目根目录在 path 中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.logger import setup_logger, print_startup_warnings
setup_logger(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    capacity=int(os.getenv("LOG_CAPACITY", "300")),
    use_stdout=os.getenv("LOG_STDOUT", "1") == "1",
)
print_startup_warnings()

from backend.api.volc_kb_api import bp as volc_kb_bp
from backend.api.qa_api import bp as qa_bp
from backend.api.kb_api import bp as kb_bp
from backend.api.health_api import bp as health_bp
from backend.api.auth_api import bp as auth_bp
from backend.api.profile_api import bp as profile_bp
from backend.api.history_api import bp as history_bp
from backend.api.share_api import bp as share_bp
from backend.api.events_api import bp as events_bp
from backend.api.admin_api.pdf_manage_api import bp as pdf_manage_bp
from backend.api.admin_api.user_manage_api import bp as user_manage_bp
from backend.api.admin_api.vector_manage_api import bp as vector_manage_bp
from backend.api.admin_api.question_manage_api import bp as question_manage_bp
from backend.api.admin_api.graphrag_manage_api import bp as graphrag_manage_bp
from backend.api.admin_api.event_manage_api import bp as admin_events_bp
from backend.api.admin_api.admin_indexes_api import bp as admin_indexes_bp
from backend.api.admin_api.admin_tasks_api import bp as admin_tasks_bp
from backend.api.admin_api.admin_logs_api import bp as admin_logs_bp
from backend.api.admin_api.admin_config_api import bp as admin_config_bp
from backend.api.admin_api.admin_export_api import bp as admin_export_bp
from backend.auth.jwt_handler import BACKOFFICE_ROLES
from backend.storage.db import init_db


def create_app():
    _backend_dir = os.path.dirname(os.path.abspath(__file__))
    _frontend_dir = os.path.join(os.path.dirname(_backend_dir), 'frontend')
    _admin_dir = os.path.join(_frontend_dir, 'admin')

    app = Flask(__name__, static_folder=os.path.join(_frontend_dir, 'static'), static_url_path='/static')
    app.config['JSON_AS_ASCII'] = False
    # 开发/自测阶段避免静态资源被旧缓存导致“代码已改但仍报旧错”
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    init_db(app)

    # 启动预热：提前加载 ViDoRAG 模型/索引，避免用户首次提问时从 HuggingFace 拉权重造成长卡顿
    # 默认开启（演示体验更好）；如需关闭可设置环境变量 VIDORAG_WARMUP=0
    try:
        if os.getenv("VIDORAG_WARMUP", "1").strip() not in ("0", "false", "False", "off", "OFF"):
            from backend.services.qa_service import _vidorag  # type: ignore
            try:
                _vidorag.warmup()
            except Exception as e:
                try:
                    app.logger.exception("ViDoRAG warmup 失败（忽略，回退懒加载）：%s", e)
                except Exception:
                    pass
    except Exception as e:
        try:
            app.logger.exception("ViDoRAG warmup 初始化失败（忽略，回退懒加载）：%s", e)
        except Exception:
            pass

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(volc_kb_bp)
    app.register_blueprint(qa_bp)
    app.register_blueprint(kb_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(share_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(pdf_manage_bp)
    app.register_blueprint(user_manage_bp)
    app.register_blueprint(vector_manage_bp)
    app.register_blueprint(question_manage_bp)
    app.register_blueprint(graphrag_manage_bp)
    app.register_blueprint(admin_indexes_bp)
    app.register_blueprint(admin_tasks_bp)
    app.register_blueprint(admin_logs_bp)
    app.register_blueprint(admin_config_bp)
    app.register_blueprint(admin_export_bp)
    app.register_blueprint(admin_events_bp)

    @app.route('/')
    def index():
        return redirect('/volc-kb')

    @app.route('/graphrag')
    def graphrag_chat_page():
        """双引擎（ViDoRAG + GraphRAG）问答页；默认入口为 /volc-kb。"""
        return send_from_directory(_frontend_dir, 'index.html')

    @app.route('/login')
    def login_page():
        return send_from_directory(_frontend_dir, 'login.html')

    @app.route('/register')
    def register_page():
        return send_from_directory(_frontend_dir, 'register.html')

    @app.route('/forgot-password')
    def forgot_password_page():
        return send_from_directory(_frontend_dir, 'forgot-password.html')

    @app.route('/change-password')
    def change_password_page():
        return send_from_directory(_frontend_dir, 'change-password.html')

    @app.route('/profile')
    def profile_page():
        return send_from_directory(_frontend_dir, 'profile.html')

    @app.route('/history')
    def history_page():
        return send_from_directory(_frontend_dir, 'history.html')

    @app.route('/events')
    def events_page():
        """赛事日历中心（游客可访问）。"""
        return send_from_directory(_frontend_dir, 'events.html')

    @app.route('/volc-kb')
    def volc_kb_page():
        """火山知识库检索+生成）。"""
        return send_from_directory(_frontend_dir, 'volc_kb_chat.html')

    @app.route('/s/<share_id>')
    def share_landing(share_id):
        return send_from_directory(_frontend_dir, 'share.html')

    @app.route('/access-denied')
    def access_denied():
        reason = (request.args.get('reason') or '').strip()
        next_path = (request.args.get('next') or '/volc-kb').strip() or '/volc-kb'
        msg = "无权限访问该页面。"
        if reason == "admin":
            msg = "当前账号不是管理员，无法进入管理后台。"
        elif reason == "backoffice":
            msg = "非管理员账号！"
        login_url = f"/login?mode=admin&next={next_path}" if reason in ("admin", "backoffice") else f"/login?next={next_path}"
        return Response(
            '<html><head><meta charset="utf-8"><title>访问受限</title>'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
            '<body style="font-family:Arial,Helvetica,sans-serif;padding:40px;max-width:720px;margin:0 auto;">'
            '<h2 style="margin:0 0 12px;">访问受限</h2>'
            f'<p style="margin:0 0 18px;line-height:1.6;">{msg}</p>'
            '<div style="display:flex;gap:12px;flex-wrap:wrap;">'
            '<a href="/volc-kb" style="padding:10px 14px;border-radius:10px;border:1px solid #ddd;text-decoration:none;color:#111;">返回首页</a>'
            f'<a href="{login_url}" style="padding:10px 14px;border-radius:10px;border:1px solid #111;background:#111;color:#fff;text-decoration:none;">切换账号登录</a>'
            '</div>'
            '</body></html>',
            status=200,
            mimetype='text/html',
        )

    @app.route('/admin')
    def admin():
        from backend.auth.jwt_handler import get_current_user
        user = get_current_user()
        if not user:
            nxt = request.path
            return redirect('/login?mode=admin&next=' + nxt)
        if user.get('role') not in BACKOFFICE_ROLES:
            return redirect('/access-denied?reason=backoffice&next=/admin')
        return send_from_directory(_admin_dir, 'index.html')

    @app.route('/admin/<path:path>')
    def admin_page(path):
        from backend.auth.jwt_handler import get_current_user
        user = get_current_user()
        if not user:
            return redirect('/login?mode=admin&next=' + request.path)
        if user.get('role') not in BACKOFFICE_ROLES:
            return redirect('/access-denied?reason=backoffice&next=/admin')
        return send_from_directory(_admin_dir, path)

    return app


app = create_app()
