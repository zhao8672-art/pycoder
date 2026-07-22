"""P2-2: 多模态 API（增强版）— 支持文件上传 + 截图智能分析

端点:
- POST /api/multimodal/upload           - 上传图片 (multipart/form-data)
- POST /api/multimodal/analyze          - 上传并分析图片元数据
- POST /api/multimodal/ocr              - 上传并 OCR 文字识别
- POST /api/multimodal/vision           - 上传并调用视觉模型理解
- POST /api/multimodal/screenshot/error - 错误截图智能分析 (UI 报错/异常)
- POST /api/multimodal/screenshot/chart - 图表/数据截图理解

支持能力:
- 多层 OCR (Tesseract → PaddleOCR → LLM 视觉回退)
- 视觉模型 (GPT-4V / DeepSeek-VL / Qwen-VL)
- 错误截图识别 (检测红框/黄底/堆栈文本)
- 图表理解 (折线/柱状/饼图 自动识别)
"""
from __future__ import annotations

import base64
import logging
import re
import time
from io import BytesIO
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/multimodal", tags=["multimodal"])

# 允许的图片格式
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp"}
MAX_SIZE_MB = 20


# ── Pydantic 模型 ──────────────────────────────────────


class VisionRequest(BaseModel):
    image_base64: str = Field(..., description="图片的 base64 编码")
    prompt: str = "描述这张图片"
    prefer: Literal["vision", "ocr", "auto"] = "auto"


class VisionResponse(BaseModel):
    success: bool
    method: str  # "vision" | "ocr" | "metadata"
    content: str
    error: str = ""
    execution_time: float = 0.0
    metadata: dict = Field(default_factory=dict)


class ScreenshotAnalysis(BaseModel):
    is_screenshot: bool
    likely_type: str  # "error" | "ui" | "chart" | "code" | "unknown"
    description: str
    extracted_text: str = ""
    error_keywords: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    suggestions: list[str] = Field(default_factory=list)


# ── 工具函数 ───────────────────────────────────────────


def _validate_image(content_type: str, size: int) -> None:
    """校验图片类型与大小"""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片类型: {content_type}。允许: {', '.join(ALLOWED_TYPES)}",
        )
    if size > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"图片过大: {size/1024/1024:.1f}MB > {MAX_SIZE_MB}MB",
        )


async def _read_image(file: UploadFile) -> bytes:
    """读取并校验上传的图片"""
    content = await file.read()
    _validate_image(file.content_type or "image/png", len(content))
    return content


# ── 端点 ──────────────────────────────────────────────


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)) -> dict:
    """上传图片，返回 base64 + 元数据

    返回的 base64 可供后续 /vision 或 /ocr 调用使用
    """
    content = await _read_image(file)
    return {
        "success": True,
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
        "size_kb": round(len(content) / 1024, 1),
        "image_base64": base64.b64encode(content).decode("ascii"),
    }


@router.post("/analyze")
async def analyze_image(file: UploadFile = File(...)) -> dict:
    """分析图片元数据 (尺寸/颜色/格式)，本地计算"""
    content = await _read_image(file)
    from pycoder.multimodal.image_analyzer import ImageAnalyzer

    analyzer = ImageAnalyzer()
    result = await analyzer.analyze(content)
    result["filename"] = file.filename
    return result


@router.post("/ocr")
async def ocr_image(file: UploadFile = File(...)) -> dict:
    """OCR 文字识别 (多层降级)"""
    content = await _read_image(file)
    start = time.time()

    from pycoder.multimodal.ocr_engine import get_ocr_engine

    engine = get_ocr_engine()
    text = await engine.extract_text(content)

    return {
        "success": True,
        "text": text,
        "method": engine.last_method if hasattr(engine, "last_method") else "unknown",
        "execution_time": round(time.time() - start, 3),
    }


