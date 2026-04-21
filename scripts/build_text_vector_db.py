#!/usr/bin/env python3
"""
本地文件型「文本向量库」建库（非 Milvus/Qdrant 服务）。

产物目录（默认 data/_vector_db/contest_text_vector_db）：
  - embeddings.pt       [N, D] float32，行 L2 归一化
  - metadata.json       模型信息、文档摘要字段、kmeans 文件名索引
  - documents.jsonl     每行一条 JSON，含完整 text（避免 metadata 过大）
  - kmeans_centers.pt / kmeans_labels.pt  可选 MiniBatchKMeans 粗筛用

用法：
  python scripts/build_text_vector_db.py --csv path/to/contest_clauses.csv
  python scripts/build_text_vector_db.py --embed-only   # 仅重算向量，跳过聚类
  python scripts/build_text_vector_db.py --cluster-only # 仅对已存在 embeddings 聚类
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import numpy as np
import torch
from sklearn.cluster import MiniBatchKMeans

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

from llama_index.embeddings.huggingface import HuggingFaceEmbedding


def default_paths() -> Dict[str, Any]:
    return {
        "db_dir": os.path.join(ROOT, "data", "_vector_db", "contest_text_vector_db"),
        "model_name": os.environ.get("BGE_MODEL_PATH", "BAAI/bge-m3"),
        "csv_path": "",
        "text_column": "",
        "n_clusters": 32,
        "kmeans_batch_size": 256,
        "kmeans_max_iter": 100,
        "kmeans_random_state": 42,
        "fit_sample_size": 0,
    }


def _demo_rows() -> List[Dict[str, Any]]:
    """无 CSV 时内置的竞赛规程/FAQ 风格多字段片段（智能竞赛客服知识库）。"""
    return [
        {
            "doc_id": "REG-2025-01",
            "title": "报名与资格",
            "body": "参赛队须为在读本科生，每队不超过 5 人；报名截止时间为 2025-04-30 24:00，以官网报名系统提交成功时间为准。",
        },
        {
            "doc_id": "SUB-2025-02",
            "title": "作品提交",
            "body": "初赛需提交设计报告 PDF 与演示视频链接；报告不超过 30 页，视频时长 5～8 分钟，格式 MP4，大小不超过 500MB。",
        },
        {
            "doc_id": "TRK-2025-A",
            "title": "赛道 A 规则摘要",
            "body": "赛道 A 侧重算法创新与可复现性；禁止抄袭开源项目未注明出处；决赛采用线上答辩，需准备 10 分钟陈述与 5 分钟问答。",
        },
        {
            "doc_id": "JDG-2025-01",
            "title": "评审与奖项",
            "body": "评审维度包括创新性 40%、完成度 35%、展示与表达 25%；设特等奖、一等奖、二等奖及优秀组织奖，具体名额以组委会公示为准。",
        },
    ]


def load_rows_from_csv(csv_path: str, text_column: str) -> List[Dict[str, Any]]:
    import pandas as pd

    df = pd.read_csv(csv_path)
    rows: List[Dict[str, Any]] = []
    for i, row in df.iterrows():
        rec = {str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()}
        if text_column:
            text = rec.get(text_column, "")
        else:
            parts = [f"{k}：{v}" for k, v in rec.items() if str(v).strip()]
            text = " | ".join(parts)
        rec["_text"] = text
        rec["_row_index"] = int(i)
        rows.append(rec)
    return rows


def rows_to_documents(rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
    documents_meta: List[Dict[str, Any]] = []
    texts: List[str] = []
    for j, r in enumerate(rows):
        text = r.get("_text", "")
        meta = {k: v for k, v in r.items() if not k.startswith("_")}
        meta["id"] = j
        documents_meta.append(meta)
        texts.append(text)
    return documents_meta, texts


def embed_texts(model_name: str, texts: List[str], batch_size: int = 8) -> torch.Tensor:
    emb_model = HuggingFaceEmbedding(model_name=model_name, trust_remote_code=True)
    vecs: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        for t in chunk:
            vecs.append(emb_model.get_text_embedding(t))
        print(f"[build_text] embedded {min(i + batch_size, len(texts))}/{len(texts)}")
    t = torch.tensor(np.array(vecs, dtype=np.float32))
    t = torch.nn.functional.normalize(t, p=2, dim=-1)
    return t


def main() -> None:
    defaults = default_paths()
    p = argparse.ArgumentParser(description="Build local file-based text vector index (BGE + optional KMeans).")
    p.add_argument("--db-dir", default=defaults["db_dir"])
    p.add_argument("--model-name", default=defaults["model_name"], help="本地目录或 HuggingFace id，如 model/bge-m3")
    p.add_argument("--csv", default="", help="竞赛文本表 CSV（如规程片段）；不传则使用内置 4 条")
    p.add_argument("--text-column", default="", help="指定作为 embedding 的列名；空则拼接所有列")
    p.add_argument("--embed-batch-size", type=int, default=8)
    p.add_argument("--n-clusters", type=int, default=defaults["n_clusters"])
    p.add_argument("--cluster-only", action="store_true", help="仅对已存在的 embeddings.pt 做 KMeans")
    p.add_argument("--embed-only", action="store_true", help="只写向量与 json/jsonl，不写 kmeans")
    p.add_argument("--kmeans-batch-size", type=int, default=defaults["kmeans_batch_size"])
    p.add_argument("--kmeans-max-iter", type=int, default=defaults["kmeans_max_iter"])
    p.add_argument("--kmeans-random-state", type=int, default=defaults["kmeans_random_state"])
    p.add_argument("--fit-sample-size", type=int, default=defaults["fit_sample_size"])
    args = p.parse_args()

    os.makedirs(args.db_dir, exist_ok=True)
    embeddings_path = os.path.join(args.db_dir, "embeddings.pt")
    metadata_path = os.path.join(args.db_dir, "metadata.json")
    documents_path = os.path.join(args.db_dir, "documents.jsonl")

    if args.cluster_only:
        if not os.path.isfile(embeddings_path) or not os.path.isfile(metadata_path):
            raise FileNotFoundError(f"--cluster-only 需要已有 {embeddings_path} 与 {metadata_path}")
        embeddings = torch.load(embeddings_path, map_location="cpu").to(torch.float32)
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=-1)
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        if args.csv:
            rows = load_rows_from_csv(args.csv, args.text_column)
        else:
            rows = _demo_rows()
            for i, r in enumerate(rows):
                parts = [f"{k}：{v}" for k, v in r.items()]
                r["_text"] = " | ".join(parts)
                r["_row_index"] = i
        documents_meta, texts = rows_to_documents(rows)
        if not texts or not any(x.strip() for x in texts):
            raise RuntimeError("没有可编码的文本")

        print(f"[build_text] model={args.model_name!r}, docs={len(texts)}")
        embeddings = embed_texts(args.model_name, texts, batch_size=args.embed_batch_size)
        torch.save(embeddings, embeddings_path)

        with open(documents_path, "w", encoding="utf-8") as f:
            for m, t in zip(documents_meta, texts):
                f.write(json.dumps({"id": m["id"], "text": t}, ensure_ascii=False) + "\n")

        metadata = {
            "model_type": "bge-m3",
            "model_name": args.model_name,
            "num_docs": len(texts),
            "embedding_dim": int(embeddings.shape[-1]),
            "documents": documents_meta,
            "documents_jsonl": os.path.basename(documents_path),
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"[build_text] wrote {embeddings_path}, {metadata_path}, {documents_path}")

    if args.embed_only:
        print("[build_text] --embed-only：跳过 KMeans")
        return

    emb_np = embeddings.cpu().numpy()
    n_clusters = max(1, min(int(args.n_clusters), emb_np.shape[0]))
    fit_sample_size = int(args.fit_sample_size)
    if fit_sample_size and fit_sample_size < emb_np.shape[0]:
        rng = np.random.default_rng(args.kmeans_random_state)
        idx = rng.choice(emb_np.shape[0], size=fit_sample_size, replace=False)
        emb_fit = emb_np[idx]
    else:
        emb_fit = emb_np

    print(f"[build_text] MiniBatchKMeans: n_clusters={n_clusters}, fit_rows={emb_fit.shape[0]}")
    km = MiniBatchKMeans(
        n_clusters=n_clusters,
        batch_size=int(args.kmeans_batch_size),
        max_iter=int(args.kmeans_max_iter),
        random_state=int(args.kmeans_random_state),
        n_init="auto",
        verbose=0,
    )
    km.fit(emb_fit)
    labels = km.predict(emb_np).astype(np.int64)
    centers = km.cluster_centers_.astype(np.float32)
    centers_t = torch.from_numpy(centers)
    centers_t = torch.nn.functional.normalize(centers_t, p=2, dim=-1)

    c_path = os.path.join(args.db_dir, "kmeans_centers.pt")
    l_path = os.path.join(args.db_dir, "kmeans_labels.pt")
    torch.save(centers_t, c_path)
    torch.save(torch.from_numpy(labels), l_path)

    metadata["kmeans"] = {
        "n_clusters": n_clusters,
        "centers_path": os.path.basename(c_path),
        "labels_path": os.path.basename(l_path),
        "batch_size": int(args.kmeans_batch_size),
        "max_iter": int(args.kmeans_max_iter),
        "random_state": int(args.kmeans_random_state),
        "fit_sample_size": int(fit_sample_size),
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"[build_text] kmeans -> {c_path}, {l_path}, shape={tuple(embeddings.shape)}")


if __name__ == "__main__":
    main()
