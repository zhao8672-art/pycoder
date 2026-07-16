"""Docker 沙箱执行器测试 — DockerSandboxExecutor 单元测试

覆盖:
  - DockerSandboxConfig 初始化
  - DockerSandboxExecutor 初始化（mock docker client）
  - execute() 方法基本 Python 代码执行
  - 超时处理
  - SandboxResult 结果验证（exit_code, stdout, stderr）
  - 错误处理（容器失败、镜像未找到）
  - 资源限制配置
  - 网络隔离设置
  - 临时文件系统挂载逻辑
  - 容器清理
  - 语言映射
  - Docker 不可用时的降级执行
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from pycoder.safety.sandbox import SandboxResult
from pycoder.safety.sandbox_executor import (
    _LANGUAGE_COMMAND_MAP,
    _LANGUAGE_EXT_MAP,
    _LANGUAGE_IMAGE_MAP,
    DockerNotAvailableError,
    DockerSandboxConfig,
    DockerSandboxExecutor,
    SandboxTimeoutError,
    _make_tar_payload,
)

# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _make_mock_exec_result(exit_code: int = 0, output: str = "hello\n") -> MagicMock:
    """创建模拟的 exec_run 返回结果"""
    result = MagicMock()
    result.exit_code = exit_code
    result.output = output.encode("utf-8") if output else b""
    return result


def _make_mock_container(
    container_id: str = "abc123def456",
    exec_result: MagicMock | None = None,
) -> MagicMock:
    """创建模拟的 Docker 容器"""
    container = MagicMock()
    container.id = container_id
    container.exec_run.return_value = exec_result or _make_mock_exec_result()
    container.put_archive.return_value = True
    container.stop.return_value = None
    return container


def _make_mock_docker_client(container: MagicMock | None = None) -> MagicMock:
    """创建模拟的 Docker 客户端"""
    client = MagicMock()
    client.ping.return_value = True
    if container:
        client.containers.run.return_value = container
    else:
        client.containers.run.return_value = _make_mock_container()
    return client


# ══════════════════════════════════════════════════════════
# DockerSandboxConfig 测试
# ══════════════════════════════════════════════════════════


class TestDockerSandboxConfig:
    """DockerSandboxConfig 配置测试"""

    def test_default_config(self) -> None:
        """默认配置值验证"""
        cfg = DockerSandboxConfig()
        assert cfg.python_image == "python:3.11-slim"
        assert cfg.node_image == "node:20-slim"
        assert cfg.default_memory_mb == 256
        assert cfg.max_memory_mb == 1024
        assert cfg.default_cpu_shares == 512
        assert cfg.max_cpu_shares == 2048
        assert cfg.default_timeout == 30.0
        assert cfg.max_timeout == 300.0
        assert cfg.disable_network is True
        assert cfg.read_only_rootfs is True
        assert cfg.work_dir == "/sandbox"

    def test_custom_config(self) -> None:
        """自定义配置值验证"""
        cfg = DockerSandboxConfig(
            python_image="python:3.12-slim",
            default_memory_mb=512,
            default_timeout=60.0,
            disable_network=False,
            read_only_rootfs=False,
            work_dir="/workspace",
        )
        assert cfg.python_image == "python:3.12-slim"
        assert cfg.default_memory_mb == 512
        assert cfg.default_timeout == 60.0
        assert cfg.disable_network is False
        assert cfg.read_only_rootfs is False
        assert cfg.work_dir == "/workspace"

    def test_partial_config_override(self) -> None:
        """部分字段覆盖时其余字段保持默认值"""
        cfg = DockerSandboxConfig(default_memory_mb=128)
        assert cfg.default_memory_mb == 128
        assert cfg.max_memory_mb == 1024  # 保持默认
        assert cfg.default_timeout == 30.0  # 保持默认


# ══════════════════════════════════════════════════════════
# DockerSandboxExecutor 初始化测试
# ══════════════════════════════════════════════════════════


class TestDockerSandboxExecutorInit:
    """DockerSandboxExecutor 初始化测试"""

    def test_init_default_config(self) -> None:
        """使用默认配置初始化"""
        executor = DockerSandboxExecutor()
        assert executor._config is not None
        assert isinstance(executor._config, DockerSandboxConfig)
        assert executor._config.default_memory_mb == 256
        assert executor._container is None
        assert executor._container_id is None

    def test_init_custom_config(self) -> None:
        """使用自定义配置初始化"""
        cfg = DockerSandboxConfig(default_memory_mb=512, default_timeout=60.0)
        executor = DockerSandboxExecutor(cfg)
        assert executor._config is cfg
        assert executor._config.default_memory_mb == 512
        assert executor._config.default_timeout == 60.0

    def test_init_creates_new_config_when_none(self) -> None:
        """传入 None 时创建新配置"""
        executor = DockerSandboxExecutor(None)
        assert executor._config is not None
        assert isinstance(executor._config, DockerSandboxConfig)

    def test_container_id_is_none_initially(self) -> None:
        """初始状态 container_id 为 None"""
        executor = DockerSandboxExecutor()
        assert executor.container_id is None


# ══════════════════════════════════════════════════════════
# Docker 客户端测试
# ══════════════════════════════════════════════════════════


class TestDockerClient:
    """Docker 客户端获取测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_get_client_creates_and_pings(self, mock_docker: MagicMock) -> None:
        """获取客户端时创建并 ping Docker"""
        mock_client = _make_mock_docker_client()
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()
        client = executor._get_client()

        mock_docker.from_env.assert_called_once()
        mock_client.ping.assert_called_once()
        assert client is mock_client

    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", False)
    def test_get_client_raises_when_docker_not_installed(self) -> None:
        """docker-py 未安装时抛出异常"""
        executor = DockerSandboxExecutor()
        with pytest.raises(DockerNotAvailableError, match="docker-py 未安装"):
            executor._get_client()

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_get_client_raises_when_docker_daemon_down(self, mock_docker: MagicMock) -> None:
        """Docker 守护进程不可用时抛出异常"""
        mock_docker.from_env.side_effect = Exception("Connection refused")

        executor = DockerSandboxExecutor()
        with pytest.raises(DockerNotAvailableError, match="Connection refused"):
            executor._get_client()

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_get_client_caches_client(self, mock_docker: MagicMock) -> None:
        """获取客户端后缓存复用"""
        mock_client = _make_mock_docker_client()
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()
        client1 = executor._get_client()
        client2 = executor._get_client()

        assert client1 is client2
        mock_docker.from_env.assert_called_once()

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_check_docker_available_true(self, mock_docker: MagicMock) -> None:
        """Docker 可用时 check_docker_available 返回 True"""
        mock_client = _make_mock_docker_client()
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()
        assert executor._check_docker_available() is True

    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", False)
    def test_check_docker_available_false(self) -> None:
        """Docker 不可用时 check_docker_available 返回 False"""
        executor = DockerSandboxExecutor()
        assert executor._check_docker_available() is False

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_is_available_property(self, mock_docker: MagicMock) -> None:
        """is_available 属性返回 Docker 可用性"""
        mock_client = _make_mock_docker_client()
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()
        assert executor.is_available is True


