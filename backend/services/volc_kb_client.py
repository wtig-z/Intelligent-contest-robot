"""
火山引擎知识库 HTTP API（search_knowledge → 拼装 prompt → chat/completions）
与主问答链路独立；凭环境变量 VOLC_KB_* 启用。

文档：https://www.volcengine.com/docs/84313/
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional, Tuple, Union

import requests

logger = logging.getLogger("contest_robot.volc_kb")

try:
    from volcengine.auth.SignerV4 import SignerV4
    from volcengine.base.Request import Request
    from volcengine.Credentials import Credentials
except ImportError:
    SignerV4 = None  # type: ignore
    Request = None  # type: ignore
    Credentials = None  # type: ignore


DEFAULT_DOMAIN = "api-knowledgebase.mlp.cn-beijing.volces.com"
DEFAULT_PROJECT = "default"
DEFAULT_COLLECTION = "wt"
DEFAULT_MODEL = "Doubao-seed-1-8"
DEFAULT_MODEL_VERSION = "251228"


BASE_PROMPT = """
# 任务
你是一位在线客服，你的首要任务是通过巧妙的话术回复用户的问题，你需要根据「参考资料」来回答接下来的「用户问题」，这些信息在 <context></context> XML tags 之内，你需要根据参考资料给出准确，简洁的回答。

你的回答要满足以下要求：
    1. 回答内容必须在参考资料范围内，尽可能简洁地回答问题，不能做任何参考资料以外的扩展解释。
    2. 回答中需要根据客户问题和参考资料保持与客户的友好沟通。
    3. 如果参考资料不能帮助你回答用户问题，告知客户无法回答该问题，并引导客户提供更加详细的信息。
    4. 如果用户输入了图片内容，也可以结合用户的图片内容来回答用户问题，即使与参考资料无关。
    5. 为了保密需要，委婉地拒绝回答有关参考资料的文档名称或文档作者等问题。

# 任务执行
现在请你根据提供的参考资料，遵循限制来回答用户的问题，你的回答需要准确和完整。

# 参考资料

注意：「参考资料」可以为文本、图片等多种内容
- 文本资料是一段文本
- 图片资料则是图片内容，可能会包括关于图片的描述性文本
<context>
  {}
</context>
参考资料中提到的图片按上传顺序排列，请结合图片与文本信息综合回答问题。如参考资料中没有图片，请仅根据参考资料中的文本信息回答问题。

# 引用要求
1. 当可以回答时，在句子末尾适当引用相关参考资料，每个参考资料引用格式必须使用<reference>标签对，例如: <reference data-ref="{{point_id}}"></reference>
2. 当告知客户无法回答时，不允许引用任何参考资料
3. 'data-ref' 字段表示对应参考资料的 point_id
4. 'point_id' 取值必须来源于参考资料对应的'point_id' 后的id号
5. 适当合并引用，当引用项相同可以合并引用，只在引用内容结束添加一个引用标签。

# 配图要求
1. 首先对参考资料的每个图片内容含义深入理解，然后从所有图片中筛选出与回答上下文直接关联的图片，在回答中的合适位置插入作为配图，图像内容必须支持直接的可视化说明问题的答案。若参考资料中无适配图片，或图片仅是间接性关联，则省略配图。
2. 使用 <illustration> 标签对表示插图，例如: <illustration data-ref="{{point_id}}"></illustration>，其中 'point_id' 字段表示对应图片的 point_id，每个配图标签对必须另起一行，相同的图片（以'point_id'区分）只允许使用一次。
3. 'point_id' 取值必须来源于参考资料，形如“_sys_auto_gen_doc_id-1005563729285435073--1”，请注意务必不要虚构，'point_id'值必须与参考资料完全一致

