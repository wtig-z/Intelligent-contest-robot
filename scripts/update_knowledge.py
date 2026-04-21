#!/usr/bin/env python3
"""
知识库增量更新脚本（以 pdfs 表为准判断新增/更新/删除）
用法: python scripts/update_knowledge.py --dataset CompetitionDataset
"""
import os
import sys
import json
import hashlib
import logging
import shutil
import subprocess
import argparse
import importlib
from datetime import datetime
from tqdm import tqdm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(asctime)s] [%(levelname)s] [update_knowledge] %(message)s",
)
logger = logging.getLogger("contest_robot.update_knowledge")

# 让直接运行脚本时也能读取项目根目录 .env（否则会提示未设置 DASHSCOPE_API_KEY）
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception as e:
    logger.warning("load_dotenv 失败（将继续尝试用系统环境变量）：%s", e)

from config.paths import get_dataset_dir, get_scripts_dir

PRODUCT_DIRS = ['img', 'ppocr', 'vlmocr', 'unified_text', 'bge_ingestion', 'colqwen_ingestion', 'img_with_boxes_vlmocr']

_CURATED_BUILT = False

def _env_on(name: str) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")

def _maybe_rebuild_curated_structured() -> bool:
    """
    若 data/curated_competitions.tsv 比 config/curated_structured.py 新，则自动运行构建脚本，
    让“后台点更新/重新解析”时无需人工先 build。

    返回：是否执行了重建（含成功/失败尝试）。
    """
    global _CURATED_BUILT
    if _CURATED_BUILT:
        return False
    _CURATED_BUILT = True

    try:
        in_path = os.path.join(ROOT, "data", "curated_competitions.tsv")
        out_path = os.path.join(ROOT, "config", "curated_structured.py")
        if not os.path.isfile(in_path):
            logger.warning("结构化知识库 TSV 不存在，跳过 build: %s", in_path)
            return False

        in_mt = os.path.getmtime(in_path)
        out_mt = os.path.getmtime(out_path) if os.path.isfile(out_path) else 0.0
        if out_mt >= in_mt:
            return False

        scripts_dir = get_scripts_dir()
        build_script = os.path.join(scripts_dir, "build_curated_structured.py")
        if not os.path.isfile(build_script):
            logger.warning("构建脚本不存在，跳过 build: %s", build_script)
            return False

        logger.info("检测到 TSV 已更新，先自动重建结构化知识库: %s -> %s", in_path, out_path)
        ok = run_script(
            [sys.executable or "python", build_script, "--input", in_path, "--output", out_path],
            "[curated] build",
        )
        if not ok:
            logger.warning("结构化知识库重建失败（将继续使用旧版本或跳过同步）")
            return True

        db_build = os.path.join(scripts_dir, "build_curated_competitions.py")
        db_out = os.path.join(ROOT, "config", "curated_competitions.py")
        if os.path.isfile(db_build):
            run_script(
                [sys.executable or "python", db_build, "--input", in_path, "--output", db_out],
                "[curated] structured_kb",
            )
            try:
                if "config.curated_competitions" in sys.modules:
                    import config.curated_competitions as _cdb  # type: ignore
                    importlib.reload(_cdb)  # type: ignore
            except Exception:
                pass

        # 若本进程已 import 过 config.curated_structured，则 reload，避免继续用旧模块缓存
        try:
            if "config.curated_structured" in sys.modules:
                import config.curated_structured as _cs  # type: ignore
                importlib.reload(_cs)  # type: ignore
                logger.info("已 reload config.curated_structured")
        except Exception as e:
            logger.warning("reload config.curated_structured 失败（不影响后续再次 import）：%s", e)

        return True
    except Exception as e:
        logger.warning("自动重建结构化知识库异常：%s", e)
        return False

