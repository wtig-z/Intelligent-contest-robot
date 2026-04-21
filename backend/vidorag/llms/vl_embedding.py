from typing import Any, List, Optional, Union

import os
import torch
import torch.nn.functional as F
from colpali_engine.models import (
    ColPali,
    ColPaliProcessor,
    ColQwen2,
    ColQwen2Processor,
)
from llama_index.core.base.embeddings.base import Embedding
from llama_index.core.bridge.pydantic import Field
from llama_index.core.callbacks import CallbackManager
from llama_index.core.embeddings import MultiModalEmbedding
from PIL import Image
from transformers import AutoModel, AutoTokenizer
from huggingface_hub import snapshot_download


def weighted_mean_pooling(hidden, attention_mask):
    attention_mask_ = attention_mask * attention_mask.cumsum(dim=1)
    s = torch.sum(hidden * attention_mask_.unsqueeze(-1).float(), dim=1)
    d = attention_mask_.sum(dim=1, keepdim=True).float()
    reps = s / d
    return reps


class VL_Embedding(MultiModalEmbedding):
    model: str = Field(description="The Multi-model to use.")
    api_key: Optional[str] = Field(default=None, description="The API key.")
    dimensions: Optional[int] = Field(default=1024, description="Output embedding dimensions.")
    timeout: Optional[float] = Field(default=None, description="The timeout.")
    mode: str = Field(default="text", description="'text' or 'image'.")
    show_progress: bool = Field(default=False, description="Whether to show progress bars.")
    embed_model: Union[ColQwen2, AutoModel, None] = Field(default=None)
    processor: Optional[ColQwen2Processor] = Field(default=None)
    tokenizer: Optional[AutoTokenizer] = Field(default=None)

    def __init__(
        self,
        model: str = "vidore/colqwen2-v1.0",
        dimensions: Optional[int] = 1024,
        timeout: Optional[int] = None,
        callback_manager: Optional[CallbackManager] = None,
        mode: str = "text",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            dimensions=dimensions,
            timeout=timeout,
            callback_manager=callback_manager,
            **kwargs,
        )
        self.mode = mode
        # 离线模式下，直接解析到本地 snapshot 目录，避免 transformers 在解析 revision 时尝试联网。
        offline = str(os.getenv("HF_OFFLINE", "")).strip() in ("1", "true", "True", "yes", "on")
        resolved_model = model
        if offline and isinstance(model, str) and ("/" in model) and (not os.path.exists(model)):
            try:
                resolved_model = snapshot_download(model, local_files_only=True)
            except Exception:
                resolved_model = model

        if "openbmb" in model:
            self.tokenizer = AutoTokenizer.from_pretrained(resolved_model, trust_remote_code=True)
            # 与 CUDA_VISIBLE_DEVICES 掩码一致：进程内仅一张卡时用 cuda:0
            self.embed_model = AutoModel.from_pretrained(
                resolved_model,
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
                device_map="cuda",
            ).eval()
        elif "vidore" in model and "qwen" in model:
            self.embed_model = ColQwen2.from_pretrained(
                resolved_model,
                torch_dtype=torch.bfloat16,
                device_map="cuda",
            ).eval()
            self.processor = ColQwen2Processor.from_pretrained(resolved_model)
        elif "vidore" in model and "pali" in model:
            self.embed_model = ColPali.from_pretrained(
                resolved_model,
                torch_dtype=torch.bfloat16,
                device_map="cuda",
            ).eval()
            self.processor = ColPaliProcessor.from_pretrained(resolved_model)

    @classmethod
    def class_name(cls) -> str:
        return "VL_Embedding"

    def embed_img(self, img_path):
        if isinstance(img_path, str):
            img_path = [img_path]
        if "vidore" in self.model:
            images = [Image.open(img) for img in img_path]
            batch_images = self.processor.process_images(images).to(self.embed_model.device)
            with torch.no_grad():
                image_embeddings = self.embed_model(**batch_images)
        elif "openbmb" in self.model:
            images = [Image.open(img).convert("RGB") for img in img_path]
            inputs = {"text": [""] * len(images), "image": images, "tokenizer": self.tokenizer}
            with torch.no_grad():
                outputs = self.embed_model(**inputs)
                reps = weighted_mean_pooling(outputs.last_hidden_state, outputs.attention_mask)
                image_embeddings = F.normalize(reps, p=2, dim=1).detach().cpu().numpy()
        return image_embeddings

    def embed_text(self, text):
        if isinstance(text, str):
            text = [text]
        if "colqwen" in self.model or "colpali" in self.model:
            batch_queries = self.processor.process_queries(text).to(self.embed_model.device)
            with torch.no_grad():
                query_embeddings = self.embed_model(**batch_queries)
        elif "openbmb" in self.model:
            INSTRUCTION = "Represent this query for retrieving relevant documents: "
            queries = [INSTRUCTION + q for q in text]
            inputs = {"text": queries, "image": [None] * len(queries), "tokenizer": self.tokenizer}
            with torch.no_grad():
                outputs = self.embed_model(**inputs)
                reps = weighted_mean_pooling(outputs.last_hidden_state, outputs.attention_mask)
                query_embeddings = F.normalize(reps, p=2, dim=1).detach().cpu().tolist()
        return query_embeddings

    def _get_query_embedding(self, query: str) -> List[float]:
        return self.embed_text(query)[0]

    def _get_text_embedding(self, text: str) -> List[float]:
        return self.embed_text(text)[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t)[0] for t in texts]

    def _aget_query_embedding(self, query: str) -> List[float]:
        return self.embed_text(query)[0]

    def _aget_text_embedding(self, text: str) -> List[float]:
        return self.embed_text(text)[0]

    def _get_image_embedding(self, img_file_path) -> Embedding:
        return self.embed_img(img_file_path)

    def _aget_image_embedding(self, img_file_path) -> Embedding:
        return self.embed_img(img_file_path)

    def __call__(self, nodes, **kwargs):
        if "vidore" in self.model:
            if self.mode == "image":
                embeddings = self.embed_img([n.metadata["file_path"] for n in nodes])
                embeddings = embeddings.view(embeddings.size(0), -1).tolist()
            else:
                embeddings = self.embed_text([n.text for n in nodes])
                embeddings = embeddings.view(embeddings.size(0), -1).tolist()
        elif "openbmb" in self.model:
            if self.mode == "image":
                embeddings = self.embed_img([n.metadata["file_path"] for n in nodes]).tolist()
            else:
                embeddings = self.embed_text([n.text for n in nodes])
        for node, embedding in zip(nodes, embeddings):
            node.embedding = embedding
        return nodes

    def score(self, image_embeddings, text_embeddings):
        if "vidore" in self.model:
            return self.processor.score_multi_vector(image_embeddings, text_embeddings)
        return text_embeddings @ image_embeddings.T
