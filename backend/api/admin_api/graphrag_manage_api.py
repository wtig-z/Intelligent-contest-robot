"""GraphRAG 知识图谱管理接口 —— 基于微软 GraphRAG"""
import os
import subprocess
import sys
import threading
import time
import uuid
from flask import Blueprint, request, jsonify

from backend.auth.jwt_handler import admin_required, backoffice_required
from backend.graphrag import GraphRAGService
from config.app_config import DEFAULT_DATASET
from config.paths import get_project_root, get_scripts_dir

bp = Blueprint("graphrag_manage", __name__, url_prefix="/api/admin/graphrag")

_build_status = {"running": False, "last_result": None}
_graphrag = GraphRAGService()

_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}

# 检索测试异步任务（页面切换后仍在服务端执行，凭 job_id 轮询取结果）
_search_jobs_lock = threading.Lock()
_search_jobs: dict[str, dict] = {}
_MAX_SEARCH_JOBS = 80
_MAX_SEARCH_JOB_AGE_SEC = 7200.0


def _prune_search_jobs() -> None:
    now = time.time()
    with _search_jobs_lock:
        to_del = [
            k
            for k, v in _search_jobs.items()
            if now - float(v.get("started_at") or 0) > _MAX_SEARCH_JOB_AGE_SEC
        ]
        for k in to_del:
            _search_jobs.pop(k, None)
        while len(_search_jobs) > _MAX_SEARCH_JOBS:
            oldest_k = min(
                _search_jobs.keys(),
                key=lambda x: float(_search_jobs[x].get("started_at") or 0),
            )
            _search_jobs.pop(oldest_k, None)


def _run_search_job(job_id: str, query: str, contest_id, mode: str) -> None:
    try:
        result = _graphrag.search(query, contest_id=contest_id, mode=mode)
        with _search_jobs_lock:
            rec = _search_jobs.get(job_id)
            if rec:
                rec["status"] = "success"
                rec["finished_at"] = time.time()
                rec["result"] = result
    except Exception as e:
        with _search_jobs_lock:
            rec = _search_jobs.get(job_id)
            if rec:
                rec["status"] = "error"
                rec["finished_at"] = time.time()
                rec["error"] = str(e)


def _start_job(cmd: list[str], *, cwd: str, env: dict | None = None) -> dict:
    job_id = f"grjob-{uuid.uuid4()}"
    p = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    rec = {
        "job_id": job_id,
        "pid": p.pid,
        "cmd": cmd,
        "cwd": cwd,
        "status": "running",
        "exit_code": None,
        "started_at": time.time(),
        "finished_at": None,
        "lines": [],
    }
    with _jobs_lock:
        _jobs[job_id] = rec

    def _reader():
        try:
            if p.stdout is not None:
                for line in p.stdout:
                    s = (line or "").rstrip("\n")
                    if not s:
                        continue
                    with _jobs_lock:
                        r = _jobs.get(job_id)
                        if not r:
                            continue
                        r["lines"].append(s)
                        if len(r["lines"]) > 500:
                            r["lines"] = r["lines"][-500:]
        finally:
            code = p.wait()
            with _jobs_lock:
                r = _jobs.get(job_id)
                if r:
                    r["exit_code"] = code
                    r["finished_at"] = time.time()
                    r["status"] = "success" if code == 0 else "error"

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    return rec


@bp.route("/jobs/<job_id>", methods=["GET"])
@backoffice_required
def job_status(job_id: str):
    jid = (job_id or "").strip()
    if not jid:
        return jsonify({"code": 400, "message": "job_id 不能为空", "data": None}), 400
    with _jobs_lock:
        r = _jobs.get(jid)
        if not r:
            return jsonify({"code": 404, "message": "job 不存在或已过期", "data": None}), 404
        now = time.time()
        out = dict(r)
        out["elapsed_sec"] = round(now - float(out.get("started_at") or now), 2)
        return jsonify({"code": 0, "message": "ok", "data": out})


@bp.route("/status", methods=["GET"])
@backoffice_required
def get_status():
    """获取 GraphRAG 索引状态"""
    contest_id = request.args.get('contest_id') or None
    stats = _graphrag.get_stats(contest_id)
    stats['build_running'] = _build_status['running']
    stats['last_result'] = _build_status['last_result']
    return jsonify({"code": 0, "data": stats})