def _sync_competition_structs_for_doc(dataset_name: str, doc_id: str) -> bool:
    """用结构化知识库（CURATED_COMPETITIONS）对齐/写入 competition_structs 的单行（按 competition_id）。"""
    _maybe_rebuild_curated_structured()
    try:
        from config.curated_structured import CURATED_COMPETITIONS
        from backend.storage import competition_struct_storage
    except Exception as e:
        logger.warning("无法导入结构化知识库或存储模块，跳过 competition_structs 同步: %s", e)
        return False

    t = (doc_id or "").strip().lower()
    if not t:
        return False
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
    if not hit:
        return False

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
        dataset=dataset_name,
        competition_id=doc_id,
        payload=payload,
        source_text=f"curated_id={hit.get('id')}",
    )
    logger.info("已同步 competition_structs: %s", doc_id)
    return True

def _ensure_ppocr_from_vlmocr(dataset_dir: str, doc_prefix: str) -> int:
    """
    兜底：当 PaddleOCR 不可用/失败时，用 VLM OCR 的文本结果生成 ppocr/{prefix}_{page}.txt，
    让后续 merge_ocr 至少有“纯文本覆盖”文件可用（企业演示场景更稳）。
    """
    vlm_dir = os.path.join(dataset_dir, "vlmocr")
    pp_dir = os.path.join(dataset_dir, "ppocr")
    if not os.path.isdir(vlm_dir):
        return 0
    os.makedirs(pp_dir, exist_ok=True)
    wrote = 0
    import json as _json
    for f in sorted(os.listdir(vlm_dir)):
        if not (f.startswith(doc_prefix + "_") and f.endswith(".json")):
            continue
        out = os.path.join(pp_dir, f[:-5] + ".txt")
        if os.path.exists(out):
            continue
        src = os.path.join(vlm_dir, f)
        try:
            with open(src, "r", encoding="utf-8", errors="replace") as fh:
                data = _json.load(fh)
        except Exception:
            continue
        objs = data.get("objects") or []
        parts = []
        for obj in objs:
            c = (obj.get("content") or "").strip()
            if c:
                parts.append(c)
        text = "\n".join(parts).strip()
        if not text:
            continue
        try:
            with open(out, "w", encoding="utf-8") as fo:
                fo.write(text)
            wrote += 1
        except Exception:
            continue
    if wrote:
        logger.info("ppocr 兜底：已从 vlmocr 生成 %s 个 txt", wrote)
    return wrote

def _write_graphrag_input_for_prefix(dataset_dir: str, doc_prefix: str) -> bool:
    """把 unified_text/{prefix}_{page}.txt 合并为 graphrag/input/{prefix}.txt（仅单文档）。"""
    uni_dir = os.path.join(dataset_dir, "unified_text")
    if not os.path.isdir(uni_dir):
        return False
    pages = sorted([f for f in os.listdir(uni_dir) if f.startswith(doc_prefix + "_") and f.endswith(".txt")])
    if not pages:
        return False
    parts = []
    for f in pages:
        try:
            with open(os.path.join(uni_dir, f), "r", encoding="utf-8", errors="replace") as fh:
                t = fh.read().strip()
            if t:
                parts.append(t)
        except Exception:
            continue
    if not parts:
        return False
    out_dir = os.path.join(dataset_dir, "graphrag", "input")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{doc_prefix}.txt")
    with open(out_path, "w", encoding="utf-8") as fo:
        fo.write("\n\n".join(parts))
    logger.info("已生成 GraphRAG input: %s", out_path)
    return True

