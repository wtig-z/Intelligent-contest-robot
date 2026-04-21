"""
论文级对比实验结果汇总与制表。

从聚合结果 JSON 读取各方法在统一测试协议下的指标，输出 Markdown / LaTeX 表格。
本脚本位于独立目录 paper_evaluation，不 import 项目 backend / frontend。

用法（在仓库根目录执行）：
  python paper_evaluation/scripts/paper_eval_report.py
  python paper_evaluation/scripts/paper_eval_report.py --input paper_evaluation/data/paper_experiment_summary.json --format latex
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _default_summary_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "paper_experiment_summary.json"


def load_summary(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("汇总文件根节点须为对象")
    methods = data.get("methods")
    if not isinstance(methods, list) or len(methods) < 1:
        raise ValueError("汇总文件须包含非空 methods 数组")
    for m in methods:
        if not isinstance(m, dict):
            raise ValueError("methods 项须为对象")
        if "label" not in m or "metrics" not in m:
            raise ValueError("每项须含 label、metrics")
        met = m["metrics"]
        for k in ("recall_at_1", "recall_at_3", "accuracy", "f1", "rouge_l"):
            if k not in met:
                raise ValueError(f"metrics 缺少字段: {k}")
    return data


def _pct(x: float) -> str:
    return f"{100.0 * float(x):.1f}%"


def _f(x: float) -> str:
    return f"{float(x):.2f}"


def table_markdown(methods: List[Dict[str, Any]]) -> str:
    lines = [
        "| 方法 | Recall@1 | Recall@3 | 准确率 | F1 | ROUGE-L |",
        "|------|----------|----------|--------|-----|---------|",
    ]
    for m in methods:
        met = m["metrics"]
        lines.append(
            "| "
            + str(m.get("label", "")).replace("|", "\\|")
            + " | "
            + _pct(met["recall_at_1"])
            + " | "
            + _pct(met["recall_at_3"])
            + " | "
            + _pct(met["accuracy"])
            + " | "
            + _f(met["f1"])
            + " | "
            + _f(met["rouge_l"])
            + " |"
        )
    return "\n".join(lines) + "\n"


def table_latex(methods: List[Dict[str, Any]]) -> str:
    rows = []
    for m in methods:
        met = m["metrics"]
        lab = str(m.get("label", "")).replace("&", r"\&")
        rows.append(
            f"{lab} & {_pct(met['recall_at_1'])} & {_pct(met['recall_at_3'])} & "
            f"{_pct(met['accuracy'])} & {_f(met['f1'])} & {_f(met['rouge_l'])} \\\\"
        )
    body = "\n".join(rows)
    return (
        "\\begin{tabular}{lccccc}\n\\hline\n"
        "方法 & Recall@1 & Recall@3 & 准确率 & F1 & ROUGE-L \\\\\n\\hline\n"
        f"{body}\n\\hline\n\\end{tabular}\n"
    )


def print_protocol_brief(data: Dict[str, Any]) -> None:
    corp = data.get("test_corpus") or {}
    ev = data.get("evaluation_set") or {}
    print("【测试协议摘要】", file=sys.stderr)
    print(
        f"  文档数: {corp.get('num_documents', '?')} ；{corp.get('notes', '')}",
        file=sys.stderr,
    )
    print(
        f"  评测题数: {ev.get('num_questions', '?')} ；题型: "
        + "、".join(ev.get("categories") or []),
        file=sys.stderr,
    )
    print(file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="论文实验汇总制表")
    ap.add_argument("--input", type=Path, default=None, help="聚合结果 JSON 路径")
    ap.add_argument(
        "--format",
        choices=("md", "latex", "both"),
        default="md",
        help="输出格式",
    )
    ap.add_argument("--quiet-protocol", action="store_true", help="不打印协议摘要到 stderr")
    args = ap.parse_args()
    path = args.input or _default_summary_path()
    if not path.is_file():
        print(f"找不到汇总文件: {path}", file=sys.stderr)
        return 1
    data = load_summary(path)
    methods = data["methods"]
    if not args.quiet_protocol:
        print_protocol_brief(data)
    if args.format in ("md", "both"):
        print(table_markdown(methods), end="")
    if args.format in ("latex", "both"):
        if args.format == "both":
            print("\n--- LaTeX ---\n")
        print(table_latex(methods), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
