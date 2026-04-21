"""
ViDoRAG 服务入口：对外暴露 chat(message) -> {answer, images, rewritten}
"""
import os
import logging
from typing import List, Optional

from config.app_config import DEFAULT_DATASET, VIDORAG_EMBED_MODEL_VL, VIDORAG_EMBED_MODEL_TEXT, VIDORAG_LLM_MODEL
from backend.vidorag.search_engine import HybridSearchEngine
from backend.vidorag.agents import ViDoRAG_Agents
from backend.vidorag.agent.prompts import rewrite_prompt

logger = logging.getLogger("contest_robot.vidorag")

class ViDoRAGModelNotReadyError(RuntimeError):
    """离线模式下模型缓存不完整等导致 ViDoRAG 无法启动。"""


def _node_doc_name(node_data: dict, img_dir: str) -> Optional[str]:
    """从节点数据得到文档名（用于按赛事过滤）。如 03_泰迪杯_1.jpg -> 03_泰迪杯"""
    if 'image_path' in node_data:
        base = os.path.basename(node_data['image_path'])
        name = '.'.join(base.split('.')[:-1])  # 去掉 .jpg
        parts = name.split('_')
        if len(parts) >= 2 and parts[-1].isdigit():
            return '_'.join(parts[:-1])
        return name
    if 'metadata' in node_data:
        filename = (node_data['metadata'].get('file_name') or node_data['metadata'].get('filename') or '')
        if filename:
            base = os.path.basename(filename).replace('.txt', '.jpg')
            name = '.'.join(base.split('.')[:-1])
            parts = name.split('_')
            if len(parts) >= 2 and parts[-1].isdigit():
                return '_'.join(parts[:-1])
            return name
    return None


def get_images_path_from_recall(
    recall_results: dict,
    search_engine: HybridSearchEngine,
    contest_filter: Optional[str] = None,
    contest_filters: Optional[List[str]] = None,
) -> tuple:
    """从检索结果中提取图片路径和 OCR 文本。
    contest_filters 非空：保留列表内任一赛事（PDF）下的节点（整类多文档）。
    否则 contest_filter 非空：仅保留该单一赛事。
    """
    images_path = []
    ocr_texts = {}
    if 'source_nodes' not in recall_results:
        logger.info("图片地址 (contest=%s): %s", contest_filter or contest_filters or "<all>", images_path)

    img_dir = search_engine.img_dir
    allowed: Optional[set] = None
    if contest_filters:
        allowed = set(str(x).strip() for x in contest_filters if str(x).strip())
    for node in recall_results['source_nodes']:
        node_data = node.get('node', {})
        if allowed is not None:
            doc = _node_doc_name(node_data, img_dir)
            if doc not in allowed:
                continue
        elif contest_filter:
            doc = _node_doc_name(node_data, img_dir)
            if doc != contest_filter:
                continue
        text = node_data.get('text', '')
        if 'image_path' in node_data:
            img_path = node_data['image_path']
            images_path.append(img_path)
            if text:
                ocr_texts[img_path] = text
            continue
        if 'metadata' in node_data:
            meta = node_data['metadata']
            filename = meta.get('file_name') or meta.get('filename', '')        
            if filename:
                if filename.endswith('.txt'):
                    filename = filename.replace('.txt', '.jpg')
                img_path = os.path.join(img_dir, os.path.basename(filename))
                if os.path.exists(img_path):
                    images_path.append(img_path)
                    if text:
                        ocr_texts[img_path] = text
    logger.info("图片地址 (contest=%s): %s", contest_filter or contest_filters or "<all>", images_path)
    return images_path, ocr_texts


