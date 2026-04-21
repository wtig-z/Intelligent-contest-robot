"""PDF / 文档管理：上传、列表（管线状态）、预览、触发重新解析。"""
import hashlib
import os
import subprocess
import sys
import threading
import time
import uuid
from flask import Blueprint, request, jsonify, send_file

from backend.auth.jwt_handler import backoffice_required, uploader_required
from backend.storage import pdf_storage
from backend.storage import competition_struct_storage
from backend.services.doc_pipeline import pipeline_status_for_pdf
from config.paths import get_pdf_dir, get_scripts_dir, get_project_root, get_unified_text_dir
from backend.api.admin_api.admin_config_api import _load as _load_runtime_config

bp = Blueprint("pdf_manage", __name__, url_prefix="/api/admin/pdf")

_kb_jobs_lock = threading.Lock()
_kb_jobs: dict[str, dict] = {}


def _start_kb_job(cmd: list[str], *, cwd: str, env: dict | None = None) -> dict:
    job_id = f"kbjob-{uuid.uuid4()}"
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
        "status": "running",  # running|success|error
        "exit_code": None,
        "started_at": time.time(),
        "finished_at": None,
        "lines": [],
    }
    with _kb_jobs_lock:
        _kb_jobs[job_id] = rec

    def _reader():
        try:
            if p.stdout is not None:
                for line in p.stdout:
                    s = (line or "").rstrip("\n")
                    if not s:
                        continue
                    with _kb_jobs_lock:
                        r = _kb_jobs.get(job_id)
                        if not r:
                            continue
                        r["lines"].append(s)
                        # keep last 300 lines
                        if len(r["lines"]) > 300:
                            r["lines"] = r["lines"][-300:]
        finally:
            code = p.wait()
            with _kb_jobs_lock:
                r = _kb_jobs.get(job_id)
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
    with _kb_jobs_lock:
        r = _kb_jobs.get(jid)
        if not r:
            return jsonify({"code": 404, "message": "job 不存在或已过期", "data": None}), 404
        now = time.time()
        out = dict(r)
        out["elapsed_sec"] = round(now - float(out.get("started_at") or now), 2)
        # do not leak full cmd in UI unless needed; keep it for admin debug
        return jsonify({"code": 0, "message": "ok", "data": out})


def _md5_file(filepath: str) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@bp.route("/list", methods=["GET"])
@backoffice_required
def list_pdfs():
    dataset = request.args.get("dataset", "CompetitionDataset")
    pdfs = pdf_storage.list_all(dataset)
    rows = []
    for p in pdfs:
        pipe = pipeline_status_for_pdf(dataset, p.filename)
        # 状态语义：
        # - pending: 已登记（仅入库/落盘）
        # - processed: 已处理（OCR/文本/图片至少一项产物已生成）
        # - archived: 已归档（手动归档）
        #
        # 这里根据磁盘产物动态推进 pending -> processed，避免一直显示 pending。
        status = p.status or "pending"
        if status != "archived":
            should = "processed" if pipe.get("parse_success") else "pending"
            if should != status:
                try:
                    pdf_storage.update_status(p.id, should)
                    status = should
                except Exception:
                    # 列表接口不应因状态更新失败而报错
                    pass
        rows.append({
            "id": p.id,
            "filename": p.filename,
            "contest_name": p.contest_name,
            "status": status,
            "updated_at": (pipe.get("updated_at") if isinstance(pipe, dict) else None),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "pipeline": pipe,
        })
    return jsonify({"code": 0, "message": "ok", "data": rows})


