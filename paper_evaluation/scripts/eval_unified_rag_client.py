"""
批量调用「统一知识检索与生成」对话接口，将逐题结果写入 JSONL，供线下聚合指标。

本脚本仅依赖 Python 标准库与 requests（可选安装），不 import 本仓库 backend/frontend。
部署方将接口基础地址与路径配置为与线上一致的服务即可。

环境变量：
  RAG_EVAL_BASE_URL   必填，如 http://127.0.0.1:5000
  RAG_EVAL_CHAT_PATH  必填，对话 HTTP 路径（含前导 /），由部署配置
  RAG_EVAL_TOKEN      可选，Authorization Bearer（若服务要求登录）
  RAG_EVAL_MANIFEST   可选，评测清单 JSON 路径（与评测说明中 schema 一致）

输出：
  默认写入 paper_evaluation/results/run_<时间戳>.jsonl（每行一题一响应摘要）
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import urllib.error
    import urllib.request
except ImportError:
    urllib = None  # type: ignore


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _post_json(url: str, body: Dict[str, Any], token: str) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # type: ignore
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": "Bearer " + token.strip()} if token.strip() else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=600) as resp:  # type: ignore
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def main() -> int:
    if urllib is None:
        print("需要 urllib", file=sys.stderr)
        return 1
    base = (os.environ.get("RAG_EVAL_BASE_URL") or "").strip().rstrip("/")
    path = (os.environ.get("RAG_EVAL_CHAT_PATH") or "").strip()
    if not base or not path:
        print("请设置 RAG_EVAL_BASE_URL 与 RAG_EVAL_CHAT_PATH", file=sys.stderr)
        return 1
    token = os.environ.get("RAG_EVAL_TOKEN") or ""
    url = base + (path if path.startswith("/") else "/" + path)

    manifest_path = os.environ.get("RAG_EVAL_MANIFEST") or ""
    if not manifest_path:
        print("请设置 RAG_EVAL_MANIFEST 指向评测清单 JSON", file=sys.stderr)
        return 1
    mp = Path(manifest_path)
    if not mp.is_file():
        print(f"清单不存在: {mp}", file=sys.stderr)
        return 1

    with open(mp, encoding="utf-8") as f:
        manifest = json.load(f)
    items = manifest.get("items") or []
    out_dir = _root() / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"run_{stamp}.jsonl"

    count = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for item in items:
            pdf = item.get("pdf_path") or ""
            comp = str(item.get("competition_id") or "").strip()
            for q in item.get("questions") or []:
                query = str(q.get("query") or "").strip()
                if not query:
                    continue
                body = {
                    "message": query,
                    "stream": False,
                    "history": [],
                    "competition_id": comp,
                }
                row: Dict[str, Any] = {
                    "item_id": item.get("id"),
                    "question_id": q.get("id"),
                    "pdf_path": pdf,
                    "query": query,
                    "ok": False,
                }
                try:
                    resp = _post_json(url, body, token)
                    row["ok"] = resp.get("code") == 0
                    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
                    row["answer"] = (data.get("answer") or "")[:2000]
                    row["references"] = data.get("references")
                except Exception as e:
                    row["error"] = str(e)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1

    print(f"已写入 {count} 条: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
