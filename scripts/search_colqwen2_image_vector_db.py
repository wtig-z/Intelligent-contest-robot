#!/usr/bin/env python3
"""
对 build_colqwen2_image_vector_db.py 产出的图像向量库做文本→图像检索。

可选 KMeans：先 query 与簇中心相似度取 top 簇，再簇内与全量向量精排；否则全库点积。

用法：
  python scripts/search_colqwen2_image_vector_db.py --query "报名表格式" --top-k 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

from colpali_engine.models import ColQwen2, ColQwen2Processor


def default_db_dir() -> str:
    return os.path.join(ROOT, "data", "_vector_db", "colqwen2_vector_db")


def load_model_and_processor(
    model_base_path: str, model_lora_path: str, device: torch.device
) -> Tuple[ColQwen2, ColQwen2Processor]:
    model_kwargs = {
        "torch_dtype": torch.bfloat16 if device.type == "cuda" else torch.float32,
    }
    if device.type == "cuda":
        model_kwargs["device_map"] = {"": device.index or 0}
    model = ColQwen2.from_pretrained(model_base_path, **model_kwargs).eval()
    processor = ColQwen2Processor.from_pretrained(model_lora_path)
    return model, processor


def encode_query(
    model: ColQwen2, processor: ColQwen2Processor, query: str
) -> torch.Tensor:
    with torch.no_grad():
        batch_queries = processor.process_queries([query]).to(model.device)
        outputs = model(**batch_queries)
        emb = outputs.mean(dim=1) if outputs.ndim == 3 else outputs
        emb = torch.nn.functional.normalize(emb, p=2, dim=-1)
    return emb[0].detach().cpu().to(torch.float32)


def main() -> None:
    p = argparse.ArgumentParser(description="Search ColQwen2 image vector index.")
    p.add_argument("--db-dir", default=default_db_dir())
    p.add_argument("--query", default="赛事说明 表格")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--top-clusters", type=int, default=3, help="0=禁用 KMeans，全库扫描")
    p.add_argument("--no-kmeans", action="store_true", help="全库扫描，不用簇中心粗筛")
    p.add_argument("--model-base", default="")
    p.add_argument("--model-lora", default="")
    p.add_argument("--cuda-index", type=int, default=int(os.environ.get("COLQWEN2_CUDA_INDEX", "0")))
    args = p.parse_args()
    use_kmeans = not bool(args.no_kmeans)

    embeddings_path = os.path.join(args.db_dir, "embeddings.pt")
    metadata_path = os.path.join(args.db_dir, "metadata.json")
    if not os.path.isfile(embeddings_path) or not os.path.isfile(metadata_path):
        raise FileNotFoundError(
            f"缺少向量库文件：{embeddings_path} 或 {metadata_path}，请先运行 build_colqwen2_image_vector_db.py"
        )

    with open(metadata_path, encoding="utf-8") as f:
        metadata: Dict[str, Any] = json.load(f)

    model_base = args.model_base or metadata.get("model_base_path", "")
    model_lora = args.model_lora or metadata.get("model_lora_path", "")
    embeddings = torch.load(embeddings_path, map_location="cpu").to(torch.float32)
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=-1)
    image_paths = metadata["image_paths"]
    if embeddings.shape[0] != len(image_paths):
        raise RuntimeError("embeddings 与 image_paths 数量不一致")

    device = torch.device(f"cuda:{args.cuda_index}" if torch.cuda.is_available() else "cpu")
    print(f"[search_vl] device={device}, query={args.query!r}, N={len(image_paths)}")

    model, processor = load_model_and_processor(model_base, model_lora, device)
    q_emb = encode_query(model, processor, args.query)

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
            raise RuntimeError("KMeans 候选为空")
        print(f"[search_vl] kmeans top_clusters={tc}, candidates={cand.numel()}")
        scores = torch.matmul(embeddings[cand], q_emb)
        tk = min(int(args.top_k), scores.shape[0])
        top_scores, top_local = torch.topk(scores, k=tk, dim=0)
        top_indices = cand[top_local]
    else:
        print("[search_vl] full scan")
        scores = torch.matmul(embeddings, q_emb)
        tk = min(int(args.top_k), scores.shape[0])
        top_scores, top_indices = torch.topk(scores, k=tk, dim=0)

    print("\n[search_vl] top results:")
    for rank, (idx, sc) in enumerate(zip(top_indices.tolist(), top_scores.tolist()), start=1):
        print(f"{rank:>2}. score={sc:.6f}  {image_paths[int(idx)]}")


if __name__ == "__main__":
    main()