# ══════════════════════════════════════════════════════════
# execute() 方法测试
# ══════════════════════════════════════════════════════════


class TestExecute:
    """execute() 方法单元测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_basic_python_code(self, mock_docker: MagicMock) -> None:
        """执行基本 Python 代码"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(exit_code=0, output="hello world\n"),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('hello world')", language="python")

        result = asyncio.run(_run())

        assert result.success is True
        assert result.exit_code == 0
        assert "hello world" in result.output
        assert result.error == ""
        assert result.duration_ms > 0

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_with_error_code(self, mock_docker: MagicMock) -> None:
        """执行返回非零退出码的代码"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(
                exit_code=1, output="NameError: name 'x' is not defined\n",
            ),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print(x)", language="python")

        result = asyncio.run(_run())

        assert result.success is False
        assert result.exit_code == 1
        assert "NameError" in result.output
        assert result.error != ""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_oom_detection(self, mock_docker: MagicMock) -> None:
        """OOM 退出码 137 被正确检测"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(exit_code=137, output=""),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("while True: pass", language="python")

        result = asyncio.run(_run())

        assert result.success is False
        assert result.exit_code == 137
        assert result.killed_by_memory is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_with_files(self, mock_docker: MagicMock) -> None:
        """执行时写入额外文件到容器"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute(
                "print('hello')",
                language="python",
                files={"data.txt": "hello data"},
            )

        result = asyncio.run(_run())
        assert result.success is True
        # put_archive 被调用了两次（代码文件 + 额外文件）
        assert mock_container.put_archive.call_count >= 2

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_with_stdin(self, mock_docker: MagicMock) -> None:
        """执行时传入 stdin"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute(
                "print(input())",
                language="python",
                stdin="hello stdin",
            )

        result = asyncio.run(_run())
        assert result.success is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_javascript(self, mock_docker: MagicMock) -> None:
        """执行 JavaScript 代码"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(exit_code=0, output="hello js\n"),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute(
                "console.log('hello js')",
                language="javascript",
            )

        result = asyncio.run(_run())
        assert result.success is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_with_custom_timeout(self, mock_docker: MagicMock) -> None:
        """使用自定义超时执行"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute(
                "print('hello')",
                language="python",
                timeout=10.0,
            )

        result = asyncio.run(_run())
        assert result.success is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_timeout_clamped_to_max(self, mock_docker: MagicMock) -> None:
        """超时被限制在最大值内"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            # 请求 9999 秒，应被限制为 max_timeout (300秒)
            return await executor.execute(
                "print('hello')",
                language="python",
                timeout=9999.0,
            )

        result = asyncio.run(_run())
        assert result.success is True


# ══════════════════════════════════════════════════════════
# 降级执行测试
# ══════════════════════════════════════════════════════════


class TestFallbackExecute:
    """Docker 不可用时的降级执行测试"""

    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", False)
    def test_fallback_when_docker_not_installed(self) -> None:
        """Docker 未安装时降级为进程沙箱"""
        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('hello fallback')", language="python")

        with patch(
            "pycoder.safety.sandbox.ProcessSandbox"
        ) as mock_process_sandbox:
            mock_instance = MagicMock()
            mock_fallback_result = SandboxResult(
                success=True,
                output="hello fallback\n",
                exit_code=0,
            )

            async def _mock_execute(*args: object, **kwargs: object) -> SandboxResult:
                return mock_fallback_result

            mock_instance.execute = _mock_execute
            mock_process_sandbox.return_value = mock_instance

            result = asyncio.run(_run())

            assert result.success is True
            assert "hello fallback" in result.output
            mock_process_sandbox.assert_called_once()

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_fallback_when_docker_daemon_down(self, mock_docker: MagicMock) -> None:
        """Docker 守护进程不可用时降级"""
        mock_docker.from_env.side_effect = Exception("Connection refused")

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('fallback')", language="python")

        with patch(
            "pycoder.safety.sandbox.ProcessSandbox"
        ) as mock_process_sandbox:
            mock_instance = MagicMock()

            async def _mock_execute(*args: object, **kwargs: object) -> SandboxResult:
                return SandboxResult(success=True, output="fallback\n", exit_code=0)

            mock_instance.execute = _mock_execute
            mock_process_sandbox.return_value = mock_instance

            result = asyncio.run(_run())
            assert result.success is True


# ══════════════════════════════════════════════════════════
# SandboxResult 验证测试
# ══════════════════════════════════════════════════════════


class TestSandboxResultValidation:
    """SandboxResult 结果对象验证"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_result_exit_code_zero_on_success(self, mock_docker: MagicMock) -> None:
        """成功执行时 exit_code 为 0"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(exit_code=0, output="ok\n"),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('ok')", language="python")

        result = asyncio.run(_run())
        assert result.exit_code == 0
        assert result.success is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_result_duration_ms_is_positive(self, mock_docker: MagicMock) -> None:
        """执行时间 duration_ms 为正数"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('test')", language="python")

        result = asyncio.run(_run())
        assert result.duration_ms > 0

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_result_error_empty_on_success(self, mock_docker: MagicMock) -> None:
        """成功执行时 error 字段为空"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('ok')", language="python")

        result = asyncio.run(_run())
        assert result.error == ""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_result_error_contains_stderr(self, mock_docker: MagicMock) -> None:
        """失败执行时 error 包含 stderr 输出"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(
                exit_code=1, output="Traceback (most recent call last):\nError\n",
            ),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("raise Exception('fail')", language="python")

        result = asyncio.run(_run())
        assert result.error != ""
        assert "Error" in result.error


