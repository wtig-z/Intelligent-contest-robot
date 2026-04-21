"""ViDoRAG Agents: Seeker, Inspector, Synthesizer"""
import os
from typing import Optional, List, Tuple

from backend.vidorag.agent.prompts import seeker_prompt, inspector_prompt, answer_prompt
from backend.vidorag.agent.map_dict import arrangement_map_dict, page_map_dict
from backend.vidorag.utils.parse_tool import extract_json
from backend.vidorag.utils.image_preprosser import concat_images_with_bbox

MAX_IMAGES = 20
MAX_RETRIES = 2
DEBUG = True


def log(*args):
    if DEBUG:
        print(' '.join(str(arg) for arg in args))


def build_ocr_section(images: List[str], ocr_texts: dict) -> str:
    lines = []
    for i, img_path in enumerate(images):
        text = ocr_texts.get(img_path, '').strip()
        if not text:
            continue
        if len(text) > 800:
            text = text[:800] + '...(截断)'
        lines.append(f'[图片{i}] {text}')
    if not lines:
        return ''
    return '## OCR参考文本（图片中文字看不清时以此文本为准）\n' + '\n\n'.join(lines)


class Seeker:
    def __init__(self, vlm):
        self.vlm = vlm
        self.buffer_images = []
        self.query = None
        self.ocr_texts = {}

    def run(self, query: Optional[str] = None, images_path: Optional[List[str]] = None,
            feedback: Optional[str] = None, ocr_texts: Optional[dict] = None) -> Tuple[List[str], str, str, List[int]]:
        if query and images_path:
            self.buffer_images = images_path
            self.query = query
            if ocr_texts:
                self.ocr_texts.update(ocr_texts)
            prompt_query = query
        elif feedback:
            if not self.query:
                raise ValueError("feedback模式需要先设置query")
            prompt_query = f"{self.query}\n\n## Additional Information\n{feedback}"
        else:
            raise ValueError("必须提供query+images_path或feedback")

        num_images = min(len(self.buffer_images), MAX_IMAGES)
        page_map_text = page_map_dict.get(num_images, f"图片编号从0到{num_images-1}，共{num_images}张图片。")
        images_to_use = self.buffer_images[:num_images]
        ocr_section = build_ocr_section(images_to_use, self.ocr_texts)
        prompt = seeker_prompt.replace('{question}', prompt_query).replace('{page_map}', page_map_text).replace('{ocr_text}', ocr_section)
        arrangement = arrangement_map_dict.get(num_images)
        if not arrangement:
            raise ValueError(f"不支持 {num_images} 张图片的排列方式")
        input_images = [concat_images_with_bbox(images_to_use, arrangement=arrangement, scale=1, line_width=40)]

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.vlm.generate(query=prompt, image=input_images)
                if not response:
                    continue
                log(f"[Seeker响应] {response}")
                j = extract_json(response)
                reason, summary, choice = j.get('reason'), j.get('summary'), j.get('choice')
                if reason is None or summary is None or choice is None:
                    raise ValueError(f"响应格式不完整")
                if not isinstance(choice, list):
                    raise ValueError(f"choice 必须是列表")
                # 与拼接图一致：只承认实际送入 VLM 的前 n 张（模型常误用示例里的「图片5」等编号）
                n = min(len(self.buffer_images), MAX_IMAGES)
                sanitized: List[int] = []
                seen = set()
                for i in choice:
                    if isinstance(i, int) and 0 <= i < n and i not in seen:
                        seen.add(i)
                        sanitized.append(i)
                if not sanitized and n > 0:
                    orig = choice
                    sanitized = list(range(n))
                    log(f"[Seeker] 警告: choice {orig} 无有效索引（合法 0..{n - 1}），已回退为全部 {n} 张")
                choice = sanitized
                selected = [self.buffer_images[idx] for idx in choice]
                orig_idx = choice.copy()
                self.buffer_images = [img for img in self.buffer_images if img not in selected]
                return selected, summary, reason, orig_idx
            except Exception as e:
                log(f"[Seeker] 错误: {e}")
                if attempt >= MAX_RETRIES:
                    raise Exception(f'Seeker timeout: {e}')
        raise Exception('Seeker timeout')


