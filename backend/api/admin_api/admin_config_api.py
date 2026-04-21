"""运行时配置（非密钥类可全员只读；密钥仅管理员读写）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from backend.auth.jwt_handler import admin_required, backoffice_required, get_current_user
from config.paths import get_project_root

bp = Blueprint("admin_config", __name__, url_prefix="/api/admin/config")

_CONFIG_PATH = os.path.join(get_project_root(), "data", "runtime_config.json")

_DEFAULTS: Dict[str, Any] = {
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 4096,
    "log_capacity": 300,
    "vector_recall_topk": 10,
    "graphrag_mode_default": "auto",
    "show_images": True,
    "ocr_enabled": True,
    "qa_interrupt_timeout_sec": 120,
    # 知识库更新的“额外可选工作”（默认快路径；演示或运维时可打开）
    "kb_update_graphrag_input": False,  # 更新后是否同步生成 graphrag/input 文档级 txt（不等于建索引）
    "kb_generate_vlm_box_images": False,  # 更新后是否生成 img_with_boxes_vlmocr 画框质检图
}


def _load() -> Dict[str, Any]:
    data = dict(_DEFAULTS)
    if os.path.isfile(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                merged = json.load(f)
            if isinstance(merged, dict):
                data.update(merged)
        except Exception:
            pass
    return data


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _mask_secrets(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data)
    for k in ("dashscope_api_key", "ocr_api_key"):
        v = out.get(k)
        if v:
            out[k] = "***" if len(str(v)) > 4 else "(set)"
        else:
            out[k] = ""
    return out


@bp.route("", methods=["GET"])
@backoffice_required
def get_config():
    user = get_current_user() or {}
    raw = _load()
    if user.get("role") != "admin":
        raw = _mask_secrets(raw)
    return jsonify({"code": 0, "message": "ok", "data": raw})


@bp.route("", methods=["PUT", "POST"])
@admin_required
def put_config():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"code": 400, "message": "无效 JSON"}), 400
    cur = _load()
    for k, v in body.items():
        if k in _DEFAULTS or k in ("dashscope_api_key", "ocr_api_key"):
            cur[k] = v
    _save(cur)
    # 可选：将密钥写入环境变量进程内覆盖（仅当前进程）
    if body.get("dashscope_api_key"):
        os.environ["DASHSCOPE_API_KEY"] = str(body["dashscope_api_key"])
    if body.get("ocr_api_key"):
        os.environ["OCR_API_KEY"] = str(body["ocr_api_key"])
    return jsonify({"code": 0, "message": "已保存", "data": _mask_secrets(cur)})
