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
        except Exception:
            return {}

    def _analyze_colors(self, img: Image.Image) -> dict[str, Any]:
        """分析图像颜色统计"""
        if img.mode not in ("RGB", "RGBA"):
            try:
                img = img.convert("RGB")
            except Exception:
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

    logger.info(
        "多模态感知能力已注册: "
        "perception.analyze_image, perception.analyze_screenshot, perception.stats"
    )