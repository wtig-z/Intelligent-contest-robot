"""混合检索引擎：文本+视觉双路召回 + GMM去噪 + K-Means分层加速"""
import os
import logging
from typing import List, Optional
import json
from tqdm import tqdm
import torch
import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.cluster import KMeans
from concurrent.futures import ThreadPoolExecutor, as_completed

from llama_index.core import Settings
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.indices.query.schema import QueryBundle
from llama_index.core.schema import NodeWithScore, ImageNode
from llama_index.core import VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from config.paths import get_dataset_dir, get_img_dir, get_bge_ingestion_dir, get_vlmocr_dir, get_unified_text_dir, get_kmeans_index_dir
from config.app_config import CUDA_VISIBLE_DEVICES
from backend.vidorag.llms.vl_embedding import VL_Embedding
from backend.vidorag.utils.format_converter import nodefile2node, nodes2dict

logger = logging.getLogger("contest_robot.search_engine")

if CUDA_VISIBLE_DEVICES:
    os.environ['CUDA_VISIBLE_DEVICES'] = CUDA_VISIBLE_DEVICES


def gmm(recall_result: list, input_length: int = 20, max_valid_length: int = 10, min_valid_length: int = 5) -> List[NodeWithScore]:
    scores = np.array([n.score for n in recall_result[:input_length]]).reshape(-1, 1)
    gmm_model = GaussianMixture(n_components=2, n_init=1, random_state=0)
    gmm_model.fit(scores)
    labels = gmm_model.predict(scores)
    scores_flat = scores.flatten()
    recall_arr = np.array(recall_result[:input_length])
    recall_split = [recall_arr[labels == label].tolist() for label in np.unique(labels)]
    scores_split = [scores_flat[labels == label] for label in np.unique(labels)]
    max_vals = np.array([np.max(p) for p in scores_split])
    sorted_idx = np.argsort(-max_vals)
    valid = recall_split[sorted_idx[0]]
    if len(valid) > max_valid_length:
        valid = valid[:max_valid_length]
    elif len(valid) < min_valid_length and len(sorted_idx) > 1:
        valid.extend(recall_split[sorted_idx[1]][:min_valid_length - len(valid)])
    for n in valid:
        n.score = None
    return valid


