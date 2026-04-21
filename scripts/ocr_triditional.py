#!/usr/bin/env python3
"""传统 OCR (PaddleOCR)，需安装 fastdeploy、paddle 等"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config.paths import get_dataset_dir, get_scripts_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='CompetitionDataset')
    args = parser.parse_args()
    dataset_dir = get_dataset_dir(args.dataset)
    scripts_dir = get_scripts_dir()
    img_dir = os.path.join(dataset_dir, 'img')
    ppocr_dir = os.path.join(dataset_dir, 'ppocr')
    os.makedirs(ppocr_dir, exist_ok=True)
    DET_MODEL_DIR = os.path.join(scripts_dir, 'ocr_models', 'ch_PP-OCRv4_det_infer')
    REC_MODEL_DIR = os.path.join(scripts_dir, 'ocr_models', 'ch_PP-OCRv4_rec_infer')
    CLS_MODEL_DIR = os.path.join(scripts_dir, 'ocr_models', 'ch_ppocr_mobile_v2.0_cls_infer')
    REC_LABEL_FILE = os.path.join(scripts_dir, 'ocr_models', 'ppocr_keys_v1.txt')
    if not all(os.path.exists(p) for p in [DET_MODEL_DIR, REC_MODEL_DIR, CLS_MODEL_DIR]):
        print("请将 PaddleOCR 模型放入 scripts/ocr_models/ 目录")
        return
    try:
        import cv2
        import numpy as np
        import fastdeploy as fd
        from PIL import Image
    except ImportError as e:
        print(f"请安装依赖: pip install opencv-python fastdeploy-gpu paddlepaddle-gpu，错误: {e}")
        return
    # 调用原 ViDoRAG 脚本或内联逻辑（此处简化，仅提示）
    print("请使用 ViDoRAG/scripts/ocr_triditional.py 或配置 ocr_models 后运行")
    print(f"IMAGE_PATH={img_dir}")
    print(f"OUTPUT -> ppocr/")


if __name__ == '__main__':
    main()
