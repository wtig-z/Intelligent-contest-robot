#!/usr/bin/env python3
"""PDF 转图片"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pdf2image import convert_from_path
from tqdm import tqdm

from config.paths import get_dataset_dir

DATASETS = ['CompetitionDataset']

for dataset in DATASETS:
    dataset_dir = get_dataset_dir(dataset)
    pdf_path = os.path.join(dataset_dir, 'pdf')
    img_path = os.path.join(dataset_dir, 'img')
    if not os.path.isdir(pdf_path):
        print(f"跳过 {dataset}: {pdf_path} 不存在")
        continue
    os.makedirs(img_path, exist_ok=True)
    pdf_files = [f for f in os.listdir(pdf_path) if f.endswith('.pdf')]
    for filename in tqdm(pdf_files, desc=dataset):
        filepath = os.path.join(pdf_path, filename)
        imgname = filename.replace('.pdf', '')
        images = convert_from_path(filepath, thread_count=4)
        for i, image in enumerate(images):
            image.save(os.path.join(img_path, f'{imgname}_{i+1}.jpg'), 'JPEG')