@bp.route("/build", methods=["POST"])
@admin_required
def build_index():
    """
    触发 GraphRAG 索引构建（异步）。
    要求在 data/<dataset>/graphrag[/<contest_id>]/ 下已有 settings.yaml 和 input/ 数据。
    构建前需通过 graphrag init 或手动创建配置文件。
    """
    if _build_status['running']:
        return jsonify({"code": 409, "message": "构建任务正在进行中"}), 409

    data = request.get_json() or {}
    contest_id = data.get('contest_id') or None
    method = data.get('method', 'standard')

    def _do_build():
        _build_status['running'] = True
        try:
            result = _graphrag.build_index(contest_id, method=method)
            _build_status['last_result'] = result
        except Exception as e:
            _build_status['last_result'] = {"status": "error", "error": str(e)}
        finally:
            _build_status['running'] = False

    t = threading.Thread(target=_do_build, daemon=True)
    t.start()

    return jsonify({
        "code": 0,
        "message": "GraphRAG 索引构建任务已启动",
        "contest_id": contest_id,
        "method": method,
    })


@bp.route("/build-full", methods=["POST"])
@admin_required
def build_full():
    """
    触发“完整 GraphRAG 构建脚本”（含数据准备：merge_ocr + prepare_input + build_index），并返回 job_id 便于前端轮询进度。
    适合后台一键执行（慢，但可观测）。
    """
    data = request.get_json(silent=True) or {}
    dataset = (data.get("dataset") or DEFAULT_DATASET).strip() or DEFAULT_DATASET
    method = (data.get("method") or "standard").strip() or "standard"
    skip_prepare = bool(data.get("skip_prepare"))

    scripts_dir = get_scripts_dir()
    script_path = os.path.join(scripts_dir, "build_graphrag.py")
    if not os.path.exists(script_path):
        return jsonify({"code": 500, "message": "构建脚本不存在", "data": None}), 500

    cmd = [sys.executable or "python", script_path, "--dataset", dataset, "--method", method]
    if skip_prepare:
        cmd.append("--skip-prepare")
    try:
        rec = _start_job(cmd, cwd=get_project_root(), env=dict(os.environ))
    except Exception as e:
        return jsonify({"code": 500, "message": str(e), "data": None}), 500
    return jsonify({"code": 0, "message": "已触发 GraphRAG 完整构建（后台处理中）", "data": {"job_id": rec["job_id"], "dataset": dataset, "method": method}})


@bp.route("/search-jobs/<job_id>", methods=["GET"])
@admin_required
def search_job_status(job_id: str):
    """轮询异步检索测试任务状态；成功后 data.result 与同步 search-test 的 data 结构一致。"""
    jid = (job_id or "").strip()
    if not jid:
        return jsonify({"code": 400, "message": "job_id 不能为空", "data": None}), 400
    _prune_search_jobs()
    with _search_jobs_lock:
        rec = _search_jobs.get(jid)
        if not rec:
            return jsonify({"code": 404, "message": "检索任务不存在或已过期", "data": None}), 404
        now = time.time()
        out = {
            "job_id": jid,
            "status": rec.get("status"),
            "started_at": rec.get("started_at"),
            "finished_at": rec.get("finished_at"),
            "elapsed_sec": round(now - float(rec.get("started_at") or now), 2),
            "result": rec.get("result"),
            "error": rec.get("error"),
        }
    return jsonify({"code": 0, "message": "ok", "data": out})


@bp.route("/search-test", methods=["POST"])
@admin_required
def search_test():
    """GraphRAG 检索测试（支持 global/local/basic/drift/auto）。

    传 async=true：立即返回 job_id，检索在后台线程执行（切换管理页不中断）；用 GET /search-jobs/<id> 轮询。
    默认 async=false：同步返回结果（兼容旧客户端）。
    """
    data = request.get_json() or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({"code": 400, "message": "query 不能为空"}), 400
    contest_id = data.get('contest_id') or None
    mode = data.get('mode', 'auto')
    # 显式 async=true 时走后台线程；默认 false 保持与旧版同步响应兼容
    use_async = bool(data.get('async'))

    if use_async:
        _prune_search_jobs()
        job_id = f"grsearch-{uuid.uuid4()}"
        with _search_jobs_lock:
            _search_jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "started_at": time.time(),
                "finished_at": None,
                "result": None,
                "error": None,
            }
        t = threading.Thread(
            target=_run_search_job,
            args=(job_id, query, contest_id, mode),
            daemon=True,
        )
        t.start()
        return jsonify(
            {
                "code": 0,
                "message": "ok",
                "data": {"async": True, "job_id": job_id},
            }
        )

    result = _graphrag.search(query, contest_id=contest_id, mode=mode)
    return jsonify({"code": 0, "data": result})
