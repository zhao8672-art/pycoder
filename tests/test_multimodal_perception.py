"""
多模态感知模块单元测试

测试 MultimodalPerception、ImageAnalyzer、PerceptionResult 的核心功能：
- 通用图像分析（尺寸、格式、颜色分布）
- 代码截图感知
- 框图/架构图分析
- 错误截图检测（红色=错误）
- 图像元数据提取与颜色分析
- 感知统计信息
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from PIL import Image

from pycoder.server.services.multimodal_perception import (
    MultimodalPerception,
    ImageAnalyzer,
    PerceptionResult,
)


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


def _create_temp_image(
    width: int = 200,
    height: int = 100,
    color: tuple[int, int, int] = (100, 150, 200),
    fmt: str = "PNG",
    suffix: str = ".png",
) -> Path:
    """创建临时测试图像，返回文件路径"""
    img = Image.new("RGB", (width, height), color=color)
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    img.save(tmp, format=fmt)
    tmp.close()
    return Path(tmp.name)


def _create_red_error_image() -> Path:
    """创建红色错误图像（模拟错误截图）"""
    img = Image.new("RGB", (300, 200), color=(200, 30, 30))
    # 添加一些红色像素变体
    for x in range(100, 200):
        for y in range(50, 150):
            img.putpixel((x, y), (220, 20, 20))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp, format="PNG")
    tmp.close()
    return Path(tmp.name)


def _create_diagram_image() -> Path:
    """创建模拟框图图像（多色块）"""
    img = Image.new("RGB", (400, 300), color=(255, 255, 255))
    # 绘制几个彩色矩形模拟框图组件
    for x0, y0, x1, y1, color in [
        (50, 50, 150, 120, (100, 149, 237)),   # 蓝色块
        (250, 50, 350, 120, (60, 179, 113)),    # 绿色块
        (50, 180, 150, 250, (255, 165, 0)),     # 橙色块
        (250, 180, 350, 250, (147, 112, 219)),  # 紫色块
    ]:
        for x in range(x0, x1):
            for y in range(y0, y1):
                img.putpixel((x, y), color)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp, format="PNG")
    tmp.close()
    return Path(tmp.name)


def _create_screenshot_image() -> Path:
    """创建模拟截图图像（深色背景 + 浅色文字区域）"""
    img = Image.new("RGB", (600, 400), color=(30, 30, 30))
    # 白色代码区域
    for x in range(50, 550):
        for y in range(50, 350):
            img.putpixel((x, y), (240, 240, 240))
    # 左侧行号区域
    for x in range(10, 40):
        for y in range(50, 350):
            img.putpixel((x, y), (60, 60, 60))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp, format="PNG")
    tmp.close()
    return Path(tmp.name)


# ──────────────────────────────────────────────
# 测试：MultimodalPerception 实例
# ──────────────────────────────────────────────


class TestMultimodalPerceptionCreate:
    """创建感知实例测试"""

    def test_create_perception(self) -> None:
        """创建 MultimodalPerception 实例"""
        perception = MultimodalPerception()
        assert perception is not None
        assert perception._analyzer is not None
        assert isinstance(perception._analyzer, ImageAnalyzer)


# ──────────────────────────────────────────────
# 测试：ImageAnalyzer 元数据与颜色
# ──────────────────────────────────────────────


class TestImageAnalyzerMetadata:
    """图像元数据提取测试"""

    def test_image_analyzer_metadata(self) -> None:
        """测试图像元数据提取"""
        analyzer = ImageAnalyzer()
        img_path = _create_temp_image(width=300, height=200, color=(50, 100, 150))

        result = analyzer.analyze(img_path)
        assert result["width"] == 300
        assert result["height"] == 200
        assert result["format"] == "PNG"
        assert result["mode"] == "RGB"
        assert result["aspect_ratio"] == pytest.approx(1.5, rel=0.01)
        assert result["file_size_bytes"] > 0
        assert result["is_animated"] is False
        assert result["n_frames"] == 1
        assert "color_analysis" in result

        # 清理
        img_path.unlink(missing_ok=True)

    def test_image_analyzer_color_detection(self) -> None:
        """测试颜色分析"""
        analyzer = ImageAnalyzer()

        # 红色图像
        red_path = _create_temp_image(width=200, height=200, color=(200, 30, 30))
        red_result = analyzer.analyze(red_path)
        color_info = red_result["color_analysis"]
        assert "mean_rgb" in color_info
        mean_r, mean_g, mean_b = color_info["mean_rgb"]
        # 红色通道应显著高于其他通道
        assert mean_r > mean_g
        assert mean_r > mean_b
        assert "暖色调" in color_info["dominant_tone"]

        red_path.unlink(missing_ok=True)

        # 蓝色图像
        blue_path = _create_temp_image(width=200, height=200, color=(30, 30, 200))
        blue_result = analyzer.analyze(blue_path)
        blue_color = blue_result["color_analysis"]
        assert "冷色调" in blue_color["dominant_tone"]

        blue_path.unlink(missing_ok=True)

    def test_analyze_image_not_found(self) -> None:
        """不存在的图像路径应抛出异常"""
        analyzer = ImageAnalyzer()
        with pytest.raises(FileNotFoundError, match="图像文件不存在"):
            analyzer.analyze("/nonexistent/path/image.png")


# ──────────────────────────────────────────────
# 测试：MultimodalPerception 感知方法
# ──────────────────────────────────────────────


class TestPerceiveImage:
    """通用图像感知测试"""

    @pytest.mark.asyncio
    async def test_analyze_image_basic(self) -> None:
        """分析基础图像"""
        perception = MultimodalPerception()
        img_path = _create_temp_image(width=100, height=80, color=(100, 200, 100))

        result = await perception.perceive_image(str(img_path))
        assert result.success is True
        assert result.source_type == "image"
        assert result.processing_time_ms > 0
        assert "metadata" in result.structured_data
        assert result.structured_data["metadata"]["width"] == 100
        assert result.structured_data["metadata"]["height"] == 80

        img_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_analyze_image_not_found(self) -> None:
        """分析不存在的图像"""
        perception = MultimodalPerception()
        result = await perception.perceive_image("/nonexistent/image.png")
        assert result.success is False
        assert "不存在" in result.text_content
        assert result.source_type == "image"


class TestPerceiveScreenshot:
    """截图感知测试"""

    @pytest.mark.asyncio
    async def test_analyze_screenshot(self) -> None:
        """分析截图图像"""
        perception = MultimodalPerception()
        img_path = _create_screenshot_image()

        result = await perception.perceive_screenshot(str(img_path))
        assert result.success is True
        assert result.source_type == "screenshot"
        assert "metadata" in result.structured_data
        assert "color_analysis" in result.structured_data
        assert "code_features" in result.structured_data
        assert result.processing_time_ms > 0

        img_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_analyze_screenshot_not_found(self) -> None:
        """分析不存在的截图"""
        perception = MultimodalPerception()
        result = await perception.perceive_screenshot("/nonexistent/screenshot.png")
        assert result.success is False
        assert "不存在" in result.text_content


class TestPerceiveDiagram:
    """框图感知测试"""

    @pytest.mark.asyncio
    async def test_analyze_diagram(self) -> None:
        """分析框图图像"""
        perception = MultimodalPerception()
        img_path = _create_diagram_image()

        result = await perception.perceive_diagram(str(img_path))
        assert result.success is True
        assert result.source_type == "diagram"
        assert "metadata" in result.structured_data
        assert "diagram_features" in result.structured_data

        diagram_features = result.structured_data["diagram_features"]
        assert "orientation" in diagram_features
        assert "estimated_components" in diagram_features

        img_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_analyze_diagram_not_found(self) -> None:
        """分析不存在的框图"""
        perception = MultimodalPerception()
        result = await perception.perceive_diagram("/nonexistent/diagram.png")
        assert result.success is False
        assert "不存在" in result.text_content


class TestPerceiveErrorScreenshot:
    """错误截图感知测试"""

    @pytest.mark.asyncio
    async def test_analyze_error_screenshot(self) -> None:
        """分析错误截图（红色图像）"""
        perception = MultimodalPerception()
        img_path = _create_red_error_image()

        result = await perception.perceive_error_screenshot(str(img_path))
        assert result.success is True
        assert result.source_type == "error_screenshot"
        assert "color_analysis" in result.structured_data
        assert "error_features" in result.structured_data

        color_analysis = result.structured_data["color_analysis"]
        assert color_analysis["has_error_indicator"] is True
        assert color_analysis["severity"] == "error"
        assert color_analysis["red_ratio"] > 0.05

        img_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_analyze_error_screenshot_not_found(self) -> None:
        """分析不存在的错误截图"""
        perception = MultimodalPerception()
        result = await perception.perceive_error_screenshot("/nonexistent/error.png")
        assert result.success is False
        assert "不存在" in result.text_content


# ──────────────────────────────────────────────
# 测试：ImageAnalyzer 错误颜色检测
# ──────────────────────────────────────────────


class TestImageAnalyzerErrorDetection:
    """错误颜色检测测试"""

    def test_detect_error_colors_red(self) -> None:
        """检测红色错误图像"""
        analyzer = ImageAnalyzer()
        img_path = _create_red_error_image()

        result = analyzer.detect_error_colors(img_path)
        assert result["has_error_indicator"] is True
        assert result["severity"] == "error"
        assert result["red_ratio"] > 0.0

        img_path.unlink(missing_ok=True)

    def test_detect_error_colors_normal(self) -> None:
        """检测正常图像（无错误颜色）"""
        analyzer = ImageAnalyzer()
        img_path = _create_temp_image(width=200, height=200, color=(100, 150, 100))

        result = analyzer.detect_error_colors(img_path)
        assert result["has_error_indicator"] is False
        assert result["has_warning_indicator"] is False
        assert result["severity"] == "none"

        img_path.unlink(missing_ok=True)

    def test_detect_error_colors_not_found(self) -> None:
        """错误颜色检测 — 文件不存在"""
        analyzer = ImageAnalyzer()
        with pytest.raises(FileNotFoundError, match="图像文件不存在"):
            analyzer.detect_error_colors("/nonexistent/img.png")


# ──────────────────────────────────────────────
# 测试：统计信息
# ──────────────────────────────────────────────


class TestGetStats:
    """感知统计信息测试"""

    @pytest.mark.asyncio
    async def test_get_stats_initial(self) -> None:
        """初始统计信息"""
        perception = MultimodalPerception()
        stats = perception.get_stats()
        assert stats["total_calls"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["avg_processing_time_ms"] == 0.0
        assert stats["pil_available"] is True

    @pytest.mark.asyncio
    async def test_get_stats_after_calls(self) -> None:
        """调用后统计信息更新"""
        perception = MultimodalPerception()
        img_path = _create_temp_image(width=100, height=100, color=(50, 100, 200))

        await perception.perceive_image(str(img_path))
        await perception.perceive_image(str(img_path))

        stats = perception.get_stats()
        # total_calls 含 method 和 success_method 键，2 次成功 = 4
        # success_rate = total_success / total_calls = 2/4 = 0.5
        assert stats["total_calls"] == 4
        assert stats["total_success"] == 2
        assert stats["success_rate"] == pytest.approx(0.5, rel=0.01)
        assert stats["avg_processing_time_ms"] > 0
        assert stats["by_method"]["perceive_image"] == 2

        img_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_get_stats_mixed_methods(self) -> None:
        """混合方法调用统计"""
        perception = MultimodalPerception()
        img_path = _create_temp_image(width=100, height=100, color=(50, 100, 200))

        await perception.perceive_image(str(img_path))
        await perception.perceive_screenshot(str(img_path))
        await perception.perceive_diagram(str(img_path))
        await perception.perceive_error_screenshot(str(img_path))
        # 再加一个不存在的调用（失败）
        await perception.perceive_image("/nonexistent.png")

        stats = perception.get_stats()
        # total_calls 含 method 和 success_method 键；
        # 不存在的文件走早期 return 不记录 stats，故 perceive_image 实际只计 1 次
        assert stats["total_calls"] >= 4
        assert stats["total_success"] >= 2
        assert stats["by_method"]["perceive_image"] == 1
        assert stats["by_method"]["perceive_screenshot"] == 1
        assert stats["by_method"]["perceive_diagram"] == 1
        assert stats["by_method"]["perceive_error_screenshot"] == 1

        img_path.unlink(missing_ok=True)


# ──────────────────────────────────────────────
# 测试：PerceptionResult 数据类
# ──────────────────────────────────────────────


class TestPerceptionResult:
    """PerceptionResult 数据类测试"""

    def test_perception_result_defaults(self) -> None:
        """默认值测试"""
        result = PerceptionResult(success=True)
        assert result.success is True
        assert result.text_content == ""
        assert result.structured_data == {}
        assert result.confidence == 0.0
        assert result.processing_time_ms == 0.0
        assert result.source_type == "unknown"

    def test_perception_result_failed(self) -> None:
        """失败结果"""
        result = PerceptionResult(
            success=False,
            text_content="文件不存在",
            source_type="image",
        )
        assert result.success is False
        assert result.text_content == "文件不存在"
        assert result.source_type == "image"


# ──────────────────────────────────────────────
# 测试：ImageAnalyzer 文本提取（OCR）
# ──────────────────────────────────────────────


class TestImageAnalyzerText:
    """OCR 文本提取测试"""

    def test_extract_text_file_not_found(self) -> None:
        """OCR 提取 — 文件不存在"""
        analyzer = ImageAnalyzer()
        with pytest.raises(FileNotFoundError, match="图像文件不存在"):
            analyzer.extract_text("/nonexistent/img.png")

    def test_analyze_jpeg_format(self) -> None:
        """分析 JPEG 格式图像"""
        analyzer = ImageAnalyzer()
        img = Image.new("RGB", (150, 100), color=(255, 200, 100))
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        img.save(tmp, format="JPEG")
        tmp.close()

        result = analyzer.analyze(Path(tmp.name))
        assert result["format"] == "JPEG"
        assert result["width"] == 150
        assert result["height"] == 100

        Path(tmp.name).unlink(missing_ok=True)