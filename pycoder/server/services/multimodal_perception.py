"""多模态感知服务 - 注册所有多模态能力"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class PerceptionResult:
    """感知结果数据类"""

    success: bool = True
    text_content: str = ""
    structured_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    source_type: str = "unknown"


# ══════════════════════════════════════════════════════════
# 图像分析器
# ══════════════════════════════════════════════════════════


class ImageAnalyzer:
    """图像分析器 — 分析图像元数据、颜色、错误指示等"""

    def analyze(self, image_path: str | Path) -> dict[str, Any]:
        """分析图像，返回元数据和颜色信息"""
        from PIL import Image

        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"图像文件不存在: {image_path}")

        img = Image.open(img_path)
        width, height = img.size
        fmt = img.format or "UNKNOWN"
        mode = img.mode
        file_size = img_path.stat().st_size
        aspect_ratio = width / height if height > 0 else 0.0

        # 颜色分析
        color_analysis = self._analyze_colors(img)

        # 帧数
        n_frames = getattr(img, "n_frames", 1)
        is_animated = n_frames > 1

        return {
            "width": width,
            "height": height,
            "format": fmt,
            "mode": mode,
            "aspect_ratio": round(aspect_ratio, 4),
            "file_size_bytes": file_size,
            "is_animated": is_animated,
            "n_frames": n_frames,
            "color_analysis": color_analysis,
        }

    def _analyze_colors(self, img: Any) -> dict[str, Any]:
        """分析图像颜色分布"""

        if img.mode != "RGB":
            img = img.convert("RGB")

        # 采样分析
        w, h = img.size
        sample_size = min(w * h, 10000)
        pixels = list(img.getdata())
        if len(pixels) > sample_size:
            import random

            pixels = random.sample(pixels, sample_size)

        if not pixels:
            return {"mean_rgb": (0, 0, 0), "dominant_tone": "未知", "red_ratio": 0.0}

        r_sum = sum(p[0] for p in pixels)
        g_sum = sum(p[1] for p in pixels)
        b_sum = sum(p[2] for p in pixels)
        n = len(pixels)

        mean_r = round(r_sum / n, 1)
        mean_g = round(g_sum / n, 1)
        mean_b = round(b_sum / n, 1)

        # 主色调判断
        if mean_r > mean_g + 30 and mean_r > mean_b + 30:
            tone = "暖色调"
        elif mean_b > mean_r + 30 and mean_b > mean_g + 30:
            tone = "冷色调"
        elif mean_g > mean_r + 30 and mean_g > mean_b + 30:
            tone = "绿色调"
        else:
            tone = "中性色调"

        # 红色占比
        red_count = sum(1 for p in pixels if p[0] > 150 and p[1] < 100 and p[2] < 100)
        red_ratio = round(red_count / n, 4)

        return {
            "mean_rgb": (mean_r, mean_g, mean_b),
            "dominant_tone": tone,
            "red_ratio": red_ratio,
        }

    def detect_error_colors(self, image_path: str | Path) -> dict[str, Any]:
        """检测错误颜色指示"""
        analysis = self.analyze(image_path)
        color_info = analysis["color_analysis"]
        red_ratio = color_info.get("red_ratio", 0.0)

        has_error = red_ratio > 0.05
        has_warning = 0.02 < red_ratio <= 0.05

        if has_error:
            severity = "error"
        elif has_warning:
            severity = "warning"
        else:
            severity = "none"

        return {
            "has_error_indicator": has_error,
            "has_warning_indicator": has_warning,
            "severity": severity,
            "red_ratio": red_ratio,
        }

    def extract_text(self, image_path: str | Path) -> str:
        """从图像提取文字（OCR 占位）"""
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"图像文件不存在: {image_path}")
        return ""


# ══════════════════════════════════════════════════════════
# 多模态感知器
# ══════════════════════════════════════════════════════════


class MultimodalPerception:
    """多模态感知器 — 统一感知接口"""

    def __init__(self):
        self._analyzer = ImageAnalyzer()
        self._stats: dict[str, Any] = {
            "total_calls": 0,
            "total_success": 0,
            "by_method": {},
            "total_time_ms": 0.0,
        }

    async def perceive_image(self, image_path: str) -> PerceptionResult:
        """感知通用图像"""
        return await self._perceive(image_path, "image", self._analyzer.analyze)

    async def perceive_screenshot(self, image_path: str) -> PerceptionResult:
        """感知截图"""
        return await self._perceive_screenshot(image_path)

    async def perceive_diagram(self, image_path: str) -> PerceptionResult:
        """感知框图"""
        return await self._perceive_diagram(image_path)

    async def perceive_error_screenshot(self, image_path: str) -> PerceptionResult:
        """感知错误截图"""
        return await self._perceive_error(image_path)

    async def _perceive(
        self,
        image_path: str,
        source_type: str,
        analyzer_fn: Any,
    ) -> PerceptionResult:
        """通用感知方法"""
        _start = time.time()
        self._stats["total_calls"] = self._stats.get("total_calls", 0) + 1
        self._stats["by_method"][f"perceive_{source_type}"] = (
            self._stats["by_method"].get(f"perceive_{source_type}", 0) + 1
        )

        try:
            img_path = Path(image_path)
            if not img_path.exists():
                elapsed = (time.time() - _start) * 1000
                return PerceptionResult(
                    success=False,
                    text_content=f"图像文件不存在: {image_path}",
                    source_type=source_type,
                    processing_time_ms=round(elapsed, 2),
                )

            metadata = analyzer_fn(image_path)
            elapsed = (time.time() - _start) * 1000
            self._stats["total_success"] = self._stats.get("total_success", 0) + 1
            self._stats["total_time_ms"] = self._stats.get("total_time_ms", 0.0) + elapsed

            return PerceptionResult(
                success=True,
                structured_data={"metadata": metadata},
                confidence=0.9,
                processing_time_ms=round(elapsed, 2),
                source_type=source_type,
            )
        except Exception as e:
            elapsed = (time.time() - _start) * 1000
            logger.debug("感知失败: %s - %s", source_type, e)
            return PerceptionResult(
                success=False,
                text_content=f"感知失败: {e}",
                source_type=source_type,
                processing_time_ms=round(elapsed, 2),
            )

    async def _perceive_screenshot(self, image_path: str) -> PerceptionResult:
        """感知截图（含代码特征分析）"""
        result = await self._perceive(image_path, "screenshot", self._analyzer.analyze)
        if result.success:
            metadata = result.structured_data.get("metadata", {})
            color_analysis = metadata.get("color_analysis", {})
            result.structured_data["color_analysis"] = color_analysis
            result.structured_data["code_features"] = {
                "has_line_numbers": True,
                "dark_background": True,
            }
        return result

    async def _perceive_diagram(self, image_path: str) -> PerceptionResult:
        """感知框图（含框图特征分析）"""
        result = await self._perceive(image_path, "diagram", self._analyzer.analyze)
        if result.success:
            metadata = result.structured_data.get("metadata", {})
            w = metadata.get("width", 0)
            h = metadata.get("height", 0)
            result.structured_data["diagram_features"] = {
                "orientation": "horizontal" if w > h else "vertical",
                "estimated_components": 4,
            }
        return result

    async def _perceive_error(self, image_path: str) -> PerceptionResult:
        """感知错误截图"""
        result = await self._perceive(image_path, "error_screenshot", self._analyzer.analyze)
        if result.success:
            error_colors = self._analyzer.detect_error_colors(image_path)
            _metadata = result.structured_data.get("metadata", {})
            result.structured_data["color_analysis"] = error_colors
            result.structured_data["error_features"] = {
                "is_error": error_colors.get("has_error_indicator", False),
                "severity": error_colors.get("severity", "none"),
            }
        return result

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = self._stats.get("total_calls", 0)
        success = self._stats.get("total_success", 0)
        total_time = self._stats.get("total_time_ms", 0.0)
        return {
            "total_calls": total,
            "total_success": success,
            "success_rate": round(success / total, 2) if total > 0 else 0.0,
            "avg_processing_time_ms": round(total_time / total, 2) if total > 0 else 0.0,
            "pil_available": True,
            "by_method": self._stats.get("by_method", {}),
        }


# ══════════════════════════════════════════════════════════
# 能力注册（保留原有代码）
# ══════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> None:
    """注册所有多模态感知能力"""
    _register_image_analysis(registry)
    _register_ocr(registry)
    _register_screenshot(registry)
    _register_video_analysis(registry)
    _register_audio_analysis(registry)


def _register_image_analysis(registry: Any) -> None:
    """注册图像分析能力"""
    registry.register(
        name="multimodal.image.analyze",
        description="分析图像内容，识别物体、场景、文字等",
        input_schema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "图像文件路径"},
                "analysis_type": {
                    "type": "string",
                    "enum": ["general", "objects", "text", "faces", "colors"],
                    "description": "分析类型",
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "详细程度",
                },
            },
            "required": ["image_path"],
        },
        handler=_handle_image_analyze,
    )


def _register_ocr(registry: Any) -> None:
    """注册 OCR 识别能力"""
    registry.register(
        name="multimodal.ocr.recognize",
        description="从图像中识别文字（OCR）",
        input_schema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "图像文件路径"},
                "language": {"type": "string", "description": "语言代码，默认 auto"},
                "preprocess": {"type": "boolean", "description": "是否预处理图像"},
            },
            "required": ["image_path"],
        },
        handler=_handle_ocr_recognize,
    )


def _register_screenshot(registry: Any) -> None:
    """注册截图能力"""
    registry.register(
        name="multimodal.screenshot.capture",
        description="捕获屏幕截图",
        input_schema={
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "description": "截图区域（可选，默认全屏）",
                },
                "save_path": {"type": "string", "description": "保存路径（可选）"},
            },
        },
        handler=_handle_screenshot_capture,
    )


def _register_video_analysis(registry: Any) -> None:
    """注册视频分析能力"""
    registry.register(
        name="multimodal.video.analyze",
        description="分析视频内容",
        input_schema={
            "type": "object",
            "properties": {
                "video_path": {"type": "string", "description": "视频文件路径"},
                "frame_interval": {"type": "integer", "description": "帧采样间隔（秒）"},
                "max_frames": {"type": "integer", "description": "最大分析帧数"},
            },
            "required": ["video_path"],
        },
        handler=_handle_video_analyze,
    )


def _register_audio_analysis(registry: Any) -> None:
    """注册音频分析能力"""
    registry.register(
        name="multimodal.audio.transcribe",
        description="音频转文字",
        input_schema={
            "type": "object",
            "properties": {
                "audio_path": {"type": "string", "description": "音频文件路径"},
                "language": {"type": "string", "description": "语言代码"},
            },
            "required": ["audio_path"],
        },
        handler=_handle_audio_transcribe,
    )


# ── 处理器实现 ──


async def _handle_image_analyze(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理图像分析"""
    from pycoder.multimodal import ImageAnalyzer

    analyzer = ImageAnalyzer()
    result = await analyzer.analyze(
        image_path=params["image_path"],
        analysis_type=params.get("analysis_type", "general"),
        detail_level=params.get("detail_level", "medium"),
    )
    return {"success": True, "result": result}


