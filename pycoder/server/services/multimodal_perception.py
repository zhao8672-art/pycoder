"""
多模态感知模块 — 屏幕/图像识别与代码截图理解

提供以下功能：
- 通用图像分析（尺寸、格式、颜色分布）
- 代码截图 OCR 识别
- 架构图/流程图分析
- 错误截图检测（红色=错误，黄色=警告）
- 感知统计信息

依赖：
- PIL/Pillow（必需）: 图像处理基础
- pytesseract（可选）: OCR 文字提取
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger('pycoder.server.services.multimodal_perception')

from typing import Any

logger = logging.getLogger(__name__)

# ── PIL/Pillow 导入（必需） ──
try:
    from PIL import Image, ImageStat

    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL/Pillow 未安装，多模态感知功能将受限。请执行: pip install Pillow")

# ── pytesseract 导入（可选 OCR） ──
try:
    import pytesseract

    HAS_TESSERACT = True
except ImportError:
    pytesseract = None  # type: ignore
    HAS_TESSERACT = False
    logger.info("pytesseract 未安装，OCR 文字提取不可用。请执行: pip install pytesseract")

# ── numpy 导入（可选，用于高级颜色分析） ──
try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False


# ══════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════


@dataclass
class PerceptionResult:
    """感知结果"""

    success: bool
    text_content: str = ""
    structured_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    source_type: str = "unknown"


# ══════════════════════════════════════════════════════════
# 图像分析器
# ══════════════════════════════════════════════════════════


class ImageAnalyzer:
    """图像分析器 — 使用 PIL/Pillow 进行基础图像分析"""

    # 错误检测颜色阈值（RGB）
    ERROR_RED_RANGE: tuple[int, int] = (180, 255)  # R 通道高值
    WARNING_YELLOW_RANGE: tuple[int, int] = (180, 255)  # R+G 通道高值，B 通道低值
    ERROR_COLOR_CHECK_SAMPLE: int = 1000  # 采样像素数

    def __init__(self):
        if not HAS_PIL:
            raise RuntimeError("PIL/Pillow 未安装，无法使用 ImageAnalyzer")

    def analyze(self, image_path: str | Path) -> dict[str, Any]:
        """分析图像基础属性。

        Args:
            image_path: 图像文件路径

        Returns:
            包含图像元数据的字典
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"图像文件不存在: {path}")

        img = Image.open(path)
        result: dict[str, Any] = {
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
            "format": img.format or "未知",
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "aspect_ratio": round(img.width / img.height, 3) if img.height > 0 else 0,
            "is_animated": getattr(img, "is_animated", False),
            "n_frames": getattr(img, "n_frames", 1),
            "dpi": img.info.get("dpi", None),
            "exif": self._extract_exif(img),
            "color_analysis": self._analyze_colors(img),
        }
        img.close()
        return result

    def extract_text(self, image_path: str | Path) -> dict[str, Any]:
        """使用 OCR 从图像中提取文字。

        Args:
            image_path: 图像文件路径

        Returns:
            包含提取文字和置信度的字典
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"图像文件不存在: {path}")

        if not HAS_TESSERACT:
            return {"text": "", "error": "pytesseract 未安装，OCR 不可用", "confidence": 0.0}

        try:
            img = Image.open(path)
            # 英文 + 中文混合识别
            text = pytesseract.image_to_string(img, lang="eng+chi_sim")
            # 获取置信度数据
            data = pytesseract.image_to_data(
                img, lang="eng+chi_sim", output_type=pytesseract.Output.DICT
            )
            confidences = [
                int(c) for c in data.get("conf", []) if c != "-1" and c != "-1"
            ]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            img.close()

            return {
                "text": text.strip(),
                "confidence": round(avg_confidence / 100.0, 3),
                "word_count": len(text.strip().split()) if text.strip() else 0,
                "char_count": len(text.strip()),
            }
        except Exception as e:
            logger.warning("OCR 文字提取失败: %s", e)
            return {"text": "", "error": str(e), "confidence": 0.0}

    def detect_error_colors(self, image_path: str | Path) -> dict[str, Any]:
        """检测图像中的错误/警告颜色区域。

        红色像素 → 可能表示错误信息
        黄色像素 → 可能表示警告信息

        Args:
            image_path: 图像文件路径

        Returns:
            包含错误/警告颜色分析结果的字典
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"图像文件不存在: {path}")

        img = Image.open(path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        # 缩小图像以加速分析
        scale = max(1, min(img.width, img.height) // 200)
        small = img.resize((img.width // scale, img.height // scale))
        pixels = list(small.getdata())
        img.close()

        total = len(pixels)
        red_pixels = 0
        yellow_pixels = 0

        for p in pixels:
            r, g, b = p[0], p[1], p[2]
            # 红色检测：R 通道明显高于 G 和 B
            if r > 180 and r > g * 1.5 and r > b * 1.5:
                red_pixels += 1
            # 黄色检测：R 和 G 通道都高，B 通道低
            elif r > 180 and g > 150 and b < 100:
                yellow_pixels += 1

        red_ratio = round(red_pixels / total, 4) if total > 0 else 0.0
        yellow_ratio = round(yellow_pixels / total, 4) if total > 0 else 0.0

        # 判断是否包含错误/警告
        has_error = red_ratio > 0.05
        has_warning = yellow_ratio > 0.05
        severity = "none"
        if has_error:
            severity = "error"
        elif has_warning:
            severity = "warning"

        return {
            "total_pixels": total,
            "red_pixels": red_pixels,
            "yellow_pixels": yellow_pixels,
            "red_ratio": red_ratio,
            "yellow_ratio": yellow_ratio,
            "has_error_indicator": has_error,
            "has_warning_indicator": has_warning,
            "severity": severity,
        }

    @staticmethod
    def _extract_exif(img: Image.Image) -> dict[str, Any]:
        """提取 EXIF 元数据"""
        try:
            exif_data = img._getexif()
            if exif_data is None:
                return {}
            # 提取常用字段
            tags = {
                271: "make",
                272: "model",
                306: "datetime",
                36867: "datetime_original",
                40962: "width",
                40963: "height",
            }
            result: dict[str, Any] = {}
            for tag_id, name in tags.items():
                val = exif_data.get(tag_id)
                if val is not None:
                    result[name] = str(val)
            return result
        except Exception as e:
            _logger.warning("silently_swallowed: {err}", exc_info=False)
            return {}

    def _analyze_colors(self, img: Image.Image) -> dict[str, Any]:
        """分析图像颜色统计"""
        if img.mode not in ("RGB", "RGBA"):
            try:
                img = img.convert("RGB")
            except Exception as e:
                _logger.warning("silently_swallowed: {err}", exc_info=False)
                return {"error": "无法转换为 RGB 模式"}

        try:
            stat = ImageStat.Stat(img)
            if stat.mean is None:
                return {"error": "无法计算颜色统计"}

            mean_r = round(stat.mean[0], 1) if len(stat.mean) > 0 else 0.0
            mean_g = round(stat.mean[1], 1) if len(stat.mean) > 1 else 0.0
            mean_b = round(stat.mean[2], 1) if len(stat.mean) > 2 else 0.0

            # 判断整体色调
            if mean_r > mean_g + 30 and mean_r > mean_b + 30:
                dominant = "暖色调（偏红）"
            elif mean_b > mean_r + 30 and mean_b > mean_g + 30:
                dominant = "冷色调（偏蓝）"
            elif mean_g > mean_r + 30 and mean_g > mean_b + 30:
                dominant = "偏绿"
            elif abs(mean_r - mean_g) < 20 and abs(mean_r - mean_b) < 20:
                dominant = "中性灰"
            else:
                dominant = "混合色调"

            return {
                "mean_rgb": (mean_r, mean_g, mean_b),
                "dominant_tone": dominant,
            }
        except Exception as e:
            logger.debug("颜色分析失败: %s", e)
            return {"error": str(e)}


# ══════════════════════════════════════════════════════════
# 多模态感知
# ══════════════════════════════════════════════════════════


class MultimodalPerception:
    """多模态感知引擎 — 整合图像分析、OCR 和错误检测"""

    def __init__(self):
        if not HAS_PIL:
            raise RuntimeError("PIL/Pillow 未安装，无法使用 MultimodalPerception")
        self._analyzer = ImageAnalyzer()
        # 统计信息
        self._stats: dict[str, int] = defaultdict(int)
        self._total_processing_time_ms: float = 0.0

    async def perceive_image(self, image_path: str) -> PerceptionResult:
        """分析通用图像，提取基础属性和文字内容。

        Args:
            image_path: 图像文件路径

        Returns:
            PerceptionResult 感知结果
        """
        start = time.monotonic()
        try:
            path = Path(image_path)
            if not path.exists():
                return PerceptionResult(
                    success=False,
                    text_content=f"文件不存在: {image_path}",
                    source_type="image",
                )

            # 图像元数据
            meta = self._analyzer.analyze(path)

            # OCR 文字提取
            ocr_result = self._analyzer.extract_text(path)

            structured = {
                "metadata": meta,
                "ocr": ocr_result,
                "image_type": self._guess_image_type(path, meta),
            }

            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_image", processing_time, success=True)

            return PerceptionResult(
                success=True,
                text_content=ocr_result.get("text", ""),
                structured_data=structured,
                confidence=ocr_result.get("confidence", 0.0),
                processing_time_ms=round(processing_time, 2),
                source_type="image",
            )
        except Exception as e:
            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_image", processing_time, success=False)
            logger.error("图像分析失败 [%s]: %s", image_path, e)
            return PerceptionResult(
                success=False,
                text_content=str(e),
                processing_time_ms=round(processing_time, 2),
                source_type="image",
            )

    async def perceive_screenshot(self, image_path: str) -> PerceptionResult:
        """分析代码截图，提取代码文字。

        针对代码截图特别优化：
        - 使用 OCR 提取代码文字
        - 判断是否包含代码特征（缩进、关键字等）

        Args:
            image_path: 截图文件路径

        Returns:
            PerceptionResult 感知结果
        """
        start = time.monotonic()
        try:
            path = Path(image_path)
            if not path.exists():
                return PerceptionResult(
                    success=False,
                    text_content=f"文件不存在: {image_path}",
                    source_type="screenshot",
                )

            # 图像元数据
            meta = self._analyzer.analyze(path)

            # OCR 文字提取
            ocr_result = self._analyzer.extract_text(path)
            extracted_text = ocr_result.get("text", "")

            # 代码特征检测
            code_features = self._detect_code_features(extracted_text)

            # 错误颜色检测
            color_analysis = self._analyzer.detect_error_colors(path)

            structured = {
                "metadata": meta,
                "ocr": ocr_result,
                "code_features": code_features,
                "color_analysis": color_analysis,
                "is_code_screenshot": code_features.get("is_likely_code", False),
            }

            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_screenshot", processing_time, success=True)

            return PerceptionResult(
                success=True,
                text_content=extracted_text,
                structured_data=structured,
                confidence=ocr_result.get("confidence", 0.0),
                processing_time_ms=round(processing_time, 2),
                source_type="screenshot",
            )
        except Exception as e:
            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_screenshot", processing_time, success=False)
            logger.error("截图分析失败 [%s]: %s", image_path, e)
            return PerceptionResult(
                success=False,
                text_content=str(e),
                processing_time_ms=round(processing_time, 2),
                source_type="screenshot",
            )

    async def perceive_diagram(self, image_path: str) -> PerceptionResult:
        """分析架构图/流程图/示意图。

        Args:
            image_path: 图像文件路径

        Returns:
            PerceptionResult 感知结果
        """
        start = time.monotonic()
        try:
            path = Path(image_path)
            if not path.exists():
                return PerceptionResult(
                    success=False,
                    text_content=f"文件不存在: {image_path}",
                    source_type="diagram",
                )

            # 图像元数据
            meta = self._analyzer.analyze(path)

            # OCR 文字提取
            ocr_result = self._analyzer.extract_text(path)

            # 颜色分析
            color_analysis = self._analyzer.detect_error_colors(path)

            # 框图特征分析
            diagram_features = self._analyze_diagram_features(meta, ocr_result)

            structured = {
                "metadata": meta,
                "ocr": ocr_result,
                "color_analysis": color_analysis,
                "diagram_features": diagram_features,
            }

            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_diagram", processing_time, success=True)

            return PerceptionResult(
                success=True,
                text_content=ocr_result.get("text", ""),
                structured_data=structured,
                confidence=ocr_result.get("confidence", 0.0),
                processing_time_ms=round(processing_time, 2),
                source_type="diagram",
            )
        except Exception as e:
            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_diagram", processing_time, success=False)
            logger.error("框图分析失败 [%s]: %s", image_path, e)
            return PerceptionResult(
                success=False,
                text_content=str(e),
                processing_time_ms=round(processing_time, 2),
                source_type="diagram",
            )

    async def perceive_error_screenshot(self, image_path: str) -> PerceptionResult:
        """分析错误截图，检测错误类型和严重程度。

        Args:
            image_path: 截图文件路径

        Returns:
            PerceptionResult 感知结果
        """
        start = time.monotonic()
        try:
            path = Path(image_path)
            if not path.exists():
                return PerceptionResult(
                    success=False,
                    text_content=f"文件不存在: {image_path}",
                    source_type="error_screenshot",
                )

            # 图像元数据
            meta = self._analyzer.analyze(path)

            # OCR 文字提取
            ocr_result = self._analyzer.extract_text(path)
            extracted_text = ocr_result.get("text", "")

            # 错误颜色检测
            color_analysis = self._analyzer.detect_error_colors(path)

            # 错误文本特征提取
            error_features = self._extract_error_features(extracted_text)

            structured = {
                "metadata": meta,
                "ocr": ocr_result,
                "color_analysis": color_analysis,
                "error_features": error_features,
                "severity": color_analysis.get("severity", "unknown"),
                "has_error_indicators": (
                    color_analysis.get("has_error_indicator", False)
                    or error_features.get("has_error_keywords", False)
                ),
            }

            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_error_screenshot", processing_time, success=True)

            return PerceptionResult(
                success=True,
                text_content=extracted_text,
                structured_data=structured,
                confidence=ocr_result.get("confidence", 0.0),
                processing_time_ms=round(processing_time, 2),
                source_type="error_screenshot",
            )
        except Exception as e:
            processing_time = (time.monotonic() - start) * 1000
            self._record_stats("perceive_error_screenshot", processing_time, success=False)
            logger.error("错误截图分析失败 [%s]: %s", image_path, e)
            return PerceptionResult(
                success=False,
                text_content=str(e),
                processing_time_ms=round(processing_time, 2),
                source_type="error_screenshot",
            )

    def get_stats(self) -> dict[str, Any]:
        """获取感知统计信息。

        Returns:
            包含各方法调用次数、成功率、平均耗时等统计
        """
        total_calls = sum(self._stats.values())
        total_success = sum(
            v for k, v in self._stats.items() if k.startswith("success_")
        )
        success_rate = (
            round(total_success / total_calls, 3) if total_calls > 0 else 0.0
        )
        avg_time = (
            round(self._total_processing_time_ms / total_calls, 2)
            if total_calls > 0
            else 0.0
        )

        return {
            "total_calls": total_calls,
            "total_success": total_success,
            "success_rate": success_rate,
            "avg_processing_time_ms": avg_time,
            "total_processing_time_ms": round(self._total_processing_time_ms, 2),
            "by_method": {
                "perceive_image": self._stats.get("perceive_image", 0),
                "perceive_screenshot": self._stats.get("perceive_screenshot", 0),
                "perceive_diagram": self._stats.get("perceive_diagram", 0),
                "perceive_error_screenshot": self._stats.get("perceive_error_screenshot", 0),
            },
            "ocr_available": HAS_TESSERACT,
            "pil_available": HAS_PIL,
        }

    # ── 内部方法 ──

    def _record_stats(self, method: str, processing_time_ms: float, *, success: bool) -> None:
        """记录统计信息"""
        self._stats[method] += 1
        if success:
            self._stats[f"success_{method}"] += 1
        self._total_processing_time_ms += processing_time_ms

    @staticmethod
    def _guess_image_type(path: Path, meta: dict[str, Any]) -> str:
        """根据文件名和元数据推测图像类型"""
        name = path.name.lower()
        if "screenshot" in name or "屏幕截图" in name:
            return "screenshot"
        elif "error" in name or "错误" in name or "bug" in name:
            return "error_screenshot"
        elif any(kw in name for kw in ("diagram", "架构", "流程图", "架构图", "flowchart", "arch")):
            return "diagram"
        elif "code" in name or "代码" in name:
            return "code_screenshot"
        else:
            return "general_image"

    @staticmethod
    def _detect_code_features(text: str) -> dict[str, Any]:
        """检测文本是否包含代码特征。

        Args:
            text: OCR 提取的文本

        Returns:
            代码特征检测结果
        """
        if not text.strip():
            return {"is_likely_code": False, "features": []}

        features: list[str] = []
        code_keywords = [
            "def ", "class ", "import ", "from ", "return ", "if ", "for ", "while ",
            "try:", "except", "async ", "await ", "yield ", "print(", "lambda ",
            "function", "const ", "let ", "var ", "public ", "private ", "protected ",
            "func ", "package ", "fn ", "struct ", "impl ",
        ]
        code_symbols = ["{", "}", "=>", "->", "::", "===", "!==", "&&", "||"]

        lines = text.split("\n")
        has_indentation = any(line.startswith("    ") or line.startswith("\t") for line in lines)
        if has_indentation:
            features.append("缩进对齐")

        for kw in code_keywords:
            if kw in text:
                features.append(f"关键字: {kw.strip()}")
                break

        for sym in code_symbols:
            if sym in text:
                features.append(f"符号: {sym}")
                break

        # 检查是否包含常见编程符号
        if any(c in text for c in "(){}[];="):
            if "符号" not in str(features):
                features.append("编程符号")

        is_likely_code = len(features) >= 2

        # 推测编程语言
        lang = "unknown"
        if "def " in text or "import " in text:
            lang = "Python"
        elif "function" in text or "const " in text or "let " in text:
            lang = "JavaScript/TypeScript"
        elif "public class" in text or "private " in text:
            lang = "Java"
        elif "func " in text or "package " in text:
            lang = "Go"
        elif "fn " in text or "struct " in text:
            lang = "Rust"

        return {
            "is_likely_code": is_likely_code,
            "features": features,
            "estimated_language": lang,
            "line_count": len(lines),
        }

    @staticmethod
    def _analyze_diagram_features(
        meta: dict[str, Any], ocr_result: dict[str, Any]
    ) -> dict[str, Any]:
        """分析框图特征"""
        text = ocr_result.get("text", "")
        features: dict[str, Any] = {
            "has_text": bool(text.strip()),
            "text_labels": [],
            "estimated_components": 0,
        }

        # 提取可能的标签（每行非空文本作为一个组件标签）
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if lines:
            features["text_labels"] = lines[:20]  # 最多保留 20 个标签
            features["estimated_components"] = len(lines)

        # 基于宽高比推测图像类型
        ratio = meta.get("aspect_ratio", 1.0)
        if ratio > 1.5:
            features["orientation"] = "横向"
        elif ratio < 0.67:
            features["orientation"] = "纵向"
        else:
            features["orientation"] = "近方形"

        return features

    @staticmethod
    def _extract_error_features(text: str) -> dict[str, Any]:
        """从文本中提取错误特征。

        Args:
            text: OCR 提取的文本

        Returns:
            错误特征字典
        """
        error_keywords = [
            "error", "Error", "ERROR", "错误", "异常",
            "exception", "Exception", "EXCEPTION",
            "traceback", "Traceback", "TRACEBACK",
            "failed", "Failed", "FAILED", "失败",
            "fatal", "Fatal", "FATAL",
            "warning", "Warning", "WARNING", "警告",
            "timeout", "Timeout", "TIMEOUT",
            "refused", "Refused", "denied", "Denied",
            "not found", "Not Found", "NOT FOUND",
            "permission", "Permission",
            "segmentation fault", "SIGSEGV",
            "out of memory", "OOM",
            "null pointer", "NullPointer",
            "undefined", "Undefined",
        ]

        found_keywords: list[str] = []
        text_lower = text.lower()

        for kw in error_keywords:
            if kw.lower() in text_lower:
                found_keywords.append(kw)

        # 提取可能的错误行号
        import re

        line_numbers = re.findall(r"(?:line|行)\s*[:#]?\s*(\d+)", text, re.IGNORECASE)

        # 提取可能的文件路径
        _path_re = r'(?:File|文件)\s*["\']?([^"\'\n]+\.(?:py|js|ts|java|go|rs|cpp|c|h))["\']?'
        file_paths = re.findall(_path_re, text)

        return {
            "has_error_keywords": len(found_keywords) > 0,
            "found_keywords": found_keywords[:10],  # 最多保留 10 个
            "error_count": len(found_keywords),
            "line_numbers": line_numbers[:5],
            "referenced_files": file_paths[:5],
            "error_type": _classify_error(found_keywords),
        }


def _classify_error(keywords: list[str]) -> str:
    """根据关键词分类错误类型"""
    kw_lower = [k.lower() for k in keywords]
    all_kw = " ".join(kw_lower)

    if any(k in all_kw for k in ("timeout", "超时")):
        return "超时错误"
    elif any(k in all_kw for k in ("permission", "denied", "权限")):
        return "权限错误"
    elif any(k in all_kw for k in ("not found", "404")):
        return "资源未找到"
    elif any(k in all_kw for k in ("out of memory", "oom", "内存")):
        return "内存不足"
    elif any(k in all_kw for k in ("null pointer", "nullpointer", "undefined")):
        return "空指针/未定义"
    elif any(k in all_kw for k in ("segmentation fault", "sigsegv")):
        return "段错误"
    elif any(k in all_kw for k in ("traceback", "exception", "异常")):
        return "程序异常"
    elif any(k in all_kw for k in ("refused", "connect", "连接")):
        return "连接错误"
    elif any(k in all_kw for k in ("warning", "警告")):
        return "警告"
    elif len(keywords) > 0:
        return "一般错误"
    else:
        return "未知"


# ══════════════════════════════════════════════════════════
# P2-1: 视觉模型客户端 (Vision Model Client)
# 对标 Codex Computer Use — 调用 GPT-4V/Claude Vision 进行语义理解
# ══════════════════════════════════════════════════════════


@dataclass
class VisionResult:
    """视觉模型分析结果"""

    description: str = ""
    objects: list[dict[str, Any]] = field(default_factory=list)
    text_content: str = ""
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    source_type: str = "vision_model"
    model: str = ""
    processing_time_ms: float = 0.0


class VisionModelClient:
    """视觉模型客户端 — 调用 GPT-4V/Claude Vision 进行图像语义理解

    对标 Codex 的屏幕视觉识别能力，支持:
    - 图像内容语义描述
    - 对象检测与分类
    - UI 元素识别（按钮、输入框、菜单、图标等）
    - 代码/错误截图深度理解
    - 屏幕截图前后对比分析
    """

    # 默认视觉模型配置
    _DEFAULT_VISION_MODEL = "gpt-4o"
    _DEFAULT_VISION_PROVIDER = "openai"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        self._model = model or self._DEFAULT_VISION_MODEL
        self._api_key = api_key
        self._api_base = api_base

    async def analyze(
        self,
        image_path: str | Path,
        prompt: str = "",
        *,
        detail: str = "auto",
    ) -> VisionResult:
        """使用视觉模型分析图像内容。

        Args:
            image_path: 图像文件路径
            prompt: 可选的引导提示词
            detail: 图像细节级别 (auto/low/high)

        Returns:
            VisionResult 分析结果
        """
        start = time.monotonic()
        path = Path(image_path)
        if not path.exists():
            return VisionResult(
                description=f"文件不存在: {image_path}",
                processing_time_ms=(time.monotonic() - start) * 1000,
            )

        try:
            import base64

            # 读取并编码图像
            ext = path.suffix.lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
            }
            mime = mime_map.get(ext, "image/png")
            image_data = base64.b64encode(path.read_bytes()).decode()

            system_prompt = (
                "你是一个专业的计算机视觉分析助手。请详细描述图像内容，"
                "包括：1) 整体场景和布局 2) 关键文本和数字 3) 可交互的UI元素 4) 颜色和视觉层次。"
                "如果图像包含代码，请识别编程语言和关键逻辑。"
                "如果图像包含错误信息，请提取错误类型、行号和堆栈。"
                "以结构化的 JSON 格式返回结果。"
            )

            user_content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{image_data}",
                        "detail": detail,
                    },
                }
            ]
            if prompt:
                user_content.append({"type": "text", "text": prompt})

            # 尝试使用 AGNES 视觉模型（免费 + OpenAI 兼容）
            result = await self._call_vision_api(system_prompt, user_content)
            processing_time = (time.monotonic() - start) * 1000
            result.processing_time_ms = round(processing_time, 2)
            result.model = self._model
            return result

        except Exception as e:
            logger.warning("视觉模型分析失败: %s", e)
            processing_time = (time.monotonic() - start) * 1000
            return VisionResult(
                description=f"分析失败: {e}",
                processing_time_ms=round(processing_time, 2),
                model=self._model,
            )

    async def detect_ui_elements(
        self,
        image_path: str | Path,
    ) -> VisionResult:
        """检测图像中的 UI 元素（按钮、输入框、菜单、图标等）。

        对标 Codex Computer Use 的 UI 元素识别能力。

        Args:
            image_path: 截图文件路径

        Returns:
            VisionResult 包含 UI 元素列表和坐标
        """
        prompt = (
            "请识别图像中的所有 UI 元素，包括：\n"
            "1. 按钮 (button) — 文字、位置、颜色、状态\n"
            "2. 输入框 (input/textfield) — 标签、占位符、当前值\n"
            "3. 下拉菜单 (dropdown/select) — 选项列表\n"
            "4. 复选框/单选框 (checkbox/radio) — 标签、选中状态\n"
            "5. 导航菜单 (navigation/menu) — 菜单项\n"
            "6. 标签页 (tab) — 标签名称、当前激活\n"
            "7. 对话框/弹窗 (dialog/modal) — 标题、内容、按钮\n"
            "8. 表格/列表 (table/list) — 列标题、行数\n"
            "9. 图标 (icon) — 类型推测\n"
            "10. 链接 (link) — 文字、目标推测\n\n"
            "返回 JSON 格式: {\"ui_elements\": [{\"type\":\"...\", \"label\":\"...\", "
            "\"position\":\"top-left|center|...\", \"state\":\"...\", \"text\":\"...\"}], "
            "\"overall_layout\": \"...\", \"primary_action\": \"...\"}"
        )
        return await self.analyze(image_path, prompt=prompt)

    async def compare_screenshots(
        self,
        before_path: str | Path,
        after_path: str | Path,
    ) -> VisionResult:
        """对比两张截图，分析前后差异。

        对标 Codex 的屏幕变化检测，用于验证操作结果。

        Args:
            before_path: 操作前截图
            after_path: 操作后截图

        Returns:
            VisionResult 包含差异分析
        """
        before = Path(before_path)
        after = Path(after_path)
        if not before.exists():
            return VisionResult(description=f"文件不存在: {before_path}")
        if not after.exists():
            return VisionResult(description=f"文件不存在: {after_path}")

        import base64

        before_data = base64.b64encode(before.read_bytes()).decode()
        after_data = base64.b64encode(after.read_bytes()).decode()

        ext_b = before.suffix.lower()
        ext_a = after.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_b = mime_map.get(ext_b, "image/png")
        mime_a = mime_map.get(ext_a, "image/png")

        system_prompt = (
            "你是一个专业的 UI 变化检测分析助手。对比两张截图，"
            "分析操作前后的差异，重点关注：新增/消失的元素、文本变化、颜色变化、布局变化。"
            "返回 JSON: {\"changes\": [...], \"summary\": \"...\"}"
        )

        user_content = [
            {"type": "text", "text": "操作前截图:"},
            {"type": "image_url", "image_url": {"url": f"data:{mime_b};base64,{before_data}"}},
            {"type": "text", "text": "操作后截图:"},
            {"type": "image_url", "image_url": {"url": f"data:{mime_a};base64,{after_data}"}},
        ]

        start = time.monotonic()
        try:
            result = await self._call_vision_api(system_prompt, user_content)
            result.processing_time_ms = round((time.monotonic() - start) * 1000, 2)
            result.model = self._model
            result.source_type = "screenshot_diff"
            return result
        except Exception as e:
            logger.warning("截图对比分析失败: %s", e)
            return VisionResult(
                description=f"对比失败: {e}",
                processing_time_ms=round((time.monotonic() - start) * 1000, 2),
                model=self._model,
            )

    async def _call_vision_api(
        self,
        system_prompt: str,
        user_content: list[dict[str, Any]],
    ) -> VisionResult:
        """调用视觉模型 API（OpenAI 兼容格式）。

        优先使用 AGNES 免费模型，回退到配置的视觉模型。
        """
        import json as _json

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        request_body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.1,
        }

        # 尝试使用 AGNES 视觉模型（免费）
        headers: dict[str, str] = {"Content-Type": "application/json"}
        api_base = self._api_base or "https://apihub.agnes-ai.com/v1"

        # 获取 API key
        import os

        api_key = self._api_key
        if not api_key:
            api_key = os.environ.get("AGNES_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    headers=headers,
                    json=request_body,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"].get("content", "")
                    return self._parse_vision_response(content)
                else:
                    logger.warning(
                        "视觉模型 API 错误: status=%d, body=%s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    return VisionResult(
                        description=f"API 错误: {resp.status_code}",
                    )
        except Exception as e:
            logger.warning("视觉模型调用失败: %s", e)
            # 回退到本地分析
            return self._fallback_local_analysis(user_content)

    def _parse_vision_response(self, content: str) -> VisionResult:
        """解析视觉模型响应，提取结构化结果"""
        import json as _json
        import re

        result = VisionResult(description=content[:500])

        # 尝试提取 JSON
        try:
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                parsed = _json.loads(json_match.group())
                if "ui_elements" in parsed:
                    result.ui_elements = parsed["ui_elements"]
                if "description" in parsed:
                    result.description = parsed["description"]
                if "objects" in parsed:
                    result.objects = parsed["objects"]
                if "text_content" in parsed:
                    result.text_content = parsed["text_content"]
        except (_json.JSONDecodeError, KeyError):
            pass

        return result

    def _fallback_local_analysis(
        self,
        user_content: list[dict[str, Any]],
    ) -> VisionResult:
        """视觉模型不可用时的本地回退分析"""
        # 尝试从 user_content 中提取图像进行本地分析
        for item in user_content:
            if isinstance(item, dict) and item.get("type") == "image_url":
                url = item["image_url"]["url"]
                if url.startswith("data:"):
                    # 解码 base64 图像进行本地分析
                    import base64
                    import tempfile

                    try:
                        data_part = url.split(",", 1)[1]
                        img_bytes = base64.b64decode(data_part)
                        with tempfile.NamedTemporaryFile(
                            suffix=".png", delete=False
                        ) as tmp:
                            tmp.write(img_bytes)
                            tmp_path = tmp.name

                        analyzer = ImageAnalyzer()
                        meta = analyzer.analyze(tmp_path)
                        ocr = analyzer.extract_text(tmp_path)
                        colors = analyzer.detect_error_colors(tmp_path)

                        Path(tmp_path).unlink(missing_ok=True)

                        return VisionResult(
                            description=f"本地分析 (回退模式): {meta.get('width')}x{meta.get('height')}, "
                            f"格式: {meta.get('format')}",
                            text_content=ocr.get("text", ""),
                            source_type="fallback_local",
                        )
                    except Exception as e:
                        logger.debug("本地回退分析失败: %s", e)

        return VisionResult(description="视觉模型不可用，本地分析失败")


# ══════════════════════════════════════════════════════════
# P2-1: UI 元素检测器
# 对标 Codex Computer Use — UI 元素识别与坐标定位
# ══════════════════════════════════════════════════════════


@dataclass
class UIElement:
    """UI 元素"""

    element_type: str  # button, input, dropdown, checkbox, radio, tab, dialog, table, icon, link, text
    label: str = ""
    text: str = ""
    position: str = ""  # top-left, center, bottom-right, etc.
    bbox: dict[str, int] = field(default_factory=dict)  # {x, y, w, h}
    state: str = ""  # active, disabled, selected, focused, normal
    confidence: float = 0.0


@dataclass
class UIDetectionResult:
    """UI 检测结果"""

    elements: list[UIElement] = field(default_factory=list)
    overall_layout: str = ""
    primary_action: str = ""
    screen_size: dict[str, int] = field(default_factory=dict)
    processing_time_ms: float = 0.0


class UIElementDetector:
    """UI 元素检测器 — 对标 Codex Computer Use

    支持:
    - 从截图识别 UI 元素（按钮、输入框、菜单等）
    - 基于视觉模型的语义元素识别
    - 基于颜色/形状的启发式元素检测（回退模式）
    - 屏幕坐标定位
    - 操作建议生成
    """

    # 常见 UI 元素颜色特征（RGB 范围）
    _UI_COLOR_PATTERNS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
        "button_blue": ((30, 100, 200), (80, 180, 255)),
        "button_green": ((30, 150, 50), (80, 220, 100)),
        "button_red": ((180, 30, 30), (255, 80, 80)),
        "button_gray": ((180, 180, 180), (230, 230, 230)),
        "input_white": ((240, 240, 240), (255, 255, 255)),
        "error_red": ((200, 30, 30), (255, 80, 80)),
        "warning_yellow": ((200, 180, 30), (255, 230, 80)),
        "success_green": ((30, 180, 50), (80, 230, 100)),
        "dark_text": ((0, 0, 0), (60, 60, 60)),
        "link_blue": ((30, 80, 200), (80, 150, 255)),
    }

    def __init__(self, vision_client: VisionModelClient | None = None):
        self._vision = vision_client or VisionModelClient()

    async def detect(
        self,
        image_path: str | Path,
        *,
        use_vision: bool = True,
    ) -> UIDetectionResult:
        """检测截图中的 UI 元素。

        Args:
            image_path: 截图文件路径
            use_vision: 是否使用视觉模型（否则用启发式方法）

        Returns:
            UIDetectionResult 检测结果
        """
        start = time.monotonic()
        path = Path(image_path)

        if not path.exists():
            return UIDetectionResult(
                processing_time_ms=(time.monotonic() - start) * 1000,
            )

        # 获取屏幕尺寸
        screen_size = {}
        if HAS_PIL:
            try:
                img = Image.open(path)
                screen_size = {"width": img.width, "height": img.height}
                img.close()
            except Exception as e:
                _logger.warning("silently_swallowed: {err}", exc_info=False)
                pass

        if use_vision:
            result = await self._detect_with_vision(path)
        else:
            result = self._detect_heuristic(path)

        result.screen_size = screen_size
        result.processing_time_ms = round((time.monotonic() - start) * 1000, 2)
        return result

    async def _detect_with_vision(self, path: Path) -> UIDetectionResult:
        """使用视觉模型检测 UI 元素"""
        vision_result = await self._vision.detect_ui_elements(path)
        elements: list[UIElement] = []

        for el in vision_result.ui_elements:
            elements.append(
                UIElement(
                    element_type=el.get("type", "unknown"),
                    label=el.get("label", ""),
                    text=el.get("text", ""),
                    position=el.get("position", ""),
                    bbox=el.get("bbox", {}),
                    state=el.get("state", "normal"),
                    confidence=el.get("confidence", 0.7),
                )
            )

        return UIDetectionResult(
            elements=elements,
            overall_layout=vision_result.description[:200],
        )

    def _detect_heuristic(self, path: Path) -> UIDetectionResult:
        """启发式 UI 元素检测（不依赖视觉模型）"""
        if not HAS_PIL:
            return UIDetectionResult()

        elements: list[UIElement] = []
        try:
            img = Image.open(path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            w, h = img.width, img.height

            # 缩小图像以加速处理
            scale = max(1, min(w, h) // 300)
            small = img.resize((w // scale, h // scale))
            pixels = list(small.getdata())

            # 颜色统计
            from collections import Counter

            color_counts = Counter(pixels)
            total = len(pixels)

            # 检测按钮色块
            blue_pixels = sum(
                c
                for color, c in color_counts.items()
                if len(color) >= 3
                and 30 < color[0] < 100
                and 100 < color[1] < 200
                and 180 < color[2] < 255
            )
            green_pixels = sum(
                c
                for color, c in color_counts.items()
                if len(color) >= 3
                and 30 < color[0] < 100
                and 150 < color[1] < 230
                and 30 < color[2] < 120
            )
            red_pixels = sum(
                c
                for color, c in color_counts.items()
                if len(color) >= 3
                and 180 < color[0] < 255
                and 30 < color[1] < 100
                and 30 < color[2] < 100
            )
            white_pixels = sum(
                c
                for color, c in color_counts.items()
                if len(color) >= 3
                and color[0] > 230
                and color[1] > 230
                and color[2] > 230
            )

            ratio = lambda p: round(p / total, 3) if total > 0 else 0.0

            if ratio(blue_pixels) > 0.01:
                elements.append(
                    UIElement(
                        element_type="button",
                        label="蓝色按钮",
                        confidence=min(ratio(blue_pixels) * 10, 0.9),
                        position="detected_by_color",
                    )
                )
            if ratio(green_pixels) > 0.01:
                elements.append(
                    UIElement(
                        element_type="button",
                        label="绿色按钮",
                        confidence=min(ratio(green_pixels) * 10, 0.9),
                        position="detected_by_color",
                    )
                )
            if ratio(red_pixels) > 0.01:
                elements.append(
                    UIElement(
                        element_type="error_indicator",
                        label="错误/警告区域",
                        confidence=min(ratio(red_pixels) * 10, 0.9),
                        position="detected_by_color",
                    )
                )
            if ratio(white_pixels) > 0.3:
                elements.append(
                    UIElement(
                        element_type="input",
                        label="输入区域（浅色背景）",
                        confidence=0.6,
                        position="detected_by_color",
                    )
                )

            img.close()

            layout = f"布局: {w}x{h}, "
            if ratio(white_pixels) > 0.5:
                layout += "浅色主题界面"
            elif ratio(white_pixels) < 0.2:
                layout += "深色主题界面"
            else:
                layout += "混合主题界面"

            return UIDetectionResult(
                elements=elements,
                overall_layout=layout,
            )

        except Exception as e:
            logger.debug("启发式 UI 检测失败: %s", e)
            return UIDetectionResult()

    def find_element_by_label(
        self,
        elements: list[UIElement],
        label: str,
    ) -> UIElement | None:
        """根据标签查找 UI 元素。

        Args:
            elements: UI 元素列表
            label: 标签文本（支持模糊匹配）

        Returns:
            匹配的 UIElement 或 None
        """
        label_lower = label.lower()
        for el in elements:
            if label_lower in el.label.lower() or label_lower in el.text.lower():
                return el
        return None

    def suggest_action(
        self,
        elements: list[UIElement],
        intent: str,
    ) -> dict[str, Any]:
        """根据意图建议操作。

        Args:
            elements: UI 元素列表
            intent: 用户意图描述

        Returns:
            建议的操作字典
        """
        intent_lower = intent.lower()

        # 点击意图
        if any(w in intent_lower for w in ("点击", "click", "按", "press", "选择", "select")):
            # 提取目标
            for el in elements:
                if el.label.lower() in intent_lower or el.text.lower() in intent_lower:
                    return {
                        "action": "click",
                        "target": el.label or el.text,
                        "element_type": el.element_type,
                        "position": el.position,
                        "confidence": el.confidence,
                    }
            return {"action": "click", "target": intent, "suggestion": "需要在屏幕上定位目标"}

        # 输入意图
        if any(w in intent_lower for w in ("输入", "type", "填写", "fill", "enter", "write")):
            input_elements = [el for el in elements if el.element_type in ("input", "textfield")]
            if input_elements:
                return {
                    "action": "type",
                    "target": input_elements[0].label or "输入框",
                    "element_type": "input",
                    "confidence": input_elements[0].confidence,
                }
            return {"action": "type", "target": "输入区域", "suggestion": "未检测到明确的输入框"}

        # 滚动意图
        if any(w in intent_lower for w in ("滚动", "scroll", "下滑", "上滑", "翻页")):
            direction = "down"
            if any(w in intent_lower for w in ("上滑", "up", "向上")):
                direction = "up"
            return {"action": "scroll", "direction": direction}

        # 等待意图
        if any(w in intent_lower for w in ("等待", "wait", "加载", "loading")):
            return {"action": "wait", "reason": "等待页面加载或操作完成"}

        return {"action": "unknown", "message": "无法确定操作意图", "intent": intent}


# 全局实例
_vision_client: VisionModelClient | None = None
_ui_detector: UIElementDetector | None = None


def get_vision_client() -> VisionModelClient:
    """获取全局视觉模型客户端"""
    global _vision_client
    if _vision_client is None:
        _vision_client = VisionModelClient()
    return _vision_client


def get_ui_detector() -> UIElementDetector:
    """获取全局 UI 元素检测器"""
    global _ui_detector
    if _ui_detector is None:
        _ui_detector = UIElementDetector()
    return _ui_detector


# ══════════════════════════════════════════════════════════
# 能力注册
# ══════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> None:
    """向能力总线注册多模态感知能力。

    注册以下能力:
    - perception.analyze_image: 分析通用图像
    - perception.analyze_screenshot: 分析代码截图
    - perception.stats: 获取感知统计

    Args:
        registry: V2 CapabilityRegistry 实例
    """
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    perception = MultimodalPerception()

    # ── 异步包装器 ──

    async def _analyze_image(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """分析通用图像"""
        image_path = params.get("image_path", "")
        if not image_path:
            return {"success": False, "error": "缺少 image_path 参数"}

        result = await perception.perceive_image(image_path)
        return {
            "success": result.success,
            "text_content": result.text_content,
            "structured_data": result.structured_data,
            "confidence": result.confidence,
            "processing_time_ms": result.processing_time_ms,
            "source_type": result.source_type,
        }

    async def _analyze_screenshot(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """分析代码截图"""
        image_path = params.get("image_path", "")
        if not image_path:
            return {"success": False, "error": "缺少 image_path 参数"}

        result = await perception.perceive_screenshot(image_path)
        return {
            "success": result.success,
            "text_content": result.text_content,
            "structured_data": result.structured_data,
            "confidence": result.confidence,
            "processing_time_ms": result.processing_time_ms,
            "source_type": result.source_type,
        }

    async def _get_stats(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """获取感知统计信息"""
        return perception.get_stats()

    # ── 注册能力 ──

    registry.register(
        CapabilityDefinition(
            id="perception.analyze_image",
            name="分析通用图像",
            description="分析图像文件的尺寸、格式、颜色分布，并使用 OCR 提取文字内容",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "图像文件的绝对路径",
                    },
                },
                "required": ["image_path"],
            },
            tags=["perception", "image", "ocr", "图像分析", "文字识别"],
        ),
        handler=_analyze_image,
    )

    registry.register(
        CapabilityDefinition(
            id="perception.analyze_screenshot",
            name="分析代码截图",
            description="分析代码截图，使用 OCR 提取代码文字，检测代码特征和错误颜色",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "截图文件的绝对路径",
                    },
                },
                "required": ["image_path"],
            },
            tags=["perception", "screenshot", "code", "ocr", "截图分析", "代码识别"],
        ),
        handler=_analyze_screenshot,
    )

    registry.register(
        CapabilityDefinition(
            id="perception.stats",
            name="获取感知统计",
            description="获取多模态感知模块的调用统计信息（调用次数、成功率、平均耗时等）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {},
            },
            tags=["perception", "stats", "统计"],
        ),
        handler=_get_stats,
    )

    # ── P2-1: 视觉模型能力 ──

    async def _vision_analyze(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """使用视觉模型分析图像"""
        image_path = params.get("image_path", "")
        if not image_path:
            return {"success": False, "error": "缺少 image_path 参数"}
        prompt = params.get("prompt", "")
        client = get_vision_client()
        result = await client.analyze(image_path, prompt=prompt)
        return {
            "success": True,
            "description": result.description,
            "text_content": result.text_content,
            "ui_elements": result.ui_elements,
            "objects": result.objects,
            "model": result.model,
            "processing_time_ms": result.processing_time_ms,
        }

    registry.register(
        CapabilityDefinition(
            id="perception.vision_analyze",
            name="视觉模型分析",
            description="使用 GPT-4V/Claude Vision 等视觉模型进行图像语义分析，支持对象检测、UI 识别、代码/错误截图理解",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.FILE_READ, SideEffect.LLM_CALL],
            schema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "图像文件的绝对路径",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "可选的引导提示词",
                    },
                },
                "required": ["image_path"],
            },
            tags=["perception", "vision", "ai", "gpt-4v", "claude", "视觉分析"],
        ),
        handler=_vision_analyze,
    )

    async def _ui_detect(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """检测 UI 元素"""
        image_path = params.get("image_path", "")
        if not image_path:
            return {"success": False, "error": "缺少 image_path 参数"}
        use_vision = params.get("use_vision", True)
        detector = get_ui_detector()
        result = await detector.detect(image_path, use_vision=use_vision)
        return {
            "success": True,
            "elements": [
                {
                    "type": el.element_type,
                    "label": el.label,
                    "text": el.text,
                    "position": el.position,
                    "state": el.state,
                    "confidence": el.confidence,
                }
                for el in result.elements
            ],
            "overall_layout": result.overall_layout,
            "screen_size": result.screen_size,
            "processing_time_ms": result.processing_time_ms,
        }

    registry.register(
        CapabilityDefinition(
            id="perception.ui_detect",
            name="UI 元素检测",
            description="检测截图中的 UI 元素（按钮、输入框、菜单、对话框等），支持视觉模型和启发式两种模式",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.FILE_READ, SideEffect.LLM_CALL],
            schema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "截图文件的绝对路径",
                    },
                    "use_vision": {
                        "type": "boolean",
                        "description": "是否使用视觉模型（默认 true）",
                    },
                },
                "required": ["image_path"],
            },
            tags=["perception", "ui", "computer-use", "screen", "UI检测"],
        ),
        handler=_ui_detect,
    )

    async def _compare_screenshots(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """对比两张截图"""
        before = params.get("before", "")
        after = params.get("after", "")
        if not before or not after:
            return {"success": False, "error": "缺少 before 或 after 参数"}
        client = get_vision_client()
        result = await client.compare_screenshots(before, after)
        return {
            "success": True,
            "description": result.description,
            "ui_elements": result.ui_elements,
            "objects": result.objects,
            "model": result.model,
            "processing_time_ms": result.processing_time_ms,
        }

    registry.register(
        CapabilityDefinition(
            id="perception.compare_screenshots",
            name="截图对比分析",
            description="对比两张截图，分析操作前后的 UI 变化差异",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.FILE_READ, SideEffect.LLM_CALL],
            schema={
                "type": "object",
                "properties": {
                    "before": {
                        "type": "string",
                        "description": "操作前截图路径",
                    },
                    "after": {
                        "type": "string",
                        "description": "操作后截图路径",
                    },
                },
                "required": ["before", "after"],
            },
            tags=["perception", "compare", "diff", "screenshot", "截图对比"],
        ),
        handler=_compare_screenshots,
    )

    logger.info(
        "多模态感知能力已注册: "
        "perception.analyze_image, perception.analyze_screenshot, perception.stats, "
        "perception.vision_analyze, perception.ui_detect, perception.compare_screenshots"
    )