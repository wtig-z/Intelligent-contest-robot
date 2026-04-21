"""
向量构建过程写库：在 ingestion / 管线中记录 pending → building → completed | failed。

依赖 Flask app_context + init_db（子进程内可用轻量 Flask 实例，无需加载完整 create_app）。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from backend.storage.db import db
from backend.models.vector_model import Vector


@contextmanager
def app_context_for_ingestion() -> Generator[None, None, None]:
    """供 ingestion.py、独立脚本使用：最小 Flask + init_db，避免拉满 create_app。"""
    from flask import Flask
    from backend.storage.db import init_db

    app = Flask(__name__)
    init_db(app)
    with app.app_context():
        yield


class VectorBuildTracker:
    """单次构建任务（如 colqwen 或 bge 全量）对应一行 vectors 记录。"""

    def __init__(self, vector_type: str, dataset: str, *, pdf_id: Optional[int] = None):
        self.vector_type = vector_type
        self.dataset = dataset or ""
        self.pdf_id = pdf_id
        self._row: Optional[Vector] = None

    @property
    def row(self) -> Optional[Vector]:
        return self._row

    def create_pending(self) -> Vector:
        v = Vector(
            vector_type=self.vector_type,
            dataset=self.dataset,
            file_path="",
            status="pending",
            progress=0,
            error_msg=None,
            pdf_id=self.pdf_id,
        )
        db.session.add(v)
        db.session.commit()
        self._row = v
        return v

    def ensure_row(self) -> Vector:
        if self._row is None:
            self.create_pending()
        assert self._row is not None
        return self._row

    def start_building(self) -> None:
        v = self.ensure_row()
        v.status = "building"
        v.progress = max(v.progress or 0, 10)
        db.session.commit()

    def update_progress(self, percent: int) -> None:
        v = self.ensure_row()
        v.status = "building"
        v.progress = max(0, min(100, int(percent)))
        db.session.commit()

    def build_success(self, file_path: str) -> None:
        v = self.ensure_row()
        v.status = "completed"
        v.progress = 100
        v.file_path = (file_path or "")[:512]
        v.error_msg = None
        db.session.commit()

    def build_failed(self, error_msg: str) -> None:
        v = self.ensure_row()
        v.status = "failed"
        v.error_msg = (error_msg or "")[:8000]
        db.session.commit()


def tracker_started(vector_type: str, dataset: str, *, pdf_id: Optional[int] = None) -> VectorBuildTracker:
    """创建并提交 pending 行，便于后续更新。"""
    t = VectorBuildTracker(vector_type, dataset, pdf_id=pdf_id)
    t.create_pending()
    return t
