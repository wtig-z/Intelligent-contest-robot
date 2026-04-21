#!/usr/bin/env python3
"""
生成“自研文件型向量库”产物



输出目录：
  data/_vector_db/courses_text_vector_db/
  data/_vector_db/colqwen2_vector_db/
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np
import torch
from sklearn.cluster import MiniBatchKMeans


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class KMeansConfig:
    n_clusters: int = 8
    batch_size: int = 256
    max_iter: int = 100
    random_state: int = 42


def l2_normalize(x: torch.Tensor) -> torch.Tensor:
    return torch.nn.functional.normalize(x.to(torch.float32), p=2, dim=-1)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def fit_kmeans(embeddings: torch.Tensor, cfg: KMeansConfig) -> tuple[torch.Tensor, torch.Tensor, Dict[str, Any]]:
    emb_np = embeddings.cpu().numpy().astype(np.float32)
    n = emb_np.shape[0]
    k = max(1, min(int(cfg.n_clusters), n))
    km = MiniBatchKMeans(
        n_clusters=k,
        batch_size=int(cfg.batch_size),
        max_iter=int(cfg.max_iter),
        random_state=int(cfg.random_state),
        n_init="auto",
        verbose=0,
    )
    km.fit(emb_np)
    labels = torch.from_numpy(km.predict(emb_np).astype(np.int64))
    centers = torch.from_numpy(km.cluster_centers_.astype(np.float32))
    centers = l2_normalize(centers)
    meta = {
        "n_clusters": int(k),
        "batch_size": int(cfg.batch_size),
        "max_iter": int(cfg.max_iter),
        "random_state": int(cfg.random_state),
    }
    return centers, labels, meta


def build_text_db(out_dir: Path, *, n_docs: int = 12, dim: int = 1024, kcfg: KMeansConfig) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # —— 模拟“竞赛规程/FAQ 条款块” —— #
    docs: List[Dict[str, Any]] = []
    docs_jsonl: List[Dict[str, Any]] = []
    base_rows = [
        ("REG-2025-01", "报名与资格", "参赛队须为在读本科生，每队不超过 5 人；报名截止以官网提交时间为准。"),
        ("SUB-2025-02", "作品提交", "初赛提交设计报告 PDF 与演示视频链接；报告不超过 30 页，视频 5～8 分钟。"),
        ("TRK-2025-A", "赛道规则", "赛道 A 侧重算法创新与可复现性；禁止抄袭且需注明引用来源。"),
        ("JDG-2025-01", "评审与奖项", "创新性 40%、完成度 35%、表达 25%；奖项名额以组委会公示为准。"),
        ("FAQ-2025-01", "常见问题", "是否允许跨校组队、报名信息修改方式、发票与证明开具流程等。"),
        ("UPD-2025-03", "补充通知", "更新了决赛答辩形式与时间安排，新增线上答辩注意事项与材料清单。"),
    ]
    while len(base_rows) < n_docs:
        i = len(base_rows) + 1
        base_rows.append((f"CL-{i:03d}", "条款补充", f"示例条款文本 {i}：用于展示向量库落盘结构与检索流程。"))
    rows = base_rows[:n_docs]

    for idx, (doc_id, title, body) in enumerate(rows):
        docs.append({"id": idx, "doc_id": doc_id, "title": title})
        docs_jsonl.append({"id": idx, "text": f"doc_id：{doc_id} | 标题：{title} | 内容：{body}"})

    # —— embeddings.pt（随机向量模拟，保持 L2）—— #
    g = torch.Generator().manual_seed(7)
    embeddings = torch.randn((n_docs, dim), generator=g, dtype=torch.float32)
    embeddings = l2_normalize(embeddings)
    torch.save(embeddings, out_dir / "embeddings.pt")

    # —— K-Means 粗筛索引 —— #
    centers, labels, km_meta = fit_kmeans(embeddings, kcfg)
    torch.save(centers, out_dir / "kmeans_centers.pt")
    torch.save(labels, out_dir / "kmeans_labels.pt")

    # —— 元数据 —— #
    write_json(out_dir / "metadata.json", {
        "db_type": "courses_text_vector_db",
        "domain": "contest_customer_service",
        "encoder": "BGE-M3 (local weights, simulated embeddings in this sample)",
        "num_docs": n_docs,
        "embedding_dim": dim,
        "documents": docs,
        "documents_jsonl": "documents.jsonl",
        "kmeans": {**km_meta, "centers_path": "kmeans_centers.pt", "labels_path": "kmeans_labels.pt"},
    })
    write_jsonl(out_dir / "documents.jsonl", docs_jsonl)

    # —— 仅作展示的 TFIDF vocab（不参与检索）—— #
    write_json(out_dir / "tfidf_vocab.json", {
        "note": "demo-only vocab for PPT/Thesis. not used in runtime search.",
        "tokens": ["报名", "截止", "提交", "评审", "奖项", "线上答辩", "材料清单"]
    })


def build_image_db(out_dir: Path, image_paths: List[str], *, dim: int = 1024, kcfg: KMeansConfig) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(image_paths)
    if n == 0:
        raise RuntimeError("no image_paths provided")

    g = torch.Generator().manual_seed(11)
    embeddings = torch.randn((n, dim), generator=g, dtype=torch.float32)
    embeddings = l2_normalize(embeddings)
    torch.save(embeddings, out_dir / "embeddings.pt")

    centers, labels, km_meta = fit_kmeans(embeddings, kcfg)
    torch.save(centers, out_dir / "kmeans_centers.pt")
    torch.save(labels, out_dir / "kmeans_labels.pt")

    write_json(out_dir / "metadata.json", {
        "db_type": "colqwen2_vector_db",
        "domain": "contest_customer_service",
        "encoder": "ColQwen2 (local weights, simulated embeddings in this sample)",
        "num_images": n,
        "embedding_dim": dim,
        "image_paths": image_paths,
        "kmeans": {**km_meta, "centers_path": "kmeans_centers.pt", "labels_path": "kmeans_labels.pt"},
    })


def main() -> None:
    base = ROOT / "data" / "_vector_db"
    text_dir = base / "courses_text_vector_db"
    img_dir = base / "colqwen2_vector_db"

    # 取项目现有数据集的前若干张页图做样例
    ds_img_dir = ROOT / "data" / "CompetitionDataset" / "img"
    img_paths = []
    if ds_img_dir.exists():
        for p in sorted(ds_img_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                img_paths.append(str(p))
            if len(img_paths) >= 12:
                break

    kcfg = KMeansConfig(n_clusters=6, batch_size=128, max_iter=80, random_state=42)
    build_text_db(text_dir, n_docs=12, dim=1024, kcfg=kcfg)
    if img_paths:
        build_image_db(img_dir, img_paths, dim=1024, kcfg=kcfg)

    print("[ok] wrote sample vector db to:")
    print(" -", text_dir)
    print(" -", img_dir if img_paths else "(skipped image db; no images found)")


if __name__ == "__main__":
    main()