def _draw_vlm_boxes_images(dataset_dir: str, doc_prefix: str) -> int:
    """
    把 vlmocr/{prefix}_{page}.json 的 bounding_box 画到 img/{prefix}_{page}.jpg，
    输出到 img_with_boxes_vlmocr/ 供人工质检。
    """
    img_dir = os.path.join(dataset_dir, "img")
    vlm_dir = os.path.join(dataset_dir, "vlmocr")
    out_dir = os.path.join(dataset_dir, "img_with_boxes_vlmocr")
    if not (os.path.isdir(img_dir) and os.path.isdir(vlm_dir)):
        return 0
    os.makedirs(out_dir, exist_ok=True)
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        logger.warning("缺少 Pillow，无法生成画框质检图: %s", e)
        return 0
    import json as _json
    wrote = 0
    for jf in sorted(os.listdir(vlm_dir)):
        if not (jf.startswith(doc_prefix + "_") and jf.endswith(".json")):
            continue
        page_key = jf[:-5]
        src_img = os.path.join(img_dir, page_key + ".jpg")
        if not os.path.exists(src_img):
            continue
        out_img = os.path.join(out_dir, page_key + ".jpg")
        if os.path.exists(out_img):
            continue
        try:
            with open(os.path.join(vlm_dir, jf), "r", encoding="utf-8", errors="replace") as fh:
                data = _json.load(fh)
        except Exception:
            continue
        objs = data.get("objects") or []
        if not objs:
            continue
        try:
            im = Image.open(src_img).convert("RGB")
            draw = ImageDraw.Draw(im)
            w, h = im.size
            for obj in objs:
                bb = obj.get("bounding_box")
                if not (isinstance(bb, list) and len(bb) == 4):
                    continue
                y1, x1, y2, x2 = bb
                try:
                    y1 = float(y1); x1 = float(x1); y2 = float(y2); x2 = float(x2)
                except Exception:
                    continue
                m = max(abs(y1), abs(x1), abs(y2), abs(x2))
                # heuristic scaling
                if m <= 1.5:
                    y1, y2 = y1 * h, y2 * h
                    x1, x2 = x1 * w, x2 * w
                elif m <= 1000 and (w > 1200 or h > 1200):
                    y1, y2 = y1 * (h / 1000.0), y2 * (h / 1000.0)
                    x1, x2 = x1 * (w / 1000.0), x2 * (w / 1000.0)
                # clamp
                x1 = max(0, min(w - 1, x1)); x2 = max(0, min(w - 1, x2))
                y1 = max(0, min(h - 1, y1)); y2 = max(0, min(h - 1, y2))
                if x2 <= x1 or y2 <= y1:
                    continue
                draw.rectangle([x1, y1, x2, y2], outline=(255, 64, 64), width=3)
            im.save(out_img, "JPEG", quality=88)
            wrote += 1
        except Exception:
            continue
    if wrote:
        logger.info("画框质检图已生成 %s 张（img_with_boxes_vlmocr）", wrote)
    return wrote


def md5_file(filepath):
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_manifest(dataset_dir, manifest):
    save_json(os.path.join(dataset_dir, 'manifest.json'), manifest)


def append_changelog(dataset_dir, action, pdf_name, detail=""):
    path = os.path.join(dataset_dir, 'changelog.json')
    changelog = load_json(path, [])
    changelog.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "file": pdf_name,
        "detail": detail
    })
    save_json(path, changelog)


def find_related_files(dataset_dir, doc_prefix):
    related = []
    for subdir in PRODUCT_DIRS:
        subdir_path = os.path.join(dataset_dir, subdir)
        if not os.path.isdir(subdir_path):
            continue
        for f in os.listdir(subdir_path):
            if f.startswith(doc_prefix + '_'):
                related.append(os.path.join(subdir_path, f))
    return related


def has_any_products(dataset_dir, doc_prefix) -> bool:
    """判断某 PDF 是否已有任意解析产物（任意子目录存在 prefix_ 开头文件即算）。"""
    return len(find_related_files(dataset_dir, doc_prefix)) > 0


def needs_rebuild_due_to_missing_products(dataset_dir, doc_prefix) -> bool:
    """只要关键产物都缺失，就应进入处理队列（避免出现“知识库无变化但无法问答”）。"""
    if not has_any_products(dataset_dir, doc_prefix):
        return True
    # 更严格：若缺 unified_text 或图片首张，也应视为缺失（后续检索依赖）
    img_dir = os.path.join(dataset_dir, 'img')
    first_img = os.path.join(img_dir, f'{doc_prefix}_1.jpg')
    unified_dir = os.path.join(dataset_dir, 'unified_text')
    has_unified = False
    if os.path.isdir(unified_dir):
        for f in os.listdir(unified_dir):
            if f.startswith(doc_prefix + '_') and f.endswith('.txt'):
                has_unified = True
                break
    if not os.path.exists(first_img) or not has_unified:
        return True
    return False