class KMeansIndex:
    """K-Means 分层检索索引：离线预聚类 + 在线粗→精两阶段检索"""

    def __init__(self, dataset: str, n_clusters: Optional[int] = None):
        self.dataset = dataset
        self.index_dir = get_kmeans_index_dir(dataset)
        self.n_clusters = n_clusters
        self._cluster_centers: Optional[np.ndarray] = None
        self._cluster_labels: Optional[np.ndarray] = None
        self._embeddings: Optional[np.ndarray] = None
        self._node_indices: Optional[List[int]] = None

    def build(self, embeddings: np.ndarray) -> None:
        """离线预聚类构建索引"""
        os.makedirs(self.index_dir, exist_ok=True)
        n = len(embeddings)
        if self.n_clusters is None:
            self.n_clusters = self._optimal_clusters(n)

        logger.info("构建 K-Means 索引: %d 向量, %d 簇", n, self.n_clusters)
        kmeans = KMeans(n_clusters=self.n_clusters, random_state=42, n_init=3)
        labels = kmeans.fit_predict(embeddings)

        self._cluster_centers = kmeans.cluster_centers_.astype(np.float32)
        self._cluster_labels = labels
        self._embeddings = embeddings.astype(np.float32)

        np.save(os.path.join(self.index_dir, 'centers.npy'), self._cluster_centers)
        np.save(os.path.join(self.index_dir, 'labels.npy'), self._cluster_labels)
        np.save(os.path.join(self.index_dir, 'embeddings.npy'), self._embeddings)
        logger.info("K-Means 索引构建完成")

    def load(self) -> bool:
        centers_path = os.path.join(self.index_dir, 'centers.npy')
        labels_path = os.path.join(self.index_dir, 'labels.npy')
        emb_path = os.path.join(self.index_dir, 'embeddings.npy')
        if not all(os.path.exists(p) for p in [centers_path, labels_path, emb_path]):
            return False
        self._cluster_centers = np.load(centers_path)
        self._cluster_labels = np.load(labels_path)
        self._embeddings = np.load(emb_path)
        self.n_clusters = len(self._cluster_centers)
        return True

    def search(self, query_embedding: np.ndarray, topk: int = 10,
               n_probe_clusters: int = 5) -> List[tuple]:
        """
        分层检索：
        第一步（粗筛）：计算 Query 与所有簇中心的余弦相似度，筛选 Top-N 簇
        第二步（精筛）：仅在筛选出的簇内暴力检索，召回 Top-K
        返回: [(node_index, score), ...]
        """
        if self._cluster_centers is None:
            return []

        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-8)
        center_norms = self._cluster_centers / (
            np.linalg.norm(self._cluster_centers, axis=1, keepdims=True) + 1e-8
        )
        center_scores = center_norms @ query_norm
        n_probe = min(n_probe_clusters, self.n_clusters)
        top_clusters = np.argsort(-center_scores)[:n_probe]

        candidate_indices = []
        for c in top_clusters:
            cluster_mask = self._cluster_labels == c
            candidate_indices.extend(np.where(cluster_mask)[0].tolist())

        if not candidate_indices:
            return []

        candidate_embs = self._embeddings[candidate_indices]
        cand_norms = candidate_embs / (
            np.linalg.norm(candidate_embs, axis=1, keepdims=True) + 1e-8
        )
        scores = cand_norms @ query_norm

        k = min(topk, len(scores))
        top_local = np.argsort(-scores)[:k]
        results = [(candidate_indices[i], float(scores[i])) for i in top_local]
        return results

    @staticmethod
    def _optimal_clusters(n: int) -> int:
        """基于数据量动态确定簇数"""
        if n <= 50:
            return max(2, n // 5)
        elif n <= 200:
            return max(5, n // 10)
        elif n <= 1000:
            return max(10, n // 20)
        else:
            return max(20, min(100, n // 50))

    @property
    def is_loaded(self) -> bool:
        return self._cluster_centers is not None


class SearchEngine:
    def __init__(self, dataset: str, node_dir_prefix: Optional[str] = None, embed_model_name: str = 'BAAI/bge-m3'):
        Settings.llm = None
        self.gmm = False
        self.return_raw = False
        self.input_gmm = 20
        self.max_output_gmm = 10
        self.min_output_gmm = 5
        self.dataset = dataset
        self.dataset_dir = get_dataset_dir(dataset)

        if node_dir_prefix is None:
            if 'bge' in embed_model_name:
                node_dir_prefix = 'bge_ingestion'
            elif 'colqwen' in embed_model_name:
                node_dir_prefix = 'colqwen_ingestion'
            elif 'NV-Embed' in embed_model_name:
                node_dir_prefix = 'nv_ingestion'
            elif 'openbmb' in embed_model_name:
                node_dir_prefix = 'visrag_ingestion'
            elif 'colpali' in embed_model_name:
                node_dir_prefix = 'colpali_ingestion'
            else:
                raise ValueError('Please specify node_dir_prefix')

        self.vl_ret = node_dir_prefix in ['colqwen_ingestion', 'visrag_ingestion', 'colpali_ingestion']
        self.node_dir = os.path.join(self.dataset_dir, node_dir_prefix)
        self.rag_dataset_path = os.path.join(self.dataset_dir, 'rag_dataset.json')
        self.workers = 1
        self.embed_model_name = embed_model_name

        if 'vidore' in embed_model_name or 'openbmb' in embed_model_name:
            self.vector_embed_model = VL_Embedding(
                model=embed_model_name,
                mode='image' if self.vl_ret else 'text'
            )
        else:
            self.vector_embed_model = HuggingFaceEmbedding(
                model_name=self.embed_model_name, embed_batch_size=10, max_length=512,
                trust_remote_code=True, device='cuda'
            )
        self.recall_num = 100
        self.query_engine = self._load_query_engine()

    def _load_nodes(self):
        files = os.listdir(self.node_dir)
        parsed = []
        for f in files:
            p = os.path.join(self.node_dir, f)
            if not p.endswith('.node'):
                continue
            parsed.extend(nodefile2node(p))
        return parsed

    def _load_query_engine(self):
        print('Loading nodes...')
        self.nodes = self._load_nodes()
        if self.vl_ret and 'vidore' in self.embed_model_name:
            self.embedding_img = [
                torch.tensor(n.embedding).view(-1, 128).bfloat16().to(self.vector_embed_model.embed_model.device)
                for n in self.nodes
            ]
            return None
        vector_index = VectorStoreIndex(
            self.nodes, embed_model=self.vector_embed_model,
            show_progress=True, use_async=False, insert_batch_size=2048
        )
        retriever = vector_index.as_retriever(similarity_top_k=self.recall_num)
        return RetrieverQueryEngine(retriever=retriever, node_postprocessors=[])

    def search(self, query: str):
        if self.vl_ret and 'vidore' in self.embed_model_name:
            qe = self.vector_embed_model.embed_text(query)
            scores = self.vector_embed_model.processor.score(qe, self.embedding_img)
            k = min(100, scores[0].numel())
            values, indices = torch.topk(scores[0], k=k)
            recall = [NodeWithScore(node=self.nodes[i], score=float(s)) for i, s in zip(indices, values)]
        else:
            recall = self.query_engine.retrieve(QueryBundle(query_str=query))

        if self.gmm:
            recall = gmm(recall, self.input_gmm, self.max_output_gmm, self.min_output_gmm)
        if self.return_raw:
            return recall
        return nodes2dict(recall)


class HybridSearchEngine:
    def __init__(
        self,
        dataset: str,
        node_dir_prefix_vl: Optional[str] = None,
        node_dir_prefix_text: Optional[str] = None,
        embed_model_name_vl: str = 'vidore/colqwen2-v1.0',
        embed_model_name_text: str = 'BAAI/bge-m3',
        topk: int = 10,
        gmm: bool = False,
        use_kmeans: bool = True,
    ):
        self.dataset = dataset
        self.dataset_dir = get_dataset_dir(dataset)
        self.img_dir = get_img_dir(dataset)
        self.unified_text_dir = get_unified_text_dir(dataset)
        self.vlmocr_dir = get_vlmocr_dir(dataset)
        self.bge_dir = get_bge_ingestion_dir(dataset)
        self.engine_vl = SearchEngine(dataset, node_dir_prefix=node_dir_prefix_vl, embed_model_name=embed_model_name_vl)
        self.engine_text = SearchEngine(dataset, node_dir_prefix=node_dir_prefix_text, embed_model_name=embed_model_name_text)
        self.topk = topk
        self.gmm = gmm
        self._kmeans_vl: Optional[KMeansIndex] = None

        if use_kmeans:
            self._init_kmeans_index()

    def _init_kmeans_index(self):
        """尝试加载 K-Means 索引，不存在时从现有节点构建"""
        try:
            self._kmeans_vl = KMeansIndex(self.dataset)
            if not self._kmeans_vl.load():
                if hasattr(self.engine_vl, 'nodes') and self.engine_vl.nodes:
                    embeddings = []
                    for node in self.engine_vl.nodes:
                        if node.embedding is not None:
                            emb = node.embedding
                            if isinstance(emb, torch.Tensor):
                                emb = emb.cpu().numpy().flatten()
                            elif not isinstance(emb, np.ndarray):
                                emb = np.array(emb).flatten()
                            embeddings.append(emb)
                    if embeddings:
                        emb_matrix = np.stack(embeddings).astype(np.float32)
                        self._kmeans_vl.build(emb_matrix)
                        logger.info("K-Means VL 索引从节点构建完成")
                    else:
                        self._kmeans_vl = None
                else:
                    self._kmeans_vl = None
            else:
                logger.info("K-Means VL 索引加载成功: %d 簇", self._kmeans_vl.n_clusters)
        except Exception as e:
            logger.warning("K-Means 索引初始化失败: %s, 使用原始检索", e)
            self._kmeans_vl = None

    def build_kmeans_index(self, n_clusters: Optional[int] = None):
        """手动触发 K-Means 索引重建"""
        if not hasattr(self.engine_vl, 'nodes') or not self.engine_vl.nodes:
            return False
        embeddings = []
        for node in self.engine_vl.nodes:
            if node.embedding is not None:
                emb = node.embedding
                if isinstance(emb, torch.Tensor):
                    emb = emb.cpu().numpy().flatten()
                elif not isinstance(emb, np.ndarray):
                    emb = np.array(emb).flatten()
                embeddings.append(emb)
        if not embeddings:
            return False
        self._kmeans_vl = KMeansIndex(self.dataset, n_clusters=n_clusters)
        self._kmeans_vl.build(np.stack(embeddings).astype(np.float32))
        return True

    def search(self, query: str):
        self.engine_vl.return_raw = True
        self.engine_text.return_raw = True
        result_vl = self.engine_vl.search(query)
        result_text = self.engine_text.search(query)
        result_vl_gmm = gmm(result_vl, self.topk * 2, self.topk, 5)
        result_text_gmm = gmm(result_text, self.topk * 2, self.topk, 5)
        result_vl_gmm = nodes2dict(result_vl_gmm)
        result_text_gmm = nodes2dict(result_text_gmm)

        result_docs = {}
        for node in result_vl_gmm['source_nodes']:
            f = '.'.join(os.path.basename(node['node']['image_path']).split('.')[:-1])
            doc, page = '_'.join(f.split('_')[:-1]), f.split('_')[-1]
            if doc not in result_docs:
                result_docs[doc] = [int(page)]
            elif int(page) not in result_docs[doc]:
                result_docs[doc].append(int(page))
        for node in result_text_gmm['source_nodes']:
            f = '.'.join(node['node']['metadata']['filename'].split('.')[:-1])
            doc, page = '_'.join(f.split('_')[:-1]), f.split('_')[-1]
            if doc not in result_docs:
                result_docs[doc] = [int(page)]
            elif int(page) not in result_docs[doc]:
                result_docs[doc].append(int(page))

        result_docs_list = [f'{k}_{p}' for k, pages in result_docs.items() for p in pages]
        result_vl_dict = nodes2dict(result_vl)
        result_text_dict = nodes2dict(result_text)
        result_docs_vl_list = []
        for node in result_vl_dict['source_nodes']:
            f = '.'.join(os.path.basename(node['node']['image_path']).split('.')[:-1])
            result_docs_vl_list.append('_'.join(f.split('_')[:-1]) + '_' + f.split('_')[-1])
        result_docs_text_list = []
        for node in result_text_dict['source_nodes']:
            f = '.'.join(node['node']['metadata']['filename'].split('.')[:-1])
            result_docs_text_list.append('_'.join(f.split('_')[:-1]) + '_' + f.split('_')[-1])

        overlap = [d for d in result_docs_vl_list if d in result_docs_text_list]
        cand = [1, 2, 4, 6, 9, 12, 16, 20]
        already = sum(len(v) for v in result_docs.values())
        target = min((x for x in cand if x >= already), default=already)
        candidate_overlap = [d for d in overlap if d not in result_docs_list][:target - already]
        candidate_overlap += [d for d in result_docs_vl_list if d not in candidate_overlap and d not in result_docs_list]
        candidate_overlap = candidate_overlap[:target - already]
        for item in candidate_overlap:
            doc, page = '_'.join(item.split('_')[:-1]), item.split('_')[-1]
            if doc not in result_docs:
                result_docs[doc] = [int(page)]
            elif int(page) not in result_docs[doc]:
                result_docs[doc].append(int(page))

        recall_result = []
        for key, pages in result_docs.items():
            for page in sorted(pages):
                text = self._load_page_text(key, page)
                img_path = os.path.join(self.img_dir, f'{key}_{page}.jpg')
                node = ImageNode(image_path=img_path, text=text, metadata=dict(file_name=img_path))
                recall_result.append(NodeWithScore(node=node, score=None))
        return nodes2dict(recall_result)

    def _load_page_text(self, doc_key: str, page: int) -> str:
        """加载页面文本：unified_text → vlmocr → bge_ingestion 三级回退"""
        unified_path = os.path.join(self.unified_text_dir, f'{doc_key}_{page}.txt')
        if os.path.exists(unified_path):
            with open(unified_path, 'r') as f:
                return f.read().strip()

        vlm_path = os.path.join(self.vlmocr_dir, f'{doc_key}_{page}.json')
        if os.path.exists(vlm_path):
            try:
                with open(vlm_path, 'r') as f:
                    data = json.load(f)
                return '\n'.join(obj['content'] for obj in data.get('objects', []))
            except (json.JSONDecodeError, KeyError):
                pass

        node_path = os.path.join(self.bge_dir, f'{doc_key}_{page}.node')
        if os.path.exists(node_path):
            try:
                with open(node_path, 'r') as f:
                    node_data = json.load(f)
                if isinstance(node_data, list):
                    return ' '.join(item.get('text', '') for item in node_data)
            except (json.JSONDecodeError, KeyError):
                pass

        return ''
