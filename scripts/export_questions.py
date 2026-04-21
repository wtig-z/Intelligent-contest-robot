#!/usr/bin/env python3
"""导出用户问题到 CSV"""
import os
import sys
import csv
import argparse

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="导出用户问题")
    parser.add_argument("-o", "--output", default="questions_export.csv", help="输出文件路径")
    parser.add_argument("-n", "--limit", type=int, default=10000, help="最大条数")
    args = parser.parse_args()

    from backend.main import create_app
    from backend.storage import question_storage

    app = create_app()
    with app.app_context():
        items = question_storage.list_all(limit=args.limit, offset=0)
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "user_id", "content", "answer", "rewritten", "created_at"])
            for q in items:
                w.writerow([
                    q.id,
                    q.user_id,
                    q.content or "",
                    (q.answer or "")[:500],
                    (q.rewritten or "")[:500],
                    q.created_at.isoformat() if q.created_at else "",
                ])
        print(f"已导出 {len(items)} 条到 {args.output}")


if __name__ == "__main__":
    main()
