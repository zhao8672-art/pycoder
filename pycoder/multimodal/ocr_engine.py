"""
多层 OCR 引擎 — Tesseract → PaddleOCR → LLM 视觉回退

每层比前一层更准确但更慢，按需降级。
"""

from __future__ import annotations

import logging

_logger = logging.getLogger('pycoder.multimodal.ocr_engine')

from io import BytesIO

logger = logging.getLogger(__name__)


class OCREngine:
    """多层 OCR 引擎"""

    def __init__(self):
        self._tesseract = self._init_tesseract()
        self._paddle = self._init_paddle()
        self._vision_client: object = None
        self._vision_timeout: float = 8.0  # LLM Vision OCR 超时阈值
        self.last_method: str = "none"

    def _init_tesseract(self):
        try:
            import pytesseract  # noqa: F401
            return True
        except ImportError:
            return False

    def _init_paddle(self):
        try:
            from paddleocr import PaddleOCR  # noqa: F401
            return True
        except ImportError:
            return False

    async def extract_text(self, image_data: bytes) -> str:
        """从图片中提取文字"""
        self.last_method = "none"
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))
        except Exception as e:
            _logger.warning("image_open_failed: %s", e)
            return ""

        # Layer 1: Tesseract (0.5-2s)
        if self._tesseract:
            try:
                import pytesseract
                text = pytesseract.image_to_string(img, lang="chi_sim+eng")
                if text.strip():
                    self.last_method = "tesseract"
                    return text.strip()
            except Exception as exc:
                logger.debug("Tesseract OCR 失败: %s", exc)

        # Layer 2: PaddleOCR (1-3s)
        if self._paddle:
            try:
                from paddleocr import PaddleOCR
                ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                import numpy as np
                result = ocr.ocr(np.array(img))
                if result and result[0]:
                    texts = [line[1][0] for line in result[0]]
                    self.last_method = "paddleocr"
                    return "\n".join(texts)
            except Exception as exc:
                logger.debug("PaddleOCR 失败: %s", exc)

        # Layer 3: LLM Vision 回退 (3-8s, 受超时控制)
        # 在测试/无网络/无 API Key 场景下快速降级，避免阻塞
        import asyncio
        if not self._has_vision_key():
            self.last_method = "none"
            return ""
        try:
            result = await asyncio.wait_for(
                self._vision_llm_ocr(img), timeout=self._vision_timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("LLM Vision OCR 超时 (%.1fs)", self._vision_timeout)
            self.last_method = "timeout"
            return ""
        except Exception as exc:
            logger.warning("LLM Vision OCR 失败: %s", exc)
            return ""

    def _has_vision_key(self) -> bool:
        """检测是否存在视觉模型 API Key (避免无效调用)"""
        try:
            from pycoder.providers.auth import get_model_manager

            mm = get_model_manager()
            detected = mm.auto_detect()
            return bool(detected.get("openai") or detected.get("deepseek") or detected.get("agnes"))
        except Exception:
            return False

    async def _vision_llm_ocr(self, image) -> str:
        """使用 LLM 视觉模型进行 OCR"""
        try:
            from pycoder.multimodal.vision_client import get_vision_client
            client = get_vision_client()
            return await client.ocr(image)
        except Exception as exc:
            logger.warning("LLM Vision OCR 失败: %s", exc)
            return ""

    async def detect_code_screenshot(self, image_data: bytes) -> dict:
        """检测是否为代码截图并提取代码"""
        try:
            text = await self.extract_text(image_data)
            code_keywords = [
                "def ", "class ", "import ", "return ", "if __name__",
                "function", "var ", "const ", "let ",
            ]
            is_code = bool(text.strip()) and any(kw in text for kw in code_keywords)
            return {
                "is_code_screenshot": is_code,
                "text": text[:5000] if text else "",
                "confidence": "high" if is_code else "low",
            }
        except Exception as exc:
            return {"is_code_screenshot": False, "text": "", "error": str(exc)}


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_ocr: OCREngine | None = None


def get_ocr_engine() -> OCREngine:
    global _ocr
    if _ocr is None:
        _ocr = OCREngine()
    return _ocr
