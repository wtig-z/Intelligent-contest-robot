#!/usr/bin/env python3
"""VLM OCR (qwen-vl)"""
import os
import sys
import json
import time
import argparse
import logging
from tqdm import tqdm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 直接运行脚本时也读取 .env（DASHSCOPE_API_KEY）
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception as e:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("contest_robot.ocr_vlms").warning("load_dotenv 失败：%s", e)

from config.paths import get_dataset_dir
from backend.vidorag.llms.llm import LLM

PROMPT = '''Generate bounding boxes for each of the objects in this image in [y_min, x_min, y_max, x_max] format.
For textual objects, provide the bounding box and text content.
For tables, provide bounding box and content in csv format.
For charts, provide bounding box and content.
For non-textual objects, provide bounding box and caption.

Response Format:
{
    "objects": [
        {"bounding_box": [y_min, x_min, y_max, x_max], "content": "...", "type": "text"|"table"|"chart"|"object"},
        ...
    ]
}'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='CompetitionDataset')
    args = parser.parse_args()
    dataset_dir = get_dataset_dir(args.dataset)
    img_dir = os.path.join(dataset_dir, 'img')
    vlmocr_dir = os.path.join(dataset_dir, 'vlmocr')
    os.makedirs(vlmocr_dir, exist_ok=True)
    if not os.path.isdir(img_dir):
        print(f"错误: {img_dir} 不存在")
        return
    vlm = LLM('qwen-vl-max')
    files = [f for f in os.listdir(img_dir) if f.endswith('.jpg')]
    for f in tqdm(files, desc='VLM OCR'):
        img_path = os.path.join(img_dir, f)
        out_path = os.path.join(vlmocr_dir, f.replace('.jpg', '.json'))
        if os.path.exists(out_path):
            continue
        while True:
            try:
                out = vlm.generate(query=PROMPT, image=[img_path])
                out = out.replace('```json', '').replace('```', '')
                data = json.loads(out)
                with open(out_path, 'w') as fp:
                    json.dump(data, fp, indent=2, ensure_ascii=False)
                break
            except Exception as e:
                print(f'Error {img_path}: {e}, retrying...')
                time.sleep(2)


if __name__ == '__main__':
    main()
