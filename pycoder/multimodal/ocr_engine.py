"""
多层 OCR 引擎 — Tesseract → PaddleOCR → LLM 视觉回退

每层比前一层更准确但更慢，按需降级。
"""

from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


class OCREngine:
    """多层 OCR 引擎"""

    def __init__(self):
        self._tesseract = self._init_tesseract()
        self._paddle = self._init_paddle()
        self._vision_client: object = None

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
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))
        except Exception:
            return ""

        # Layer 1: Tesseract (0.5-2s)
        if self._tesseract:
            try:
                import pytesseract
                text = pytesseract.image_to_string(img, lang="chi_sim+eng")
                if text.strip():
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
                    return "\n".join(texts)
            except Exception as exc:
                logger.debug("PaddleOCR 失败: %s", exc)

        # Layer 3: LLM Vision 回退 (3-8s)
        return await self._vision_llm_ocr(img)

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
