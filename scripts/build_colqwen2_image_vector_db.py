#!/usr/bin/env python3
"""
本地文件型「图像向量库」建库（ColQwen2 编码 + 可选 MiniBatchKMeans 粗筛索引）。

默认输出目录：data/_vector_db/colqwen2_vector_db/
  - embeddings.pt / metadata.json
  - kmeans_centers.pt / kmeans_labels.pt

环境变量（可选）：
  COLQWEN2_CUDA_INDEX   默认 0
  VECTOR_DB_IMAGE_DIR / VECTOR_COLQWEN_DB_DIR / COLQWEN2_MODEL_BASE / COLQWEN2_LORA

用法：
  python scripts/build_colqwen2_image_vector_db.py --image-dir data/CompetitionDataset/img
  python scripts/build_colqwen2_image_vector_db.py --cluster-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image
from sklearn.cluster import MiniBatchKMeans

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

from colpali_engine.models import ColQwen2, ColQwen2Processor


SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def get_build_config() -> dict:
    img_default = os.path.join(ROOT, "data", "CompetitionDataset", "img")
    db_default = os.path.join(ROOT, "data", "_vector_db", "colqwen2_vector_db")
    return {
        "image_dir": os.environ.get("VECTOR_DB_IMAGE_DIR", img_default),
        "db_dir": os.environ.get("VECTOR_COLQWEN_DB_DIR", db_default),
        "model_base_path": os.environ.get(
            "COLQWEN2_MODEL_BASE", "vidore/colqwen2-v1.0"
        ),
        "model_lora_path": os.environ.get(
            "COLQWEN2_LORA", "Qwen/Qwen2-VL-2B-Instruct"
        ),
        "cuda_index": int(os.environ.get("COLQWEN2_CUDA_INDEX", "0")),
        "batch_size": int(os.environ.get("COLQWEN2_BATCH_SIZE", "4")),
        "cluster_only": False,
        "n_clusters": 32,
        "kmeans_batch_size": 512,
        "kmeans_max_iter": 200,
        "kmeans_random_state": 42,
        "fit_sample_size": 0,
    }


def list_images(image_dir: str) -> List[str]:
    paths: List[str] = []
    for root, _, files in os.walk(image_dir):
        for name in files:
            if name.lower().endswith(SUPPORTED_IMAGE_EXTS):
                paths.append(os.path.join(root, name))
    paths.sort()
    return paths


def load_rgb_image(path: str) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGB").copy()


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


def encode_image_embeddings(
    model: ColQwen2,
    processor: ColQwen2Processor,
    image_paths: List[str],
    batch_size: int,
) -> torch.Tensor:
    all_embs: List[torch.Tensor] = []
    with torch.no_grad():
        for i in range(0, len(image_paths), batch_size):
            batch_paths = image_paths[i : i + batch_size]
            images = [load_rgb_image(p) for p in batch_paths]
            batch_images = processor.process_images(images).to(model.device)
            outputs = model(**batch_images)
            emb = outputs.mean(dim=1) if outputs.ndim == 3 else outputs
            emb = torch.nn.functional.normalize(emb, p=2, dim=-1)
            all_embs.append(emb.detach().cpu().to(torch.float32))
            print(f"[build_vl] images {min(i + batch_size, len(image_paths))}/{len(image_paths)}")
    return torch.cat(all_embs, dim=0)


def main() -> None:
    cfg = get_build_config()
    parser = argparse.ArgumentParser(description="Build ColQwen2 image vector index (local files + KMeans).")
    parser.add_argument("--cuda-index", type=int, default=None)
    parser.add_argument("--image-dir", default=None)
    parser.add_argument("--db-dir", default=None)
    parser.add_argument("--model-base", default=None)
    parser.add_argument("--model-lora", default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--cluster-only", action="store_true")
    parser.add_argument("--embed-only", action="store_true", help="只写向量与 metadata，不写 KMeans")
    parser.add_argument("--n-clusters", type=int, default=None)
    parser.add_argument("--kmeans-batch-size", type=int, default=None)
    parser.add_argument("--kmeans-max-iter", type=int, default=None)
    parser.add_argument("--kmeans-random-state", type=int, default=None)
    parser.add_argument("--fit-sample-size", type=int, default=None)
    args = parser.parse_args()

    if args.cuda_index is not None:
        cfg["cuda_index"] = args.cuda_index
    if args.image_dir:
        cfg["image_dir"] = args.image_dir
    if args.db_dir:
        cfg["db_dir"] = args.db_dir
    if args.model_base:
        cfg["model_base_path"] = args.model_base
    if args.model_lora:
        cfg["model_lora_path"] = args.model_lora
    if args.batch_size is not None:
        cfg["batch_size"] = args.batch_size
    if args.cluster_only:
        cfg["cluster_only"] = True
    if args.n_clusters is not None:
        cfg["n_clusters"] = args.n_clusters
    if args.kmeans_batch_size is not None:
        cfg["kmeans_batch_size"] = args.kmeans_batch_size
    if args.kmeans_max_iter is not None:
        cfg["kmeans_max_iter"] = args.kmeans_max_iter
    if args.kmeans_random_state is not None:
        cfg["kmeans_random_state"] = args.kmeans_random_state
    if args.fit_sample_size is not None:
        cfg["fit_sample_size"] = args.fit_sample_size

    os.makedirs(cfg["db_dir"], exist_ok=True)
    embeddings_path = os.path.join(cfg["db_dir"], "embeddings.pt")
    metadata_path = os.path.join(cfg["db_dir"], "metadata.json")
    device = torch.device(f"cuda:{cfg['cuda_index']}" if torch.cuda.is_available() else "cpu")
    print(f"[build_vl] device={device}")

    if cfg["cluster_only"]:
        if not os.path.isfile(embeddings_path) or not os.path.isfile(metadata_path):
            raise FileNotFoundError(f"--cluster-only 需要 {embeddings_path} 与 {metadata_path}")
        print(f"[build_vl] cluster-only, load {embeddings_path}")
        embeddings = torch.load(embeddings_path, map_location="cpu").to(torch.float32)
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=-1)
        with open(metadata_path, encoding="utf-8") as f:
            metadata_base = json.load(f)
        image_paths = metadata_base["image_paths"]
        if embeddings.shape[0] != len(image_paths):
            raise RuntimeError("embeddings 行数与 image_paths 不一致")
    else:
        image_paths = list_images(cfg["image_dir"])
        if not image_paths:
            raise RuntimeError(f"目录下无图片: {cfg['image_dir']}")
        print(f"[build_vl] found {len(image_paths)} images under {cfg['image_dir']!r}")
        model, processor = load_model_and_processor(
            cfg["model_base_path"], cfg["model_lora_path"], device
        )
        embeddings = encode_image_embeddings(model, processor, image_paths, int(cfg["batch_size"]))
        torch.save(embeddings, embeddings_path)
        metadata_base = {
            "model_type": "colqwen2",
            "model_base_path": cfg["model_base_path"],
            "model_lora_path": cfg["model_lora_path"],
            "image_dir": cfg["image_dir"],
            "num_images": len(image_paths),
            "embedding_dim": int(embeddings.shape[-1]),
            "image_paths": image_paths,
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata_base, f, ensure_ascii=False, indent=2)
        print(f"[build_vl] wrote {embeddings_path}, {metadata_path}")

    if args.embed_only:
        print("[build_vl] --embed-only，跳过 KMeans")
        return

    emb_np = embeddings.cpu().numpy()
    n_clusters = max(1, min(int(cfg["n_clusters"]), emb_np.shape[0]))
    fit_sample_size = int(cfg["fit_sample_size"])
    if fit_sample_size and fit_sample_size < emb_np.shape[0]:
        rng = np.random.default_rng(int(cfg["kmeans_random_state"]))
        idx = rng.choice(emb_np.shape[0], size=fit_sample_size, replace=False)
        emb_fit = emb_np[idx]
    else:
        emb_fit = emb_np

    print(f"[build_vl] MiniBatchKMeans n_clusters={n_clusters}, fit_rows={emb_fit.shape[0]}")
    kmeans = MiniBatchKMeans(
        n_clusters=n_clusters,
        batch_size=int(cfg["kmeans_batch_size"]),
        max_iter=int(cfg["kmeans_max_iter"]),
        random_state=int(cfg["kmeans_random_state"]),
        n_init="auto",
        verbose=0,
    )
    kmeans.fit(emb_fit)
    labels = kmeans.predict(emb_np).astype(np.int64)
    centers = torch.from_numpy(kmeans.cluster_centers_.astype(np.float32))
    centers = torch.nn.functional.normalize(centers, p=2, dim=-1)

    centers_path = os.path.join(cfg["db_dir"], "kmeans_centers.pt")
    labels_path = os.path.join(cfg["db_dir"], "kmeans_labels.pt")
    torch.save(centers, centers_path)
    torch.save(torch.from_numpy(labels), labels_path)

    metadata_base["kmeans"] = {
        "n_clusters": n_clusters,
        "centers_path": os.path.basename(centers_path),
        "labels_path": os.path.basename(labels_path),
        "batch_size": int(cfg["kmeans_batch_size"]),
        "max_iter": int(cfg["kmeans_max_iter"]),
        "random_state": int(cfg["kmeans_random_state"]),
        "fit_sample_size": int(fit_sample_size),
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata_base, f, ensure_ascii=False, indent=2)

    print(f"[build_vl] kmeans -> {centers_path}, {labels_path}, emb_shape={tuple(embeddings.shape)}")


if __name__ == "__main__":
    main()
