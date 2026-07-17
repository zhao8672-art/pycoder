"""
视觉模型客户端 — 调用 GPT-4V / DeepSeek-VL / Qwen-VL
"""

from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


class VisionClient:
    """视觉模型客户端 — 图像语义理解"""

    def __init__(self):
        self._model = "gpt-4o-mini"

    async def analyze(self, image_data: bytes, prompt: str = "描述这张图片") -> str:
        """分析图片内容"""
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            return await self._call_vision(img, prompt)
        except Exception as exc:
            return f"分析失败: {exc}"

    async def ocr(self, image) -> str:
        """LLM 视觉 OCR"""
        prompt = "请提取图片中的所有文字内容，保持原格式输出。如果图片中没有文字，请回复'无文字'。"
        return await self._call_vision(image, prompt)

    async def _call_vision(self, image, prompt: str) -> str:
        """调用视觉模型"""
        try:
            from pycoder.providers.auth import get_model_manager

            mm = get_model_manager()
            detected = mm.auto_detect()

            # 尝试找到支持视觉的模型
            if "openai" in detected:
                api_key = detected["openai"]
                return await self._call_openai_vision(image, prompt, api_key)
            elif "deepseek" in detected:
                api_key = detected["deepseek"]
                return await self._call_deepseek_vision(image, prompt, api_key)
            else:
                return "无可用的视觉模型 API Key"
        except Exception as exc:
            return f"视觉分析失败: {exc}"

    async def _call_openai_vision(self, image, prompt: str, api_key: str) -> str:
        """调用 GPT-4V"""
        import io
        import base64
        import httpx

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        url_content = {"url": f"data:image/png;base64,{b64}"}
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": url_content},
                        ],
                    }],
                    "max_tokens": 1024,
                },
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            return f"视觉 API 错误: {resp.text[:200]}"

    async def _call_deepseek_vision(self, image, prompt: str, api_key: str) -> str:
        """调用 DeepSeek VL (待 API 支持)"""
        # DeepSeek 视觉 API 尚未公开，回退到 OpenAI
        return await self._call_openai_vision(image, prompt, api_key)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_client: VisionClient | None = None


def get_vision_client() -> VisionClient:
    global _client
    if _client is None:
        _client = VisionClient()
    return _client
