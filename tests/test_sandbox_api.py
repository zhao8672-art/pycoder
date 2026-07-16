"""
Docker 沙箱执行器 API 路由单元测试 — 覆盖 sandbox_api.py 所有端点

测试范围:
  - POST /api/sandbox/execute    — 执行代码
  - POST /api/sandbox/command    — 执行 Shell 命令
  - POST /api/sandbox/build-test — 构建测试
  - GET  /api/sandbox/status     — 获取状态
  - POST /api/sandbox/cleanup    — 清理容器
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.safety.sandbox import SandboxResult
from pycoder.safety.sandbox_executor import (
    DockerNotAvailableError,
    PoolStats,
    SandboxMemoryError,
    SandboxPool,
    SandboxTimeoutError,
)


# ── 辅助函数 ──────────────────────────────────────────────


def _make_success_result(
    output: str = "hello world\n",
    exit_code: int = 0,
) -> SandboxResult:
    """创建成功的沙箱执行结果"""
    return SandboxResult(
        success=True,
        output=output,
        error="",
        exit_code=exit_code,
        duration_ms=15.5,
        killed_by_timeout=False,
        killed_by_memory=False,
        memory_used_mb=12.3,
    )


def _make_error_result(error: str = "error occurred") -> SandboxResult:
    """创建失败的沙箱执行结果"""
    return SandboxResult(
        success=False,
        output="",
        error=error,
        exit_code=1,
        duration_ms=10.0,
        killed_by_timeout=False,
        killed_by_memory=False,
        memory_used_mb=5.0,
    )


def _make_mock_executor() -> MagicMock:
    """创建模拟的沙箱执行器"""
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=_make_success_result())
    executor.execute_command = AsyncMock(return_value=_make_success_result("cmd output\n"))
    executor.build_and_test = AsyncMock(return_value=_make_success_result("test output\n"))
    return executor


def _make_mock_pool_stats() -> PoolStats:
    """创建模拟的池统计信息"""
    stats = PoolStats()
    stats.available = 2
    stats.in_use = 1
    stats.total = 3
    stats.max_containers = 10
    stats.docker_available = True
    return stats


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_executor() -> MagicMock:
    """创建模拟的沙箱执行器"""
    return _make_mock_executor()


@pytest.fixture
def client_with_pool(mock_executor: MagicMock) -> TestClient:
    """注入模拟沙箱池的 TestClient"""
    from pycoder.server.routers import sandbox_api

    # 保存原始池
    orig_pool = sandbox_api._sandbox_pool

    # 创建模拟池
    mock_pool = MagicMock()

    # 正确地模拟 async with pool.acquire() as executor
    async def _mock_acquire(self):
        return mock_executor

    mock_pool.acquire.return_value.__aenter__ = _mock_acquire
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_pool.get_stats.return_value = _make_mock_pool_stats()
    mock_pool.cleanup = AsyncMock(return_value=None)

    sandbox_api._sandbox_pool = mock_pool

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    sandbox_api._sandbox_pool = orig_pool


# ── POST /api/sandbox/execute 测试 ────────────────────────


class TestExecuteCode:
    """沙箱代码执行端点"""

    def test_execute_python_success(self, client_with_pool: TestClient) -> None:
        """测试执行 Python 代码成功"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={
                "code": "print('hello world')",
                "language": "python",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "hello world" in data["output"]
        assert data["exit_code"] == 0
        assert data["duration_ms"] > 0
        assert data["killed_by_timeout"] is False
        assert data["killed_by_memory"] is False

    def test_execute_with_files(self, client_with_pool: TestClient) -> None:
        """测试带额外文件的代码执行"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={
                "code": "print('hello')",
                "language": "python",
                "files": {"data.txt": "hello data"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_execute_with_network_enabled(self, client_with_pool: TestClient) -> None:
        """测试启用网络的代码执行"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={
                "code": "print('hello')",
                "language": "python",
                "network_enabled": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_execute_empty_code(self, client_with_pool: TestClient) -> None:
        """测试空代码返回 400"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={"code": "", "language": "python"},
        )
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["detail"]

    def test_execute_whitespace_code(self, client_with_pool: TestClient) -> None:
        """测试纯空白代码返回 400"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={"code": "   ", "language": "python"},
        )
        assert resp.status_code == 400

    def test_execute_timeout_error(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试超时返回 408"""
        mock_executor.execute = AsyncMock(side_effect=SandboxTimeoutError(30.0))

        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={"code": "while True: pass", "language": "python"},
        )
        assert resp.status_code == 408

    def test_execute_memory_error(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试内存超限返回 413"""
        mock_executor.execute = AsyncMock(side_effect=SandboxMemoryError(1024))

        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={"code": "big_array = [0]*10**9", "language": "python"},
        )
        assert resp.status_code == 413

    def test_execute_docker_not_available(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试 Docker 不可用返回 503"""
        mock_executor.execute = AsyncMock(
            side_effect=DockerNotAvailableError("连接被拒绝")
        )

        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={"code": "print('hello')", "language": "python"},
        )
        assert resp.status_code == 503
        assert "Docker" in resp.json()["detail"]

    def test_execute_with_custom_timeout(self, client_with_pool: TestClient) -> None:
        """测试自定义超时参数"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={
                "code": "print('hello')",
                "language": "python",
                "timeout": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_execute_default_language(self, client_with_pool: TestClient) -> None:
        """测试默认语言为 python"""
        resp = client_with_pool.post(
            "/api/sandbox/execute",
            json={"code": "print('hello')"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ── POST /api/sandbox/command 测试 ────────────────────────


class TestExecuteCommand:
    """沙箱命令执行端点"""

    def test_execute_command_success(self, client_with_pool: TestClient) -> None:
        """测试命令执行成功"""
        resp = client_with_pool.post(
            "/api/sandbox/command",
            json={"command": "ls -la"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "cmd output" in data["output"]

    def test_execute_command_with_cwd(self, client_with_pool: TestClient) -> None:
        """测试指定工作目录的命令执行"""
        resp = client_with_pool.post(
            "/api/sandbox/command",
            json={
                "command": "ls",
                "cwd": "/sandbox",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_execute_command_empty(self, client_with_pool: TestClient) -> None:
        """测试空命令返回 400"""
        resp = client_with_pool.post(
            "/api/sandbox/command",
            json={"command": ""},
        )
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["detail"]

    def test_execute_command_timeout(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试命令超时"""
        mock_executor.execute_command = AsyncMock(
            side_effect=SandboxTimeoutError(30.0)
        )

        resp = client_with_pool.post(
            "/api/sandbox/command",
            json={"command": "sleep 100"},
        )
        assert resp.status_code == 408

    def test_execute_command_docker_unavailable(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试 Docker 不可用"""
        mock_executor.execute_command = AsyncMock(
            side_effect=DockerNotAvailableError("不可用")
        )

        resp = client_with_pool.post(
            "/api/sandbox/command",
            json={"command": "echo hello"},
        )
        assert resp.status_code == 503


# ── POST /api/sandbox/build-test 测试 ─────────────────────


class TestBuildTest:
    """构建测试端点"""

    def test_build_test_success(self, client_with_pool: TestClient) -> None:
        """测试构建测试成功"""
        resp = client_with_pool.post(
            "/api/sandbox/build-test",
            json={
                "project_path": "/tmp/test-project",
                "test_command": "pytest",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "test output" in data["output"]

    def test_build_test_empty_path(self, client_with_pool: TestClient) -> None:
        """测试空项目路径返回 400"""
        resp = client_with_pool.post(
            "/api/sandbox/build-test",
            json={
                "project_path": "",
                "test_command": "pytest",
            },
        )
        assert resp.status_code == 400
        assert "项目路径" in resp.json()["detail"]

    def test_build_test_empty_command(self, client_with_pool: TestClient) -> None:
        """测试空测试命令返回 400"""
        resp = client_with_pool.post(
            "/api/sandbox/build-test",
            json={
                "project_path": "/tmp/test-project",
                "test_command": "",
            },
        )
        assert resp.status_code == 400
        assert "测试命令" in resp.json()["detail"]

    def test_build_test_timeout(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试构建超时"""
        mock_executor.build_and_test = AsyncMock(
            side_effect=SandboxTimeoutError(60.0)
        )

        resp = client_with_pool.post(
            "/api/sandbox/build-test",
            json={
                "project_path": "/tmp/test-project",
                "test_command": "pytest",
            },
        )
        assert resp.status_code == 408

    def test_build_test_docker_unavailable(self, client_with_pool: TestClient, mock_executor: MagicMock) -> None:
        """测试 Docker 不可用"""
        mock_executor.build_and_test = AsyncMock(
            side_effect=DockerNotAvailableError("不可用")
        )

        resp = client_with_pool.post(
            "/api/sandbox/build-test",
            json={
                "project_path": "/tmp/test-project",
                "test_command": "pytest",
            },
        )
        assert resp.status_code == 503


# ── GET /api/sandbox/status 测试 ──────────────────────────


class TestGetStatus:
    """沙箱状态端点"""

    def test_get_status_success(self, client_with_pool: TestClient) -> None:
        """测试获取沙箱状态"""
        resp = client_with_pool.get("/api/sandbox/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "docker_available" in data
        assert "stats" in data
        assert data["stats"]["max_containers"] == 10

    def test_get_status_docker_unavailable(self, client_with_pool: TestClient) -> None:
        """测试 Docker 不可用状态"""
        from pycoder.server.routers import sandbox_api

        stats = _make_mock_pool_stats()
        stats.docker_available = False
        sandbox_api._sandbox_pool.get_stats.return_value = stats

        resp = client_with_pool.get("/api/sandbox/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["docker_available"] is False


# ── POST /api/sandbox/cleanup 测试 ────────────────────────


class TestCleanup:
    """清理端点"""

    def test_cleanup_success(self, client_with_pool: TestClient) -> None:
        """测试成功清理"""
        resp = client_with_pool.post("/api/sandbox/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "已清理" in data["message"]

    def test_cleanup_error(self, client_with_pool: TestClient) -> None:
        """测试清理失败返回 500"""
        from pycoder.server.routers import sandbox_api

        sandbox_api._sandbox_pool.cleanup = AsyncMock(
            side_effect=Exception("清理异常")
        )

        resp = client_with_pool.post("/api/sandbox/cleanup")
        assert resp.status_code == 500
        assert "清理失败" in resp.json()["detail"]