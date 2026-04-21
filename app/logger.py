"""
统一日志模块（项目级日志规范入口）
- setup_logger: 初始化 root logger（工程标准 3 handler：控制台/全局按天/错误按天）
- LogInterceptor: 可选拦截 stdout/stderr 到缓冲区（用于 Web/API 查看）
- get_logs: 供 Web/API 读取日志
"""

import logging
import sys
from collections import deque
from datetime import datetime
from typing import List, Dict, Any, Optional

# 默认缓冲区容量
DEFAULT_CAPACITY = 300
_log_buffer: Optional[deque] = None
_original_stdout = None
_original_stderr = None


def _get_buffer():
    return _log_buffer


class _RingBufferLogHandler(logging.Handler):
    """把 logging 记录写入内存环形缓冲区，供 /api/admin/logs/buffer 查看。"""

    def __init__(self, capacity: int):
        super().__init__()
        self.capacity = capacity

    def emit(self, record: logging.LogRecord) -> None:
        buf = _get_buffer()
        if buf is None:
            return
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        if not msg:
            return
        buf.append({
            "t": datetime.now().isoformat(),
            "m": msg.rstrip(),
            "stream": "log",
        })
        cap = self.capacity
        while len(buf) > cap:
            buf.popleft()


class LogInterceptor:
    """包装 stdout/stderr，将输出写入内部缓冲区"""

    def __init__(self, stream_name: str, capacity: int = DEFAULT_CAPACITY):
        self.stream_name = stream_name
        self.capacity = capacity

    def write(self, msg: str):
        buf = _get_buffer()
        if msg and msg.strip() and buf is not None:
            buf.append({
                "t": datetime.now().isoformat(),
                "m": msg.rstrip(),
                "stream": self.stream_name,
            })
            cap = self.capacity
            while len(buf) > cap:
                buf.popleft()
        # 仍然输出到原始流
        if self.stream_name == "stdout" and _original_stdout:
            _original_stdout.write(msg)
            _original_stdout.flush()
        elif self.stream_name == "stderr" and _original_stderr:
            _original_stderr.write(msg)
            _original_stderr.flush()

    def flush(self):
        if self.stream_name == "stdout" and _original_stdout:
            _original_stdout.flush()
        elif self.stream_name == "stderr" and _original_stderr:
            _original_stderr.flush()


def setup_logger(
    log_level: str = "INFO",
    capacity: int = DEFAULT_CAPACITY,
    use_stdout: bool = True,
    intercept_streams: bool = False,
) -> None:
    """
    初始化日志
    :param log_level: INFO, DEBUG, WARNING, ERROR
    :param capacity: 缓冲区最大条数
    :param use_stdout: 是否输出到 stdout（否则 stderr）
    :param intercept_streams: 是否拦截 stdout/stderr
    """
    global _log_buffer, _original_stdout, _original_stderr

    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler
    for h in root.handlers[:]:
        root.removeHandler(h)

    # 先初始化缓冲区和拦截，再添加 Handler（这样 logging 输出也会走 buffer）
    global _log_buffer
    _log_buffer = deque(maxlen=capacity)
    if intercept_streams:
        global _original_stdout, _original_stderr
        _original_stdout = sys.stdout
        _original_stderr = sys.stderr
        sys.stdout = LogInterceptor("stdout", capacity)
        sys.stderr = LogInterceptor("stderr", capacity)

    # StreamHandler（控制台输出）
    stream = sys.stdout if use_stdout else sys.stderr
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)

    # 内存环形缓冲：无论是否拦截 stdout/stderr，都能拿到 logging 输出
    ring = _RingBufferLogHandler(capacity=capacity)
    ring.setLevel(level)
    ring.setFormatter(fmt)
    root.addHandler(ring)

    # 文件日志：主日志 + 错误日志（按天文件名）
    try:
        from config.logger_config import setup_file_logging, setup_frontend_file_logging
        setup_file_logging(log_level=log_level)
        setup_frontend_file_logging(log_level=log_level)
    except Exception as e:
        root.warning("文件日志初始化失败: %s", e)


def get_logs() -> List[Dict[str, Any]]:
    """返回缓冲区中的日志供 Web/API 读取"""
    global _log_buffer
    if _log_buffer is None:
        return []
    return list(_log_buffer)


def log_startup_warning(msg: str) -> None:
    """记录启动期警告"""
    logging.warning(msg)


def print_startup_warnings() -> None:
    """打印启动期警告（可在此集中检查配置等）"""
    import os
    if not os.getenv("DASHSCOPE_API_KEY"):
        log_startup_warning("未设置 DASHSCOPE_API_KEY，调用 LLM 将失败")