class ViDoRAGService:
    """对外服务：检索 + Agent 推理 → 返回 answer、images、rewritten"""

    def __init__(self, dataset: Optional[str] = None):
        self._dataset = dataset or DEFAULT_DATASET
        self._engine: Optional[HybridSearchEngine] = None
        self._vlm = None
        self._agent: Optional[ViDoRAG_Agents] = None

    def _ensure_loaded(self):
        try:
            if self._engine is None:
                self._engine = HybridSearchEngine(
                    dataset=self._dataset,
                    embed_model_name_vl=VIDORAG_EMBED_MODEL_VL,
                    embed_model_name_text=VIDORAG_EMBED_MODEL_TEXT,
                    gmm=True
                )
        except Exception as e:
            # 常见：开启 HF/Transformers 离线模式后，本机缓存不完整，from_pretrained 会抛 LocalEntryNotFoundError/OSError。
            offline = str(os.getenv("HF_OFFLINE", "")).strip() in ("1", "true", "True", "yes", "on")
            msg = f"{type(e).__name__}: {e}"
            looks_like_hf_cache_miss = (
                "LocalEntryNotFoundError" in msg
                or "couldn't connect to 'https://huggingface.co'" in msg
                or "couldn't connect to 'https://hf.co'" in msg
                or "couldn't connect to 'https://hf-mirror.com'" in msg
                or ("outgoing traffic has been disabled" in msg)
                or ("couldn't find them in the cached files" in msg)
            )
            if offline and looks_like_hf_cache_miss:
                logger.warning("ViDoRAG 初始化失败（疑似离线缓存缺失）: %s", msg, exc_info=True)
                raise ViDoRAGModelNotReadyError(
                    "ViDoRAG 模型缓存不完整，且当前处于离线模式（禁止联网下载），因此无法加载检索模型。"
                    f"\n- 需要补全的模型通常包括：`{VIDORAG_EMBED_MODEL_VL}`、`{VIDORAG_EMBED_MODEL_TEXT}`"
                    "\n- 处理办法：临时联网补全下载一次（可用镜像 `HF_ENDPOINT=https://hf-mirror.com`），"
                    "下载完成后再保持离线运行。"
                ) from e
            # 其他初始化失败：原样抛出，让上层返回明确错误
            logger.warning("ViDoRAG 初始化失败（非离线缓存缺失路径）: %s", msg, exc_info=True)
            raise
        if self._vlm is None:
            from backend.vidorag.llms.llm import LLM
            self._vlm = LLM(VIDORAG_LLM_MODEL)
        if self._agent is None:
            self._agent = ViDoRAG_Agents(self._vlm)

    def warmup(self) -> None:
        """
        服务启动预热：提前完成模型/索引加载，避免用户首次提问时加载 HuggingFace 权重导致卡顿。
        注意：预热会占用显存/内存并延长启动时间，适合演示或常驻服务。
        """
        try:
            self._ensure_loaded()
            # 轻量触发一次检索路径（不跑 agent），让底层 embedding/索引尽早初始化完成
            try:
                if self._engine is not None:
                    _ = self._engine.search("预热")
            except Exception:
                pass
            logger.info("ViDoRAG warmup 完成")
        except Exception as e:
            logger.warning("ViDoRAG warmup 失败（将回退到懒加载）: %s", e)

    def _rewrite_query(self, raw_query: str) -> str:
        """用 LLM 对用户查询做纠错和润色"""
        try:
            prompt = rewrite_prompt.replace('{query}', raw_query)
            rewritten = self._vlm.generate(query=prompt)
            if rewritten and isinstance(rewritten, str):
                rewritten = rewritten.strip().strip('"').strip("'")
                if len(rewritten) > 0 and len(rewritten) < len(raw_query) * 5:
                    return rewritten
        except Exception as e:
            if hasattr(self, '_log'):
                self._log(f"[查询改写] 失败: {e}")
        return raw_query

    def chat(
        self,
        message: str,
        contest_filter: Optional[str] = None,
        contest_filters: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ) -> dict:
        """
        对外接口：检索 + Agent 推理 → 返回 answer、images、rewritten
        contest_filter: 单一赛事（文档 id，无扩展名）。
        contest_filters: 多赛事并集（整类范围）；与 contest_filter 互斥，优先 contest_filters。
        """
        self._ensure_loaded()
        raw_query = message.strip()
        rewritten = self._rewrite_query(raw_query)

        recall_results = self._engine.search(rewritten)
        images_path, ocr_texts = get_images_path_from_recall(
            recall_results,
            self._engine,
            contest_filter=contest_filter if not contest_filters else None,
            contest_filters=contest_filters,
        )

        if not images_path:
            return {
                "answer": "未检索到相关文档，请换一种方式描述您的问题。",
                "images": [],
                "rewritten": rewritten,
                "seeker_rounds": 0,
            }

        try:
            # 取消检查：在 Agent 长流程之前/之后快速退出
            from backend.services.cancel_registry import raise_if_cancelled
            raise_if_cancelled(request_id)
            answer, used_images = self._agent.run_agent(
                query=raw_query,
                images_path=images_path,
                ocr_texts=ocr_texts,
                request_id=request_id,
            )
            raise_if_cancelled(request_id)
            seeker_rounds = getattr(self._agent, '_last_seeker_rounds', 0)
            return {
                "answer": answer or "未能生成有效答案。",
                "images": used_images or [],
                "rewritten": rewritten,
                "seeker_rounds": seeker_rounds,
            }
        except Exception as e:
            # 被取消的请求必须向上抛出：上层负责丢弃中间结果/不落库/不上传
            from backend.services.cancel_registry import CancelledError
            if isinstance(e, CancelledError):
                raise
            return {
                "answer": f"处理失败: {str(e)}",
                "images": [],
                "rewritten": rewritten,
                "seeker_rounds": 0,
            }