def archive_related_files(dataset_dir, doc_prefix):
    files = find_related_files(dataset_dir, doc_prefix)
    if not files:
        return 0, None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join(dataset_dir, 'archive', f'{doc_prefix}_{timestamp}')
    for f in files:
        dest_dir = os.path.join(archive_dir, os.path.basename(os.path.dirname(f)))
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(f, os.path.join(dest_dir, os.path.basename(f)))
    return len(files), archive_dir


def run_script(cmd, step_name):
    try:
        logger.info("$ %s", " ".join([str(x) for x in cmd]))
    except Exception as e:
        logger.warning("打印命令失败: %s", e)
    process = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in process.stdout:
            line = line.rstrip()
            if line:
                logger.info("%s", line)
        process.wait()
    except KeyboardInterrupt:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        raise
    if process.returncode != 0:
        logger.warning("%s 退出码: %s", step_name, process.returncode)
    return process.returncode == 0


def run_pipeline(dataset_dir, pdf_path, doc_prefix):
    scripts_dir = get_scripts_dir()
    dataset_name = os.path.basename(dataset_dir)
    img_dir = os.path.join(dataset_dir, 'img')
    os.makedirs(img_dir, exist_ok=True)

    # 打印将要执行的脚本路径，便于排查“同名脚本跑错”的问题
    try:
        tri = os.path.join(scripts_dir, 'ocr_triditional.py')
        logger.info("scripts_dir=%s", scripts_dir)
        logger.info("ocr_triditional.py=%s", tri)
        try:
            with open(tri, "r", encoding="utf-8", errors="replace") as fh:
                head = "\n".join(fh.read().splitlines()[:10])
            logger.info("ocr_triditional.py(head):\n%s", head)
        except Exception as e:
            logger.warning("读取 ocr_triditional.py 失败: %s", e)
    except Exception as e:
        logger.warning("打印 ocr_triditional 调试信息失败: %s", e)

    logger.info("[1/5] PDF → 图片...")
    first_img = os.path.join(img_dir, f'{doc_prefix}_1.jpg')
    if os.path.exists(first_img):
        n = len([f for f in os.listdir(img_dir) if f.startswith(doc_prefix + '_') and f.endswith('.jpg')])
        logger.info("已存在 %s 张图片，跳过", n)
    else:
        try:
            from pdf2image import convert_from_path
        except Exception as e:
            logger.error("缺少依赖 pdf2image: %s", e)
            logger.error("请安装: pip install pdf2image；并安装 poppler（Ubuntu: sudo apt-get install -y poppler-utils）")
            return
        images = convert_from_path(pdf_path, thread_count=4)
        for i, image in enumerate(tqdm(images, desc="    生成图片")):
            image.save(os.path.join(img_dir, f'{doc_prefix}_{i+1}.jpg'), 'JPEG')

    # [2/5] PaddleOCR（可选）：当前环境常见缺 fastdeploy/paddle/cv2，失败不阻断后续。
    logger.info("[2/5] PaddleOCR（可选）...")
    ok_pp = run_script(
        [sys.executable or 'python', os.path.join(scripts_dir, 'ocr_triditional.py'), '--dataset', dataset_name],
        "[2/5] Padd",
    )

    logger.info("[3/5] VLM OCR...")
    run_script([sys.executable or 'python', os.path.join(scripts_dir, 'ocr_vlms.py'), '--dataset', dataset_name], "[3/5] VLM")

    # 如果 PaddleOCR 失败且该文档没有 ppocr 产物，做兜底生成（只生成本 doc_prefix）。
    if not ok_pp:
        _ensure_ppocr_from_vlmocr(dataset_dir, doc_prefix)

    logger.info("[4/5] 双层 OCR 融合...")
    run_script([sys.executable or 'python', os.path.join(scripts_dir, 'merge_ocr.py'), '--dataset', dataset_name], "[4/5] 融合")

    logger.info("[5/5] 嵌入...")
    run_script([sys.executable or 'python', os.path.join(ROOT, 'ingestion.py'), '--dataset', dataset_name], "[5/5] 嵌入")

    # 可选工作：GraphRAG input / 画框质检图
    if _env_on("KB_UPDATE_GRAPHRAG_INPUT"):
        try:
            _write_graphrag_input_for_prefix(dataset_dir, doc_prefix)
        except Exception as e:
            logger.warning("生成 GraphRAG input 失败: %s", e)
    if _env_on("KB_GENERATE_VLM_BOX_IMAGES"):
        try:
            _draw_vlm_boxes_images(dataset_dir, doc_prefix)
        except Exception as e:
            logger.warning("生成画框质检图失败: %s", e)


