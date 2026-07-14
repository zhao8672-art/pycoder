"""P4: Docker 容器化沙箱测试

覆盖:
  - DockerSandbox.is_available() — 可用性检测
  - DockerSandbox.execute() — 容器内执行（mock docker CLI）
  - execute_code_safely() — 自动降级逻辑
  - 资源限制参数构造
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from pycoder.server.services.docker_sandbox import (
    DEFAULT_CPU_QUOTA,
    DEFAULT_IMAGE,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_PIDS_LIMIT,
    DockerSandbox,
    SandboxResult,
    execute_code_safely,
    get_docker_sandbox,
)


# ══════════════════════════════════════════════════════════
# DockerSandbox.is_available
# ══════════════════════════════════════════════════════════


class TestDockerAvailability:

    def test_unavailable_when_docker_not_found(self, monkeypatch):
        """docker 命令不存在时返回 False"""
        def fake_run(cmd, **kw):
            raise FileNotFoundError("docker not found")
        monkeypatch.setattr("subprocess.run", fake_run)
        sandbox = DockerSandbox()
        sandbox._available = None  # 重置缓存
        assert sandbox.is_available() is False

    def test_unavailable_when_docker_not_running(self, monkeypatch):
        """docker 命令返回非 0 时返回 False"""
        fake_proc = MagicMock(returncode=1, stdout=b"", stderr=b"")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)
        sandbox = DockerSandbox()
        sandbox._available = None
        assert sandbox.is_available() is False

    def test_available_when_docker_running(self, monkeypatch):
        fake_proc = MagicMock(returncode=0, stdout=b"20.10.0", stderr=b"")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)
        sandbox = DockerSandbox()
        sandbox._available = None
        assert sandbox.is_available() is True

    def test_availability_cached(self, monkeypatch):
        """可用性结果被缓存"""
        call_count = 0
        def fake_run(cmd, **kw):
            nonlocal call_count
            call_count += 1
            return MagicMock(returncode=0, stdout=b"20.10", stderr=b"")
        monkeypatch.setattr("subprocess.run", fake_run)
        sandbox = DockerSandbox()
        sandbox._available = None
        sandbox.is_available()
        sandbox.is_available()
        assert call_count == 1  # 只调用一次


# ══════════════════════════════════════════════════════════
# DockerSandbox.execute
# ══════════════════════════════════════════════════════════


class TestDockerExecute:

    def test_execute_returns_unavailable_when_no_docker(self, monkeypatch):
        """Docker 不可用时返回明确错误"""
        def fake_run(cmd, **kw):
            raise FileNotFoundError("docker")
        monkeypatch.setattr("subprocess.run", fake_run)
        sandbox = DockerSandbox()
        sandbox._available = None
        result = sandbox.execute("print('hi')")
        assert result.success is False
        assert result.error_type == "DockerUnavailable"
        assert result.backend == "docker"

    def test_execute_parses_sandbox_result(self, monkeypatch):
        """成功执行时解析 SANDBOX_RESULT 标记"""
        sandbox_output = {
            "success": True,
            "stdout": "hello\n",
            "stderr": "",
            "error_type": "",
            "error_message": "",
            "traceback": "",
            "execution_time": 0.05,
        }
        stdout_bytes = (
            b"__SANDBOX_RESULT__" +
            json.dumps(sandbox_output).encode() +
            b"__SANDBOX_END__"
        )
        fake_proc = MagicMock(
            returncode=0,
            stdout=stdout_bytes,
            stderr=b"",
        )
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)
        sandbox = DockerSandbox()
        sandbox._available = True  # 跳过可用性检查
        result = sandbox.execute("print('hello')")
        assert result.success is True
        assert result.stdout == "hello\n"
        assert result.backend == "docker"

    def test_execute_handles_timeout(self, monkeypatch):
        """容器超时返回 TimeoutError"""
        import subprocess as sp
        def fake_run(cmd, **kw):
            raise sp.TimeoutExpired(cmd=cmd, timeout=30)
        monkeypatch.setattr("subprocess.run", fake_run)
        sandbox = DockerSandbox()
        sandbox._available = True
        result = sandbox.execute("while True: pass", timeout=5)
        assert result.success is False
        assert result.error_type == "TimeoutError"
        assert result.backend == "docker"

    def test_execute_handles_subprocess_error(self, monkeypatch):
        """docker run 失败返回错误"""
        def fake_run(cmd, **kw):
            raise OSError("docker daemon error")
        monkeypatch.setattr("subprocess.run", fake_run)
        sandbox = DockerSandbox()
        sandbox._available = True
        result = sandbox.execute("print('hi')")
        assert result.success is False
        assert result.error_type == "OSError"
        assert result.backend == "docker"

    def test_execute_fallback_on_parse_failure(self, monkeypatch):
        """SANDBOX_RESULT 解析失败时返回原始输出"""
        fake_proc = MagicMock(
            returncode=0,
            stdout=b"raw output without markers",
            stderr=b"",
        )
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)
        sandbox = DockerSandbox()
        sandbox._available = True
        result = sandbox.execute("print('hi')")
        assert result.success is True  # returncode 0
        assert "raw output" in result.stdout
        assert result.backend == "docker"

    def test_execute_passes_code_via_stdin(self, monkeypatch):
        """代码通过 stdin 传给容器"""
        captured_kwargs = {}
        fake_proc = MagicMock(returncode=0, stdout=b"__SANDBOX_RESULT__" + json.dumps({"success": True}).encode() + b"__SANDBOX_END__", stderr=b"")
        def fake_run(cmd, **kw):
            captured_kwargs.update(kw)
            return fake_proc
        monkeypatch.setattr("subprocess.run", fake_run)
        sandbox = DockerSandbox()
        sandbox._available = True
        sandbox.execute("print('test')")
        assert b"print('test')" in captured_kwargs["input"]


# ══════════════════════════════════════════════════════════
# 资源限制参数
# ══════════════════════════════════════════════════════════


class TestResourceLimits:

    def test_default_limits(self):
        s = DockerSandbox()
        assert s.memory_limit == DEFAULT_MEMORY_LIMIT
        assert s.cpu_quota == DEFAULT_CPU_QUOTA
        assert s.pids_limit == DEFAULT_PIDS_LIMIT
        assert s.network_enabled is False

    def test_custom_limits(self):
        s = DockerSandbox(
            memory_limit="512m",
            cpu_quota=100000,
            pids_limit=128,
            network_enabled=True,
        )
        assert s.memory_limit == "512m"
        assert s.cpu_quota == 100000
        assert s.pids_limit == 128
        assert s.network_enabled is True

    def test_default_image(self):
        s = DockerSandbox()
        assert s.image == DEFAULT_IMAGE
        assert "python" in s.image


# ══════════════════════════════════════════════════════════
# execute_code_safely — 自动降级
# ══════════════════════════════════════════════════════════


class TestExecuteCodeSafely:

    def test_falls_back_to_subprocess_when_docker_unavailable(self, monkeypatch):
        """Docker 不可用时降级到子进程"""
        # Docker 不可用
        def docker_unavailable(cmd, **kw):
            raise FileNotFoundError("docker")
        monkeypatch.setattr("subprocess.run", docker_unavailable)

        # 子进程模拟返回
        from pycoder.server.routers import code_exec
        fake_result = MagicMock(
            success=True, stdout="ok", stderr="",
            error_type="", error_message="", traceback="",
            execution_time=0.1,
        )
        monkeypatch.setattr(code_exec, "_run_in_subprocess", lambda code, timeout: fake_result)

        result = execute_code_safely("print('hi')", timeout=5)
        assert result.success is True
        assert result.backend == "subprocess"
        assert result.stdout == "ok"

    def test_prefers_docker_when_available(self, monkeypatch):
        """Docker 可用时优先使用"""
        sandbox_output = {
            "success": True, "stdout": "docker ok", "stderr": "",
            "error_type": "", "error_message": "", "traceback": "",
            "execution_time": 0.05,
        }
        stdout_bytes = (
            b"__SANDBOX_RESULT__" +
            json.dumps(sandbox_output).encode() +
            b"__SANDBOX_END__"
        )
        fake_proc = MagicMock(returncode=0, stdout=stdout_bytes, stderr=b"")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

        result = execute_code_safely("print('hi')", timeout=5, prefer_docker=True)
        assert result.backend == "docker"
        assert result.stdout == "docker ok"

    def test_force_subprocess_with_prefer_false(self, monkeypatch):
        """prefer_docker=False 强制子进程"""
        from pycoder.server.routers import code_exec
        fake_result = MagicMock(
            success=True, stdout="subprocess", stderr="",
            error_type="", error_message="", traceback="",
            execution_time=0.1,
        )
        monkeypatch.setattr(code_exec, "_run_in_subprocess", lambda code, timeout: fake_result)

        result = execute_code_safely("print('hi')", prefer_docker=False)
        assert result.backend == "subprocess"
        assert result.stdout == "subprocess"


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestSingleton:

    def test_get_docker_sandbox_returns_same_instance(self):
        s1 = get_docker_sandbox()
        s2 = get_docker_sandbox()
        assert s1 is s2
