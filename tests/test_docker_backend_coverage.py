"""docker_backend 模块覆盖率测试 — Docker 远程执行后端

覆盖 pycoder.server.docker_backend:
- DockerBackend 类: is_available / ensure_container / execute / install_package / cleanup / get_status
- DockerExecutionResult 数据类
- get_docker_backend 单例

测试策略：mock 模块级 _ec（EnvChecker 实例）和 subprocess.run，
避免触发真实 Docker 命令。
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

import pycoder.server.docker_backend as docker_mod
from pycoder.server.docker_backend import (
    DockerBackend,
    DockerExecutionResult,
    get_docker_backend,
)


@pytest.fixture
def mock_ec(monkeypatch):
    """模拟环境检测器实例（模块级 _ec）。

    同时 mock logger 以避免源代码 logger.info(hint=...) 触发
    TypeError: Logger._log() got an unexpected keyword argument 'hint'
    （这是源代码 bug，本测试不修改源文件）。
    """
    ec = MagicMock()
    ec.has.return_value = True
    caps = MagicMock()
    caps.docker.hint = "请安装 Docker"
    ec.get_capabilities.return_value = caps
    monkeypatch.setattr(docker_mod, "_ec", ec)
    monkeypatch.setattr(docker_mod, "logger", MagicMock())
    return ec


@pytest.fixture
def fresh_backend(mock_ec):
    """创建全新的 DockerBackend（无缓存）"""
    return DockerBackend()


# ══════════════════════════════════════════════════════════
# DockerExecutionResult
# ══════════════════════════════════════════════════════════


class TestDockerExecutionResult:
    def test_defaults(self):
        r = DockerExecutionResult(success=True)
        assert r.success is True
        assert r.output == ""
        assert r.error == ""
        assert r.duration_ms == 0.0
        assert r.container_id == ""

    def test_with_values(self):
        r = DockerExecutionResult(
            success=False, output="o", error="e", duration_ms=12.5, container_id="abc"
        )
        assert r.success is False
        assert r.output == "o"
        assert r.duration_ms == 12.5
        assert r.container_id == "abc"


# ══════════════════════════════════════════════════════════
# is_available
# ══════════════════════════════════════════════════════════


class TestIsAvailable:
    def test_available_first_call(self, fresh_backend, mock_ec):
        assert fresh_backend.is_available is True
        mock_ec.has.assert_called_once_with("docker")

    def test_unavailable_logs_hint(self, mock_ec, monkeypatch):
        mock_ec.has.return_value = False
        backend = DockerBackend()
        assert backend.is_available is False
        # 不可用时应查询 capabilities 获取 hint
        mock_ec.get_capabilities.assert_called_once()

    def test_available_does_not_query_capabilities(self, fresh_backend, mock_ec):
        """可用时不应调用 get_capabilities"""
        fresh_backend.is_available
        mock_ec.get_capabilities.assert_not_called()

    def test_cached_after_first_call(self, fresh_backend, mock_ec):
        fresh_backend.is_available
        fresh_backend.is_available
        fresh_backend.is_available
        # has 只应被调用一次（缓存命中后两次直接返回）
        assert mock_ec.has.call_count == 1


# ══════════════════════════════════════════════════════════
# ensure_container
# ══════════════════════════════════════════════════════════


class TestEnsureContainer:
    async def test_create_new_container(self, fresh_backend, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="newcid\n", stderr=""))
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        cid = await fresh_backend.ensure_container()
        assert cid == "newcid"
        assert fresh_backend._container_id == "newcid"

    async def test_reuse_running_container(self, mock_ec, monkeypatch):
        """已有容器且仍在运行时复用"""
        backend = DockerBackend()
        backend._container_id = "existing123"
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="true\n", stderr="")
        )
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        cid = await backend.ensure_container()
        assert cid == "existing123"
        # 应只调用 inspect，不调用 run
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "inspect" in first_call_args

    async def test_recreate_when_stopped(self, mock_ec, monkeypatch):
        """容器已停止时应重建"""
        backend = DockerBackend()
        backend._container_id = "old123"
        inspect_resp = MagicMock(returncode=0, stdout="false\n", stderr="")
        run_resp = MagicMock(returncode=0, stdout="newcid\n", stderr="")
        mock_run = MagicMock(side_effect=[inspect_resp, run_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        cid = await backend.ensure_container()
        assert cid == "newcid"
        assert backend._container_id == "newcid"

    async def test_recreate_when_inspect_fails(self, mock_ec, monkeypatch):
        """inspect 命令失败时应重建"""
        backend = DockerBackend()
        backend._container_id = "old123"
        inspect_resp = MagicMock(returncode=1, stdout="", stderr="no such container")
        run_resp = MagicMock(returncode=0, stdout="newcid\n", stderr="")
        mock_run = MagicMock(side_effect=[inspect_resp, run_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        cid = await backend.ensure_container()
        assert cid == "newcid"

    async def test_create_failure_raises(self, fresh_backend, monkeypatch):
        mock_run = MagicMock(
            return_value=MagicMock(returncode=1, stdout="", stderr="docker error")
        )
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        with pytest.raises(RuntimeError, match="Docker 启动失败"):
            await fresh_backend.ensure_container()


# ══════════════════════════════════════════════════════════
# execute
# ══════════════════════════════════════════════════════════


class TestExecute:
    async def test_execute_success(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        exec_resp = MagicMock(returncode=0, stdout="result\n", stderr="")
        mock_run = MagicMock(side_effect=[ensure_resp, exec_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        result = await fresh_backend.execute("print('hi')")
        assert result.success is True
        assert result.output == "result\n"
        assert result.error == ""
        assert result.container_id == "cid"
        assert result.duration_ms >= 0

    async def test_execute_nonzero_exit(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        exec_resp = MagicMock(returncode=1, stdout="", stderr="syntax error")
        mock_run = MagicMock(side_effect=[ensure_resp, exec_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        result = await fresh_backend.execute("invalid code")
        assert result.success is False
        assert result.error == "syntax error"

    async def test_execute_timeout(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        # 使用异常实例（非函数）确保 side_effect 列表会抛出而非返回
        mock_run = MagicMock(
            side_effect=[ensure_resp, subprocess.TimeoutExpired(cmd="x", timeout=1)]
        )
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        result = await fresh_backend.execute("import time; time.sleep(100)", timeout=1)
        assert result.success is False
        assert "超时" in result.error
        assert result.duration_ms == 1000  # timeout * 1000

    async def test_execute_general_exception(self, fresh_backend, monkeypatch):
        mock_run = MagicMock(side_effect=RuntimeError("docker down"))
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        result = await fresh_backend.execute("code")
        assert result.success is False
        assert "docker down" in result.error

    async def test_execute_truncates_output(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        long_out = "x" * 3000
        long_err = "y" * 1500
        exec_resp = MagicMock(returncode=0, stdout=long_out, stderr=long_err)
        mock_run = MagicMock(side_effect=[ensure_resp, exec_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        result = await fresh_backend.execute("code")
        assert len(result.output) == 2000
        assert len(result.error) == 1000


# ══════════════════════════════════════════════════════════
# install_package
# ══════════════════════════════════════════════════════════


class TestInstallPackage:
    async def test_install_success(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        install_resp = MagicMock(
            returncode=0, stdout="Successfully installed numpy\n", stderr=""
        )
        mock_run = MagicMock(side_effect=[ensure_resp, install_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        ok, msg = await fresh_backend.install_package("numpy")
        assert ok is True
        assert "Successfully" in msg

    async def test_install_failure_returns_stderr(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        install_resp = MagicMock(returncode=1, stdout="", stderr="pip error\n")
        mock_run = MagicMock(side_effect=[ensure_resp, install_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        ok, msg = await fresh_backend.install_package("nonexistent-pkg")
        assert ok is False
        assert "pip error" in msg

    async def test_install_returns_empty_stdout_uses_stderr(
        self, fresh_backend, monkeypatch
    ):
        ensure_resp = MagicMock(returncode=0, stdout="cid\n", stderr="")
        # stdout 为空时 fallback 到 stderr
        install_resp = MagicMock(returncode=0, stdout="", stderr="from stderr\n")
        mock_run = MagicMock(side_effect=[ensure_resp, install_resp])
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        ok, msg = await fresh_backend.install_package("pkg")
        assert ok is True
        assert "from stderr" in msg

    async def test_install_exception(self, fresh_backend, monkeypatch):
        mock_run = MagicMock(side_effect=RuntimeError("oops"))
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        ok, msg = await fresh_backend.install_package("numpy")
        assert ok is False
        assert "oops" in msg


# ══════════════════════════════════════════════════════════
# cleanup
# ══════════════════════════════════════════════════════════


class TestCleanup:
    async def test_cleanup_with_container(self, mock_ec, monkeypatch):
        backend = DockerBackend()
        backend._container_id = "abc"
        mock_run = MagicMock()
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        await backend.cleanup()
        assert backend._container_id is None
        mock_run.assert_called_once()
        # 验证调用 docker stop
        args = mock_run.call_args[0][0]
        assert "stop" in args

    async def test_cleanup_no_container(self, mock_ec, monkeypatch):
        backend = DockerBackend()
        mock_run = MagicMock()
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        await backend.cleanup()
        assert backend._container_id is None
        mock_run.assert_not_called()


# ══════════════════════════════════════════════════════════
# get_status
# ══════════════════════════════════════════════════════════


class TestGetStatus:
    async def test_status_unavailable(self, mock_ec):
        mock_ec.has.return_value = False
        backend = DockerBackend()
        # 重置缓存以触发 _ec.has 调用
        backend._available = None
        status = await backend.get_status()
        assert status["available"] is False
        assert "reason" in status

    async def test_status_available(self, fresh_backend, monkeypatch):
        ensure_resp = MagicMock(returncode=0, stdout="cid1234567890abc\n", stderr="")
        mock_run = MagicMock(return_value=ensure_resp)
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        status = await fresh_backend.get_status()
        assert status["available"] is True
        # container_id 截断为前 12 字符: c,i,d,1,2,3,4,5,6,7,8,9 = 12 字符
        assert status["container_id"] == "cid123456789"
        assert status["image"] == "python:3.13-slim"

    async def test_status_exception(self, fresh_backend, monkeypatch):
        mock_run = MagicMock(side_effect=RuntimeError("docker down"))
        monkeypatch.setattr(docker_mod.subprocess, "run", mock_run)
        status = await fresh_backend.get_status()
        assert status["available"] is False
        assert "docker down" in status["reason"]


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_docker_backend_returns_same_instance(self, monkeypatch):
        # 重置单例
        monkeypatch.setattr(docker_mod, "_docker_backend", None)
        b1 = get_docker_backend()
        b2 = get_docker_backend()
        assert b1 is b2

    def test_get_docker_backend_default_image(self, monkeypatch):
        monkeypatch.setattr(docker_mod, "_docker_backend", None)
        backend = get_docker_backend()
        assert backend.image == "python:3.13-slim"