# ══════════════════════════════════════════════════════════
# 错误处理测试
# ══════════════════════════════════════════════════════════


class TestErrorHandling:
    """错误处理测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_container_creation_failure(self, mock_docker: MagicMock) -> None:
        """容器创建失败时返回错误结果"""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.containers.run.side_effect = Exception("container creation failed")
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('hello')", language="python")

        with patch(
            "pycoder.safety.sandbox.ProcessSandbox"
        ) as mock_process_sandbox:
            mock_instance = MagicMock()

            async def _mock_execute(*args: object, **kwargs: object) -> SandboxResult:
                return SandboxResult(success=True, output="ok\n", exit_code=0)

            mock_instance.execute = _mock_execute
            mock_process_sandbox.return_value = mock_instance

            result = asyncio.run(_run())
            # 降级到 ProcessSandbox 执行
            assert result.success is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_exec_run_exception(self, mock_docker: MagicMock) -> None:
        """exec_run 执行异常时返回错误结果"""
        mock_container = _make_mock_container()
        mock_container.exec_run.side_effect = Exception("exec failed")
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("print('hello')", language="python")

        result = asyncio.run(_run())
        assert result.success is False
        assert result.exit_code == -1
        assert "exec failed" in result.error

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_execute_with_empty_code(self, mock_docker: MagicMock) -> None:
        """执行空代码"""
        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(exit_code=0, output=""),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> SandboxResult:
            return await executor.execute("", language="python")

        result = asyncio.run(_run())
        assert result.success is True
        assert result.exit_code == 0


# ══════════════════════════════════════════════════════════
# 资源限制配置测试
# ══════════════════════════════════════════════════════════


class TestResourceLimits:
    """资源限制配置测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_default_memory_limit(self, mock_docker: MagicMock) -> None:
        """默认内存限制配置"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        # 验证容器创建时传入了正确的内存限制
        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["mem_limit"] == "256m"

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_custom_memory_limit(self, mock_docker: MagicMock) -> None:
        """自定义内存限制配置"""
        cfg = DockerSandboxConfig(default_memory_mb=512)
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor(cfg)

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["mem_limit"] == "512m"

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_cpu_shares_config(self, mock_docker: MagicMock) -> None:
        """CPU 份额配置"""
        cfg = DockerSandboxConfig(default_cpu_shares=1024)
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor(cfg)

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["cpu_shares"] == 1024

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_read_only_rootfs_config(self, mock_docker: MagicMock) -> None:
        """根文件系统只读配置"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["read_only"] is True