def scan_and_update(dataset_name):
    from backend.main import create_app
    from backend.storage import pdf_storage

    app = create_app()
    with app.app_context():
        rebuilt_curated = _maybe_rebuild_curated_structured()
        dataset_dir = get_dataset_dir(dataset_name)
        pdf_dir = os.path.join(dataset_dir, 'pdf')
        if not os.path.isdir(pdf_dir):
            logger.error("错误: %s 不存在", pdf_dir)
            return

        # 以 pdfs 表为准：表内已有记录
        all_rows = list(pdf_storage.list_all(dataset_name))
        table_pdfs = {p.filename: {"id": p.id, "file_hash": getattr(p, "file_hash", None)} for p in all_rows}

        # 关键：当 TSV 有改动并触发了 build 时，即使 PDF 本身没有变化，也需要先把
        # competition_structs 按新结构化知识库全量对齐一次（否则会出现“点更新但 DB 没更新”）。
        if rebuilt_curated:
            try:
                # “删了重建”的等价实现：先清空当前 dataset 的所有行，再按结构化知识库重灌
                try:
                    from backend.storage.db import db
                    from backend.models.competition_struct_model import CompetitionStruct
                    deleted = CompetitionStruct.query.filter_by(dataset=dataset_name).delete()
                    db.session.commit()
                    logger.info("结构化知识库已更新：已清空 competition_structs dataset=%s rows=%s", dataset_name, deleted)
                except Exception as e:
                    logger.warning("清空 competition_structs 失败（将尝试覆盖式 upsert）：%s", e)

                synced = 0
                for p in all_rows:
                    fn = getattr(p, "filename", "") or ""
                    doc_id = fn[:-4] if fn.lower().endswith(".pdf") else fn
                    if _sync_competition_structs_for_doc(dataset_name, doc_id):
                        synced += 1
                logger.info("结构化知识库已更新：已全量对齐 competition_structs %s 条", synced)

                # 额外：生成一个带中文列名的 SQLite 视图，便于你直接在 DB 里看“赛系/赛名/赛道…”
                try:
                    from backend.storage.db import db
                    sql = """
                    DROP VIEW IF EXISTS competition_structs_cn;
                    CREATE VIEW competition_structs_cn AS
                    SELECT
                      id AS id,
                      dataset AS 数据集,
                      competition_id AS competition_id,
                      competition_name AS 赛系,
                      COALESCE(json_extract(tracks_json, '$[0]'), '/') AS "赛名/赛道",
                      competition_category AS 赛事类别,
                      session AS 发布时间,
                      registration_time AS 报名时间,
                      organizer AS 组织单位,
                      official_website AS 官网,
                      created_at AS 创建时间,
                      updated_at AS 更新时间
                    FROM competition_structs;
                    """
                    # exec multi statements
                    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                        db.session.execute(db.text(stmt))
                    db.session.commit()
                    logger.info("已生成 SQLite 视图 competition_structs_cn（中文字段名）")
                except Exception as e:
                    logger.warning("生成视图 competition_structs_cn 失败（不影响主流程）：%s", e)
            except Exception as e:
                logger.warning("结构化知识库全量对齐 competition_structs 失败: %s", e)
        # 磁盘上当前存在的 PDF 文件
        current_files = [f for f in os.listdir(pdf_dir) if f.endswith('.pdf')]
        current_set = set(current_files)

        added, updated, unchanged, deleted = [], [], [], []
        missing_products = []
        new_manifest = {}

        for pdf_name in tqdm(current_files, desc="扫描 PDF"):
            pdf_path = os.path.join(pdf_dir, pdf_name)
            prefix = pdf_name.replace('.pdf', '')
            try:
                current_md5 = md5_file(pdf_path)
            except Exception as e:
                logger.warning("跳过 %s: %s", pdf_name, e)
                continue
            new_manifest[pdf_name] = current_md5
            row = table_pdfs.get(pdf_name)
            if not row:
                added.append((pdf_name, prefix, pdf_path, current_md5))
            elif row["file_hash"] is not None and row["file_hash"] != current_md5:
                updated.append((pdf_name, prefix, pdf_path, current_md5, row["id"]))
            else:
                # MD5 未变化，但如果解析产物缺失，也要进入重建队列
                if needs_rebuild_due_to_missing_products(dataset_dir, prefix):
                    missing_products.append((pdf_name, prefix, pdf_path, current_md5, row["id"] if row else None))
                else:
                    unchanged.append(pdf_name)
                if row["file_hash"] is None:
                    pdf_storage.update_file_hash(row["id"], current_md5)

        for pdf_name, row in table_pdfs.items():
            if pdf_name not in current_set:
                deleted.append((pdf_name, row["id"]))

        logger.info(
            f"\n知识库扫描 [{dataset_name}]（以 pdfs 表为准） "
            f"新增:{len(added)} 更新:{len(updated)} 删除:{len(deleted)} "
            f"补齐缺失产物:{len(missing_products)} 未变:{len(unchanged)}\n"
        )
        if not added and not updated and not deleted and not missing_products:
            logger.info("知识库无变化")
            save_manifest(dataset_dir, new_manifest)
            return

        for pdf_name, pdf_id in deleted:
            prefix = pdf_name.replace('.pdf', '')
            n, _ = archive_related_files(dataset_dir, prefix)
            pdf_storage.delete_by_id(pdf_id)
            append_changelog(dataset_dir, "DELETE", pdf_name, f"归档 {n} 个文件，并从 pdfs 表移除")
            logger.info("[删除/归档] %s", pdf_name)

        for pdf_name, prefix, pdf_path, current_md5, pdf_id in updated:
            logger.info("[更新] %s", pdf_name)
            n, _ = archive_related_files(dataset_dir, prefix)
            run_pipeline(dataset_dir, pdf_path, prefix)
            pdf_storage.update_file_hash(pdf_id, current_md5)
            try:
                _sync_competition_structs_for_doc(dataset_name, prefix)
            except Exception as e:
                logger.warning("同步 competition_structs 失败: %s", e)
            append_changelog(dataset_dir, "UPDATE", pdf_name, f"MD5 已变更，已归档旧产物并重建")

        for pdf_name, prefix, pdf_path, current_md5 in added:
            logger.info("[新增] %s", pdf_name)
            pdf_storage.create(pdf_name, pdf_path, dataset_name, file_hash=current_md5)
            run_pipeline(dataset_dir, pdf_path, prefix)
            try:
                _sync_competition_structs_for_doc(dataset_name, prefix)
            except Exception as e:
                logger.warning("同步 competition_structs 失败: %s", e)
            append_changelog(dataset_dir, "ADD", pdf_name, f"MD5: {current_md5}")

        for pdf_name, prefix, pdf_path, current_md5, pdf_id in missing_products:
            logger.info("[补齐缺失产物] %s", pdf_name)
            # 不归档旧产物（可能本来就没有），直接跑一遍管线补齐
            run_pipeline(dataset_dir, pdf_path, prefix)
            if pdf_id:
                pdf_storage.update_file_hash(pdf_id, current_md5)
            try:
                _sync_competition_structs_for_doc(dataset_name, prefix)
            except Exception as e:
                logger.warning("同步 competition_structs 失败: %s", e)
            append_changelog(dataset_dir, "REBUILD_MISSING", pdf_name, "产物缺失，已补齐重建")

        save_manifest(dataset_dir, new_manifest)
        logger.info("更新完成")


