"""
数据路径、脚本路径统一配置
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_project_root() -> str:
    return PROJECT_ROOT


def get_dataset_dir(dataset_name: str) -> str:
    """指定数据集的根目录"""
    return os.path.join(PROJECT_ROOT, 'data', dataset_name)


def get_scripts_dir() -> str:
    """脚本目录 scripts/"""
    return os.path.join(PROJECT_ROOT, 'scripts')


def get_img_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'img')


def get_bge_ingestion_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'bge_ingestion')


def get_vlmocr_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'vlmocr')


def get_pdf_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'pdf')


def get_ppocr_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'ppocr')


def get_unified_text_dir(dataset_name: str) -> str:
    """双层 OCR 融合后的统一文本目录（页级 .txt）"""
    return os.path.join(get_dataset_dir(dataset_name), 'unified_text')


def get_graphrag_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'graphrag')


def get_kmeans_index_dir(dataset_name: str) -> str:
    return os.path.join(get_dataset_dir(dataset_name), 'kmeans_index')
