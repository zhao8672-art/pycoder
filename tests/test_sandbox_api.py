"""
沙箱 API 路由单元测试 — 覆盖 sandbox_api.py 所有端点

测试范围:
  - GET  /api/sandbox/status       — 获取沙箱状态
  - GET  /api/sandbox/check-docker — 检测 Docker 可用性
  - POST /api/sandbox/execute      — 执行代码
  - POST /api/sandbox/select       — 切换沙箱后端
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.core.ports.code_sandbox import CodeExecutionResult

_TEST_API_KEY = "test-task-api-key-12345"
_AUTH_HEADERS = {"X-API-Key": _TEST_API_KEY}


# ── 辅助函数 ──────────────────────────────────────────────


def _make_success_result(
    stdout: str = "hello world\n",
) -> CodeExecutionResult:
    """创建成功的沙箱执行结果"""
    return CodeExecutionResult(
        success=True,
        stdout=stdout,
        stderr="",
        execution_time=0.015,
    )


def _make_error_result(error_message: str = "error occurred") -> CodeExecutionResult:
    """创建失败的沙箱执行结果"""
    return CodeExecutionResult(
        success=False,
        stdout="",
        stderr=error_message,
        error_message=error_message,
        execution_time=0.010,
    )


def _make_mock_info(backend: str = "subprocess", docker_available: bool = False):
    """创建模拟的沙箱信息"""
    info = MagicMock()
    info.backend = backend
    info.docker_available = docker_available
    info.reason = "降级到 subprocess"
    info.image = ""
    return info


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def client_with_auth(monkeypatch) -> TestClient:
    """注入认证的 TestClient"""
    monkeypatch.setenv("PYCODER_API_KEY", _TEST_API_KEY)
    import importlib
    import pycoder.server.app as app_module
    importlib.reload(app_module)
    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c


# ── GET /api/sandbox/status 测试 ──────────────────────────


class TestGetStatus:
    """沙箱状态端点"""

    @patch("pycoder.server.routers.sandbox_api.get_selector")
    def test_get_status_success(self, mock_get_selector: MagicMock, client_with_auth: TestClient) -> None:
        """测试获取沙箱状态"""
        mock_selector = MagicMock()
        mock_selector.select = AsyncMock(return_value=_make_mock_info())
        mock_get_selector.return_value = mock_selector

        resp = client_with_auth.get("/api/sandbox/status", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "backend" in data
        assert "docker_available" in data
        assert "reason" in data


# ── GET /api/sandbox/check-docker 测试 ────────────────────


class TestCheckDocker:
    """Docker 检测端点"""

    @patch("pycoder.server.routers.sandbox_api.check_docker_available")
    @patch("pycoder.adapters.sandbox_selector.invalidate_docker_cache")
    def test_check_docker(
        self, mock_invalidate: MagicMock, mock_check: AsyncMock, client_with_auth: TestClient
    ) -> None:
        """测试检测 Docker 可用性"""
        mock_check.return_value = (False, "Docker 未安装")

        resp = client_with_auth.get("/api/sandbox/check-docker", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "docker_available" in data
        assert "reason" in data


# ── POST /api/sandbox/execute 测试 ────────────────────────


class TestExecuteCode:
    """沙箱代码执行端点"""

    def test_execute_empty_code(self, client_with_auth: TestClient) -> None:
        """测试空代码返回 400"""
        resp = client_with_auth.post(
            "/api/sandbox/execute",
            json={"code": "", "timeout": 30},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["error"]["message"]

    def test_execute_whitespace_code(self, client_with_auth: TestClient) -> None:
        """测试纯空白代码返回 400"""
        resp = client_with_auth.post(
            "/api/sandbox/execute",
            json={"code": "   ", "timeout": 30},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 400

    @patch("pycoder.server.routers.sandbox_api.execute_code", new_callable=AsyncMock)
    def test_execute_python_success(
        self, mock_execute: AsyncMock, client_with_auth: TestClient
    ) -> None:
        """测试执行 Python 代码成功"""
        mock_execute.return_value = (
            _make_success_result("hello world\n"),
            _make_mock_info(),
        )
        resp = client_with_auth.post(
            "/api/sandbox/execute",
            json={"code": "print('hello world')", "timeout": 30},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "hello world" in data["stdout"]
        assert data["sandbox_backend"] == "subprocess"

    @patch("pycoder.server.routers.sandbox_api.execute_code", new_callable=AsyncMock)
    def test_execute_with_error(
        self, mock_execute: AsyncMock, client_with_auth: TestClient
    ) -> None:
        """测试执行含错误代码"""
        mock_execute.return_value = (
            _make_error_result("NameError: name 'x' is not defined"),
            _make_mock_info(),
        )
        resp = client_with_auth.post(
            "/api/sandbox/execute",
            json={"code": "print(x)", "timeout": 30},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    @patch("pycoder.server.routers.sandbox_api.execute_code", new_callable=AsyncMock)
    def test_execute_with_custom_timeout(
        self, mock_execute: AsyncMock, client_with_auth: TestClient
    ) -> None:
        """测试自定义超时参数"""
        mock_execute.return_value = (
            _make_success_result("done"),
            _make_mock_info(),
        )
        resp = client_with_auth.post(
            "/api/sandbox/execute",
            json={"code": "print('hello')", "timeout": 10},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @patch("pycoder.server.routers.sandbox_api.SandboxSelector")
    def test_execute_with_prefer_docker(
        self, mock_selector_cls: MagicMock, client_with_auth: TestClient
    ) -> None:
        """测试偏好 Docker 执行"""
        mock_selector = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.execute = AsyncMock(return_value=_make_success_result("hello"))
        mock_selector.get_sandbox = AsyncMock(return_value=(mock_sandbox, _make_mock_info()))
        mock_selector_cls.return_value = mock_selector

        resp = client_with_auth.post(
            "/api/sandbox/execute",
            json={"code": "print('hello')", "timeout": 30, "prefer": "docker"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200


# ── POST /api/sandbox/select 测试 ─────────────────────────


class TestSelectBackend:
    """沙箱后端选择端点"""

    @patch("pycoder.server.routers.sandbox_api.reset_selector")
    @patch("pycoder.server.routers.sandbox_api.SandboxSelector")
    def test_select_subprocess(
        self, mock_selector_cls: MagicMock, mock_reset: MagicMock, client_with_auth: TestClient
    ) -> None:
        """测试切换到 subprocess 后端"""
        mock_selector = MagicMock()
        mock_selector.select = AsyncMock(return_value=_make_mock_info("subprocess"))
        mock_selector_cls.return_value = mock_selector

        resp = client_with_auth.post(
            "/api/sandbox/select",
            json={"prefer": "subprocess"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["backend"] == "subprocess"

    @patch("pycoder.server.routers.sandbox_api.reset_selector")
    @patch("pycoder.server.routers.sandbox_api.SandboxSelector")
    def test_select_docker(
        self, mock_selector_cls: MagicMock, mock_reset: MagicMock, client_with_auth: TestClient
    ) -> None:
        """测试切换到 docker 后端"""
        mock_selector = MagicMock()
        mock_selector.select = AsyncMock(return_value=_make_mock_info("docker"))
        mock_selector_cls.return_value = mock_selector

        resp = client_with_auth.post(
            "/api/sandbox/select",
            json={"prefer": "docker"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "backend" in data

    def test_select_invalid(self, client_with_auth: TestClient) -> None:
        """测试无效的 prefer 值返回 422"""
        resp = client_with_auth.post(
            "/api/sandbox/select",
            json={"prefer": "invalid"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 422