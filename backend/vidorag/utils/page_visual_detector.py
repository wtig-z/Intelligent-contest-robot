"""页面视觉内容检测：图片/表格（True/False）。"""
import os
from typing import Dict

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


_RESULT_CACHE: Dict[str, Dict[str, bool]] = {}


def has_table(img_path: str, threshold: int = 20) -> bool:
    """通过水平/垂直线条统计判断是否存在表格。"""
    if cv2 is None:
        return False
    img = cv2.imread(img_path, 0)
    if img is None:
        return False

    edges = cv2.Canny(img, 50, 150)

    horizontal = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
    horizontal_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, horizontal)

    vertical = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 50))
    vertical_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, vertical)

    line_count = int(np.count_nonzero(horizontal_lines) + np.count_nonzero(vertical_lines))
    return line_count > threshold


def has_image(img_path: str, color_threshold: float = 15.0, edge_threshold: int = 5000) -> bool:
    """通过颜色波动和边缘密度判断页面是否包含非纯文本图像区域。"""
    if cv2 is None:
        return False
    img = cv2.imread(img_path)
    if img is None:
        return False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    color_std = float(img.std())
    edges = cv2.Canny(gray, 50, 150)
    edge_count = int(cv2.countNonZero(edges))

    return (color_std > color_threshold) or (edge_count > edge_threshold)


def check_pdf_page(img_path: str) -> Dict[str, bool]:
    """
    输出该页是否含图片/表格：
    {"has_image": True/False, "has_table": True/False}
    """
    key = os.path.abspath(img_path)
    if key in _RESULT_CACHE:
        return _RESULT_CACHE[key]

    result = {
        "has_image": has_image(key),
        "has_table": has_table(key),
    }
    _RESULT_CACHE[key] = result
    return result

