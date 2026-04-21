"""
GraphRAG 服务 —— 全部通过 _lib vendored 包调用 Python API（零外部依赖）。

- build_index: 通过 graphrag.api.build_index() 构建知识图谱索引
- search: 通过 graphrag.api 的各级检索 API 查询
"""
import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

from config.app_config import DEFAULT_DATASET
from config.logger_config import LOGS_DIR
from config.paths import get_graphrag_dir

logger = logging.getLogger("contest_robot.graphrag")

# ── 确保 _lib 在 sys.path 中 ─────────────────────────────────
_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# ── 延迟导入 ──────────────────────────────────────────────────
_gapi = None
_load_cfg = None
_create_storage = None
_create_tp = None
_DataReader = None
_IndexingMethod = None


def _ensure_imports():
    global _gapi, _load_cfg, _create_storage, _create_tp, _DataReader, _IndexingMethod
    if _gapi is not None:
        return

    import graphrag.api as gapi
    from graphrag.config.load_config import load_config
    from graphrag.config.enums import IndexingMethod
    from graphrag_storage import create_storage
    from graphrag_storage.tables.table_provider_factory import create_table_provider
    from graphrag.data_model.data_reader import DataReader

    _gapi = gapi
    _load_cfg = load_config
    _create_storage = create_storage
    _create_tp = create_table_provider
    _DataReader = DataReader
    _IndexingMethod = IndexingMethod


# ── 辅助函数 ──────────────────────────────────────────────────

def _root_dir(dataset: str, contest_id: Optional[str] = None) -> Path:
    base = Path(get_graphrag_dir(dataset))
    return base / contest_id if contest_id else base


def _resolve_root(dataset: str, contest_id: Optional[str] = None) -> Path:
    """
    解析实际可用 root：
    - 指定 contest_id 且目录存在：用赛事子目录
    - 指定 contest_id 但目录不存在：回退到全量目录（避免后台误报“未构建”）
    - 未指定：用全量目录
    """
    if contest_id:
        croot = _root_dir(dataset, contest_id)
        if croot.exists():
            return croot
    return _root_dir(dataset, None)


def _config(root: Path, data_dir: Optional[Path] = None):
    _ensure_imports()
    overrides: dict[str, Any] = {
        # 将 GraphRAG 内部 workflow 报告日志集中到项目统一日志目录
        "reporting": {"base_dir": str(LOGS_DIR)},
    }
    if data_dir:
        overrides["output_storage"] = {"base_dir": str(data_dir)}
    return _load_cfg(root_dir=root, cli_overrides=overrides)


def _tables(cfg, names: list[str], optional: list[str] | None = None) -> dict[str, Any]:
    _ensure_imports()
    storage = _create_storage(cfg.output_storage)
    tp = _create_tp(cfg.table_provider, storage=storage)
    reader = _DataReader(tp)
    out: dict[str, Any] = {}
    for n in names:
        out[n] = asyncio.run(getattr(reader, n)())
    for n in (optional or []):
        out[n] = asyncio.run(getattr(reader, n)()) if asyncio.run(tp.has(n)) else None
    return out


# ═══════════════════════════════════════════════════════════════
#  GraphRAGService
# ═══════════════════════════════════════════════════════════════

