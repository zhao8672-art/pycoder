"""
图像分析器 — 元数据 / 颜色分布 / 尺寸 / 图表检测

纯本地计算，不依赖外部 API。
"""

from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


class ImageAnalyzer:
    """图像分析器 — 纯本地元数据+颜色分析"""

    async def analyze(self, image_data: bytes) -> dict:
        """完整图像分析"""
        try:
            from PIL import Image, ImageStat
            img = Image.open(BytesIO(image_data))
        except Exception as exc:
            return {"error": f"无法打开图片: {exc}"}

        result = {
            "format": img.format or "unknown",
            "size": {"width": img.width, "height": img.height},
            "mode": img.mode,
            "file_size_kb": round(len(image_data) / 1024, 1),
            "aspect_ratio": round(img.width / max(img.height, 1), 2),
        }

        # 颜色分析 (缩放到 100x100 加速)
        try:
            small = img.copy()
            small.thumbnail((100, 100))
            stat = ImageStat.Stat(small)
            result["color"] = {
                "mean_rgb": [round(v, 1) for v in stat.mean[:3]],
                "std_rgb": [round(v, 1) for v in stat.stddev[:3]],
            }

            # 检测是否包含大量红色/黄色（错误截图）
            r, g, b = stat.mean[:3]
            result["has_red_tint"] = r > 200 and g < 100
            result["has_yellow_tint"] = r > 200 and g > 180 and b < 100
        except Exception:
            pass

        # 估算 DPI
        try:
            dpi = img.info.get("dpi", (72, 72))
            result["dpi"] = dpi
        except Exception:
            pass

        return result

    async def is_screenshot(self, image_data: bytes) -> bool:
        """检测是否为截图"""
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))

            # 截图通常有特定尺寸比例
            if img.width > 800 and img.height > 400:
                return True
            return False
        except Exception:
            return False