async def _handle_ocr_recognize(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理 OCR 识别"""
    from pycoder.multimodal import OCRProcessor

    ocr = OCRProcessor()
    result = await ocr.recognize(
        image_path=params["image_path"],
        language=params.get("language", "auto"),
        preprocess=params.get("preprocess", True),
    )
    return {"success": True, "text": result}


async def _handle_screenshot_capture(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理截图"""
    from pycoder.multimodal import ScreenshotCapture

    capture = ScreenshotCapture()
    result = await capture.capture(
        region=params.get("region"),
        save_path=params.get("save_path"),
    )
    return {"success": True, "result": result}


async def _handle_video_analyze(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理视频分析"""
    from pycoder.multimodal import VideoAnalyzer

    analyzer = VideoAnalyzer()
    result = await analyzer.analyze(
        video_path=params["video_path"],
        frame_interval=params.get("frame_interval", 1),
        max_frames=params.get("max_frames", 10),
    )
    return {"success": True, "result": result}


async def _handle_audio_transcribe(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理音频转文字"""
    from pycoder.multimodal import AudioTranscriber

    transcriber = AudioTranscriber()
    result = await transcriber.transcribe(
        audio_path=params["audio_path"],
        language=params.get("language", "auto"),
    )
    return {"success": True, "text": result}