# ══════════════════════════════════════════════════════════
# 网络隔离测试
# ══════════════════════════════════════════════════════════


class TestNetworkIsolation:
    """网络隔离设置测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_network_disabled_by_default(self, mock_docker: MagicMock) -> None:
        """默认禁用网络"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs.get("network_disabled") is True

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_network_enabled_config(self, mock_docker: MagicMock) -> None:
        """配置允许网络时 network_disabled 不应出现"""
        cfg = DockerSandboxConfig(disable_network=False)
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor(cfg)

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert "network_disabled" not in call_kwargs or call_kwargs.get("network_disabled") is False


# ══════════════════════════════════════════════════════════
# tmpfs 挂载测试
# ══════════════════════════════════════════════════════════


class TestTmpfsMounts:
    """临时文件系统挂载测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_tmpfs_mounts_configured(self, mock_docker: MagicMock) -> None:
        """tmpfs 挂载配置正确"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        tmpfs = call_kwargs.get("tmpfs")
        assert tmpfs is not None
        assert "/sandbox" in tmpfs
        assert "/tmp" in tmpfs
        assert "noexec" in tmpfs["/tmp"]

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_tmpfs_work_dir_config(self, mock_docker: MagicMock) -> None:
        """自定义工作目录时 tmpfs 也相应调整"""
        cfg = DockerSandboxConfig(work_dir="/workspace")
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor(cfg)

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        tmpfs = call_kwargs.get("tmpfs")
        assert "/workspace" in tmpfs


