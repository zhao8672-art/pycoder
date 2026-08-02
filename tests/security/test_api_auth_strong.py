"""P0-4 测试：API 认证强制模式

原实现：PYCODER_API_KEY 未设置时不认证（开发友好但生产危险）。
现实现：未设置时自动生成临时 key，避免无意识暴露；
        显式设置 'disabled' 才完全关闭认证。
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def _reload_app_module():
    """重新加载 pycoder.server.app 模块以应用新的环境变量

    注意：`import pycoder.server.app as app_module` 在某些包结构下会被解析为
    FastAPI 实例（因包 __init__.py 的导出），因此使用 sys.modules 获取真正的模块。
    """
    # 清除已加载的模块缓存
    for mod_name in list(sys.modules.keys()):
        if mod_name == "pycoder.server.app" or mod_name.startswith("pycoder.server.app."):
            del sys.modules[mod_name]
    # 重新导入模块（必须重新 import，否则 sys.modules 中不存在，会 KeyError）
    return importlib.import_module("pycoder.server.app")


@pytest.fixture
def client_with_auth(monkeypatch):
    """配置了认证的测试客户端"""
    monkeypatch.setenv("PYCODER_API_KEY", "test-secret-key-12345")
    app_module = _reload_app_module()
    yield TestClient(app_module.app)
    # 清理：恢复无认证状态
    monkeypatch.setenv("PYCODER_API_KEY", "")
    _reload_app_module()


@pytest.fixture
def client_disabled(monkeypatch):
    """显式禁用认证的测试客户端"""
    monkeypatch.setenv("PYCODER_API_KEY", "disabled")
    app_module = _reload_app_module()
    yield TestClient(app_module.app)
    # 清理
    monkeypatch.setenv("PYCODER_API_KEY", "")
    _reload_app_module()


@pytest.fixture
def client_auto_generated(monkeypatch):
    """未设置环境变量时自动生成临时 key 的测试客户端"""
    monkeypatch.delenv("PYCODER_API_KEY", raising=False)
    app_module = _reload_app_module()
    # 保存自动生成的 key 用于测试
    auto_key = app_module._API_KEY
    yield TestClient(app_module.app), auto_key
    # 清理
    monkeypatch.setenv("PYCODER_API_KEY", "")
    _reload_app_module()


class TestAPIAuthEnforced:
    """认证模式：必须携带正确 X-API-Key"""

    def test_no_key_returns_401(self, client_with_auth):
        """未携带 X-API-Key 应返回 401"""
        resp = client_with_auth.get("/api/health")
        # /api/health 免认证
        assert resp.status_code == 200

        # 其他端点应 401（需携带 Origin 头，否则 file:// 免认证）
        resp = client_with_auth.get(
            "/api/config/keys",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, client_with_auth):
        """错误的 X-API-Key 应返回 401"""
        resp = client_with_auth.get(
            "/api/config/keys",
            headers={
                "X-API-Key": "wrong-key",
                "Origin": "http://localhost:5173",
            },
        )
        assert resp.status_code == 401

    def test_correct_key_passes(self, client_with_auth):
        """正确的 X-API-Key 应通过认证"""
        resp = client_with_auth.get(
            "/api/config/keys",
            headers={
                "X-API-Key": "test-secret-key-12345",
                "Origin": "http://localhost:5173",
            },
        )
        assert resp.status_code == 200

    def test_disabled_mode_allows_all(self, client_disabled):
        """显式 disabled 模式：任何请求都放行"""
        resp = client_disabled.get(
            "/api/config/keys",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200

    def test_auto_generated_key_works(self, client_auto_generated):
        """未设置 key 时自动生成临时 key 且可用"""
        client, auto_key = client_auto_generated
        resp = client.get(
            "/api/config/keys",
            headers={
                "X-API-Key": auto_key,
                "Origin": "http://localhost:5173",
            },
        )
        assert resp.status_code == 200
