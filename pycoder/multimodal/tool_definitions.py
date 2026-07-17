"""
AI 可调用的多模态工具注册表

向 ChatBridge 注册以下工具:
  - image_analyze    分析图片
  - image_ocr        图片文字识别
  - screenshot_code  代码截图识别
"""

from __future__ import annotations

MULTIMODAL_TOOLS: list[dict] = [
    {
        "name": "image_analyze",
        "description": "分析图片文件：尺寸、格式、颜色分布、文件大小等元数据",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "图片文件的完整路径",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "image_ocr",
        "description": "从图片中提取文字（OCR）。自动使用 Tesseract → PaddleOCR → LLM 逐层降级",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "图片文件的完整路径",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "screenshot_code",
        "description": "检测截图是否包含代码，如果是则提取代码文本",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "截图文件的完整路径",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "image_vision",
        "description": "使用视觉 AI 模型理解图片内容（需要 OpenAI API Key）",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "图片文件的完整路径",
                },
                "prompt": {
                    "type": "string",
                    "description": "对图片的提问或描述要求",
                    "default": "描述这张图片",
                },
            },
            "required": ["file_path"],
        },
    },
]


async def execute_image_analyze(file_path: str) -> dict:
    """执行 image_analyze 工具"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        from pycoder.multimodal.image_analyzer import ImageAnalyzer
        analyzer = ImageAnalyzer()
        result = await analyzer.analyze(data)
        return {"success": True, **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def execute_image_ocr(file_path: str) -> dict:
    """执行 image_ocr 工具"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        from pycoder.multimodal.ocr_engine import get_ocr_engine
        ocr = get_ocr_engine()
        text = await ocr.extract_text(data)
        return {
            "success": True,
            "text": text[:10000],
            "word_count": len(text.split()),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def execute_screenshot_code(file_path: str) -> dict:
    """执行 screenshot_code 工具"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        from pycoder.multimodal.ocr_engine import get_ocr_engine
        ocr = get_ocr_engine()
        result = await ocr.detect_code_screenshot(data)
        return {"success": True, **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def execute_image_vision(file_path: str, prompt: str = "描述这张图片") -> dict:
    """执行 image_vision 工具"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        from pycoder.multimodal.vision_client import get_vision_client
        client = get_vision_client()
        analysis = await client.analyze(data, prompt)
        return {"success": True, "analysis": analysis[:5000]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
