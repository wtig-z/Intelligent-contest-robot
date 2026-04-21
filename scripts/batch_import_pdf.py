#!/usr/bin/env python3
"""批量导入 PDF 到知识库"""
import os
import sys
import argparse

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv()

from config.paths import get_pdf_dir, get_dataset_dir


def main():
    parser = argparse.ArgumentParser(description="批量导入 PDF")
    parser.add_argument("dir", nargs="?", default=".", help="PDF 所在目录")
    parser.add_argument("--dataset", default="CompetitionDataset", help="数据集名")
    args = parser.parse_args()

    src_dir = os.path.abspath(args.dir)
    if not os.path.isdir(src_dir):
        print(f"目录不存在: {src_dir}")
        sys.exit(1)

    from backend.main import create_app
    from backend.storage import pdf_storage

    app = create_app()
    pdf_dir = get_pdf_dir(args.dataset)
    os.makedirs(pdf_dir, exist_ok=True)

    count = 0
    with app.app_context():
        for name in os.listdir(src_dir):
            if not name.lower().endswith(".pdf"):
                continue
            src_path = os.path.join(src_dir, name)
            if not os.path.isfile(src_path):
                continue
            dst_path = os.path.join(pdf_dir, name)
            if os.path.exists(dst_path):
                print(f"跳过（已存在）: {name}")
                continue
            import shutil
            shutil.copy2(src_path, dst_path)
            pdf_storage.create(name, dst_path, args.dataset)
            count += 1
            print(f"已导入: {name}")
    print(f"共导入 {count} 个 PDF")


if __name__ == "__main__":
    main()
