"""
应用配置
"""
import os

# 默认数据集
DEFAULT_DATASET = os.getenv('VIDORAG_DATASET', 'CompetitionDataset')

# ViDoRAG 模型配置
VIDORAG_EMBED_MODEL_VL = os.getenv('VIDORAG_EMBED_VL', 'vidore/colqwen2-v1.0')
VIDORAG_EMBED_MODEL_TEXT = os.getenv('VIDORAG_EMBED_TEXT', 'BAAI/bge-m3')
VIDORAG_LLM_MODEL = os.getenv('VIDORAG_LLM', 'qwen-vl-max')

# GraphRAG 配置（微软 GraphRAG，实际模型/参数在 settings.yaml 中配置）
# GraphRAG 工作目录位于 data/<dataset>/graphrag/，需包含 settings.yaml 和 input/

# 多轮→单轮总结 Agent：统一使用 Qwen 文本模型（qwen-turbo / qwen-plus）
CHAT_LLM_MODEL = os.getenv('CHAT_LLM', 'qwen-turbo')
# 历史轮数上限（保留最近 N 轮 user+assistant）
MAX_HISTORY_TURNS = int(os.getenv('MAX_HISTORY_TURNS', '10'))
# 历史总字符数上限（截断时优先保留最近）
MAX_HISTORY_CHARS = int(os.getenv('MAX_HISTORY_CHARS', '8000'))

# CUDA：默认使用物理 GPU 编号 2（三卡环境 0/1/2 中的第三张）
# 由 run.py 在 import torch 前写入 os.environ；此处供模块读取
CUDA_VISIBLE_DEVICES = (os.getenv('CUDA_VISIBLE_DEVICES', '2') or '2').strip()

# 问答内存缓存过期时间（秒），仅用于重复查询加速，与用户历史记录无关
QA_CACHE_TTL = int(os.getenv('QA_CACHE_TTL', '3600'))
    