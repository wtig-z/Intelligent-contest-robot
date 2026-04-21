"""
GraphRAG 知识图谱构建脚本（全 Python API，无外部 CLI 依赖）。

完整管线（3 步）：
  1. 双层 OCR 融合 → unified_text/   (merge_ocr.py)
  2. 页级文本拼接为文档级 → graphrag/input/ (prepare_graphrag_input.py)
  3. graphrag.api.build_index() 构建索引

用法：
  python scripts/build_graphrag.py                   # 完整流程
  python scripts/build_graphrag.py --method fast      # fast 模式
  python scripts/build_graphrag.py --skip-prepare     # 跳过 1+2（已有 input 数据）

日志：
  统一写入：`/data/zwt/test/AG/ContestRobot_web/logs/contest_robot_error.log`（按日期由项目日志模块归档）
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from config.app_config import DEFAULT_DATASET
from config.paths import get_graphrag_dir
from config.logger_config import ERROR_LOG_PATH, MAIN_LOG_PATH
from app.logger import setup_logger


def _fail(logger: logging.Logger, msg: str, code: int = 1) -> None:
    logger.error("%s", msg)
    sys.exit(code)

def _log_build_failure(logger: logging.Logger, result: dict) -> None:
    """优先输出 errors 列表，避免仅有 workflows 失败却看不到具体步骤名。"""
    wf_errors = result.get("errors") or []
    err_detail = result.get("error")

    if wf_errors:
        logger.error("失败工作流: %s", ", ".join(wf_errors))
    if err_detail:
        logger.error("失败原因: %s", err_detail)
    elif wf_errors:
        logger.error(
            "失败原因: 未返回 error 字段；请在本日志文件中搜索上述工作流名称，查看对应 Traceback"
        )
    else:
        logger.error("失败原因: 未返回 errors 与 error 字段，请查看构建结果字典与日志全文")

    logger.error("完整日志文件: %s", ERROR_LOG_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="GraphRAG 知识图谱构建")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="数据集名称")
    parser.add_argument(
        "--method",
        default="standard",
        choices=["standard", "fast", "standard-update", "fast-update"],
        help="索引方法",
    )
    parser.add_argument(
        "--skip-prepare",
        action="store_true",
        help="跳过 OCR 融合 + 文本准备（已有 graphrag/input/ 数据）",
    )
    args = parser.parse_args()

    # 复用项目日志模块（按日期归档到 logs/archive/）。
    # 目标：统一写到 contest_robot_error.log（移除 contest_robot.log handler，并放开错误日志 handler 的等级）。
    setup_logger(log_level="INFO", intercept_streams=False)
    root = logging.getLogger()
    for h in list(root.handlers):
        base = getattr(h, "baseFilename", None)
        if not base:
            continue
        if os.path.abspath(base) == os.path.abspath(MAIN_LOG_PATH):
            root.removeHandler(h)
        elif os.path.abspath(base) == os.path.abspath(ERROR_LOG_PATH):
            h.setLevel(logging.DEBUG)

    logger = logging.getLogger("contest_robot.build_graphrag")

    graphrag_root = get_graphrag_dir(args.dataset)

    logger.info("数据集: %s", args.dataset)
    logger.info("GraphRAG 根: %s", graphrag_root)
    logger.info("方法: %s", args.method)
    logger.info("%s", "=" * 60)

    settings_path = os.path.join(graphrag_root, "settings.yaml")
    if not os.path.isfile(settings_path):
        _fail(logger, f"settings.yaml 不存在: {settings_path}")

    if not args.skip_prepare:
        logger.info("[步骤 1/3] 双层 OCR 融合 (ppocr + vlmocr → unified_text)...")
        from scripts.merge_ocr import merge_all

        page_count = merge_all(args.dataset)
        if page_count == 0:
            _fail(
                logger,
                "没有融合到任何页面，请检查 ppocr/ 和 vlmocr/ 目录",
            )

        logger.info("[步骤 2/3] 页级文本 → 文档级 (unified_text → graphrag/input)...")
        from scripts.prepare_graphrag_input import prepare_input

        doc_count = prepare_input(args.dataset)
        if doc_count == 0:
            _fail(logger, "没有生成任何文档")
    else:
        logger.info("[步骤 1-2/3] 跳过数据准备")

    logger.info("[步骤 3/3] 构建 GraphRAG 索引 (Python API)...")
    from backend.graphrag import GraphRAGService

    service = GraphRAGService(args.dataset)
    result = service.build_index(method=args.method)

    logger.info("构建结果: %s", result)
    if result.get("status") == "error":
        _log_build_failure(logger, result)
        sys.exit(1)

    logger.info("构建成功，workflows: %s", result.get("workflows", "?"))


if __name__ == "__main__":
    main()