# ══════════════════════════════════════════════════════════
# 安全选项测试
# ══════════════════════════════════════════════════════════


class TestSecurityOptions:
    """安全选项测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_security_opt_no_new_privileges(self, mock_docker: MagicMock) -> None:
        """安全选项 no-new-privileges 已配置"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert "no-new-privileges:true" in call_kwargs["security_opt"]

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_cap_drop_all(self, mock_docker: MagicMock) -> None:
        """所有 Linux capabilities 已移除"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()

        asyncio.run(_run())

        call_kwargs = mock_client.containers.run.call_args[1]
        assert call_kwargs["cap_drop"] == ["ALL"]


# ══════════════════════════════════════════════════════════
# 容器清理测试
# ══════════════════════════════════════════════════════════


class TestContainerCleanup:
    """容器清理测试"""

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_cleanup_stops_container(self, mock_docker: MagicMock) -> None:
        """清理时停止容器"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()
            await executor.cleanup()

        asyncio.run(_run())
        mock_container.stop.assert_called_once()

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_cleanup_clears_container_ref(self, mock_docker: MagicMock) -> None:
        """清理后容器引用置空"""
        mock_container = _make_mock_container()
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()
            await executor.cleanup()

        asyncio.run(_run())
        assert executor._container is None
        assert executor._container_id is None

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_cleanup_handles_stop_error(self, mock_docker: MagicMock) -> None:
        """清理时 stop 异常不影响容器引用置空"""
        mock_container = _make_mock_container()
        mock_container.stop.side_effect = Exception("stop failed")
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor._ensure_container()
            await executor.cleanup()

        asyncio.run(_run())
        assert executor._container is None
        assert executor._container_id is None

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_cleanup_noop_when_no_container(self, mock_docker: MagicMock) -> None:
        """无容器时清理为空操作"""
        executor = DockerSandboxExecutor()

        async def _run() -> None:
            await executor.cleanup()

        asyncio.run(_run())
        # 不应抛出异常
        assert executor._container is None


# ══════════════════════════════════════════════════════════
# 语言映射测试
# ══════════════════════════════════════════════════════════


class TestLanguageMapping:
    """语言映射表测试"""

    def test_python_language_image(self) -> None:
        """Python 语言映射到正确镜像"""
        assert _LANGUAGE_IMAGE_MAP["python"] == "python:3.11-slim"
        assert _LANGUAGE_IMAGE_MAP["python3"] == "python:3.11-slim"

    def test_javascript_language_image(self) -> None:
        """JavaScript 语言映射到正确镜像"""
        assert _LANGUAGE_IMAGE_MAP["javascript"] == "node:20-slim"
        assert _LANGUAGE_IMAGE_MAP["js"] == "node:20-slim"
        assert _LANGUAGE_IMAGE_MAP["node"] == "node:20-slim"

    def test_typescript_language_image(self) -> None:
        """TypeScript 语言映射到正确镜像"""
        assert _LANGUAGE_IMAGE_MAP["typescript"] == "node:20-slim"
        assert _LANGUAGE_IMAGE_MAP["ts"] == "node:20-slim"

    def test_bash_language_image(self) -> None:
        """Bash 语言映射到正确镜像"""
        assert _LANGUAGE_IMAGE_MAP["bash"] == "ubuntu:22.04"
        assert _LANGUAGE_IMAGE_MAP["shell"] == "ubuntu:22.04"

    def test_python_command(self) -> None:
        """Python 命令映射"""
        assert _LANGUAGE_COMMAND_MAP["python"] == "python3"

    def test_javascript_command(self) -> None:
        """JavaScript 命令映射"""
        assert _LANGUAGE_COMMAND_MAP["javascript"] == "node"

    def test_python_extension(self) -> None:
        """Python 文件扩展名"""
        assert _LANGUAGE_EXT_MAP["python"] == "py"

    def test_javascript_extension(self) -> None:
        """JavaScript 文件扩展名"""
        assert _LANGUAGE_EXT_MAP["javascript"] == "js"

    def test_get_image_for_language_known(self) -> None:
        """已知语言返回正确镜像"""
        executor = DockerSandboxExecutor()
        assert executor._get_image_for_language("python") == "python:3.11-slim"
        assert executor._get_image_for_language("javascript") == "node:20-slim"

    def test_get_image_for_language_unknown(self) -> None:
        """未知语言返回默认镜像"""
        executor = DockerSandboxExecutor()
        assert executor._get_image_for_language("rust") == "ubuntu:22.04"

    def test_get_command_for_language(self) -> None:
        """命令构建测试"""
        executor = DockerSandboxExecutor()
        cmd = executor._get_command_for_language("python", "/sandbox/code.py")
        assert "python3" in cmd
        assert "/sandbox/code.py" in cmd


