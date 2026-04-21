#!/usr/bin/env python3
"""
嵌入生成：img -> colqwen, ppocr -> bge
用法: python ingestion.py --dataset CompetitionDataset

构建过程会写入 vectors 表（需能 import Flask/SQLAlchemy；失败则仅跳过写库，仍生成 .node）。
"""
import os
import sys
import argparse
import logging
from contextlib import nullcontext
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# 直接运行脚本时也读取 .env（避免 LLM Key/模型配置缺失）
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception as e:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("contest_robot.ingestion").warning("load_dotenv 失败：%s", e)

from config.paths import get_dataset_dir
from config.app_config import CUDA_VISIBLE_DEVICES

if CUDA_VISIBLE_DEVICES:
    os.environ['CUDA_VISIBLE_DEVICES'] = CUDA_VISIBLE_DEVICES

from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SimpleFileNodeParser, SentenceSplitter
from llama_index.readers.file import FlatReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import SimpleDirectoryReader

from backend.vidorag.llms.vl_embedding import VL_Embedding


class Ingestion:
    def __init__(self, dataset_dir: str, input_prefix: str = 'ppocr', output_prefix: str = 'bge_ingestion', embed_model_name: str = 'BAAI/bge-m3'):
        self.dataset_dir = dataset_dir
        self.input_dir = os.path.join(dataset_dir, input_prefix)
        self.output_dir = os.path.join(dataset_dir, output_prefix)
        self.chunk_size = 1024
        self.overlap_size = 0
        self.workers = 5
        self.reader = FlatReader()
        self.embed_model_name = embed_model_name

        if 'vidore' in embed_model_name or 'openbmb' in embed_model_name:
            if input_prefix == 'img':
                self.reader = SimpleDirectoryReader(input_dir=self.input_dir)
                self.pipeline = IngestionPipeline(transformations=[
                    SimpleFileNodeParser(),
                    VL_Embedding(model=embed_model_name, mode='image')
                ])
            else:
                self.pipeline = IngestionPipeline(transformations=[
                    SimpleFileNodeParser(),
                    SentenceSplitter(
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.overlap_size,
                        separator=' ',
                        paragraph_separator='\n\n\n',
                        secondary_chunking_regex='[^,.;。？！]+[,.;。？！]?',
                        include_metadata=True, include_prev_next_rel=True
                    ),
                    VL_Embedding(model=embed_model_name, mode='text')
                ])
        else:
            self.pipeline = IngestionPipeline(transformations=[
                SimpleFileNodeParser(),
                SentenceSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.overlap_size,
                    separator=' ',
                    paragraph_separator='\n\n\n',
                    secondary_chunking_regex='[^,.;。？！]+[,.;。？！]?',
                    include_metadata=True, include_prev_next_rel=True
                ),
                HuggingFaceEmbedding(model_name=self.embed_model_name, trust_remote_code=True)
            ])

    def ingestion_example(self, input_file: str, output_file: str):
        import json
        if input_file.endswith('.jpg') or input_file.endswith('.png'):
            documents = self.reader.load_file(Path(input_file), self.reader.file_metadata, self.reader.file_extractor)
            nodes = self.pipeline.run(documents=documents, num_workers=1, show_progress=False)
        else:
            documents = self.reader.load_data(Path(input_file))
            nodes = self.pipeline.run(documents=documents, show_progress=False)
        nodes_json = [node.to_dict() for node in nodes]
        # 产物可能包含中文路径/元数据，必须用 utf-8 写入
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(nodes_json, f, indent=2, ensure_ascii=False)
        return True

    def ingestion_multi_session(self, tracker=None):
        import json
        os.makedirs(self.output_dir, exist_ok=True)
        file_to_process = []
        for f in os.listdir(self.input_dir):
            prefix, _ = os.path.splitext(f)
            inp = os.path.join(self.input_dir, f)
            out = os.path.join(self.output_dir, prefix) + '.node'
            if not os.path.exists(out):
                file_to_process.append((inp, out))
        total = len(file_to_process)
        if tracker and total == 0:
            tracker.update_progress(100)
            return
        for i, (inp, out) in enumerate(tqdm(file_to_process, desc='Ingestion')):
            self.ingestion_example(inp, out)
            if tracker is not None and total > 0:
                tracker.update_progress(10 + int(80 * (i + 1) / total))


def _tracked_pipeline(dataset_name: str, vector_type: str, build_fn, success_path: str) -> None:
    """在已处于 app_context 内时调用；写 vectors 行。"""
    try:
        from backend.storage.vector_builder import VectorBuildTracker
    except Exception:
        build_fn(None)
        return
    t = None
    try:
        t = VectorBuildTracker(vector_type, dataset_name)
        t.create_pending()
        t.start_building()
        build_fn(t)
        t.build_success(success_path)
    except Exception as e:
        if t is not None:
            try:
                t.build_failed(str(e))
            except Exception:
                pass
        raise


def _main_inner(args):
    dataset_dir = get_dataset_dir(args.dataset)
    if not os.path.isdir(dataset_dir):
        print(f"错误: {dataset_dir} 不存在")
        return
    img_dir = os.path.join(dataset_dir, 'img')
    unified_dir = os.path.join(dataset_dir, 'unified_text')
    ppocr_dir = os.path.join(dataset_dir, 'ppocr')
    ds = args.dataset

    if os.path.isdir(img_dir):
        out_col = os.path.join(dataset_dir, 'colqwen_ingestion')

        def _visual(tr):
            print("视觉管道: img -> colqwen_ingestion")
            ing = Ingestion(
                dataset_dir,
                input_prefix='img',
                output_prefix='colqwen_ingestion',
                embed_model_name='vidore/colqwen2-v1.0',
            )
            ing.ingestion_multi_session(tracker=tr)

        _tracked_pipeline(ds, 'colqwen', _visual, out_col)

    text_source = None
    if os.path.isdir(unified_dir) and os.listdir(unified_dir):
        text_source = 'unified_text'
    elif os.path.isdir(ppocr_dir) and os.listdir(ppocr_dir):
        text_source = 'ppocr'

    if text_source:
        out_bge = os.path.join(dataset_dir, 'bge_ingestion')

        def _text(tr):
            print(f"文本管道: {text_source} -> bge_ingestion")
            ing = Ingestion(
                dataset_dir,
                input_prefix=text_source,
                output_prefix='bge_ingestion',
                embed_model_name='BAAI/bge-m3',
            )
            ing.ingestion_multi_session(tracker=tr)

        _tracked_pipeline(ds, 'bge', _text, out_bge)
    else:
        print("警告: 没有找到 unified_text/ 或 ppocr/ 文本数据，跳过文本管道")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='CompetitionDataset')
    args = parser.parse_args()
    try:
        from backend.storage.vector_builder import app_context_for_ingestion

        ctx = app_context_for_ingestion()
    except Exception:
        ctx = nullcontext()
    with ctx:
        _main_inner(args)


if __name__ == '__main__':
    main()
