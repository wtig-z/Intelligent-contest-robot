"""
请求取消注册表（线程安全）。

目标：当用户发起新问题 B 时，前端会把 A 的 request_id 作为 cancel_request_id 传给后端；
后端将其标记为 cancelled，正在执行 A 的流程在关键循环/阶段检查到后立即退出。
"""

from __future__ import annotations

import threading
import time
from typing import Optional


class CancelledError(RuntimeError):
    pass


_lock = threading.Lock()
_cancelled: dict[str, float] = {}  # request_id -> cancel_ts
_TTL_SECONDS = 60 * 30  # 30分钟后自动清理，防止无限增长


def cancel(request_id: Optional[str]) -> None:
    rid = (request_id or "").strip()
    if not rid:
        return
    with _lock:
        # opportunistic cleanup
        now = time.time()
        expired = [k for k, ts in _cancelled.items() if now - ts > _TTL_SECONDS]
        for k in expired:
            _cancelled.pop(k, None)
        _cancelled[rid] = time.time()


def is_cancelled(request_id: Optional[str]) -> bool:
    rid = (request_id or "").strip()
    if not rid:
        return False
    with _lock:
        return rid in _cancelled


def raise_if_cancelled(request_id: Optional[str]) -> None:
    if is_cancelled(request_id):
        raise CancelledError(f"request cancelled: {request_id}")

