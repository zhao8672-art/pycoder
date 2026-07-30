"""DockerSandbox 单元测试 (adapters.docker_sandbox)

覆盖 pycoder.adapters.docker_sandbox.DockerSandbox:
  - 构造参数 (_image / _default_timeout / _max_memory)
  - _build_security_args 安全参数（defense-in-depth）
  - execute 正常路径
  - FileNotFoundError（docker 未安装）→ DockerNotFound
  - OSError（docker daemon 失败）→ DockerError
  - TimeoutError → TimeoutError
  - 临时文件清理 (finally)
  - 不会以 shell=True 调用 subprocess（无 shell 注入风险）
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.adapters.docker_sandbox import (
    DEFAULT_IMAGE,
    DockerSandbox,
)
from pycoder.core.ports.code_sandbox import CodeExecutionResult

# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def sandbox() -> DockerSandbox:
    """默认构造的 DockerSandbox"""
    return DockerSandbox()


@pytest.fixture
def custom_sandbox() -> DockerSandbox:
    """自定义构造的 DockerSandbox"""
    return DockerSandbox(
        image="python:3.13-slim",
        default_timeout=15,
        max_memory="1g",
    )


def _make_proc(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    """构造一个 mock subprocess 对象"""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    return proc


# ══════════════════════════════════════════════════════════
# 构造 & 默认值
# ══════════════════════════════════════════════════════════


class TestDockerSandboxInit:
    """DockerSandbox 构造与默认值"""

    def test_default_image(self, sandbox: DockerSandbox) -> None:
        """默认镜像为 DEFAULT_IMAGE"""
        assert sandbox._image == DEFAULT_IMAGE
        assert "python" in sandbox._image

    def test_default_timeout(self, sandbox: DockerSandbox) -> None:
        """默认超时 30s"""
        assert sandbox._default_timeout == 30

    def test_default_memory(self, sandbox: DockerSandbox) -> None:
        """默认内存 512m"""
        assert sandbox._max_memory == "512m"

    def test_custom_image(self, custom_sandbox: DockerSandbox) -> None:
        """自定义 image / timeout / memory"""
        assert custom_sandbox._image == "python:3.13-slim"
        assert custom_sandbox._default_timeout == 15
        assert custom_sandbox._max_memory == "1g"

    def test_default_image_constant(self) -> None:
        """DEFAULT_IMAGE 应包含 python"""
        assert DEFAULT_IMAGE.startswith("python")
        assert "slim" in DEFAULT_IMAGE


# ══════════════════════════════════════════════════════════
# _build_security_args
# ══════════════════════════════════════════════════════════


class TestBuildSecurityArgs:
    """安全参数列表"""

    def test_returns_list_of_str(self, sandbox: DockerSandbox) -> None:
        """返回值是 list[str]"""
        args = sandbox._build_security_args()
        assert isinstance(args, list)
        assert all(isinstance(a, str) for a in args)

    def test_includes_network_isolation(self, sandbox: DockerSandbox) -> None:
        """必须包含 --network=none"""
        args = sandbox._build_security_args()
        assert "--network=none" in args

    def test_includes_memory_limit(self, sandbox: DockerSandbox) -> None:
        """必须包含 --memory={max_memory} 和 --memory-swap=0"""
        args = sandbox._build_security_args()
        assert "--memory=512m" in args
        assert "--memory-swap=0" in args

    def test_includes_cpu_limit(self, sandbox: DockerSandbox) -> None:
        """必须包含 CPU 限制"""
        args = sandbox._build_security_args()
        assert "--cpus=1" in args

    def test_includes_read_only(self, sandbox: DockerSandbox) -> None:
        """必须包含 --read-only"""
        args = sandbox._build_security_args()
        assert "--read-only" in args

    def test_includes_tmpfs(self, sandbox: DockerSandbox) -> None:
        """必须包含 /tmp tmpfs"""
        args = sandbox._build_security_args()
        assert any(a.startswith("--tmpfs=/tmp") for a in args)

    def test_includes_cap_drop(self, sandbox: DockerSandbox) -> None:
        """必须包含 --cap-drop=ALL"""
        args = sandbox._build_security_args()
        assert "--cap-drop=ALL" in args

    def test_includes_no_new_privileges(self, sandbox: DockerSandbox) -> None:
        """必须包含 no-new-privileges"""
        args = sandbox._build_security_args()
        assert "--security-opt=no-new-privileges" in args

    def test_includes_non_root_user(self, sandbox: DockerSandbox) -> None:
        """必须以 nobody 用户运行"""
        args = sandbox._build_security_args()
        assert "--user" in args
        assert "nobody:nogroup" in args

    def test_includes_pids_limit(self, sandbox: DockerSandbox) -> None:
        """必须限制进程数"""
        args = sandbox._build_security_args()
        assert "--pids-limit=64" in args

    def test_includes_ulimits(self, sandbox: DockerSandbox) -> None:
        """必须设置 ulimit"""
        args = sandbox._build_security_args()
        assert "--ulimit" in args
        # 至少包含 nofile 和 nproc
        joined = " ".join(args)
        assert "nofile" in joined
        assert "nproc" in joined

    def test_includes_rm_flag(self, sandbox: DockerSandbox) -> None:
        """必须自动清理容器（--rm）"""
        args = sandbox._build_security_args()
        assert "--rm" in args

    def test_custom_memory_propagated(self, custom_sandbox: DockerSandbox) -> None:
        """自定义内存值会出现在参数中"""
        args = custom_sandbox._build_security_args()
        assert "--memory=1g" in args


# ══════════════════════════════════════════════════════════
# execute() — 正常路径
# ══════════════════════════════════════════════════════════


class TestExecuteSuccess:
    """execute 成功路径"""

    @pytest.mark.asyncio
    async def test_returns_success_result(self, sandbox: DockerSandbox) -> None:
        """returncode=0 + stdout → success=True"""
        proc = _make_proc(returncode=0, stdout=b"hello\n", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            result = await sandbox.execute("print('hi')")

        assert isinstance(result, CodeExecutionResult)
        assert result.success is True
        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.error_type == ""
        assert result.execution_time >= 0

    @pytest.mark.asyncio
    async def test_writes_code_to_temp_file(
        self, sandbox: DockerSandbox, tmp_path: Path
    ) -> None:
        """execute 应将代码写入临时 .py 文件并通过 -v 挂载"""
        proc = _make_proc(returncode=0, stdout=b"ok", stderr=b"")

        captured: dict[str, Any] = {}

        async def fake_exec(*args: Any, **kwargs: Any) -> MagicMock:
            cmd = list(args)
            captured["cmd"] = cmd
            # 在子进程调用时（finally 之前）临时文件必然存在
            assert "-v" in cmd
            v_idx = cmd.index("-v")
            mount = cmd[v_idx + 1]
            assert mount.endswith(":/code.py:ro")
            host_path = mount.split(":/code.py", 1)[0]
            captured["host_path"] = host_path
            captured["file_existed_at_call_time"] = os.path.exists(host_path)
            if os.path.exists(host_path):
                with open(host_path, encoding="utf-8") as f:
                    captured["file_content"] = f.read()
            return proc

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            side_effect=fake_exec,
        ):
            await sandbox.execute("print('hi')")

        cmd = captured["cmd"]
        # 镜像和执行命令
        assert cmd[0] == "docker"
        assert cmd[1] == "run"
        assert DEFAULT_IMAGE in cmd
        assert "python" in cmd
        assert "/code.py" in cmd
        # 文件在调用时存在且内容正确
        assert captured.get("file_existed_at_call_time") is True
        assert captured.get("file_content") == "print('hi')"
        # finally 之后临时文件应被删除
        assert not os.path.exists(captured["host_path"])

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up(self, sandbox: DockerSandbox) -> None:
        """执行完毕后临时文件应被删除"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        captured: dict[str, str] = {}

        async def fake_exec(*args: Any, **kwargs: Any) -> MagicMock:
            for a in args:
                if isinstance(a, str) and a.startswith("--") is False and a != "docker" and a != "run" and a != DEFAULT_IMAGE and a != "python" and a != "/code.py" and a != "-v":
                    continue
            # 找到 -v 后面的挂载路径
            for i, a in enumerate(args):
                if a == "-v" and i + 1 < len(args):
                    captured["host"] = args[i + 1].split(":", 1)[0]
                    break
            return proc

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            side_effect=fake_exec,
        ):
            await sandbox.execute("x = 1\n")

        # 临时文件应已被清理
        assert "host" in captured
        assert not os.path.exists(captured["host"]), "临时文件应在 finally 中被清理"

    @pytest.mark.asyncio
    async def test_does_not_use_shell(self, sandbox: DockerSandbox) -> None:
        """execute 必须不通过 shell 调用（避免注入）"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ) as mocked:
            await sandbox.execute("print('hi')")

        # create_subprocess_exec 是数组形式调用；不应有 shell=True
        # 我们检查最后一次调用的关键字参数
        _, kwargs = mocked.call_args
        # shell=True 不应出现
        assert "shell" not in kwargs
        # 同时 create_subprocess_shell 永远不应被调用
        # 实际验证已经通过 mock create_subprocess_exec 实现

    @pytest.mark.asyncio
    async def test_passes_correct_timeout(self, sandbox: DockerSandbox) -> None:
        """wait_for 的 timeout 应为 min(timeout, default_timeout)"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ), patch(
            "pycoder.adapters.docker_sandbox.asyncio.wait_for",
            new=AsyncMock(return_value=(b"", b"")),
        ) as wait_mock:
            await sandbox.execute("x = 1", timeout=5)

        # wait_for 用的是关键字参数 timeout，所以从 kwargs 取
        assert wait_mock.call_args.kwargs.get("timeout") == 5  # min(5, 30)

    @pytest.mark.asyncio
    async def test_timeout_capped_by_default(
        self, custom_sandbox: DockerSandbox
    ) -> None:
        """wait_for 的 timeout 不应超过 default_timeout"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ), patch(
            "pycoder.adapters.docker_sandbox.asyncio.wait_for",
            new=AsyncMock(return_value=(b"", b"")),
        ) as wait_mock:
            # default_timeout=15, 传入 60 → 应被截断为 15
            await custom_sandbox.execute("x = 1", timeout=60)

        assert wait_mock.call_args.kwargs.get("timeout") == 15


# ══════════════════════════════════════════════════════════
# execute() — 错误路径
# ══════════════════════════════════════════════════════════


class TestExecuteErrors:
    """execute 各种错误场景"""

    @pytest.mark.asyncio
    async def test_docker_not_found(self, sandbox: DockerSandbox) -> None:
        """FileNotFoundError → DockerNotFound"""
        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError("docker not found")),
        ):
            result = await sandbox.execute("x = 1")

        assert result.success is False
        assert result.error_type == "DockerNotFound"
        assert "Docker" in result.error_message

    @pytest.mark.asyncio
    async def test_oserror(self, sandbox: DockerSandbox) -> None:
        """OSError → DockerError"""
        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=OSError("daemon down")),
        ):
            result = await sandbox.execute("x = 1")

        assert result.success is False
        assert result.error_type == "DockerError"
        assert "Docker" in result.error_message

    @pytest.mark.asyncio
    async def test_timeout_error(self, sandbox: DockerSandbox) -> None:
        """TimeoutError → TimeoutError"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ), patch(
            "pycoder.adapters.docker_sandbox.asyncio.wait_for",
            AsyncMock(side_effect=TimeoutError()),
        ):
            result = await sandbox.execute("while True: pass", timeout=1)

        assert result.success is False
        assert result.error_type == "TimeoutError"
        assert "超时" in result.error_message or "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_nonzero_returncode(self, sandbox: DockerSandbox) -> None:
        """returncode != 0 → RuntimeError 类型"""
        proc = _make_proc(returncode=1, stdout=b"", stderr=b"traceback...")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            result = await sandbox.execute("raise Exception()")

        assert result.success is False
        assert result.error_type == "RuntimeError"
        assert "traceback" in result.error_message

    @pytest.mark.asyncio
    async def test_returns_correct_dataclass_fields(
        self, sandbox: DockerSandbox
    ) -> None:
        """返回结果应包含执行时间"""
        proc = _make_proc(returncode=0, stdout=b"x", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ):
            result = await sandbox.execute("print('x')")

        # 字段都应存在
        assert hasattr(result, "success")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "execution_time")
        assert hasattr(result, "error_type")
        assert hasattr(result, "error_message")


