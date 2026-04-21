#!/usr/bin/env python3
"""
双层 OCR 融合：PP-OCR + VLM OCR → unified_text/

融合策略：
  1. VLM OCR (qwen-vl) 提供结构化内容（表格、图表、排版保留）
  2. PP-OCR 提供完整文字覆盖（VLM 可能遗漏的小字、页眉页脚等）
  3. 以 VLM 为主干，将 PP-OCR 中 VLM 未覆盖的文本追加到末尾

输入：data/<dataset>/ppocr/{prefix}_{page}.txt
      data/<dataset>/vlmocr/{prefix}_{page}.json
输出：data/<dataset>/unified_text/{prefix}_{page}.txt

用法：
  python scripts/merge_ocr.py
  python scripts/merge_ocr.py --dataset CompetitionDataset
"""
import os
import sys
import json
import re
import argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config.paths import get_ppocr_dir, get_vlmocr_dir, get_unified_text_dir


def _extract_vlm_text(json_path: str) -> str:
    """从 VLM OCR JSON 提取全部文本，按 objects 顺序拼接。"""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ""

    objects = data.get("objects", [])
    if not objects:
        return ""

    parts = []
    for obj in objects:
        content = obj.get("content", "").strip()
        if not content:
            continue
        obj_type = obj.get("type", "text")
        if obj_type == "table":
            parts.append(f"[表格]\n{content}")
        elif obj_type == "chart":
            parts.append(f"[图表]\n{content}")
        else:
            parts.append(content)

    return "\n".join(parts)


def _read_ppocr_text(txt_path: str) -> str:
    """读取 PP-OCR 纯文本。"""
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _normalize(text: str) -> str:
    """统一空白、去掉连续空行。"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_unique_ppocr_lines(vlm_text: str, ppocr_text: str, min_line_len: int = 4) -> list[str]:
    """找到 PP-OCR 中存在但 VLM 文本中未覆盖的行。"""
    vlm_lower = vlm_text.lower()
    unique = []
    for line in ppocr_text.split("\n"):
        line = line.strip()
        if len(line) < min_line_len:
            continue
        if line.lower() not in vlm_lower:
            unique.append(line)
    return unique


def merge_page(vlm_text: str, ppocr_text: str) -> str:
    """
    融合单页双层 OCR 结果。

    策略：
    - VLM 文本为主干（结构化、类型标注）
    - PP-OCR 中 VLM 未覆盖的独有文本追加到末尾（补全小字/页眉页脚等）
    - 如果 VLM 为空则直接用 PP-OCR
    """
    vlm_text = vlm_text.strip()
    ppocr_text = ppocr_text.strip()

    if not vlm_text and not ppocr_text:
        return ""
    if not vlm_text:
        return _normalize(ppocr_text)
    if not ppocr_text:
        return _normalize(vlm_text)

    unique_lines = _find_unique_ppocr_lines(vlm_text, ppocr_text)

    if unique_lines:
        supplement = "\n".join(unique_lines)
        merged = f"{vlm_text}\n\n{supplement}"
    else:
        merged = vlm_text

    return _normalize(merged)


def merge_all(dataset: str) -> int:
    ppocr_dir = get_ppocr_dir(dataset)
    vlmocr_dir = get_vlmocr_dir(dataset)
    unified_dir = get_unified_text_dir(dataset)
    os.makedirs(unified_dir, exist_ok=True)

    page_keys = set()

    if os.path.isdir(ppocr_dir):
        for f in os.listdir(ppocr_dir):
            if f.endswith(".txt"):
                page_keys.add(f.replace(".txt", ""))

    if os.path.isdir(vlmocr_dir):
        for f in os.listdir(vlmocr_dir):
            if f.endswith(".json"):
                page_keys.add(f.replace(".json", ""))

    if not page_keys:
        print("没有找到任何 OCR 输出文件")
        return 0

    page_keys = sorted(page_keys)
    stats = {"vlm_only": 0, "ppocr_only": 0, "merged": 0, "empty": 0}

    for key in page_keys:
        vlm_path = os.path.join(vlmocr_dir, f"{key}.json")
        ppocr_path = os.path.join(ppocr_dir, f"{key}.txt")
        out_path = os.path.join(unified_dir, f"{key}.txt")

        has_vlm = os.path.exists(vlm_path)
        has_ppocr = os.path.exists(ppocr_path)

        vlm_text = _extract_vlm_text(vlm_path) if has_vlm else ""
        ppocr_text = _read_ppocr_text(ppocr_path) if has_ppocr else ""

        unified = merge_page(vlm_text, ppocr_text)

        if not unified:
            stats["empty"] += 1
            continue

        if has_vlm and has_ppocr:
            stats["merged"] += 1
        elif has_vlm:
            stats["vlm_only"] += 1
        else:
            stats["ppocr_only"] += 1

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(unified)

    total = stats["merged"] + stats["vlm_only"] + stats["ppocr_only"]
    print(f"融合完成: {total} 页")
    print(f"  双源融合: {stats['merged']}")
    print(f"  仅 VLM:   {stats['vlm_only']}")
    print(f"  仅 PP-OCR: {stats['ppocr_only']}")
    print(f"  空页跳过: {stats['empty']}")
    print(f"输出目录: {unified_dir}")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="双层 OCR 融合 → unified_text/")
    parser.add_argument("--dataset",
                        default=os.getenv("VIDORAG_DATASET", "CompetitionDataset"))
    args = parser.parse_args()

    print(f"数据集: {args.dataset}")
    print("=" * 50)
    result = merge_all(args.dataset)
    sys.exit(0 if result > 0 else 1)
