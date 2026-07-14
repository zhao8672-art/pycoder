"""P4: Docker 容器化代码执行沙箱

提供比子进程更强的隔离：
  - 文件系统隔离（容器内独立 FS）
  - 资源限制（CPU/内存/进程数）
  - 网络隔离（默认禁网）
  - 只读根文件系统 + 临时 tmpfs

使用方式:
    from pycoder.server.services.docker_sandbox import DockerSandbox
    sandbox = DockerSandbox()
    if sandbox.is_available():
        result = sandbox.execute(code, timeout=30)
    else:
        # 降级到子进程
        from pycoder.server.routers.code_exec import _run_in_subprocess
        result = _run_in_subprocess(code, timeout)

设计原则:
  - 可选升级：Docker 不可用时自动降级到子进程
  - 失败安全：容器启动失败/超时返回明确错误，不阻塞调用方
  - 资源限制：默认 256MB 内存、0.5 CPU、无网络
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 执行结果（与 ExecutionResult 兼容）
# ══════════════════════════════════════════════════════════


@dataclass
class SandboxResult:
    """沙箱执行结果"""

    success: bool = False
    stdout: str = ""
    stderr: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    execution_time: float = 0.0
    backend: str = "unknown"  # docker | subprocess


# ══════════════════════════════════════════════════════════
# Docker 沙箱
# ══════════════════════════════════════════════════════════

# 默认镜像（轻量 Python 镜像）
DEFAULT_IMAGE = "python:3.12-slim"

# 资源限制默认值
DEFAULT_MEMORY_LIMIT = "256m"
DEFAULT_CPU_QUOTA = 50000  # 0.5 CPU（CFS quota，单位微秒）
DEFAULT_PIDS_LIMIT = 64

# 沙箱内执行的 Python 脚本（与子进程沙箱兼容）
_SANDBOX_RUNNER = """
import sys, json, traceback, io, signal, resource

def handler(signum, frame):
    raise TimeoutError("sandbox_timeout")

signal.signal(signal.SIGALRM, handler)
signal.alarm({timeout})

old_stdout, old_stderr = sys.stdout, sys.stderr
sys.stdout = sys.stderr = io.StringIO()
result = {{}}
try:
    code = sys.stdin.read()
    exec(compile(code, "<sandbox>", "exec"), {{"__name__": "__main__"}}, result)
    result["success"] = True
except Exception as e:
    result["success"] = False
    result["error_type"] = type(e).__name__
    result["error_message"] = str(e)
    result["traceback"] = traceback.format_exc()
finally:
    signal.alarm(0)
    out = sys.stdout.getvalue()
    err = sys.stderr.getvalue()
    sys.stdout, sys.stderr = old_stdout, old_stderr
    result["stdout"] = out[:50000]
    result["stderr"] = err[:5000]
    print("__SANDBOX_RESULT__" + json.dumps(result) + "__SANDBOX_END__")