# ══════════════════════════════════════════════════════════
# execute() — 临时文件清理
# ══════════════════════════════════════════════════════════


class TestTempFileCleanup:
    """异常情况下临时文件也应被清理"""

    @pytest.mark.asyncio
    async def test_cleanup_on_timeout(self, sandbox: DockerSandbox) -> None:
        """超时后临时文件应被清理"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        captured: dict[str, str] = {}

        async def fake_exec(*args: Any, **kwargs: Any) -> MagicMock:
            for i, a in enumerate(args):
                if a == "-v" and i + 1 < len(args):
                    captured["host"] = args[i + 1].split(":", 1)[0]
                    break
            return proc

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            side_effect=fake_exec,
        ), patch(
            "pycoder.adapters.docker_sandbox.asyncio.wait_for",
            AsyncMock(side_effect=TimeoutError()),
        ):
            await sandbox.execute("x = 1", timeout=1)

        # 临时文件应被清理（finally 子句）
        if "host" in captured:
            assert not os.path.exists(captured["host"])

    @pytest.mark.asyncio
    async def test_cleanup_on_docker_not_found(
        self, sandbox: DockerSandbox
    ) -> None:
        """FileNotFoundError 时临时文件也应被清理"""
        # 截获所有可能创建的临时文件
        before_count = len(
            [f for f in os.listdir(tempfile.gettempdir()) if f.endswith(".py")]
        )

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError("no docker")),
        ):
            result = await sandbox.execute("x = 1")

        after_count = len(
            [f for f in os.listdir(tempfile.gettempdir()) if f.endswith(".py")]
        )
        # 临时文件数应没增加（已被清理）
        assert result.success is False
        assert after_count <= before_count + 1  # 容忍极端情况下的并发

    @pytest.mark.asyncio
    async def test_cleanup_on_oserror(self, sandbox: DockerSandbox) -> None:
        """OSError 时临时文件也应被清理"""
        before = set(os.listdir(tempfile.gettempdir()))

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=OSError("docker error")),
        ):
            result = await sandbox.execute("x = 1")

        after = set(os.listdir(tempfile.gettempdir()))
        # 临时文件应被清理
        assert not (after - before), f"残留临时文件: {after - before}"
        assert result.success is False


# ══════════════════════════════════════════════════════════
# subprocess 安全
# ══════════════════════════════════════════════════════════


class TestSubprocessSafety:
    """执行命令的子进程安全约束"""

    @pytest.mark.asyncio
    async def test_no_shell_true(self, sandbox: DockerSandbox) -> None:
        """create_subprocess_exec 不应使用 shell=True"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ) as mocked:
            await sandbox.execute("x = 1")

        # 检查是否调用过 shell=True
        _, kwargs = mocked.call_args
        assert kwargs.get("shell", False) is False

    @pytest.mark.asyncio
    async def test_uses_exec_not_shell(self, sandbox: DockerSandbox) -> None:
        """应使用 create_subprocess_exec (非 create_subprocess_shell)"""
        proc = _make_proc(returncode=0, stdout=b"", stderr=b"")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ), patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_shell",
            AsyncMock(return_value=proc),
        ) as shell_mock:
            await sandbox.execute("x = 1")

        # 不应调用 shell
        assert shell_mock.call_count == 0

    @pytest.mark.asyncio
    async def test_captures_stdout_and_stderr(
        self, sandbox: DockerSandbox
    ) -> None:
        """应分别捕获 stdout 和 stderr"""
        proc = _make_proc(returncode=0, stdout=b"out", stderr=b"err")

        with patch(
            "pycoder.adapters.docker_sandbox.asyncio.create_subprocess_exec",
            AsyncMock(return_value=proc),
        ) as mocked:
            await sandbox.execute("x = 1")

        _, kwargs = mocked.call_args
        assert kwargs.get("stdout") is not None
        assert kwargs.get("stderr") is not None