@bp.route("/upload", methods=["POST"])
@uploader_required
def upload():
    if "file" not in request.files:
        return jsonify({"code": 400, "message": "未选择文件", "data": None}), 400
    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return jsonify({"code": 400, "message": "仅支持 PDF 文件", "data": None}), 400
    dataset = request.form.get("dataset", "CompetitionDataset")
    contest_name = request.form.get("contest_name", "").strip() or None
    pdf_dir = get_pdf_dir(dataset)
    os.makedirs(pdf_dir, exist_ok=True)
    file_path = os.path.join(pdf_dir, f.filename)
    f.save(file_path)
    file_hash = _md5_file(file_path)
    existing = pdf_storage.get_by_filename(dataset, f.filename)
    if existing:
        pdf_storage.update_file_hash(existing.id, file_hash)
        if contest_name:
            pdf_storage.update_contest_name(existing.id, contest_name)
        # 上传/覆盖时同步一条 competition_structs（以 TSV 结构化知识库为准，匹配不到则跳过）
        try:
            from config.curated_structured import CURATED_COMPETITIONS
            doc_id = f.filename[:-4] if f.filename.lower().endswith(".pdf") else f.filename
            t = doc_id.strip().lower()
            hit = None
            for it in (CURATED_COMPETITIONS or []):
                comp = str(it.get("competition_name") or "").strip()
                track = str(it.get("track") or "").strip()
                aliases = it.get("aliases") or []
                hay = [comp, track] + [str(a) for a in (aliases if isinstance(aliases, list) else [])]
                for x in hay:
                    xx = (x or "").strip().lower()
                    if not xx:
                        continue
                    if xx in t or t in xx:
                        hit = it
                        break
                if hit:
                    break
            if hit:
                comp = str(hit.get("competition_name") or "").strip()
                track = str(hit.get("track") or "").strip()
                track_one = (track or "/").strip() or "/"
                if track_one in ("无", "／", ""):
                    track_one = "/"
                payload = {
                    "competition_system": comp,
                    "competition_name": track_one,
                    "organizer": str(hit.get("organizer") or "").strip(),
                    "official_website": str(hit.get("official_website") or "").strip(),
                    "registration_time": str(hit.get("registration_time") or "").strip(),
                    "competition_category": str(hit.get("category") or "其他").strip() or "其他",
                    "session": str(hit.get("publish_time") or "").strip(),
                    "evidence_pages": "",
                    "source": "curated_tsv",
                    "curated_id": hit.get("id"),
                }
                competition_struct_storage.upsert(
                    dataset=dataset,
                    competition_id=doc_id,
                    payload=payload,
                    source_text=f"curated_id={hit.get('id')}",
                )
        except Exception:
            pass
        return jsonify({"code": 0, "message": "ok", "data": {"id": existing.id, "filename": f.filename, "contest_name": contest_name or existing.contest_name}})
    p = pdf_storage.create(f.filename, file_path, dataset, file_hash=file_hash, contest_name=contest_name)
    try:
        from config.curated_structured import CURATED_COMPETITIONS
        doc_id = f.filename[:-4] if f.filename.lower().endswith(".pdf") else f.filename
        t = doc_id.strip().lower()
        hit = None
        for it in (CURATED_COMPETITIONS or []):
            comp = str(it.get("competition_name") or "").strip()
            track = str(it.get("track") or "").strip()
            aliases = it.get("aliases") or []
            hay = [comp, track] + [str(a) for a in (aliases if isinstance(aliases, list) else [])]
            for x in hay:
                xx = (x or "").strip().lower()
                if not xx:
                    continue
                if xx in t or t in xx:
                    hit = it
                    break
            if hit:
                break
        if hit:
            comp = str(hit.get("competition_name") or "").strip()
            track = str(hit.get("track") or "").strip()
            track_one = (track or "/").strip() or "/"
            if track_one in ("无", "／", ""):
                track_one = "/"
            payload = {
                "competition_system": comp,
                "competition_name": track_one,
                "organizer": str(hit.get("organizer") or "").strip(),
                "official_website": str(hit.get("official_website") or "").strip(),
                "registration_time": str(hit.get("registration_time") or "").strip(),
                "competition_category": str(hit.get("category") or "其他").strip() or "其他",
                "session": str(hit.get("publish_time") or "").strip(),
                "evidence_pages": "",
                "source": "curated_tsv",
                "curated_id": hit.get("id"),
            }
            competition_struct_storage.upsert(
                dataset=dataset,
                competition_id=doc_id,
                payload=payload,
                source_text=f"curated_id={hit.get('id')}",
            )
    except Exception:
        pass
    return jsonify({"code": 0, "message": "ok", "data": {"id": p.id, "filename": p.filename, "contest_name": p.contest_name}})


