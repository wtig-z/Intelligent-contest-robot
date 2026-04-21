from PIL import Image
from pathlib import Path
import base64
from io import BytesIO
import os
import dashscope
from dashscope import MultiModalConversation
from openai import OpenAI


def _encode_image(image_path):
    if isinstance(image_path, Image.Image):
        buffered = BytesIO()
        image_path.save(buffered, format="JPEG")
        img_data = buffered.getvalue()
        base64_encoded = base64.b64encode(img_data).decode("utf-8")
        return base64_encoded
    else:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")


class LLM:
    def __init__(self, model_name):
        self.model_name = model_name
        print(f"正在调用的LLM模型: {model_name}")

        if 'qwen-vl' in model_name.lower():
            self.model = MultiModalConversation
            self.api_model = 'qwen3-vl-plus'
        elif model_name.startswith('gpt'):
            self.model = OpenAI()
        else:
            raise ValueError(f"Unsupported model: {model_name}")

    def generate(self, **kwargs):
        query = kwargs.get('query', '')
        image = kwargs.get('image', '')
        model_name = kwargs.get('model_name', '')

        if 'qwen-vl' in self.model_name.lower():
            messages = [{"role": "user", "content": []}]
            if query:
                messages[0]["content"].append({"text": query})
            if image:
                if isinstance(image, str):
                    image = [image]
                elif not isinstance(image, list):
                    image = [image]
                for img_item in image:
                    if isinstance(img_item, Image.Image):
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                            img_item.save(tmp_file.name, format='JPEG')
                            img_path = tmp_file.name
                        messages[0]["content"].append({"image": f"file://{img_path}"})
                    elif isinstance(img_item, str):
                        img_path = Path(img_item).resolve().as_posix()
                        messages[0]["content"].append({"image": f"file://{img_path}"})
                    else:
                        raise ValueError(f"Unsupported image type: {type(img_item)}")

            api_key = os.getenv("DASHSCOPE_API_KEY")
            if not api_key:
                raise ValueError("DASHSCOPE_API_KEY environment variable is not set.")
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            try:
                response = self.model.call(
                    api_key=api_key,
                    model=self.api_model,
                    messages=messages,
                    result_format='message',
                    stream=False,
                    watermark=False,
                    prompt_extend=True
                )
                if response.status_code == 200:
                    if hasattr(response, 'output') and response.output:
                        if hasattr(response.output, 'choices') and response.output.choices:
                            if hasattr(response.output.choices[0], 'message'):
                                message = response.output.choices[0].message
                                if hasattr(message, 'content'):
                                    if isinstance(message.content, list) and len(message.content) > 0:
                                        first_content = message.content[0]
                                        if isinstance(first_content, dict):
                                            return first_content.get('text', '')
                                        return str(first_content)
                                    elif isinstance(message.content, str):
                                        return message.content
                    return str(response)
                else:
                    error_msg = f"DashScope API error: HTTP {response.status_code}"
                    if hasattr(response, 'code'):
                        error_msg += f", Code: {response.code}"
                    if hasattr(response, 'message'):
                        error_msg += f", Message: {response.message}"
                    raise Exception(error_msg)
            except Exception as e:
                raise Exception(f"Error calling DashScope API: {e}")
        elif self.model_name.startswith('gpt'):
            content = [{"type": "text", "text": query}]
            if image != '':
                filepaths = [Path(img).resolve().as_posix() for img in image]
                for filepath in filepaths:
                    base64_image = _encode_image(filepath)
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    })
            completion = self.model.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": content}]
            )
            return completion.choices[0].message.content
        else:
            raise ValueError(f"Unsupported model for generation: {self.model_name}")
