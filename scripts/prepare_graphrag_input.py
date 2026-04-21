"""
准备 GraphRAG 输入数据：从 unified_text/ 页级文本合并为文档级文本。

输入：data/<dataset>/unified_text/{doc_prefix}_{page}.txt
输出：data/<dataset>/graphrag/input/{doc_prefix}.txt

用法：
  python scripts/prepare_graphrag_input.py
  python scripts/prepare_graphrag_input.py --dataset CompetitionDataset
"""
import os
import re
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import get_unified_text_dir, get_graphrag_dir


def natural_sort_key(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', s)]


def prepare_input(dataset: str) -> int:
    unified_dir = get_unified_text_dir(dataset)
    graphrag_input_dir = os.path.join(get_graphrag_dir(dataset), "input")

    if not os.path.isdir(unified_dir):
        print(f"unified_text 目录不存在: {unified_dir}")
        print("请先运行: python scripts/merge_ocr.py")
        return 0

    os.makedirs(graphrag_input_dir, exist_ok=True)

    files = [f for f in os.listdir(unified_dir) if f.endswith(".txt")]
    if not files:
        print("unified_text/ 下没有 .txt 文件")
        return 0

    docs = defaultdict(list)
    page_pattern = re.compile(r'^(.+)_(\d+)\.txt$')

    for f in files:
        m = page_pattern.match(f)
        if m:
            doc_name = m.group(1)
            page_num = int(m.group(2))
            docs[doc_name].append((page_num, f))
        else:
            docs[f.replace('.txt', '')].append((0, f))

    count = 0
    for doc_name in sorted(docs.keys(), key=natural_sort_key):
        pages = docs[doc_name]
        pages.sort(key=lambda x: x[0])

        merged_parts = []
        for page_num, filename in pages:
            filepath = os.path.join(unified_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    text = fh.read().strip()
                    if text:
                        merged_parts.append(text)
            except Exception as e:
                print(f"  警告: 读取 {filename} 失败: {e}")

        if not merged_parts:
            continue

        full_text = "\n\n".join(merged_parts)
        output_file = os.path.join(graphrag_input_dir, f"{doc_name}.txt")
        with open(output_file, "w", encoding="utf-8") as fh:
            fh.write(full_text)

        count += 1
        print(f"  [{count:2d}] {doc_name} ({len(pages)} 页, {len(full_text):,} 字)")

    print(f"\n完成: {len(files)} 个页面 → {count} 篇文档")
    print(f"输出目录: {graphrag_input_dir}")
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="unified_text → GraphRAG 文档级输入")
    parser.add_argument("--dataset",
                        default=os.getenv("VIDORAG_DATASET", "CompetitionDataset"))
    args = parser.parse_args()

    print(f"数据集: {args.dataset}")
    print("=" * 50)
    result = prepare_input(args.dataset)
    sys.exit(0 if result > 0 else 1)
