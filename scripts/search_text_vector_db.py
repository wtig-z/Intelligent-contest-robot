#!/usr/bin/env python3
"""
对 build_text_vector_db.py 产出的本地文本向量库做检索。

流程：
  1) 用同一套 BGE 将 query 编成 q_emb（L2 归一化）
  2) 可选：与 kmeans 簇中心点积粗筛 top 簇，再在簇内向量上精排
  3) 否则：与全库 embeddings 点积（余弦）后取 Top-K

用法：
  python scripts/search_text_vector_db.py --db-dir data/_vector_db/contest_text_vector_db --query "报名截止时间"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

import numpy as np
from llama_index.embeddings.huggingface import HuggingFaceEmbedding


def load_documents_jsonl(path: str) -> Dict[int, str]:
    id_to_text: Dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            id_to_text[int(o["id"])] = o.get("text", "")
    return id_to_text


def main() -> None:
    default_db = os.path.join(ROOT, "data", "_vector_db", "contest_text_vector_db")
    p = argparse.ArgumentParser(description="Search local file-based text vector index.")
    p.add_argument("--db-dir", default=default_db)
    p.add_argument("--query", default="决赛是线上还是线下答辩")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--top-clusters", type=int, default=3, help="0 表示禁用 KMeans 粗筛，全库扫描")
    p.add_argument("--no-kmeans", action="store_true", help="禁用粗筛，对全库向量精排")
    p.add_argument("--model-name", default="", help="默认读 metadata.model_name")
    args = p.parse_args()
    use_kmeans = not bool(args.no_kmeans)

    embeddings_path = os.path.join(args.db_dir, "embeddings.pt")
    metadata_path = os.path.join(args.db_dir, "metadata.json")
    if not os.path.isfile(embeddings_path) or not os.path.isfile(metadata_path):
        raise FileNotFoundError(
            f"缺少 {embeddings_path} 或 {metadata_path}，请先运行 scripts/build_text_vector_db.py"
        )

    with open(metadata_path, encoding="utf-8") as f:
        metadata: Dict[str, Any] = json.load(f)

    model_name = args.model_name or metadata.get("model_name", "BAAI/bge-m3")
    emb_model = HuggingFaceEmbedding(model_name=model_name, trust_remote_code=True)
    q = np.array(emb_model.get_text_embedding(args.query), dtype=np.float32)
    q_emb = torch.from_numpy(q)
    q_emb = torch.nn.functional.normalize(q_emb, p=2, dim=-1)

    embeddings = torch.load(embeddings_path, map_location="cpu").to(torch.float32)
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=-1)

    docs_jsonl = os.path.join(args.db_dir, metadata.get("documents_jsonl", "documents.jsonl"))
    id_to_text = load_documents_jsonl(docs_jsonl) if os.path.isfile(docs_jsonl) else {}
    documents = metadata.get("documents", [])

    km_meta = metadata.get("kmeans") if isinstance(metadata.get("kmeans"), dict) else {}
    centers_file = str(km_meta.get("centers_path", "kmeans_centers.pt"))
    labels_file = str(km_meta.get("labels_path", "kmeans_labels.pt"))
    centers_path = os.path.join(args.db_dir, centers_file)
    labels_path = os.path.join(args.db_dir, labels_file)

    ok_km = (
        use_kmeans
        and int(args.top_clusters) > 0
        and os.path.isfile(centers_path)
        and os.path.isfile(labels_path)
    )

    print(f"[search_text] query={args.query!r}")
    print(f"[search_text] index_size={embeddings.shape[0]}, dim={embeddings.shape[1]}")

    if ok_km:
        centers = torch.load(centers_path, map_location="cpu").to(torch.float32)
        labels = torch.load(labels_path, map_location="cpu").to(torch.int64)
        if labels.shape[0] != embeddings.shape[0]:
            raise RuntimeError("kmeans_labels 长度与 embeddings 不一致")
        cluster_scores = torch.matmul(centers, q_emb)
        tc = min(int(args.top_clusters), int(cluster_scores.shape[0]))
        _, top_ci = torch.topk(cluster_scores, k=tc, dim=0)
        mask = torch.zeros_like(labels, dtype=torch.bool)
        for ci in top_ci.tolist():
            mask |= labels == int(ci)
        cand = mask.nonzero(as_tuple=False).view(-1)
        if cand.numel() == 0:
            raise RuntimeError("KMeans 候选为空，请重建索引或改用全量扫描（--no-kmeans）")
        print(f"[search_text] kmeans: top_clusters={tc}, candidates={cand.numel()}")
        scores = torch.matmul(embeddings[cand], q_emb)
        tk = min(int(args.top_k), scores.shape[0])
        top_scores, top_local = torch.topk(scores, k=tk, dim=0)
        top_indices = cand[top_local]
    else:
        print("[search_text] full scan (no kmeans or top_clusters=0)")
        scores = torch.matmul(embeddings, q_emb)
        tk = min(int(args.top_k), scores.shape[0])
        top_scores, top_indices = torch.topk(scores, k=tk, dim=0)

    print("\n[search_text] top results:")
    for rank, (idx, sc) in enumerate(zip(top_indices.tolist(), top_scores.tolist()), start=1):
        idx = int(idx)
        snippet = id_to_text.get(idx, "")
        if len(snippet) > 120:
            snippet = snippet[:120] + "…"
        meta = documents[idx] if idx < len(documents) else {}
        print(f"{rank:>2}. score={sc:.6f}  id={idx}  meta={meta}")
        if snippet:
            print(f"    text: {snippet}")


if __name__ == "__main__":
    main()
