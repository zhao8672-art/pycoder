"""F4: 移动端精简 API 单元测试

覆盖:
    - GET /api/mobile/ping    — 连通性自检响应结构
    - GET /api/mobile/summary — 首屏聚合数据（工作区名/会话数/运行中任务数/版本）
    - GET /api/mobile/files   — 精简文件列表、路径穿越防护、条数限制
    - 鉴权                    — 完整 App 下 X-API-Key 强制校验（复用既有中间件）
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from pycoder.server.routers import files as files_module
from pycoder.server.routers import mobile_api

_TEST_API_KEY = "test-mobile-key-12345"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """仅挂载 mobile 路由的独立 FastAPI 测试客户端。

    将工作区根目录 monkeypatch 到 tmp_path，保证文件相关用例完全隔离。
    """
    from fastapi import FastAPI

    monkeypatch.setattr(files_module, "_WORKSPACE_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(mobile_api.router)
    return TestClient(app), tmp_path


def _reload_app_module():
    """重新加载 pycoder.server.app 模块以应用新的环境变量（与 test_api_auth_strong 同模式）"""
    for mod_name in list(sys.modules.keys()):
        if mod_name == "pycoder.server.app" or mod_name.startswith("pycoder.server.app."):
            del sys.modules[mod_name]
    return importlib.import_module("pycoder.server.app")


@pytest.fixture
def client_with_auth(monkeypatch):
    """启用 X-API-Key 强制鉴权的完整 App 测试客户端"""
    monkeypatch.setenv("PYCODER_API_KEY", _TEST_API_KEY)
    app_module = _reload_app_module()
    yield TestClient(app_module.app)
    # 清理：恢复无认证状态，避免影响其他测试
    monkeypatch.setenv("PYCODER_API_KEY", "")
    _reload_app_module()


# ── ping ─────────────────────────────────────────────────


def test_ping_returns_ok(client):
    """ping 应返回 ok/version/mobile 三字段"""
    c, _ = client
    resp = c.get("/api/mobile/ping")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["mobile"] is True
    assert isinstance(data["version"], str) and data["version"]


# ── summary ──────────────────────────────────────────────


def test_summary_returns_aggregated_data(client):
    """summary 应聚合工作区名/会话数/运行中任务数/版本"""
    c, tmp_path = client
    resp = c.get("/api/mobile/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace_name"] == tmp_path.name
    assert data["workspace"] == str(tmp_path)
    assert isinstance(data["session_count"], int)
    assert isinstance(data["running_tasks"], int)
    assert data["mobile"] is True
    assert isinstance(data["version"], str) and data["version"]


# ── files ────────────────────────────────────────────────


def test_files_lists_directory(client):
    """files 应列出目录内容（目录在前，只读最小字段）"""
    c, tmp_path = client
    (tmp_path / "subdir").mkdir()
    (tmp_path / "a.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "b.md").write_text("# doc", encoding="utf-8")

    resp = c.get("/api/mobile/files", params={"path": "."})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert data["truncated"] is False
    names = [item["name"] for item in data["items"]]
    assert names == ["subdir", "a.py", "b.md"]  # 目录优先，再按名称排序
    dir_item = data["items"][0]
    assert dir_item["is_dir"] is True
    file_item = data["items"][1]
    assert file_item["is_dir"] is False
    assert file_item["size"] > 0
    # 字段保持精简
    assert set(file_item.keys()) == {"name", "is_dir", "path", "size"}


def test_files_rejects_path_traversal(client):
    """路径穿越（.. 逃逸工作区）应被拦截返回 400"""
    c, _ = client
    for evil in ("..", "../..", "../../etc", "..\\..\\windows"):
        resp = c.get("/api/mobile/files", params={"path": evil})
        assert resp.status_code == 400, f"路径穿越未被拦截: {evil}"
        assert "路径穿越" in resp.json()["detail"]


def test_files_limit_truncates_results(client):
    """limit 参数应截断结果并置 truncated 标记"""
    c, tmp_path = client
    for i in range(10):
        (tmp_path / f"file_{i:02d}.txt").write_text("x", encoding="utf-8")

    resp = c.get("/api/mobile/files", params={"path": ".", "limit": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert len(data["items"]) == 3
    assert data["truncated"] is True


def test_files_limit_upper_bound(client):
    """limit 超过上限（500）应返回 422 校验错误"""
    c, _ = client
    resp = c.get("/api/mobile/files", params={"path": ".", "limit": 9999})
    assert resp.status_code == 422


def test_files_not_found(client):
    """不存在的路径应返回 404"""
    c, _ = client
    resp = c.get("/api/mobile/files", params={"path": "no_such_dir"})
    assert resp.status_code == 404


def test_files_rejects_file_path(client):
    """对文件（非目录）请求列表应返回 400"""
    c, tmp_path = client
    (tmp_path / "a.py").write_text("pass", encoding="utf-8")
    resp = c.get("/api/mobile/files", params={"path": "a.py"})
    assert resp.status_code == 400


# ── 鉴权（完整 App + 既有 APIKeyMiddleware） ──────────────


class TestMobileApiAuth:
    """移动端 API 全程走既有 X-API-Key 鉴权"""

    def test_ping_without_key_returns_401(self, client_with_auth):
        """未携带 X-API-Key 应返回 401"""
        resp = client_with_auth.get("/api/mobile/ping")
        assert resp.status_code == 401

    def test_ping_with_wrong_key_returns_401(self, client_with_auth):
        """错误 X-API-Key 应返回 401"""
        resp = client_with_auth.get(
            "/api/mobile/ping",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_ping_with_valid_key_returns_200(self, client_with_auth):
        """正确 X-API-Key 应放行并返回 mobile 标记"""
        resp = client_with_auth.get(
            "/api/mobile/ping",
            headers={"X-API-Key": _TEST_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["mobile"] is True

    def test_summary_and_files_also_require_auth(self, client_with_auth):
        """summary/files 无 Key 同样应返回 401"""
        for path in ("/api/mobile/summary", "/api/mobile/files"):
            resp = client_with_auth.get(path)
            assert resp.status_code == 401, f"{path} 未强制鉴权"
