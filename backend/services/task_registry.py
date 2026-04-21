"""
问答任务注册表：并发槽位、运行中任务、历史记录、管理员强制取消。
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

from backend.services.cancel_registry import cancel as cancel_request

_MAX_HISTORY = int(os.getenv("QA_TASK_HISTORY_MAX", "500"))
_DEFAULT_MAX_CONCURRENT = int(os.getenv("QA_MAX_CONCURRENT", "4"))

_lock = threading.Lock()
_running: Dict[str, Dict[str, Any]] = {}
_history: deque = deque(maxlen=_MAX_HISTORY)
_semaphore = threading.BoundedSemaphore(value=max(1, _DEFAULT_MAX_CONCURRENT))


def max_concurrent() -> int:
    return max(1, _DEFAULT_MAX_CONCURRENT)


def available_slots() -> int:
    """近似可用槽位（BoundedSemaphore 无官方查询，用计数器维护）。"""
    with _lock:
        return max(0, max_concurrent() - len(_running))


def acquire_qa_slot(blocking: bool = True, timeout: Optional[float] = None) -> bool:
    """获取一个问答并发槽位。timeout 为 None 时行为与 blocking 一致。"""
    if timeout is not None:
        return _semaphore.acquire(blocking=True, timeout=timeout)
    return _semaphore.acquire(blocking=blocking)


def release_qa_slot() -> None:
    try:
        _semaphore.release()
    except ValueError:
        pass


def register_running(
    request_id: str,
    *,
    user_id: Optional[int],
    username: Optional[str],
    message_preview: str,
    pdf_name: Optional[str],
    phase: str = "qa",
) -> None:
    rid = (request_id or "").strip()
    if not rid:
        return
    with _lock:
        _running[rid] = {
            "request_id": rid,
            "user_id": user_id,
            "username": username or "",
            "message_preview": (message_preview or "")[:200],
            "pdf_name": pdf_name or "",
            "phase": phase,
            "started_at": time.time(),
        }


def update_phase(request_id: Optional[str], phase: str) -> None:
    rid = (request_id or "").strip()
    if not rid:
        return
    with _lock:
        if rid in _running:
            _running[rid]["phase"] = phase


def finish_running(
    request_id: Optional[str],
    *,
    status: str,
    error: Optional[str] = None,
    duration_ms: Optional[float] = None,
    engine_source: str = "",
    interrupted: bool = False,
) -> None:
    rid = (request_id or "").strip()
    rec: Optional[Dict[str, Any]] = None
    with _lock:
        rec = _running.pop(rid, None)
    if not rec and not rid:
        return
    started = (rec or {}).get("started_at") or time.time()
    dur = duration_ms
    if dur is None:
        dur = (time.time() - started) * 1000.0
    entry = {
        "request_id": rid or "(unknown)",
        "user_id": (rec or {}).get("user_id"),
        "username": (rec or {}).get("username", ""),
        "message_preview": (rec or {}).get("message_preview", ""),
        "pdf_name": (rec or {}).get("pdf_name", ""),
        "status": status,
        "error": (error or "")[:500] if error else "",
        "duration_ms": round(dur, 2),
        "engine_source": engine_source,
        "interrupted": bool(interrupted),
        "finished_at": time.time(),
    }
    with _lock:
        _history.appendleft(entry)


def list_running() -> List[Dict[str, Any]]:
    with _lock:
        out = []
        now = time.time()
        for v in _running.values():
            item = dict(v)
            item["elapsed_sec"] = round(now - float(item.get("started_at", now)), 2)
            out.append(item)
        return out


def list_history(limit: int = 100) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit), _MAX_HISTORY))
    with _lock:
        return list(_history)[:lim]


def admin_cancel(request_id: str) -> bool:
    """标记取消并尝试让正在执行的流程退出。"""
    rid = (request_id or "").strip()
    if not rid:
        return False
    cancel_request(rid)
    with _lock:
        return rid in _running


def user_cancel_own_request(request_id: str, user_id: Optional[Any]) -> bool:
    """当前用户取消自己正在进行的问答（非管理端）。"""
    rid = (request_id or "").strip()
    if not rid:
        return False
    with _lock:
        rec = _running.get(rid)
        if rec is None:
            return False
        if user_id is not None and str(rec.get("user_id")) != str(user_id):
            return False
    cancel_request(rid)
    return True