def rebuild_one(dataset_name: str, pdf_name: str, *, force: bool = False) -> None:
    """
    只重建单个 PDF（用于后台“重新解析”）。
    - pdf_name: 形如 "<prefix>_xxx.pdf" 的文件名（带 .pdf）
    - force: True 时先归档旧产物再重跑（确保真正“重新解析”）
    """
    from backend.main import create_app
    from backend.storage import pdf_storage

    app = create_app()
    with app.app_context():
        _maybe_rebuild_curated_structured()
        dataset_dir = get_dataset_dir(dataset_name)
        pdf_dir = os.path.join(dataset_dir, 'pdf')
        if not os.path.isdir(pdf_dir):
            logger.error("错误: %s 不存在", pdf_dir)
            return

        pdf_path = os.path.join(pdf_dir, pdf_name)
        if not os.path.exists(pdf_path):
            logger.error("错误: PDF 不存在: %s", pdf_path)
            return

        prefix = pdf_name.replace('.pdf', '')
        try:
            current_md5 = md5_file(pdf_path)
        except Exception as e:
            logger.error("错误: 无法计算 MD5: %s", e)
            return

        row = None
        try:
            row = pdf_storage.get_by_filename(dataset_name, pdf_name)
        except Exception:
            row = None

        if force:
            n, _ = archive_related_files(dataset_dir, prefix)
            append_changelog(dataset_dir, "REPARSE_FORCE", pdf_name, f"强制归档旧产物 {n} 个文件，并重建")
        else:
            append_changelog(dataset_dir, "REPARSE", pdf_name, "重建单文档")

        logger.info("[单文档重建] dataset=%s pdf=%s force=%s", dataset_name, pdf_name, force)
        run_pipeline(dataset_dir, pdf_path, prefix)

        # 更新/写入 file_hash，避免后续扫描判断异常
        if row and getattr(row, "id", None):
            try:
                pdf_storage.update_file_hash(row.id, current_md5)
            except Exception:
                pass
        else:
            try:
                pdf_storage.create(pdf_name, pdf_path, dataset_name, file_hash=current_md5)
            except Exception:
                pass

        # 同步 competition_structs：以 data/curated_competitions.tsv（生成的 CURATED_COMPETITIONS）为准
        # 只更新本 doc_id，对新增 PDF/重新解析最关键，且不会依赖 LLM 抽取。
        try:
            from config.curated_structured import CURATED_COMPETITIONS
            from backend.storage import competition_struct_storage

            doc_id = prefix
            t = (doc_id or "").strip().lower()
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
                    dataset=dataset_name,
                    competition_id=doc_id,
                    payload=payload,
                    source_text=f"curated_id={hit.get('id')}",
                )
                logger.info("已同步 competition_structs: %s", doc_id)
            else:
                logger.info("未在结构化知识库中匹配到该 PDF，跳过 competition_structs 同步: %s", doc_id)
        except Exception as e:
            logger.warning("同步 competition_structs 失败: %s", e)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='CompetitionDataset')
    parser.add_argument('--only', default='', help='仅处理指定 PDF 文件名（带 .pdf），用于单文档重建')
    parser.add_argument('--force', action='store_true', help='单文档重建时强制归档旧产物并重跑')
    args = parser.parse_args()
    if args.only:
        rebuild_one(args.dataset, args.only.strip(), force=bool(args.force))
    else:
        scan_and_update(args.dataset)