# ══════════════════════════════════════════════════════════
# tar 工具函数测试
# ══════════════════════════════════════════════════════════


class TestTarPayload:
    """tar 打包工具函数测试"""

    def test_make_tar_payload_valid(self) -> None:
        """生成有效的 tar 包"""
        payload = _make_tar_payload("test.py", b"print('hello')")
        assert isinstance(payload, bytes)
        assert len(payload) > 0

    def test_make_tar_payload_empty_content(self) -> None:
        """空内容 tar 包"""
        payload = _make_tar_payload("empty.txt", b"")
        assert isinstance(payload, bytes)
        assert len(payload) > 0  # tar 头至少有一些字节

    def test_make_tar_payload_binary_content(self) -> None:
        """二进制内容 tar 包"""
        payload = _make_tar_payload("data.bin", bytes(range(256)))
        assert isinstance(payload, bytes)
        assert len(payload) > 256


# ══════════════════════════════════════════════════════════
# 超时处理测试
# ══════════════════════════════════════════════════════════


class TestTimeoutHandling:
    """超时处理测试"""

    def test_sandbox_timeout_error(self) -> None:
        """SandboxTimeoutError 异常属性"""
        err = SandboxTimeoutError(30.0, output="partial output")
        assert err.timeout == 30.0
        assert err.output == "partial output"
        assert "30.0" in str(err)

    @patch("pycoder.safety.sandbox_executor.docker")
    @patch("pycoder.safety.sandbox_executor._HAS_DOCKER", True)
    def test_timeout_result_fields(self, mock_docker: MagicMock) -> None:
        """超时结果包含正确字段"""
        import time as time_module

        mock_container = _make_mock_container(
            exec_result=_make_mock_exec_result(exit_code=0, output="ok\n"),
        )
        mock_client = _make_mock_docker_client(mock_container)
        mock_docker.from_env.return_value = mock_client

        cfg = DockerSandboxConfig(default_timeout=0.001)
        executor = DockerSandboxExecutor(cfg)

        # 模拟时间单调递增：start_time 小，elapsed 检查时大
        _t = [0.0]

        def _fake_monotonic() -> float:
            _t[0] += 100.0
            return _t[0]

        with patch.object(time_module, "monotonic", _fake_monotonic):
            async def _run() -> SandboxResult:
                return await executor.execute(
                    "print('hello')",
                    language="python",
                    timeout=0.001,
                )

            result = asyncio.run(_run())

        assert result.success is False
        assert result.killed_by_timeout is True
        assert result.exit_code == -1


# ══════════════════════════════════════════════════════════
# DockerNotAvailableError 测试
# ══════════════════════════════════════════════════════════


class TestDockerNotAvailableError:
    """DockerNotAvailableError 异常测试"""

    def test_default_message(self) -> None:
        """默认错误消息"""
        err = DockerNotAvailableError()
        assert "Docker 不可用" in str(err)
        assert err.reason == "Docker 未安装或 Docker 服务未运行"

    def test_custom_message(self) -> None:
        """自定义错误消息"""
        err = DockerNotAvailableError("自定义错误")
        assert "自定义错误" in str(err)
        assert err.reason == "自定义错误"