""".strip()


class DockerSandbox:
    """Docker 容器化代码执行沙箱

    资源限制:
      - 内存: 256MB（可配置）
      - CPU: 0.5 核（可配置）
      - 进程数: 64（防止 fork 炸弹）
      - 网络: 默认禁用
      - 文件系统: 只读根 + tmpfs /tmp
    """

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        cpu_quota: int = DEFAULT_CPU_QUOTA,
        pids_limit: int = DEFAULT_PIDS_LIMIT,
        network_enabled: bool = False,
    ):
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.pids_limit = pids_limit
        self.network_enabled = network_enabled
        self._available: bool | None = None

    def is_available(self) -> bool:
        """检查 Docker 是否可用（缓存结果）"""
        if self._available is not None:
            return self._available
        try:
            import subprocess

            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                timeout=5,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            self._available = result.returncode == 0
            if self._available:
                logger.info("docker_sandbox_available version=%s", result.stdout.decode().strip())
            else:
                logger.info("docker_sandbox_unavailable docker_not_running")
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
            logger.info("docker_sandbox_unavailable error=%s", e)
            self._available = False
        return self._available

    def execute(self, code: str, timeout: int = 30) -> SandboxResult:
        """在 Docker 容器中执行代码

        Args:
            code: Python 代码字符串
            timeout: 超时秒数

        Returns:
            SandboxResult — 执行结果
        """
        if not self.is_available():
            return SandboxResult(
                success=False,
                error_type="DockerUnavailable",
                error_message="Docker 不可用，请降级到子进程执行",
                backend="docker",
            )

        import subprocess

        # 准备沙箱脚本
        runner_script = _SANDBOX_RUNNER.format(timeout=timeout)

        # 构造 docker run 命令
        cmd = [
            "docker",
            "run",
            "--rm",
            # 资源限制
            "--memory",
            self.memory_limit,
            "--cpu-quota",
            str(self.cpu_quota),
            "--pids-limit",
            str(self.pids_limit),
            # 文件系统隔离
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=64m",
            # 网络隔离
            "--network",
            "none" if not self.network_enabled else "bridge",
            # 超时
            "--stop-timeout",
            str(timeout),
            # 镜像
            self.image,
            # 执行命令：从 stdin 读取代码
            "python",
            "-c",
            runner_script,
        ]

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                input=code.encode("utf-8"),
                capture_output=True,
                timeout=timeout + 10,  # 额外 10s 给容器启动
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                error_type="TimeoutError",
                error_message=f"Docker 执行超过 {timeout} 秒",
                execution_time=time.time() - start,
                backend="docker",
            )
        except (OSError, subprocess.SubprocessError) as e:
            return SandboxResult(
                success=False,
                error_type=type(e).__name__,
                error_message=f"Docker 执行失败: {e}",
                execution_time=time.time() - start,
                backend="docker",
            )

        elapsed = time.time() - start
        stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""

        # 从 stdout 提取 SANDBOX_RESULT（与子进程沙箱兼容）
        marker_start = "__SANDBOX_RESULT__"
        marker_end = "__SANDBOX_END__"
        idx_start = stdout.find(marker_start)
        idx_end = stdout.find(marker_end)

        if idx_start >= 0 and idx_end > idx_start:
            json_str = stdout[idx_start + len(marker_start) : idx_end].strip()
            try:
                data = json.loads(json_str)
                return SandboxResult(
                    success=data.get("success", False),
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    error_type=data.get("error_type", ""),
                    error_message=data.get("error_message", ""),
                    traceback=data.get("traceback", ""),
                    execution_time=data.get("execution_time", elapsed),
                    backend="docker",
                )
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning("docker_result_parse_failed error=%s", e)

        # fallback: 返回原始输出
        return SandboxResult(
            success=proc.returncode == 0,
            stdout=stdout[:50000],
            stderr=stderr[:5000],
            error_type="DockerError" if proc.returncode != 0 else "",
            error_message=f"Exit code: {proc.returncode}" if proc.returncode != 0 else "",
            execution_time=elapsed,
            backend="docker",
        )


# ══════════════════════════════════════════════════════════
# 统一执行接口（自动降级）
# ══════════════════════════════════════════════════════════


def execute_code_safely(
    code: str,
    timeout: int = 30,
    *,
    prefer_docker: bool = True,
) -> SandboxResult:
    """统一代码执行接口 — 优先 Docker，不可用时降级子进程

    Args:
        code: Python 代码
        timeout: 超时秒数
        prefer_docker: 是否优先使用 Docker（False 强制子进程）

    Returns:
        SandboxResult — 统一结果格式
    """
    if prefer_docker:
        sandbox = DockerSandbox()
        if sandbox.is_available():
            logger.debug("code_exec_backend=docker")
            return sandbox.execute(code, timeout)

    # 降级到子进程
    logger.debug("code_exec_backend=subprocess")
    try:
        from pycoder.server.routers.code_exec import _run_in_subprocess

        result = _run_in_subprocess(code, timeout)
        # 转换为 SandboxResult
        return SandboxResult(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            error_type=result.error_type,
            error_message=result.error_message,
            traceback=result.traceback,
            execution_time=result.execution_time,
            backend="subprocess",
        )
    except (ImportError, RuntimeError, OSError, ValueError) as e:
        return SandboxResult(
            success=False,
            error_type="SubprocessError",
            error_message=f"子进程执行失败: {e}",
            backend="subprocess",
        )


# 模块级单例
_docker_sandbox: DockerSandbox | None = None


def get_docker_sandbox() -> DockerSandbox:
    """获取全局 DockerSandbox 单例"""
    global _docker_sandbox
    if _docker_sandbox is None:
        _docker_sandbox = DockerSandbox()
    return _docker_sandbox


__all__ = [
    "SandboxResult",
    "DockerSandbox",
    "execute_code_safely",
    "get_docker_sandbox",
]
