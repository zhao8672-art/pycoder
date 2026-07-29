"""P2: DockerSandbox — 容器化代码执行（安全默认实现）

通过 Docker 容器提供完全隔离的代码执行环境:
    - 网络隔离 (--network=none)
    - 内存限制 (--memory=512m, --memory-swap=0 禁止swap)
    - CPU 限制 (--cpus=1)
    - 只读文件系统 (--read-only)
    - 临时写空间 (--tmpfs /tmp)
    - 最小权限 (--cap-drop=ALL, --security-opt=no-new-privileges)
    - 非 root 用户 (--user nobody:nogroup)
    - 进程数限制 (--pids-limit)
    - 文件描述符限制 (--ulimit)

用法:
    sandbox = DockerSandbox()
    result = await sandbox.execute("print('hello')")
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from pycoder.core.ports.code_sandbox import CodeExecutionResult

logger = logging.getLogger(__name__)

# Docker 镜像
DEFAULT_IMAGE = "python:3.12-slim"


class DockerSandbox:
    """Docker 容器沙箱 — 完全隔离的代码执行

    安全特性 (defense-in-depth):
        - 无网络访问 (network=none)
        - 512MB 内存限制, 禁止 swap
        - 1 CPU 限制
        - 只读根文件系统
        - /tmp 临时可写 (100MB, mode=1777)
        - 30s 默认超时
        - --cap-drop=ALL 移除所有 Linux capabilities
        - --security-opt=no-new-privileges 禁止提权
        - --user nobody:nogroup 非 root 运行
        - --pids-limit=64 限制进程数
        - --ulimit nofile=64 文件描述符限制
    """

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        default_timeout: int = 30,
        max_memory: str = "512m",
    ) -> None:
        self._image = image
        self._default_timeout = default_timeout
        self._max_memory = max_memory

    def _build_security_args(self) -> list[str]:
        """构建 Docker 安全参数（defense-in-depth）"""
        return [
            "--rm",
            # 网络隔离
            "--network=none",
            # 资源限制
            f"--memory={self._max_memory}",
            "--memory-swap=0",  # 禁止 swap
            "--cpus=1",
            # 文件系统
            "--read-only",
            "--tmpfs=/tmp:size=100m,mode=1777",
            # 最小权限（defense-in-depth）
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            # 非 root 用户
            "--user",
            "nobody:nogroup",
            # 进程/资源限制
            "--pids-limit=64",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "nproc=32:32",
        ]

    async def execute(self, code: str, timeout: int = 30) -> CodeExecutionResult:
        """在 Docker 容器中执行代码"""
        import time as _time

        start_time = _time.time()

        # 写入临时文件
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8"
            ) as f:
                f.write(code)
                tmp_path = f.name

            # 构建完整命令（安全参数 + 代码挂载 + 镜像 + 执行命令）
            docker_args = [
                "docker",
                "run",
                *self._build_security_args(),
                "-v",
                f"{tmp_path}:/code.py:ro",
                self._image,
                "python",
                "/code.py",
            ]

            proc = await asyncio.create_subprocess_exec(
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=min(timeout, self._default_timeout)
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            execution_time = _time.time() - start_time

            return CodeExecutionResult(
                success=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                execution_time=round(execution_time, 3),
                error_type="RuntimeError" if proc.returncode != 0 else "",
                error_message=stderr[:500] if proc.returncode != 0 else "",
            )

        except TimeoutError:
            return CodeExecutionResult(
                success=False,
                error_type="TimeoutError",
                error_message=f"代码执行超时 ({timeout}s)",
                execution_time=round(_time.time() - start_time, 3),
            )
        except FileNotFoundError:
            logger.warning("docker_not_found — 回退到 SubprocessSandbox")
            return CodeExecutionResult(
                success=False,
                error_type="DockerNotFound",
                error_message="Docker 未安装或不可用。请安装 Docker 或使用 SubprocessSandbox。",
            )
        except OSError as e:
            return CodeExecutionResult(
                success=False,
                error_type="DockerError",
                error_message=f"Docker 执行失败: {e}",
            )
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
