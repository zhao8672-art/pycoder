"""
多模态 REST API 路由
"""

from fastapi import APIRouter

router = APIRouter()


@router.post("/api/media/analyze")
async def media_analyze(req: dict):
    """分析图片"""
    from pycoder.multimodal.tool_definitions import execute_image_analyze
    return await execute_image_analyze(req.get("file_path", ""))


@router.post("/api/media/ocr")
async def media_ocr(req: dict):
    """图片文字识别"""
    from pycoder.multimodal.tool_definitions import execute_image_ocr
    return await execute_image_ocr(req.get("file_path", ""))


@router.post("/api/media/vision")
async def media_vision(req: dict):
    """视觉 AI 理解图片"""
    from pycoder.multimodal.tool_definitions import execute_image_vision
    return await execute_image_vision(
        req.get("file_path", ""),
        req.get("prompt", "描述这张图片"),
    )
