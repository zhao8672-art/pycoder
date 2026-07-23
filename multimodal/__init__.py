"""PyCoder 多模态支持 - 根级入口.

支持图像 / OCR / 视觉模型 (GPT-4V, DeepSeek-VL).
完整实现位于 `pycoder.multimodal` 子包, 此处重导出以便根级 `import multimodal` 访问.
"""

from pycoder.multimodal import (
    ImageAnalyzer,
    OCREngine,
    VisionClient,
    MULTIMODAL_TOOLS,
    get_ocr_engine,
    get_vision_client,
)

__version__ = "0.5.0"
__all__ = [
    "ImageAnalyzer",
    "OCREngine",
    "VisionClient",
    "MULTIMODAL_TOOLS",
    "get_ocr_engine",
    "get_vision_client",
    "__version__",
]
