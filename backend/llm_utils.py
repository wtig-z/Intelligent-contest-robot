"""
LLM 通用工具：统一 Qwen 调用与是/否分类器。

注意：
- 这里不放任何“业务意图”的提示词，提示词集中放在 prompts 模块里。
"""

from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
from typing import Optional

from config.app_config import CHAT_LLM_MODEL
from backend.prompts.graphrag_compress import build_graphrag_compress_user_message

logger = logging.getLogger("contest_robot.llm_utils")

# GraphRAG 二次精简：避免资料过长撑爆上下文
GRAPHRAG_COMPRESS_MAX_CONTEXT_CHARS = 16000


def call_qwen(messages: list[dict]) -> str:
    """统一使用 Qwen（DashScope）文本模型。返回 content（str）。"""
    import dashscope

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY 未设置")

    response = dashscope.Generation.call(
        model=CHAT_LLM_MODEL,
        messages=messages,
        result_format="message",
    )
    if response.status_code != HTTPStatus.OK:
        err = f"LLM API 错误: HTTP {response.status_code}"
        if getattr(response, "code", None):
            err += f", code={response.code}"
        if getattr(response, "message", None):
            err += f", message={response.message}"
        logger.error("%s model=%s", err, CHAT_LLM_MODEL)
        raise RuntimeError(err)

    output = getattr(response, "output", None)
    if not output or not getattr(output, "choices", None):
        raise RuntimeError("LLM 返回无有效 content")
    choice = output.choices[0]
    msg = getattr(choice, "message", None)
    if not msg:
        raise RuntimeError("LLM 返回无 message")
    content = getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("text"):
                return c["text"].strip()
        return ""
    return (content or "").strip()


def compress_graphrag_answer(user_query: str, raw_answer: str) -> str:
    """
    GraphRAG 生成后再次调用 Qwen，按智能竞赛客服机器人口径压到约 600 字内。
    失败或返回空时回退为 raw_answer。
    """
    ctx = (raw_answer or "").strip()
    if not ctx:
        return ""
    if len(ctx) > GRAPHRAG_COMPRESS_MAX_CONTEXT_CHARS:
        ctx = ctx[:GRAPHRAG_COMPRESS_MAX_CONTEXT_CHARS] + "\n…（资料已截断）"
    user_content = build_graphrag_compress_user_message(user_query, ctx)
    messages = [{"role": "user", "content": user_content}]
    try:
        out = call_qwen(messages)
        out = (out or "").strip()
        return out if out else raw_answer
    except Exception as e:
        logger.warning("GraphRAG 回答精简失败，沿用原文: %s", e, exc_info=True)
        return raw_answer


def classify_yes_no(system_prompt: str, user_text: str) -> Optional[bool]:
    """通用是/否分类器：返回 True/False，无法判断时返回 None。"""
    text = (user_text or "").strip()
    if not text:
        return None
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"问题：{text}"},
    ]
    result = (call_qwen(messages) or "").strip()
    if "是" in result:
        return True
    if "否" in result:
        return False
    r = result.lower()
    if "yes" in r:
        return True
    if "no" in r:
        return False
    return None


def extract_json(system_prompt: str, user_text: str) -> dict:
    """调用 LLM 并解析 JSON（期望返回 dict）。解析失败抛异常。"""
    text = (user_text or "").strip()
    if not text:
        raise ValueError("empty_user_text")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]
    out = call_qwen(messages)
    obj = json.loads(out)
    if not isinstance(obj, dict):
        raise ValueError("json_not_dict")
    return obj

