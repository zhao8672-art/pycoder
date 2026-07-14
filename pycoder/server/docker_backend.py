"""
Docker 远程执行后端 — 在容器中运行代码和执行环境

功能:
- 启动/停止 Python 容器作为执行后端
- 在容器中执行代码
- 继承现有 CodeExecutor 接口
- 自动检测环境并优雅降级
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

from pycoder.server.env_checker import get_env_checker

logger = logging.getLogger(__name__)
_ec = get_env_checker()


@dataclass
class DockerExecutionResult:
    """Docker 执行结果"""

    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    container_id: str = ""


class DockerBackend:
    """
    Docker 执行后端 — 在 Python 容器中执行代码。

    需要 Docker 已安装且当前用户有权限访问。
    自动管理容器生命周期。
    """

    def __init__(self, image: str = "python:3.13-slim"):
        self.image = image
        self._container_id: str | None = None
        self._available: bool | None = None

    @property
    def is_available(self) -> bool:
        """检查 Docker 是否可用（使用统一环境检测器）"""
        if self._available is not None:
            return self._available
        self._available = _ec.has("docker")
        if not self._available:
            logger.info("docker_unavailable_fallback: %s", _ec.get_capabilities().docker.hint)
        return self._available

    async def ensure_container(self) -> str:
        """确保运行中的 Python 容器"""
        if self._container_id:
            check = subprocess.run(
                ["docker", "inspect", self._container_id, "--format", "{{.State.Running}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if check.returncode == 0 and check.stdout.strip() == "true":
                return self._container_id

        # 创建新容器
        r = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                f"pycoder-runner-{os.getpid()}",
                self.image,
                "tail",
                "-f",
                "/dev/null",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Docker 启动失败: {r.stderr[:200]}")
        self._container_id = r.stdout.strip()
        return self._container_id

    async def execute(self, code: str, timeout: int = 30) -> DockerExecutionResult:
        """在容器中执行 Python 代码"""
        import time

        start = time.time()
        try:
            cid = await self.ensure_container()
            # 写入代码到容器
            r = subprocess.run(
                ["docker", "exec", "-i", cid, "python", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.time() - start) * 1000
            return DockerExecutionResult(
                success=r.returncode == 0,
                output=r.stdout[:2000],
                error=r.stderr[:1000],
                duration_ms=duration,
                container_id=cid,
            )
        except subprocess.TimeoutExpired:
            return DockerExecutionResult(
                success=False,
                error=f"执行超时 ({timeout}s)",
                duration_ms=timeout * 1000,
            )
        except Exception as e:
            return DockerExecutionResult(success=False, error=str(e))

    async def install_package(self, package: str) -> tuple[bool, str]:
        """在容器中安装 Python 包"""
        try:
            cid = await self.ensure_container()
            r = subprocess.run(
                ["docker", "exec", cid, "pip", "install", package],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return r.returncode == 0, r.stdout[:500] or r.stderr[:500]
        except Exception as e:
            return False, str(e)

    async def cleanup(self):
        """停止并移除容器"""
        if self._container_id:
            subprocess.run(
                ["docker", "stop", self._container_id],
                capture_output=True,
                timeout=10,
            )
            self._container_id = None

    async def get_status(self) -> dict:
        """获取后端状态"""
        if not self.is_available:
            return {"available": False, "reason": "Docker 未安装或不可用"}
        try:
            cid = await self.ensure_container()
            return {"available": True, "container_id": cid[:12], "image": self.image}
        except Exception as e:
            return {"available": False, "reason": str(e)}


# 全局单例
_docker_backend: DockerBackend | None = None


def get_docker_backend() -> DockerBackend:
    global _docker_backend
    if _docker_backend is None:
        _docker_backend = DockerBackend()
    return _docker_backend