class Inspector:
    def __init__(self, vlm):
        self.vlm = vlm
        self.buffer_images = []
        self.original_index_to_image = {}
        self.ocr_texts = {}

    def run(self, query: str, images_path: List[str], original_indices: Optional[List[int]] = None,
            ocr_texts: Optional[dict] = None) -> Tuple[Optional[str], Optional[str], Optional[List[str]]]:
        if ocr_texts:
            self.ocr_texts.update(ocr_texts)
        if not self.buffer_images and not images_path:
            return None, None, None
        if not images_path:
            return 'synthesizer', None, self.buffer_images

        if not self.buffer_images:
            self.buffer_images = list(images_path)
        else:
            self.buffer_images.extend(images_path)
        if original_indices:
            for img, idx in zip(images_path, original_indices):
                self.original_index_to_image[idx] = img

        num_images = min(len(self.buffer_images), MAX_IMAGES)
        if num_images == 0:
            return None, None, None
        page_map_text = page_map_dict.get(num_images, f"图片编号从0到{num_images-1}，共{num_images}张图片。")
        images_to_use = self.buffer_images[:num_images]
        ocr_section = build_ocr_section(images_to_use, self.ocr_texts)
        prompt = inspector_prompt.replace('{question}', query).replace('{page_map}', page_map_text).replace('{ocr_text}', ocr_section)
        arrangement = arrangement_map_dict.get(num_images)
        if not arrangement:
            raise ValueError(f"不支持 {num_images} 张图片的排列方式")
        input_images = [concat_images_with_bbox(images_to_use, arrangement=arrangement, scale=1, line_width=40)]

        def get_images_from_ref(ref_list):
            result = []
            for idx in ref_list:
                if idx in self.original_index_to_image:
                    result.append(self.original_index_to_image[idx])
                elif 0 <= idx < len(self.buffer_images):
                    result.append(self.buffer_images[idx])
            seen = set()
            return [x for x in result if x not in seen and not seen.add(x)]

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.vlm.generate(query=prompt, image=input_images)
                if not response:
                    continue
                log(f"[Inspector响应] {response}")
                j = extract_json(response)
                reason, info, choice, answer, ref = j.get('reason'), j.get('information'), j.get('choice'), j.get('answer'), j.get('reference')
                if not reason:
                    raise ValueError('响应缺少reason字段')
                if answer:
                    if ref:
                        ref_images = get_images_from_ref(ref)
                        if not ref_images and self.buffer_images:
                            ref_images = self.buffer_images
                        if not ref_images:
                            raise ValueError("无法从reference获取图片")
                        return 'synthesizer', answer, ref_images
                    return 'answer', answer, self.buffer_images
                if info is not None:
                    if choice and isinstance(choice, list):
                        if not all(0 <= i < num_images for i in choice):
                            raise ValueError("choice索引无效")
                        self.buffer_images = [self.buffer_images[i] for i in choice]
                        return 'seeker', info, self.buffer_images
                    # choice 为空或缺失：当前图片无法回答问题，直接以 information 作为回复
                    return 'answer', info, self.buffer_images
                if ref and not answer:
                    ref_images = get_images_from_ref(ref)
                    return 'seeker', 'Need more detail from referenced pages', ref_images
                raise ValueError('unrecognized inspector json format')
            except Exception as e:
                log(f"[Inspector] 错误: {e}")
                if attempt >= MAX_RETRIES:
                    raise Exception(f'Inspector timeout: {e}')
        raise Exception('Inspector timeout')


class Synthesizer:
    def __init__(self, vlm):
        self.vlm = vlm

    def run(self, query: str, candidate_answer: Optional[str], ref_images: List[str],
            ocr_texts: Optional[dict] = None) -> Tuple[str, str]:
        if candidate_answer:
            query = f"{query}\n\n## Related Information\n{candidate_answer}"
        num_images = len(ref_images)
        page_map_text = page_map_dict.get(num_images, f"图片编号从0到{num_images-1}，共{num_images}张图片。")
        ocr_section = build_ocr_section(ref_images, ocr_texts or {})
        prompt = answer_prompt.replace('{question}', query).replace('{page_map}', page_map_text).replace('{ocr_text}', ocr_section)
        arrangement = arrangement_map_dict.get(num_images)
        if not arrangement:
            raise ValueError(f"不支持 {num_images} 张图片的排列方式")
        input_images = [concat_images_with_bbox(ref_images, arrangement=arrangement, scale=1, line_width=40)]
        while True:
            try:
                response = self.vlm.generate(query=prompt, image=input_images)
                if not response:
                    continue
                log(f"[Synthesizer响应] {response}")
                j = extract_json(response)
                reason, answer = j.get('reason'), j.get('answer')
                if not reason or not answer:
                    raise ValueError('响应格式不完整')
                return reason, answer
            except Exception as e:
                log(f"[Synthesizer] 错误: {e}")
                continue


class ViDoRAG_Agents:
    def __init__(self, vlm):
        self.seeker = Seeker(vlm)
        self.inspector = Inspector(vlm)
        self.synthesizer = Synthesizer(vlm)

    def run_agent(self, query: str, images_path: List[str], ocr_texts: Optional[dict] = None,
                  request_id: Optional[str] = None) -> Tuple[Optional[str], List[str]]:
        ocr_texts = ocr_texts or {}
        from backend.services.cancel_registry import raise_if_cancelled
        self.seeker.buffer_images = []
        self.seeker.ocr_texts = {}
        self.inspector.buffer_images = []
        self.inspector.original_index_to_image = {}
        self.inspector.ocr_texts = {}
        self._last_seeker_rounds = 0
        raise_if_cancelled(request_id)

        selected_images, summary, reason, original_indices = self.seeker.run(
            query=query, images_path=images_path, ocr_texts=ocr_texts)
        self._last_seeker_rounds = 1
        MAX_LOOPS = 5
        last_information = None
        for _ in range(MAX_LOOPS):
            raise_if_cancelled(request_id)
            status, information, images = self.inspector.run(
                query, selected_images, original_indices=original_indices, ocr_texts=ocr_texts)
            if status == 'answer':
                return information, images or []
            elif status == 'synthesizer':
                raise_if_cancelled(request_id)
                reason, answer = self.synthesizer.run(query, information, images, ocr_texts=ocr_texts)
                return answer, images or []
            elif status == 'seeker':
                last_information = information
                if not self.seeker.buffer_images:
                    log("[ViDoRAG] Seeker 已无剩余图片，强制进入 Synthesizer")
                    break
                raise_if_cancelled(request_id)
                selected_images, summary, reason, original_indices = self.seeker.run(feedback=information)
                self._last_seeker_rounds += 1
                if not selected_images:
                    log("[ViDoRAG] Seeker 未选择任何图片，强制进入 Synthesizer")
                    break
                continue
            else:
                return None, []

        log("[ViDoRAG] 达到最大迭代次数，强制用已有信息生成答案")
        all_images = self.inspector.buffer_images if self.inspector.buffer_images else images_path[:5]
        raise_if_cancelled(request_id)
        reason, answer = self.synthesizer.run(query, last_information, all_images, ocr_texts=ocr_texts)
        return answer, all_images