下面是「用户问题」，可以为文本和图片内容，你需要根据上面的「参考资料」来回答接下来的「用户问题」
"""


def is_sdk_available() -> bool:
    return SignerV4 is not None and Request is not None and Credentials is not None


def load_config() -> dict:
    return {
        "ak": (os.getenv("VOLC_KB_AK") or "").strip(),
        "sk": (os.getenv("VOLC_KB_SK") or "").strip(),
        "account_id": (os.getenv("VOLC_KB_ACCOUNT_ID") or "").strip(),
        "domain": (os.getenv("VOLC_KB_DOMAIN") or DEFAULT_DOMAIN).strip(),
        "project": (os.getenv("VOLC_KB_PROJECT") or DEFAULT_PROJECT).strip(),
        "collection": (
            os.getenv("VOLC_KB_COLLECTION_NAME") or os.getenv("VOLC_KB_COLLECTION") or DEFAULT_COLLECTION
        ).strip(),
        "model": (os.getenv("VOLC_KB_MODEL") or DEFAULT_MODEL).strip(),
        "model_version": (os.getenv("VOLC_KB_MODEL_VERSION") or DEFAULT_MODEL_VERSION).strip(),
    }


def is_configured() -> bool:
    c = load_config()
    return bool(c["ak"] and c["sk"] and c["account_id"])


def prepare_request(
    method: str,
    path: str,
    domain: str,
    ak: str,
    sk: str,
    account_id: str,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    doseq: int = 0,
) -> Any:
    if not is_sdk_available():
        raise RuntimeError("未安装 volcengine SDK，请 pip install volcengine-python-sdk")
    if params:
        for key in list(params.keys()):
            v = params[key]
            if isinstance(v, (int, float, bool)):
                params[key] = str(v)
            elif isinstance(v, list) and not doseq:
                params[key] = ",".join(str(x) for x in v)
    r = Request()
    r.set_shema("http")
    r.set_method(method)
    r.set_connection_timeout(30)
    r.set_socket_timeout(120)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "Host": domain,
        "V-Account-Id": account_id,
    }
    r.set_headers(headers)
    if params:
        r.set_query(params)
    r.set_host(domain)
    r.set_path(path)
    if data is not None:
        r.set_body(json.dumps(data, ensure_ascii=False))
    credentials = Credentials(ak, sk, "air", "cn-north-1")
    SignerV4.sign(r, credentials)
    return r


def _do_http(req: Any) -> requests.Response:
    url = "http://{}{}".format(req.host, req.path)
    return requests.request(
        method=req.method,
        url=url,
        headers=req.headers,
        data=req.body,
        timeout=120,
    )


def is_vision_model(model_name: Optional[str], model_version: Optional[str]) -> bool:
    if not model_name:
        return False
    mv = model_version or ""
    return "vision" in model_name.lower() or "m" in mv


def get_content_for_prompt(point: dict) -> str:
    content = point.get("content") or ""
    original_question = point.get("original_question")
    if original_question:
        return '当询问到相似问题时，请参考对应答案进行回答：问题：“{question}”。答案：“{answer}”'.format(
            question=original_question,
            answer=content,
        )
    return content


def generate_prompt(
    rsp_txt: str,
    model_name: str,
    model_version: str,
) -> Tuple[Union[str, List[dict]], str]:
    """返回 (system_prompt 或 多模态 content list, 合并后的纯文本 context 摘要用于日志)。"""
    rsp = json.loads(rsp_txt)
    if rsp.get("code") != 0:
        return "", json.dumps(rsp, ensure_ascii=False)[:500]
    rsp_data = rsp.get("data") or {}
    points = rsp_data.get("result_list") or []
    using_vlm = is_vision_model(model_name, model_version)
    prompt_parts: List[str] = []
    content: List[dict] = []

    for point in points:
        if not isinstance(point, dict):
            continue
        doc_text_part = ""
        doc_info = point.get("doc_info") or {}
        if not isinstance(doc_info, dict):
            doc_info = {}
        for system_field in ["point_id", "doc_name", "title", "chunk_title", "content"]:
            if system_field in ("doc_name", "title"):
                if system_field in doc_info:
                    doc_text_part += f"{system_field}: {doc_info[system_field]}\n"
            else:
                if system_field == "content":
                    doc_text_part += f"content: {get_content_for_prompt(point)}\n"
                elif system_field == "point_id" and point.get("point_id") is not None:
                    doc_text_part += f'point_id: "{point["point_id"]}"\n'
                elif point.get(system_field) is not None:
                    doc_text_part += f"{system_field}: {point[system_field]}\n"

        image_link = None
        if using_vlm and point.get("chunk_attachment"):
            atts = point["chunk_attachment"]
            if isinstance(atts, list) and len(atts) > 0 and isinstance(atts[0], dict):
                image_link = atts[0].get("link")
        if image_link:
            doc_text_part += "图片: \n"

        content.append({"type": "text", "text": doc_text_part})
        if image_link:
            content.append({"type": "image_url", "image_url": {"url": image_link}})
        prompt_parts.append(doc_text_part)

    merged = "\n".join(prompt_parts)
    if using_vlm:
        parts = BASE_PROMPT.split("{}")
        pre = parts[0] if parts else BASE_PROMPT
        sub = parts[1] if len(parts) > 1 else ""
        return (
            [{"type": "text", "text": pre}] + content + [{"type": "text", "text": sub}],
            merged[:2000],
        )
    return BASE_PROMPT.format(merged), merged[:2000]


def search_knowledge(
    cfg: dict,
    query: str,
    image_query: str,
) -> str:
    path = "/api/knowledge/collection/search_knowledge"
    body = {
        "project": cfg["project"],
        "name": cfg["collection"],
        "query": query,
        "image_query": image_query or "",
        "limit": 10,
        "pre_processing": {
            "need_instruction": True,
            "return_token_usage": True,
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": ""},
            ],
            "rewrite": False,
        },
        "post_processing": {
            "get_attachment_link": True,
            "rerank_only_chunk": False,
            "rerank_switch": False,
            "chunk_group": True,
            "rerank_model": "doubao-seed-rerank",
            "enable_rerank_threshold": False,
            "retrieve_count": 25,
            "chunk_diffusion_count": 0,
        },
        "dense_weight": 0.5,
    }
    req = prepare_request(
        "POST",
        path,
        cfg["domain"],
        cfg["ak"],
        cfg["sk"],
        cfg["account_id"],
        data=body,
    )
    rsp = _do_http(req)
    rsp.encoding = "utf-8"
    return rsp.text


def chat_completion(
    cfg: dict,
    messages: List[dict],
) -> Tuple[str, Optional[dict]]:
    """非流式；返回 (answer_text, raw_json_or_none)。"""
    path = "/api/knowledge/chat/completions"
    body = {
        "messages": messages,
        "stream": False,
        "return_token_usage": True,
        "model": cfg["model"],
        "max_tokens": 4096,
        "temperature": 1,
        "model_version": cfg["model_version"],
        "thinking": {"type": "enabled"},
    }
    req = prepare_request(
        "POST",
        path,
        cfg["domain"],
        cfg["ak"],
        cfg["sk"],
        cfg["account_id"],
        data=body,
    )
    rsp = _do_http(req)
    rsp.encoding = "utf-8"
    text = rsp.text or ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("chat/completions 非 JSON: %s", text[:500])
        return ("", None)

    # 兼容多种返回结构
    if isinstance(data, dict):
        if data.get("code") not in (None, 0) and data.get("code") != 0:
            msg = data.get("message") or str(data)
            raise RuntimeError(msg)
        ans = (
            data.get("data", {})
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )
        if ans:
            return (str(ans), data)
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            c0 = choices[0] or {}
            msg = c0.get("message") or {}
            if isinstance(msg, dict) and msg.get("content"):
                return (str(msg["content"]), data)
        # 部分网关直接返回 OpenAI 风格
        if data.get("choices"):
            c0 = data["choices"][0]
            mc = (c0.get("message") or {}).get("content")
            if mc:
                return (str(mc), data)
    return ("", data)


def run_pipeline(
    query: str,
    image_query: str = "",
    history: Optional[List[dict]] = None,
) -> dict:
    """
    执行 search_knowledge → generate_prompt → chat/completions。
    history: [{role,user|assistant, content:str}, ...]
    """
    cfg = load_config()
    if not is_configured():
        raise RuntimeError("未配置 VOLC_KB_AK / VOLC_KB_SK / VOLC_KB_ACCOUNT_ID")

    rsp_txt = search_knowledge(cfg, query, image_query)
    logger.info("search_knowledge 返回长度=%s", len(rsp_txt))
    prompt_payload, _ctx_snip = generate_prompt(
        rsp_txt,
        cfg["model"],
        cfg["model_version"],
    )
    if not prompt_payload:
        try:
            err = json.loads(rsp_txt)
        except Exception:
            err = {"raw": rsp_txt[:800]}
        raise RuntimeError("检索未返回有效内容: " + json.dumps(err, ensure_ascii=False)[:400])

    using_vlm = is_vision_model(cfg["model"], cfg["model_version"])
    if using_vlm and isinstance(prompt_payload, list):
        system_content: Any = prompt_payload
    else:
        system_content = prompt_payload if isinstance(prompt_payload, str) else str(prompt_payload)

    user_content: Any
    if image_query:
        user_content = [{"type": "image_url", "image_url": {"url": image_query}}]
        if query:
            user_content.append({"type": "text", "text": query})
    else:
        user_content = query

    messages: List[dict] = [{"role": "system", "content": system_content}]
    for h in history or []:
        if not isinstance(h, dict):
            continue
        role = (h.get("role") or "").strip().lower()
        c = h.get("content")
        if role not in ("user", "assistant") or c is None:
            continue
        messages.append({"role": role, "content": c})
    messages.append({"role": "user", "content": user_content})

    answer, raw = chat_completion(cfg, messages)
    return {
        "answer": answer or "",
        "raw": raw,
        "search_preview": rsp_txt[:1200] if len(rsp_txt) > 1200 else rsp_txt,
    }