@bp.route("/batch_upload", methods=["POST"])
@uploader_required
def batch_upload():
    """multipart: files[] 多个 PDF，可选 dataset、contest_name（统一写入每条）。"""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"code": 400, "message": "未选择文件", "data": None}), 400
    dataset = request.form.get("dataset", "CompetitionDataset")
    contest_name = request.form.get("contest_name", "").strip() or None
    pdf_dir = get_pdf_dir(dataset)
    os.makedirs(pdf_dir, exist_ok=True)
    ok, failed = [], []
    for f in files:
        if not f or not f.filename:
            continue
        if not f.filename.lower().endswith(".pdf"):
            failed.append({"filename": f.filename, "error": "非 PDF"})
            continue
        try:
            file_path = os.path.join(pdf_dir, f.filename)
            f.save(file_path)
            file_hash = _md5_file(file_path)
            existing = pdf_storage.get_by_filename(dataset, f.filename)
            if existing:
                pdf_storage.update_file_hash(existing.id, file_hash)
                if contest_name:
                    pdf_storage.update_contest_name(existing.id, contest_name)
                ok.append({"id": existing.id, "filename": f.filename})
            else:
                p = pdf_storage.create(f.filename, file_path, dataset, file_hash=file_hash, contest_name=contest_name)
                ok.append({"id": p.id, "filename": p.filename})
            # 尝试同步结构化表（匹配不到则跳过）
            try:
                from config.curated_structured import CURATED_COMPETITIONS
                doc_id = f.filename[:-4] if f.filename.lower().endswith(".pdf") else f.filename
                t = doc_id.strip().lower()
                hit = None
                for it in (CURATED_COMPETITIONS or []):
                    comp = str(it.get("competition_name") or "").strip()
                    track = str(it.get("track") or "").strip()
                    aliases = it.get("aliases") or []
                    hay = [comp, track] + [str(a) for a in (aliases if isinstance(aliases, list) else [])]
                    for x in hay:
                        xx = (x or "").strip().lower()
                        if not xx:
                            continue
                        if xx in t or t in xx:
                            hit = it
                            break
                    if hit:
                        break
                if hit:
                    comp = str(hit.get("competition_name") or "").strip()
                    track = str(hit.get("track") or "").strip()
                    track_one = (track or "/").strip() or "/"
                    if track_one in ("无", "／", ""):
                        track_one = "/"
                    payload = {
                        "competition_system": comp,
                        "competition_name": track_one,
                        "organizer": str(hit.get("organizer") or "").strip(),
                        "official_website": str(hit.get("official_website") or "").strip(),
                        "registration_time": str(hit.get("registration_time") or "").strip(),
                        "competition_category": str(hit.get("category") or "其他").strip() or "其他",
                        "session": str(hit.get("publish_time") or "").strip(),
                        "evidence_pages": "",
                        "source": "curated_tsv",
                        "curated_id": hit.get("id"),
                    }
                    competition_struct_storage.upsert(
                        dataset=dataset,
                        competition_id=doc_id,
                        payload=payload,
                        source_text=f"curated_id={hit.get('id')}",
                    )
            except Exception:
                pass
        except Exception as e:
            failed.append({"filename": f.filename, "error": str(e)})
    return jsonify({"code": 0, "message": "ok", "data": {"uploaded": ok, "failed": failed}})


