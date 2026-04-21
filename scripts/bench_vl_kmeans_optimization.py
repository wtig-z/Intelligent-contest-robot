"""
Benchmark: ViDoRAG VL brute-force vs K-Means coarse-to-fine optimization.

What we measure (engineering metrics, not model-quality claims):
- Latency: p50 / p95 per-query end-to-end VL retrieval time
- Speedup: brute_time / kmeans_time
- Agreement: TopK overlap with brute-force results (proxy for "same ranking")
- Scale visibility:
  - N: total VL nodes (images/pages) in corpus
  - M: candidate size after K-Means coarse filter (mean/p95)
  - M/N: coarse filter ratio (mean/p95)

Notes:
- This script benchmarks the *VL retrieval stage* only (image/page retrieval),
  not full QA generation.
- If your environment lacks torch/numpy/llama_index, install deps first.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import time
from typing import Any, Dict, List, Tuple


def _pctl(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    xs2 = sorted(xs)
    if p <= 0:
        return xs2[0]
    if p >= 100:
        return xs2[-1]
    k = int(round((p / 100.0) * (len(xs2) - 1)))
    return xs2[max(0, min(len(xs2) - 1, k))]


def _extract_ids(recall: Any, *, topk: int) -> List[str]:
    """
    Convert SearchEngine.search() return to stable identifiers.

    We prefer ImageNode.image_path; fallback to metadata filename.
    """
    ids: List[str] = []
    # SearchEngine.search may return dict via nodes2dict, or raw NodeWithScore list
    if isinstance(recall, dict) and "source_nodes" in recall:
        for item in recall.get("source_nodes")[:topk]:
            node = (item or {}).get("node") or {}
            # ImageNode path (VL)
            p = node.get("image_path")
            if p:
                ids.append(os.path.basename(str(p)))
                continue
            md = node.get("metadata") or {}
            fn = md.get("filename") or md.get("file_name")
            if fn:
                ids.append(os.path.basename(str(fn)))
                continue
            ids.append(json.dumps(node, ensure_ascii=False)[:120])
        return ids

    # Raw list of NodeWithScore
    try:
        for nws in list(recall)[:topk]:
            node = getattr(nws, "node", None)
            p = getattr(node, "image_path", None)
            if p:
                ids.append(os.path.basename(str(p)))
                continue
            md = getattr(node, "metadata", None) or {}
            fn = md.get("filename") or md.get("file_name")
            if fn:
                ids.append(os.path.basename(str(fn)))
                continue
            ids.append(str(node)[:120])
        return ids
    except Exception:
        return []


def _overlap(a: List[str], b: List[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / float(len(sa))


def _load_queries(path: str, limit: int) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    qs: List[str] = []
    # Accept either ["q1", ...] or [{"question": "..."} ...]
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                q = item.strip()
            elif isinstance(item, dict):
                q = str(item.get("question") or item.get("query") or item.get("q") or "").strip()
            else:
                q = ""
            if q:
                qs.append(q)
    if limit > 0:
        qs = qs[:limit]
    return qs


def _bench_once(engine, query: str, *, topk: int) -> Tuple[float, List[str]]:
    t0 = time.perf_counter()
    recall = engine.search(query)
    dt = (time.perf_counter() - t0) * 1000.0
    ids = _extract_ids(recall, topk=topk)
    return dt, ids


def _safe_len(x) -> int:
    try:
        return len(x)  # type: ignore[arg-type]
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="CompetitionDataset", help="Dataset name")
    ap.add_argument("--queries", default="qa_evaluation/mo/dataset.json", help="JSON queries path")
    ap.add_argument("--limit", type=int, default=50, help="Number of queries to benchmark")
    ap.add_argument("--shuffle", action="store_true", help="Shuffle queries before sampling")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=5, help="Warm-up queries count (excluded from stats)")
    ap.add_argument("--n_probe_clusters", type=int, default=8, help="K-Means n_probe_clusters for coarse filter")
    args = ap.parse_args()

    # Lazy import (so the script can print a clearer error if deps missing)
    try:
        from backend.vidorag.search_engine import SearchEngine, HybridSearchEngine  # type: ignore
    except Exception as e:
        print("[ERROR] import backend.vidorag.search_engine failed:", repr(e))
        print("        Please install runtime deps (torch/numpy/sklearn/llama_index) and run from repo root.")
        return 2

    qs = _load_queries(args.queries, args.limit if args.limit > 0 else 0)
    if not qs:
        print("[ERROR] No queries loaded from:", args.queries)
        return 2
    if args.shuffle:
        random.seed(args.seed)
        random.shuffle(qs)

    # --- Baseline: VL brute-force (SearchEngine with vidore VL path) ---
    brute = SearchEngine(
        dataset=args.dataset,
        node_dir_prefix="colqwen_ingestion",
        embed_model_name="vidore/colqwen2-v1.0",
    )
    brute.return_raw = False
    n_nodes = _safe_len(getattr(brute, "nodes", None))

    # --- Optimized: HybridSearchEngine with K-Means coarse-to-fine ---
    opt = HybridSearchEngine(
        dataset=args.dataset,
        node_dir_prefix_vl="colqwen_ingestion",
        node_dir_prefix_text="bge_ingestion",
        embed_model_name_vl="vidore/colqwen2-v1.0",
        embed_model_name_text="BAAI/bge-m3",
        topk=max(10, args.topk),
        gmm=False,
        use_kmeans=True,
    )

    # Override search() coarse params if needed (by mutating the loaded index)
    # We keep the implementation simple: n_probe_clusters is currently hardcoded in HybridSearchEngine.search().
    # If you want to benchmark different probes, adjust that constant in code or extend HybridSearchEngine.
    _ = args.n_probe_clusters  # kept for CLI symmetry

    # Warm-up (exclude)
    warm = min(max(args.warmup, 0), len(qs))
    for i in range(warm):
        q = qs[i]
        _bench_once(brute, q, topk=args.topk)
        _bench_once(opt, q, topk=args.topk)

    times_brute: List[float] = []
    times_opt: List[float] = []
    overlaps: List[float] = []
    cand_sizes: List[float] = []
    cand_ratios: List[float] = []

    for q in qs[warm:]:
        tb, ids_b = _bench_once(brute, q, topk=args.topk)
        to, ids_o = _bench_once(opt, q, topk=args.topk)
        times_brute.append(tb)
        times_opt.append(to)
        overlaps.append(_overlap(ids_b, ids_o))
        # Candidate stats: read from kmeans index directly to avoid instrumenting production code.
        try:
            km = getattr(opt, "_kmeans_vl", None)
            evl = getattr(opt, "engine_vl", None)
            if km and getattr(km, "is_loaded", False) and evl and hasattr(evl, "vector_embed_model"):
                qe = evl.vector_embed_model.embed_text(q)
                qe0 = qe[0] if isinstance(qe, (list, tuple)) else qe
                import numpy as np  # local import
                import torch  # local import

                if isinstance(qe0, torch.Tensor):
                    qe_flat = qe0.detach().float().flatten().cpu().numpy()
                else:
                    qe_flat = np.array(qe0, dtype=np.float32).flatten()
                approx = km.search(
                    qe_flat,
                    topk=max(args.topk * 8, 50),
                    n_probe_clusters=min(8, int(getattr(km, "n_clusters", 0) or 0) or 8),
                )
                m = float(len(approx))
                cand_sizes.append(m)
                cand_ratios.append(m / float(max(n_nodes, 1)))
        except Exception:
            pass

    def _summ(name: str, xs: List[float]) -> Dict[str, float]:
        return {
            f"{name}_p50_ms": _pctl(xs, 50),
            f"{name}_p95_ms": _pctl(xs, 95),
            f"{name}_mean_ms": statistics.mean(xs) if xs else 0.0,
        }

    out: Dict[str, Any] = {}
    out.update(_summ("brute", times_brute))
    out.update(_summ("kmeans", times_opt))
    out["speedup_p50"] = (out["brute_p50_ms"] / out["kmeans_p50_ms"]) if out["kmeans_p50_ms"] else 0.0
    out["speedup_p95"] = (out["brute_p95_ms"] / out["kmeans_p95_ms"]) if out["kmeans_p95_ms"] else 0.0
    out["topk_overlap_mean"] = statistics.mean(overlaps) if overlaps else 0.0
    out["topk_overlap_p50"] = _pctl(overlaps, 50)
    out["topk_overlap_p95"] = _pctl(overlaps, 95)
    out["vl_nodes_N"] = int(n_nodes)
    out["candidates_M_mean"] = statistics.mean(cand_sizes) if cand_sizes else 0.0
    out["candidates_M_p95"] = _pctl(cand_sizes, 95) if cand_sizes else 0.0
    out["candidate_ratio_mean"] = statistics.mean(cand_ratios) if cand_ratios else 0.0
    out["candidate_ratio_p95"] = _pctl(cand_ratios, 95) if cand_ratios else 0.0
    out["n_queries"] = max(0, len(qs) - warm)
    out["topk"] = args.topk
    out["dataset"] = args.dataset

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

