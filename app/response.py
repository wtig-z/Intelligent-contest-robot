"""统一响应格式"""
from flask import jsonify
from typing import Any, Optional


def success(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def error(message: str = "error", code: int = 400) -> dict:
    return {"code": code, "message": message, "data": None}


def json_success(data: Any = None, message: str = "ok"):
    return jsonify(success(data, message))


def json_error(message: str = "error", code: int = 400):
    return jsonify(error(message, code))
