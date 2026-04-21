"""
项目统一日志对外入口（供所有模块 import 使用）。

使用示例：
from project_logger import model_logger, data_logger, api_logger

model_logger.info("开始加载模型")
data_logger.warning("存在缺失值")
api_logger.error("调用第三方 API 失败", exc_info=True)
"""

from __future__ import annotations

import logging

from app.logger import setup_logger

_initialized = False


def init_logging(log_level: str = "INFO") -> None:
    """幂等初始化（工程标准 3 个 handler）。"""
    global _initialized
    if _initialized:
        return
    setup_logger(log_level=log_level, intercept_streams=False)
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    init_logging()
    return logging.getLogger(name)


# 统一模块名（对应日志格式中的 [模块名]）
model_logger = get_logger("model")
data_logger = get_logger("data")
api_logger = get_logger("api")
algo_logger = get_logger("algo")
frontend_logger = get_logger("frontend")
backend_logger = get_logger("backend")

