"""
GraphRAG 模块 —— 内嵌微软 GraphRAG (v3) 算法包。

_lib/ 目录包含微软 GraphRAG 全部源码（graphrag, graphrag_common, graphrag_storage 等）。
对外通过 GraphRAGService 提供索引构建与多级查询能力。
"""
import os
import sys

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from backend.graphrag.service import GraphRAGService

__all__ = ["GraphRAGService"]