@bp.route("/<int:pdf_id>/contest_name", methods=["PUT"])
@uploader_required
def update_contest_name(pdf_id):
    data = request.get_json() or {}
    name = (data.get("contest_name") or "").strip()
    if not name:
        return jsonify({"code": 400, "message": "赛事名称不能为空"}), 400
    p = pdf_storage.update_contest_name(pdf_id, name)
    if not p:
        return jsonify({"code": 404, "message": "PDF 不存在"}), 404
    return jsonify({"code": 0, "message": "ok", "data": {"id": p.id, "contest_name": p.contest_name}})


@bp.route("/<int:pdf_id>/file", methods=["GET"])
@backoffice_required
def serve_pdf_file(pdf_id):
    p = pdf_storage.get_by_id(pdf_id)
    if not p or not p.file_path or not os.path.isfile(p.file_path):
        return jsonify({"code": 404, "message": "文件不存在"}), 404
    return send_file(p.file_path, mimetype="application/pdf", as_attachment=False, download_name=p.filename)


@bp.route("/<int:pdf_id>/text_preview", methods=["GET"])
@backoffice_required
def text_preview(pdf_id):
    """合并前几页 unified_text 为纯文本预览（截断）。"""
    p = pdf_storage.get_by_id(pdf_id)
    if not p:
        return jsonify({"code": 404, "message": "PDF 不存在"}), 404
    dataset = p.dataset or "CompetitionDataset"
    prefix = p.filename[:-4] if p.filename.lower().endswith(".pdf") else p.filename
    uni = get_unified_text_dir(dataset)
    if not os.path.isdir(uni):
        return jsonify({"code": 0, "message": "ok", "data": {"text": "", "pages": 0}})
    names = sorted(
        x for x in os.listdir(uni)
        if x.startswith(prefix + "_") and x.lower().endswith(".txt")
    )
    max_pages = min(int(request.args.get("max_pages", "5")), 50)
    max_chars = min(int(request.args.get("max_chars", "12000")), 200000)
    chunks = []
    for name in names[:max_pages]:
        path = os.path.join(uni, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                chunks.append(fh.read())
        except Exception:
            continue
    text = "\n\n---\n\n".join(chunks)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n…(已截断)"
    return jsonify({"code": 0, "message": "ok", "data": {"text": text, "pages": len(names)}})


@bp.route("/update_kb", methods=["POST"])
@uploader_required
def update_kb():
    dataset = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        dataset = (data.get("dataset") or "").strip()
    if not dataset:
        dataset = request.form.get("dataset", "").strip()
    if not dataset:
        dataset = "CompetitionDataset"

    scripts_dir = get_scripts_dir()
    script_path = os.path.join(scripts_dir, "update_knowledge.py")
    if not os.path.exists(script_path):
        return jsonify({"code": 500, "message": "更新脚本不存在", "data": None}), 500

    try:
        cfg = _load_runtime_config()
        env = dict(os.environ)
        env["KB_UPDATE_GRAPHRAG_INPUT"] = "1" if cfg.get("kb_update_graphrag_input") else "0"
        env["KB_GENERATE_VLM_BOX_IMAGES"] = "1" if cfg.get("kb_generate_vlm_box_images") else "0"
        rec = _start_kb_job(
            [sys.executable or "python", script_path, "--dataset", dataset],
            cwd=get_project_root(),
            env=env,
        )
    except Exception as e:
        return jsonify({"code": 500, "message": f"触发知识库更新失败: {e}", "data": None}), 500

    return jsonify({"code": 0, "message": "已触发知识库更新（后台处理中）", "data": {"dataset": dataset, "job_id": rec["job_id"]}})

@bp.route("/rebuild_structs", methods=["POST"])
@uploader_required
def rebuild_structs():
    """
    仅重建结构化表（competition_structs）：
    - data/curated_competitions.tsv -> config/curated_structured.py
    - schema migrate（旧 tracks_json -> 新 competition_system/competition_name）
    - sync competition_structs（不跑 OCR/图片/向量）
    """
    dataset = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        dataset = (data.get("dataset") or "").strip()
    if not dataset:
        dataset = request.form.get("dataset", "").strip()
    if not dataset:
        dataset = "CompetitionDataset"

    scripts_dir = get_scripts_dir()
    build_script = os.path.join(scripts_dir, "build_curated_structured.py")
    mig_script = os.path.join(scripts_dir, "migrate_competition_structs_schema.py")
    sync_script = os.path.join(scripts_dir, "sync_competition_structs_from_curated.py")
    if not os.path.exists(build_script):
        return jsonify({"code": 500, "message": "构建脚本不存在", "data": None}), 500
    if not os.path.exists(mig_script):
        return jsonify({"code": 500, "message": "迁移脚本不存在", "data": None}), 500
    if not os.path.exists(sync_script):
        return jsonify({"code": 500, "message": "同步脚本不存在", "data": None}), 500

    root = get_project_root()
    in_path = os.path.join(root, "data", "curated_competitions.tsv")
    out_path = os.path.join(root, "config", "curated_structured.py")
    db_build = os.path.join(scripts_dir, "build_curated_competitions.py")
    db_out = os.path.join(root, "config", "curated_competitions.py")
    chain = [
        f"\"{sys.executable or 'python'}\" \"{build_script}\" --input \"{in_path}\" --output \"{out_path}\"",
    ]
    if os.path.exists(db_build):
        chain.append(f"\"{sys.executable or 'python'}\" \"{db_build}\" --input \"{in_path}\" --output \"{db_out}\"")
    chain.append(f"\"{sys.executable or 'python'}\" \"{mig_script}\"")
    chain.append(f"\"{sys.executable or 'python'}\" \"{sync_script}\" --dataset \"{dataset}\" --rebuild")

    # 用 bash -lc 串行执行脚本，便于单 job 展示完整日志
    cmd = [
        "bash",
        "-lc",
        " && ".join(chain),
    ]
    try:
        rec = _start_kb_job(cmd, cwd=root, env=dict(os.environ))
    except Exception as e:
        return jsonify({"code": 500, "message": f"触发重建结构化表失败: {e}", "data": None}), 500

    return jsonify({"code": 0, "message": "已触发结构化表重建（后台处理中）", "data": {"dataset": dataset, "job_id": rec["job_id"]}})


@bp.route("/<int:pdf_id>/reparse", methods=["POST"])
@uploader_required
def reparse_pdf(pdf_id):
    """
    单文档“重新解析”：只针对这一份 PDF 强制重建产物（归档旧产物后重跑）。
    目的：避免全库扫描 + “MD5 未变就不重建”导致看起来一直“无变化”。
    """
    p = pdf_storage.get_by_id(pdf_id)
    if not p:
        return jsonify({"code": 404, "message": "PDF 不存在"}), 404
    dataset = p.dataset or "CompetitionDataset"
    scripts_dir = get_scripts_dir()
    script_path = os.path.join(scripts_dir, "update_knowledge.py")
    if not os.path.exists(script_path):
        return jsonify({"code": 500, "message": "更新脚本不存在", "data": None}), 500
    try:
        cfg = _load_runtime_config()
        env = dict(os.environ)
        env["KB_UPDATE_GRAPHRAG_INPUT"] = "1" if cfg.get("kb_update_graphrag_input") else "0"
        env["KB_GENERATE_VLM_BOX_IMAGES"] = "1" if cfg.get("kb_generate_vlm_box_images") else "0"
        rec = _start_kb_job(
            [
                sys.executable or "python",
                script_path,
                "--dataset",
                dataset,
                "--only",
                p.filename,
                "--force",
            ],
            cwd=get_project_root(),
            env=env,
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e), "data": None}), 500
    return jsonify({
        "code": 0,
        "message": f"已触发单文档重新解析（后台处理中）：{p.filename}",
        "data": {"dataset": dataset, "filename": p.filename, "job_id": rec["job_id"]},
    })
