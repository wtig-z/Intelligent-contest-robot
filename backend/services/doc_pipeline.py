"""根据磁盘产物推断单份 PDF 的解析 / OCR / 文本状态。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict


def _doc_prefix(filename: str) -> str:
    fn = (filename or "").strip()
    if fn.lower().endswith(".pdf"):
        return fn[:-4]
    return fn


def _count_prefix_files(directory: str, prefix: str, suffix: str) -> int:
    if not directory or not os.path.isdir(directory):
        return 0
    p = prefix + "_"
    suf = suffix.lower()
    n = 0
    for name in os.listdir(directory):
        if not name.lower().endswith(suf):
            continue
        if name.startswith(p):
            n += 1
    return n


def _latest_mtime_for_prefix(directory: str, prefix: str) -> float | None:
    """返回某目录下 prefix_ 开头文件的最新 mtime（秒），不存在则 None。"""
    if not directory or not os.path.isdir(directory):
        return None
    p = prefix + "_"
    latest: float | None = None
    for name in os.listdir(directory):
        if not name.startswith(p):
            continue
        path = os.path.join(directory, name)
        try:
            mt = os.path.getmtime(path)
        except Exception:
            continue
        if latest is None or mt > latest:
            latest = mt
    return latest


def pipeline_status_for_pdf(dataset: str, filename: str) -> Dict[str, Any]:
    from config.paths import (
        get_pdf_dir,
        get_img_dir,
        get_ppocr_dir,
        get_unified_text_dir,
        get_vlmocr_dir,
        get_bge_ingestion_dir,
        get_graphrag_dir,
    )
    from config.paths import get_dataset_dir

    prefix = _doc_prefix(filename)
    pdf_path = os.path.join(get_pdf_dir(dataset), filename)
    pdf_on_disk = os.path.isfile(pdf_path)

    img_pages = _count_prefix_files(get_img_dir(dataset), prefix, ".png")
    if img_pages == 0:
        img_pages = _count_prefix_files(get_img_dir(dataset), prefix, ".jpg")

    ppocr_pages = _count_prefix_files(get_ppocr_dir(dataset), prefix, ".txt")
    vlm_pages = _count_prefix_files(get_vlmocr_dir(dataset), prefix, ".txt")
    unified_pages = _count_prefix_files(get_unified_text_dir(dataset), prefix, ".txt")

    ocr_done = unified_pages > 0 or ppocr_pages > 0 or vlm_pages > 0
    text_extracted = unified_pages > 0
    images_ready = img_pages > 0
    parse_ok = pdf_on_disk and (images_ready or text_extracted or ocr_done)

    # 更新时间：以该文档相关“知识库产物”的最新修改时间为准
    mt_candidates = [
        _latest_mtime_for_prefix(get_img_dir(dataset), prefix),
        _latest_mtime_for_prefix(get_ppocr_dir(dataset), prefix),
        _latest_mtime_for_prefix(get_vlmocr_dir(dataset), prefix),
        _latest_mtime_for_prefix(get_unified_text_dir(dataset), prefix),
        _latest_mtime_for_prefix(get_bge_ingestion_dir(dataset), prefix),
        _latest_mtime_for_prefix(os.path.join(get_dataset_dir(dataset), "colqwen_ingestion"), prefix),
        _latest_mtime_for_prefix(os.path.join(get_dataset_dir(dataset), "img_with_boxes_vlmocr"), prefix),
        # graphrag/input/<prefix>.txt 也算一次更新（如果启用了开关）
        (os.path.getmtime(os.path.join(get_graphrag_dir(dataset), "input", f"{prefix}.txt"))
         if os.path.isfile(os.path.join(get_graphrag_dir(dataset), "input", f"{prefix}.txt")) else None),
    ]
    latest_mt = None
    for mt in mt_candidates:
        if mt is None:
            continue
        if latest_mt is None or mt > latest_mt:
            latest_mt = mt
    updated_at = datetime.fromtimestamp(latest_mt).isoformat() if latest_mt else None

    issues = []
    if not pdf_on_disk:
        issues.append("pdf_missing")
    elif pdf_on_disk and not images_ready and not text_extracted and not ocr_done:
        issues.append("not_processed")

    return {
        "doc_prefix": prefix,
        "pdf_on_disk": pdf_on_disk,
        "image_pages": img_pages,
        "ppocr_pages": ppocr_pages,
        "vlmocr_pages": vlm_pages,
        "unified_text_pages": unified_pages,
        "ocr_complete": bool(ocr_done),
        "text_extracted": bool(text_extracted),
        "parse_success": bool(parse_ok),
        "updated_at": updated_at,
        "issues": issues,
    }
