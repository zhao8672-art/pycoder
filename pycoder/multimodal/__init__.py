"""多模态感知模块 — 图片 OCR / 视觉分析 / 截图理解

架构:
  OCREngine ── Layer 1: Tesseract (最快)
           └── Layer 2: PaddleOCR (最准)
           └── Layer 3: LLM Vision 回退

  VisionClient ── GPT-4V / DeepSeek-VL / Qwen-VL 视觉理解

  ImageAnalyzer ── 元数据 / 颜色 / 结构 / 图表分析
"""

from __future__ import annotations

from pycoder.multimodal.ocr_engine import OCREngine, get_ocr_engine
from pycoder.multimodal.vision_client import VisionClient, get_vision_client
from pycoder.multimodal.image_analyzer import ImageAnalyzer
from pycoder.multimodal.tool_definitions import MULTIMODAL_TOOLS

__all__ = [
    "OCREngine",
    "get_ocr_engine",
    "VisionClient",
    "get_vision_client",
    "ImageAnalyzer",
    "MULTIMODAL_TOOLS",
]
