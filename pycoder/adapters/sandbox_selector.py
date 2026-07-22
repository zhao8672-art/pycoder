"""P1-4: 沙箱工厂 — 自动选择 Docker / Subprocess 实现

决策点 (按用户偏好 P1-4): 可选 + 降级
- 不强制要求 Docker 安装
- 若 Docker 可用 → 优先使用 DockerSandbox（更强隔离）
- 若 Docker 不可用 → 自动降级到 SubprocessSandbox
- 可通过环境变量 / 配置强制指定

配置项（环境变量优先）：
- PYCODER_SANDBOX=docker|subprocess|auto（默认 auto）
- PYCODER_DOCKER_IMAGE=python:3.12-slim（默认）
- PYCODER_DOCKER_REQUIRED=true|false（默认 false — 不可用时静默降级）

Docker 可用性检测：
- 缓存 60s，避免每次执行都跑 docker info
- 同时检查 docker CLI 与 docker daemon
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass

from pycoder.core.ports.code_sandbox import CodeExecutionResult, CodeSandbox

logger = logging.getLogger(__name__)


@dataclass
class SandboxInfo:
    """沙箱选择信息"""

    backend: str  # "docker" | "subprocess"
    docker_available: bool
    reason: str
    image: str = ""


# ── Docker 可用性检测 ──────────────────────────────────

_docker_check_cache: tuple[float, bool, str] | None = None
_CACHE_TTL = 60  # 秒


async def check_docker_available() -> tuple[bool, str]:
    """异步检测 Docker 是否可用

    Returns:
        (可用, 原因)
    """
    global _docker_check_cache
    now = time.time()
    if _docker_check_cache and now - _docker_check_cache[0] < _CACHE_TTL:
        return _docker_check_cache[1], _docker_check_cache[2]

    # 1) 检查 docker CLI
    if not shutil.which("docker"):
        result = (False, "docker CLI 未安装")
        _docker_check_cache = (now, *result)
        return result

    # 2) 检查 docker daemon
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "info",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            result = (True, "docker daemon 可访问")
        else:
            err = stderr.decode("utf-8", errors="replace")[:200]
            result = (False, f"docker daemon 不可用: {err.strip()}")
        _docker_check_cache = (now, *result)
        return result
    except (TimeoutError, OSError) as e:
        result = (False, f"docker info 超时或失败: {e}")
        _docker_check_cache = (now, *result)
        return result


def invalidate_docker_cache() -> None:
    """清空 docker 可用性缓存"""
    global _docker_check_cache
    _docker_check_cache = None


# ── 沙箱选择器 ─────────────────────────────────────────


class SandboxSelector:
    """沙箱选择器 — 决策使用哪个后端"""

    def __init__(
        self,
        prefer: str | None = None,
        docker_image: str | None = None,
        docker_required: bool | None = None,
    ) -> None:
        self._prefer = (prefer or os.getenv("PYCODER_SANDBOX", "auto")).lower()
        self._docker_image = docker_image or os.getenv(
            "PYCODER_DOCKER_IMAGE", "python:3.12-slim"
        )
        if docker_required is None:
            self._docker_required = os.getenv("PYCODER_DOCKER_REQUIRED", "false").lower() == "true"
        else:
            self._docker_required = docker_required
        self._cached_backend: str | None = None
        self._cached_subprocess: CodeSandbox | None = None
        self._cached_docker: CodeSandbox | None = None
        self._cached_info: SandboxInfo | None = None

    async def select(self, force_check: bool = False) -> SandboxInfo:
        """选择后端（带缓存）"""
        if self._cached_info and not force_check:
            return self._cached_info

        docker_available, reason = await check_docker_available()
        backend: str

        if self._prefer == "docker":
            if docker_available:
                backend = "docker"
            elif self._docker_required:
                raise RuntimeError(
                    f"Docker 不可用但 PYCODER_SANDBOX=docker 且 required: {reason}"
                )
            else:
                logger.warning(
                    "sandbox_docker_unavailable_fallback reason=%s", reason
                )
                backend = "subprocess"
        elif self._prefer == "subprocess":
            backend = "subprocess"
        else:  # auto
            backend = "docker" if docker_available else "subprocess"
            if not docker_available:
                logger.info(
                    "sandbox_auto_select_subprocess reason=%s", reason
                )

        info = SandboxInfo(
            backend=backend,
            docker_available=docker_available,
            reason=reason,
            image=self._docker_image if backend == "docker" else "",
        )
        self._cached_info = info
        return info

    async def get_sandbox(self) -> tuple[CodeSandbox, SandboxInfo]:
        """获取沙箱实例（懒创建）"""
        info = await self.select()
        if info.backend == "docker":
            if self._cached_docker is None:
                from pycoder.adapters.docker_sandbox import DockerSandbox

                self._cached_docker = DockerSandbox(image=self._docker_image)
            return self._cached_docker, info
        if self._cached_subprocess is None:
            from pycoder.adapters.subprocess_sandbox import SubprocessSandbox

            self._cached_subprocess = SubprocessSandbox()
        return self._cached_subprocess, info

    def reset(self) -> None:
        """重置选择器状态"""
        self._cached_backend = None
        self._cached_subprocess = None
        self._cached_docker = None
        self._cached_info = None


# ── 全局单例 ───────────────────────────────────────────

_selector: SandboxSelector | None = None


def get_selector() -> SandboxSelector:
    """获取全局选择器"""
    global _selector
    if _selector is None:
        _selector = SandboxSelector()
    return _selector


def reset_selector() -> None:
    """重置全局选择器（用于配置变更后）"""
    global _selector
    _selector = None
    invalidate_docker_cache()


# ── 便捷函数 ───────────────────────────────────────────


async def execute_code(code: str, timeout: int = 30) -> tuple[CodeExecutionResult, SandboxInfo]:
    """便捷执行入口 — 自动选择沙箱

    Returns:
        (执行结果, 沙箱信息)
    """
    selector = get_selector()
    sandbox, info = await selector.get_sandbox()
    result = await sandbox.execute(code, timeout=timeout)
    return result, info