@router.post("/vision", response_model=VisionResponse)
async def vision_analyze(req: VisionRequest) -> VisionResponse:
    """视觉模型理解图片内容"""
    start = time.time()
    try:
        image_data = base64.b64decode(req.image_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Base64 解码失败: {e}")

    from pycoder.multimodal.vision_client import get_vision_client

    client = get_vision_client()
    if req.prefer == "ocr":
        # 强制 OCR 模式
        from pycoder.multimodal.ocr_engine import get_ocr_engine

        engine = get_ocr_engine()
        text = await engine.extract_text(image_data)
        return VisionResponse(
            success=True,
            method="ocr",
            content=text,
            execution_time=round(time.time() - start, 3),
        )
    else:
        content = await client.analyze(image_data, req.prompt)
        return VisionResponse(
            success=not content.startswith("分析失败") and not content.startswith("无可用"),
            method="vision",
            content=content,
            execution_time=round(time.time() - start, 3),
        )


@router.post("/screenshot/error", response_model=ScreenshotAnalysis)
async def analyze_error_screenshot(file: UploadFile = File(...)) -> ScreenshotAnalysis:
    """错误截图智能分析

    自动检测:
    1. 是否为错误弹窗/异常堆栈
    2. 提取错误关键信息
    3. 给出修复建议
    """
    content = await _read_image(file)
    from pycoder.multimodal.image_analyzer import ImageAnalyzer

    analyzer = ImageAnalyzer()
    meta = await analyzer.analyze(content)

    # OCR 提取文字
    from pycoder.multimodal.ocr_engine import get_ocr_engine

    engine = get_ocr_engine()
    text = await engine.extract_text(content)

    # 错误关键词检测
    error_keywords = []
    error_patterns = [
        (r"Error", "Error"),
        (r"Exception", "Exception"),
        (r"Traceback", "Traceback"),
        (r"Failed", "Failed"),
        (r"fatal", "Fatal"),
        (r"SyntaxError", "语法错误"),
        (r"TypeError", "类型错误"),
        (r"ValueError", "值错误"),
        (r"KeyError", "键错误"),
        (r"ImportError|ModuleNotFoundError", "导入错误"),
        (r"PermissionError", "权限错误"),
        (r"TimeoutError", "超时"),
        (r"500|502|503|504", "HTTP 5xx"),
        (r"404|403|401", "HTTP 4xx"),
    ]

    for pat, label in error_patterns:
        if re.search(pat, text, re.IGNORECASE):
            error_keywords.append(label)

    # 判断截图类型
    is_error_screenshot = bool(error_keywords) or meta.get("has_red_tint", False)
    is_chart = "chart" in text.lower() or "数据" in text[:100] and "%" in text
    is_code = "def " in text or "class " in text or "import " in text

    if is_error_screenshot:
        likely_type = "error"
        description = f"检测到错误截图，包含 {len(error_keywords)} 个错误关键词"
    elif is_code:
        likely_type = "code"
        description = "检测到代码截图"
    elif is_chart:
        likely_type = "chart"
        description = "检测到图表/数据截图"
    else:
        likely_type = "ui"
        description = "UI 截图"

    # 计算置信度
    confidence = 0.5
    if error_keywords:
        confidence = min(0.95, 0.6 + len(error_keywords) * 0.1)
    if meta.get("has_red_tint"):
        confidence = min(0.95, confidence + 0.2)

    # 生成建议
    suggestions = []
    if "Traceback" in error_keywords:
        suggestions.append("完整堆栈已提取，建议从堆栈最后一行（非框架代码）开始定位")
    if "500" in str(error_keywords) or "502" in str(error_keywords):
        suggestions.append("服务端内部错误，查看服务端日志")
    if "404" in str(error_keywords):
        suggestions.append("资源不存在，检查 URL/路径是否正确")
    if "ModuleNotFoundError" in str(error_keywords) or "导入错误" in str(error_keywords):
        suggestions.append("缺失模块，运行: pip install <module>")

    return ScreenshotAnalysis(
        is_screenshot=True,
        likely_type=likely_type,
        description=description,
        extracted_text=text[:1000],  # 截断
        error_keywords=error_keywords,
        confidence=round(confidence, 2),
        suggestions=suggestions,
    )


@router.post("/screenshot/chart")
async def analyze_chart(file: UploadFile = File(...)) -> dict:
    """图表/数据截图理解

    提取图表类型、数据趋势、关键数值
    """
    content = await _read_image(file)
    from pycoder.multimodal.vision_client import get_vision_client

    client = get_vision_client()
    prompt = (
        "请分析这张图表：\n"
        "1. 图表类型 (折线/柱状/饼图/散点/其他)\n"
        "2. X/Y 轴标签\n"
        "3. 数据趋势 (上升/下降/波动)\n"
        "4. 关键数值 (最大值/最小值/拐点)\n"
        "5. 异常点 (如有)\n"
    )
    description = await client.analyze(content, prompt)

    # 同时提取文字
    from pycoder.multimodal.ocr_engine import get_ocr_engine

    engine = get_ocr_engine()
    text = await engine.extract_text(content)

    return {
        "success": True,
        "chart_description": description,
        "extracted_text": text[:500],
    }


@router.get("/capabilities")
async def get_capabilities() -> dict:
    """获取当前可用的多模态能力"""
    caps = {
        "image_analyze": True,  # 本地元数据
        "ocr": {
            "tesseract": False,
            "paddleocr": False,
            "vision_fallback": True,
        },
        "vision_models": [],
        "max_size_mb": MAX_SIZE_MB,
        "allowed_types": list(ALLOWED_TYPES),
    }

    # 检测 OCR 引擎
    try:
        import pytesseract  # noqa: F401

        caps["ocr"]["tesseract"] = True
    except ImportError:
        pass

    try:
        from paddleocr import PaddleOCR  # noqa: F401

        caps["ocr"]["paddleocr"] = True
    except ImportError:
        pass

    # 检测视觉模型
    try:
        from pycoder.providers.auth import get_model_manager

        mm = get_model_manager()
        detected = mm.auto_detect()
        for provider in detected:
            if "vision" in provider or provider in ["openai", "deepseek", "qwen"]:
                caps["vision_models"].append(provider)
    except Exception as e:
        logger.debug("vision_model_detect_failed error=%s", e)

    return caps
