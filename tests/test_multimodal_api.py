"""P2-2: Multimodal API 单元测试"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 测试客户端"""
    from fastapi import FastAPI

    from pycoder.server.routers.multimodal_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def sample_png_bytes():
    """创建一个最小的有效 PNG 图片 (1x1 红色像素)"""
    try:
        from PIL import Image
        from io import BytesIO

        img = Image.new("RGB", (1, 1), color=(255, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        pytest.skip("PIL not available")


def test_capabilities_endpoint(client):
    """能力查询端点应返回可用引擎"""
    response = client.get("/api/multimodal/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "image_analyze" in data
    assert "ocr" in data
    assert "max_size_mb" in data
    assert "allowed_types" in data
    assert data["max_size_mb"] == 20
    assert "image/png" in data["allowed_types"]


def test_upload_image(client, sample_png_bytes):
    """上传图片应返回 base64 编码"""
    response = client.post(
        "/api/multimodal/upload",
        files={"file": ("test.png", sample_png_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["filename"] == "test.png"
    assert "image_base64" in data
    assert data["size"] == len(sample_png_bytes)
    # 验证 base64 可解码回原始字节
    assert base64.b64decode(data["image_base64"]) == sample_png_bytes


def test_upload_rejects_invalid_type(client):
    """上传非图片类型应返回 400"""
    response = client.post(
        "/api/multimodal/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "不支持" in response.json()["detail"]


def test_upload_rejects_oversized(client):
    """上传超大文件应返回 400"""
    # 创建一个 > 20MB 的字节串（但声明 image/png）
    big_data = b"\x00" * (21 * 1024 * 1024)
    response = client.post(
        "/api/multimodal/upload",
        files={"file": ("big.png", big_data, "image/png")},
    )
    assert response.status_code == 400
    assert "过大" in response.json()["detail"]


def test_analyze_image_metadata(client, sample_png_bytes):
    """analyze 应返回图片元数据"""
    response = client.post(
        "/api/multimodal/analyze",
        files={"file": ("test.png", sample_png_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "format" in data
    assert "size" in data
    assert "mode" in data
    assert data["size"]["width"] == 1
    assert data["size"]["height"] == 1


def test_vision_base64_valid(client, sample_png_bytes, monkeypatch):
    """vision 端点接受合法 base64

    Mock 视觉客户端，避免真实 API 调用导致测试挂起
    """
    from pycoder.multimodal import vision_client as vc

    async def _fake_analyze(self, image_data, prompt="描述这张图片"):
        return "mock analysis: image has 1x1 pixel"

    monkeypatch.setattr(vc.VisionClient, "analyze", _fake_analyze)

    b64 = base64.b64encode(sample_png_bytes).decode("ascii")
    response = client.post(
        "/api/multimodal/vision",
        json={"image_base64": b64, "prompt": "测试", "prefer": "auto"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "method" in data
    assert "content" in data


def test_vision_rejects_invalid_base64(client):
    """vision 端点拒绝非法 base64"""
    response = client.post(
        "/api/multimodal/vision",
        json={"image_base64": "not!valid!base64!@#$", "prompt": "测试"},
    )
    assert response.status_code == 400


def test_screenshot_error_endpoint(client, sample_png_bytes, monkeypatch):
    """错误截图分析端点 — Mock OCR 避免真实 API"""
    from pycoder.multimodal import ocr_engine as oe

    async def _fake_extract(self, image_data):
        return "Traceback (most recent call last):\n  File test.py\n    raise ValueError"

    monkeypatch.setattr(oe.OCREngine, "extract_text", _fake_extract)

    response = client.post(
        "/api/multimodal/screenshot/error",
        files={"file": ("err.png", sample_png_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "is_screenshot" in data
    assert "likely_type" in data
    assert "description" in data
    assert "confidence" in data
    assert "suggestions" in data
    # 验证错误关键词被识别
    assert data["likely_type"] == "error"


def test_screenshot_chart_endpoint(client, sample_png_bytes, monkeypatch):
    """图表截图分析端点 — Mock 视觉/OCR 避免真实 API"""
    from pycoder.multimodal import vision_client as vc
    from pycoder.multimodal import ocr_engine as oe

    async def _fake_analyze(self, image_data, prompt="描述这张图片"):
        return "mock chart: line chart, x=time y=value, 上升趋势"

    async def _fake_extract(self, image_data):
        return "data 10 20 30 40 50"

    monkeypatch.setattr(vc.VisionClient, "analyze", _fake_analyze)
    monkeypatch.setattr(oe.OCREngine, "extract_text", _fake_extract)

    response = client.post(
        "/api/multimodal/screenshot/chart",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "chart_description" in data
    assert "extracted_text" in data


def test_ocr_endpoint(client, sample_png_bytes, monkeypatch):
    """OCR 端点 — Mock OCR 避免真实 API"""
    from pycoder.multimodal import ocr_engine as oe

    async def _fake_extract(self, image_data):
        return "mocked text content"

    monkeypatch.setattr(oe.OCREngine, "extract_text", _fake_extract)

    response = client.post(
        "/api/multimodal/ocr",
        files={"file": ("text.png", sample_png_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "text" in data
    assert "method" in data
    assert "execution_time" in data


def test_all_allowed_image_types(client):
    """所有允许的图片类型应被接受（类型校验）"""
    for content_type in ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp"]:
        # 用最小字节模拟
        response = client.post(
            "/api/multimodal/upload",
            files={"file": ("test.png", b"\x89PNG", content_type)},
        )
        # 应当通过类型校验（即使内容不是有效图片）
        assert response.status_code in (200, 400)
        if response.status_code == 400:
            # 400 应是大小或解码错误，不是类型
            assert "类型" not in response.json()["detail"]