class GraphRAGService:
    """对外服务类：通过 _lib vendored 包提供索引构建与查询能力。"""

    def __init__(self, dataset: Optional[str] = None):
        self._ds = dataset or DEFAULT_DATASET

    # ── 索引构建 (Python API) ──────────────────────────────────

    def build_index(self, contest_id: Optional[str] = None,
                    method: str = "standard") -> dict:
        """通过 graphrag.api.build_index() 构建索引。"""
        _ensure_imports()
        root = _root_dir(self._ds, contest_id)
        if not (root / "settings.yaml").exists() and not (root / "settings.yml").exists():
            return {"status": "error", "error": f"未找到配置: {root}/settings.yaml"}
        try:
            cfg = _config(root)
            results = asyncio.run(
                _gapi.build_index(config=cfg, method=_IndexingMethod(method))
            )
            failed = [r for r in results if getattr(r, "error", None)]
            errors = [r.workflow for r in failed]

            def _last_exception_line(err: Any) -> str:
                """尽量提取 traceback 的最后一条异常信息（如 ModuleNotFoundError: ...）。"""
                try:
                    if isinstance(err, BaseException):
                        # format_exception_only 返回形如 ['ModuleNotFoundError: ...\n']
                        lines = traceback.format_exception_only(type(err), err)
                        last = (lines[-1] if lines else str(err)).strip()
                        return last or str(err)
                    if isinstance(err, str):
                        return err.strip() or err
                    # 一些库会用自定义 error 类型，str() 通常包含最后一行信息
                    s = str(err).strip()
                    return s or repr(err)
                except Exception:
                    # 格式化 workflow 错误对象失败时仍需在日志里留痕；返回值仍描述原始 err
                    logger.warning(
                        "GraphRAG _last_exception_line 格式化失败: err_type=%s, err=%r",
                        type(err).__name__,
                        err,
                        exc_info=True,
                    )
                    return repr(err)

            error_msg = ""
            if failed:
                # 取第一个失败 workflow 的错误摘要（终端直接可见，便于快速定位）
                wf = failed[0].workflow
                err = failed[0].error
                error_msg = f"{wf}: {_last_exception_line(err)}"

            out = {"status": "error" if errors else "success",
                   "workflows": len(results), "errors": errors}
            if errors:
                out["error"] = error_msg or "索引构建失败（详见日志）"
            return out
        except Exception as e:
            logger.error("GraphRAG build failed: %s", e, exc_info=True)
            return {"status": "error", "error": str(e)}

    # ── 查询 ──────────────────────────────────────────────────

    def search(self, query: str, contest_id: Optional[str] = None,
               mode: str = "auto") -> dict:
        if mode == "auto":
            return self._auto(query, contest_id)
        try:
            root = _resolve_root(self._ds, contest_id)
            if not root.exists():
                return {"answer": "", "mode": mode, "status": "no_index"}
            cfg = _config(root)
            fn = {"basic": self._basic, "local": self._local,
                  "global": self._global, "drift": self._drift}.get(mode)
            if fn is None:
                return {"answer": "", "mode": mode, "status": "unknown_mode"}
            return fn(cfg, query)
        except Exception as e:
            logger.error("GraphRAG %s search failed: %s", mode, e, exc_info=True)
            return {"answer": "", "mode": mode, "status": "error", "error": str(e)}

    def _auto(self, query: str, cid: Optional[str]) -> dict:
        """auto 模式：basic 最稳最快，仅在 basic 失败时降级到 local。"""
        r = self.search(query, cid, mode="basic")
        if r.get("status") == "success" and r.get("answer"):
            return r
        r = self.search(query, cid, mode="local")
        if r.get("status") == "success" and r.get("answer"):
            return r
        return {"answer": "", "mode": "auto", "status": "all_failed"}

    # ── 各模式实现 ────────────────────────────────────────────

    def _basic(self, cfg, q: str) -> dict:
        _ensure_imports()
        t = _tables(cfg, ["text_units"])
        resp, _ = asyncio.run(_gapi.basic_search(
            config=cfg, text_units=t["text_units"],
            response_type="Multiple Paragraphs", query=q))
        return {"answer": resp if isinstance(resp, str) else str(resp),
                "mode": "basic", "status": "success" if resp else "empty"}

    def _local(self, cfg, q: str) -> dict:
        _ensure_imports()
        t = _tables(cfg,
                     ["entities", "communities", "community_reports",
                      "text_units", "relationships"],
                     optional=["covariates"])
        resp, _ = asyncio.run(_gapi.local_search(
            config=cfg, entities=t["entities"], communities=t["communities"],
            community_reports=t["community_reports"], text_units=t["text_units"],
            relationships=t["relationships"], covariates=t.get("covariates"),
            community_level=2, response_type="Multiple Paragraphs", query=q))
        return {"answer": resp if isinstance(resp, str) else str(resp),
                "mode": "local", "status": "success" if resp else "empty"}

    def _global(self, cfg, q: str) -> dict:
        _ensure_imports()
        t = _tables(cfg, ["entities", "communities", "community_reports"])
        resp, _ = asyncio.run(_gapi.global_search(
            config=cfg, entities=t["entities"], communities=t["communities"],
            community_reports=t["community_reports"],
            community_level=None, dynamic_community_selection=True,
            response_type="Multiple Paragraphs", query=q))
        return {"answer": resp if isinstance(resp, str) else str(resp),
                "mode": "global", "status": "success" if resp else "empty"}

    def _drift(self, cfg, q: str) -> dict:
        _ensure_imports()
        t = _tables(cfg,
                     ["entities", "communities", "community_reports",
                      "text_units", "relationships"])
        resp, _ = asyncio.run(_gapi.drift_search(
            config=cfg, entities=t["entities"], communities=t["communities"],
            community_reports=t["community_reports"], text_units=t["text_units"],
            relationships=t["relationships"],
            community_level=2, response_type="Multiple Paragraphs", query=q))
        return {"answer": resp if isinstance(resp, str) else str(resp),
                "mode": "drift", "status": "success" if resp else "empty"}

    # ── 工具 ──────────────────────────────────────────────────

    def is_available(self, contest_id: Optional[str] = None) -> bool:
        root = _resolve_root(self._ds, contest_id)
        if not (root / "settings.yaml").exists() and not (root / "settings.yml").exists():
            return False
        try:
            cfg = _config(root)
            out = Path(cfg.output_storage.base_dir)
            if not out.is_absolute():
                out = root / out
            return out.exists() and any(out.iterdir())
        except Exception as e:
            # 过去这里静默 False 会导致“索引不可用”无法定位真实原因（如配置解析/权限/路径错误等）
            logger.warning("GraphRAG is_available 检查失败: root=%s, contest_id=%s, err=%s",
                           str(root), contest_id, str(e), exc_info=True)
            return False

    def get_stats(self, contest_id: Optional[str] = None) -> dict:
        root = _resolve_root(self._ds, contest_id)
        if not root.exists():
            return {"available": False}
        try:
            cfg = _config(root)
            t = _tables(cfg, ["entities", "communities", "community_reports",
                               "text_units", "relationships"])
            return {
                "available": True,
                "entities": len(t.get("entities", [])),
                "relationships": len(t.get("relationships", [])),
                "communities": len(t.get("communities", [])),
                "community_reports": len(t.get("community_reports", [])),
                "text_units": len(t.get("text_units", [])),
                "root_dir": str(root),
            }
        except Exception as e:
            logger.error(
                "GraphRAG get_stats 失败: root=%s, contest_id=%s, err=%s",
                str(root),
                contest_id,
                str(e),
                exc_info=True,
            )
            return {"available": False, "error": str(e)}

    def export_entities_relationships(
        self, contest_id: Optional[str] = None, *, include_embeddings: bool = False
    ) -> dict:
        """
        从 GraphRAG TableProvider 读取 entities / relationships 全表，
        导出为可 JSON 序列化的记录列表（默认去掉 embedding 列以控制体积）。
        """
        import json

        import pandas as pd

        root = _resolve_root(self._ds, contest_id)
        if not root.exists():
            return {"available": False, "error": "索引根目录不存在"}
        try:
            cfg = _config(root)
            t = _tables(cfg, ["entities", "relationships"])
        except Exception as e:
            logger.error("GraphRAG export_entities_relationships 加载失败: %s", e, exc_info=True)
            return {"available": False, "error": str(e)}

        def _df_records(df: Any) -> list:
            if df is None:
                return []
            if hasattr(df, "empty") and df.empty:
                return []
            if not include_embeddings:
                drop_cols = [c for c in df.columns if "embedding" in str(c).lower()]
                if drop_cols:
                    df = df.drop(columns=drop_cols, errors="ignore")
            try:
                return json.loads(df.to_json(orient="records", date_format="iso"))
            except Exception as json_exc:
                logger.warning(
                    "GraphRAG export: DataFrame.to_json 失败，已降级为 astype+to_dict（列类型可能含不可序列化值）",
                    exc_info=True,
                )
                out = df.astype(object).where(pd.notnull(df), None)
                return out.to_dict(orient="records")

        ent = t.get("entities")
        rel = t.get("relationships")
        return {
            "available": True,
            "root_dir": str(root),
            "dataset": self._ds,
            "contest_id": contest_id or "",
            "entity_count": len(ent) if ent is not None and hasattr(ent, "__len__") else 0,
            "relationship_count": len(rel) if rel is not None and hasattr(rel, "__len__") else 0,
            "include_embeddings": bool(include_embeddings),
            "entities": _df_records(ent),
            "relationships": _df_records(rel),
        }
