"""
项目统一日志规范（按天、可检索、排查不切换）。

日志体系（工程标准：3 个 handler）：
- StreamHandler -> 控制台（开发调试）
- TimedRotatingFileHandler -> 全局按天日志（INFO/WARNING/ERROR）
- TimedRotatingFileHandler -> 全局错误按天日志（仅 ERROR）

文件命名：
- logs/contest_robot_YYYY-MM-DD.log
- logs/contest_robot_error_YYYY-MM-DD.log

日志格式（plaintext）：
[时间] [级别] [模块名] 内容
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_CONFIG_DIR)
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

PROJECT_NAME = "contest_robot"
FRONTEND_LOGGER_NAME = f"{PROJECT_NAME}.frontend"
FRONTEND_PROJECT_NAME = f"{PROJECT_NAME}_frontend"


def _ensure_dirs() -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _main_log_path(date_str: str | None = None) -> str:
    ds = date_str or _today_str()
    return os.path.join(LOGS_DIR, f"{PROJECT_NAME}_{ds}.log")


def _error_log_path(date_str: str | None = None) -> str:
    ds = date_str or _today_str()
    return os.path.join(LOGS_DIR, f"{PROJECT_NAME}_error_{ds}.log")


def _frontend_main_log_path(date_str: str | None = None) -> str:
    ds = date_str or _today_str()
    return os.path.join(LOGS_DIR, f"{FRONTEND_PROJECT_NAME}_{ds}.log")


def _frontend_error_log_path(date_str: str | None = None) -> str:
    ds = date_str or _today_str()
    return os.path.join(LOGS_DIR, f"{FRONTEND_PROJECT_NAME}_error_{ds}.log")


MAIN_LOG_PATH = _main_log_path()
ERROR_LOG_PATH = _error_log_path()


class DailyTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler 的“按天文件名”实现：
    - 当前文件名本身带日期后缀（满足“一天一个文件”）
    - 到午夜切换到新日期文件，不依赖 rename old file
    """

    def __init__(self, path_fn, **kwargs):
        self._path_fn = path_fn
        super().__init__(filename=path_fn(), when="midnight", interval=1, **kwargs)

    def doRollover(self) -> None:
        if self.stream:
            try:
                self.stream.close()
            finally:
                self.stream = None
        # 切换到新日期文件
        self.baseFilename = os.path.abspath(self._path_fn())
        current_time = int(time.time())
        self.rolloverAt = self.computeRollover(current_time)
        if not self.delay:
            self.stream = self._open()


def setup_file_logging(
    log_level: str = "INFO",
    backup_count: int = 30,
) -> None:
    """
    为 root logger 添加文件 Handler（按天文件名）：
    - 主日志：logs/contest_robot_YYYY-MM-DD.log（INFO/WARNING/ERROR）
    - 错误日志：logs/contest_robot_error_YYYY-MM-DD.log（仅 ERROR）
    """
    _ensure_dirs()
    level = getattr(logging, log_level.upper(), logging.INFO)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 主日志：按天一个文件
    main_handler = DailyTimedRotatingFileHandler(
        _main_log_path,
        backupCount=backup_count,
        encoding="utf-8",
    )
    main_handler.setLevel(level)
    main_handler.setFormatter(fmt)

    # 错误日志：仅 ERROR
    error_handler = DailyTimedRotatingFileHandler(
        _error_log_path,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(main_handler)
    root.addHandler(error_handler)


def get_logger(name: str) -> logging.Logger:
    """获取带名称的 logger，写入会进入主日志/错误日志。"""
    return logging.getLogger(name)


def setup_frontend_file_logging(
    log_level: str = "INFO",
    backup_count: int = 30,
) -> None:
    """
    前端工程化日志（独立文件体系，格式/切割规则与后端对齐）：
    - logs/contest_robot_frontend_YYYY-MM-DD.log（INFO/WARNING/ERROR）
    - logs/contest_robot_frontend_error_YYYY-MM-DD.log（仅 ERROR）
    """
    _ensure_dirs()
    level = getattr(logging, log_level.upper(), logging.INFO)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    main_handler = DailyTimedRotatingFileHandler(
        _frontend_main_log_path,
        backupCount=backup_count,
        encoding="utf-8",
    )
    main_handler.setLevel(level)
    main_handler.setFormatter(fmt)

    error_handler = DailyTimedRotatingFileHandler(
        _frontend_error_log_path,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    logger = logging.getLogger(FRONTEND_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    if not any(isinstance(h, DailyTimedRotatingFileHandler) for h in logger.handlers):
        logger.addHandler(main_handler)
        logger.addHandler(error_handler)
