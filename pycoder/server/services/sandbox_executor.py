"""
SandboxExecutor — Docker 沙箱隔离执行引擎，对标 Codex "沙箱隔离执行" 核心能力

在独立容器中安全执行代码，支持：
  - --network=none 隔离网络，杜绝安全风险
  - --memory 内存限制，防止 OOM
  - 自动容器生命周期管理（超时自动清理）
  - 项目代码挂载模式 vs 临时代码执行模式
  - 预装开发环境（python + pip + git）
  - graceful fallback: Docker 不可用时降级到进程内执行

用法:
    from pycoder.server.services.sandbox_executor import SandboxExecutor

    executor = SandboxExecutor()
    result = await executor.execute_code(
        code="print('hello')", language="python", timeout=30,
    )
    # SandboxResult(success=True, output="hello", ...)
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# ══════════════════════════════════════════════════════════
# 配置常量
# ══════════════════════════════════════════════════════════

SANDBOX_IMAGE = "python:3.13-slim"
SANDBOX_MEMORY_LIMIT = "512m"
SANDBOX_MEMORY_SWAP = "512m"
SANDBOX_CLEANUP_TIMEOUT = 5  # 容器停止超时秒数
EXEC_TIMEOUT_DEFAULT = 30
MAX_CONTAINER_AGE = 3600  # 容器最大存活时间（1小时）


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class SandboxResult:
    """沙箱执行结果"""

    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = -1
    duration_ms: float = 0.0
    container_id: str = ""
    sandbox_mode: str = ""  # "docker" | "subprocess" | "unavailable"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output[:2000],
            "error": self.error[:1000],
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 1),
            "container_id": self.container_id[:12] if self.container_id else "",
            "sandbox_mode": self.sandbox_mode,
        }


@dataclass
class SandboxBuildResult:
    """项目构建结果"""

    success: bool
    output: str = ""
    error: str = ""
    container_id: str = ""
    image_id: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output[:2000],
            "error": self.error[:1000],
        }


# ══════════════════════════════════════════════════════════
# 沙箱执行器
# ══════════════════════════════════════════════════════════

# 沙箱标签用于性能分析
_sandbox_counter = 0


class SandboxExecutor:
    """Docker 沙箱执行器 — 隔离、安全、自动清理"""

    def __init__(
        self,
        image: str = SANDBOX_IMAGE,
        memory_limit: str = SANDBOX_MEMORY_LIMIT,
        network_disabled: bool = True,
    ):
        self._image = image
        self._memory = memory_limit
        self._network_disabled = network_disabled
        self._containers: dict[str, float] = {}  # cid -> created_at

    # ── 可用性检测 ──────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            r = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    async def get_status(self) -> dict:
        """获取沙箱状态概览"""
        available = self.is_available
        active = len(self._containers)
        return {
            "sandbox_mode": "docker" if available else "subprocess",
            "available": available,
            "active_containers": active,
            "image": self._image,
            "network_disabled": self._network_disabled,
            "memory_limit": self._memory,
        }

    # ── 代码执行 ────────────────────────────────────────

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout: int = EXEC_TIMEOUT_DEFAULT,
    ) -> SandboxResult:
        """在沙箱中执行代码

        优先 Docker 容器执行，不可用时降级到 subprocess。
        """
        if self.is_available:
            return await self._docker_exec(code, language, timeout)
        else:
            return self._subprocess_exec(code, language, timeout)

    async def build_project(
        self,
        project_path: str,
        build_cmd: str = "pip install -r requirements.txt",
        timeout: int = 120,
    ) -> SandboxBuildResult:
        """在沙箱中构建项目"""
        if not self.is_available:
            return SandboxBuildResult(
                success=False,
                error="Docker 不可用，无法沙箱构建",
            )

        try:
            cid = await self._start_container()
            abs_path = Path(project_path).resolve()

            # 复制项目到容器
            copy_r = subprocess.run(
                ["docker", "cp", str(abs_path), f"{cid}:/workspace"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if copy_r.returncode != 0:
                return SandboxBuildResult(
                    success=False,
                    error=f"复制项目失败: {copy_r.stderr[:200]}",
                )

            # 执行构建命令
            r = subprocess.run(
                ["docker", "exec", "-w", "/workspace", cid, "sh", "-c", build_cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return SandboxBuildResult(
                success=r.returncode == 0,
                output=r.stdout[:2000],
                error=r.stderr[:1000],
                container_id=cid,
            )

        except subprocess.TimeoutExpired:
            return SandboxBuildResult(success=False, error="构建超时")
        except Exception as e:
            return SandboxBuildResult(success=False, error=str(e))

    # ── Docker 执行 ─────────────────────────────────────

    async def _docker_exec(
        self,
        code: str,
        language: str,
        timeout: int,
    ) -> SandboxResult:
        t0 = time.time()
        try:
            cid = await self._start_container()

            if language == "python":
                cmd = ["docker", "exec", "-i", cid, "python", "-c", code]
            elif language in ("sh", "bash"):
                cmd = ["docker", "exec", "-i", cid, "sh", "-c", code]
            elif language == "node":
                cmd = ["docker", "exec", "-i", cid, "node", "-e", code]
            else:
                # 尝试通过 sh 执行
                cmd = ["docker", "exec", "-i", cid, "sh", "-c", code]

            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.time() - t0) * 1000
            return SandboxResult(
                success=r.returncode == 0,
                output=r.stdout[:5000],
                error=r.stderr[:2000],
                exit_code=r.returncode,
                duration_ms=duration,
                container_id=cid,
                sandbox_mode="docker",
            )

        except subprocess.TimeoutExpired:
            duration = (time.time() - t0) * 1000
            return SandboxResult(
                success=False,
                error=f"⏱ 沙箱执行超时 ({timeout}s)",
                duration_ms=duration,
                sandbox_mode="docker",
            )
        except Exception as e:
            duration = (time.time() - t0) * 1000
            return SandboxResult(
                success=False,
                error=str(e),
                duration_ms=duration,
                sandbox_mode="docker",
            )

    async def _start_container(self) -> str:
        """启动一个隔离沙箱容器"""
        global _sandbox_counter
        _sandbox_counter += 1
        name = f"pyc-sandbox-{uuid.uuid4().hex[:8]}"

        docker_args = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "none",  # 无网络 — 最核心的隔离
            "--memory",
            self._memory,
            "--memory-swap",
            self._memory,
            "--pids-limit",
            "100",  # 限制进程数
            "--read-only",  # 只读文件系统
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop",
            "ALL",  # 删除所有内核能力
            "--security-opt",
            "no-new-privileges:true",
            self._image,
            "tail",
            "-f",
            "/dev/null",  # 保持运行
        ]

        r = subprocess.run(
            docker_args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"沙箱容器启动失败: {r.stderr[:300]}")

        cid = r.stdout.strip()
        self._containers[cid] = time.time()

        # 安装基础工具
        subprocess.run(
            ["docker", "exec", cid, "pip", "install", "--quiet", "pytest", "httpx"],
            capture_output=True,
            timeout=30,
        )

        return cid

    # ── Subprocess 降级 ─────────────────────────────────

    def _subprocess_exec(
        self,
        code: str,
        language: str,
        timeout: int,
    ) -> SandboxResult:
        """Docker 不可用时的降级方案"""
        t0 = time.time()
        try:
            if language == "python":
                cmd = [sys.executable, "-c", code]
            else:
                cmd = [sys.executable, "-c", code]

            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.time() - t0) * 1000
            return SandboxResult(
                success=r.returncode == 0,
                output=r.stdout[:5000],
                error=r.stderr[:2000],
                exit_code=r.returncode,
                duration_ms=duration,
                sandbox_mode="subprocess",
            )
        except subprocess.TimeoutExpired:
            duration = (time.time() - t0) * 1000
            return SandboxResult(
                success=False,
                error=f"超时 ({timeout}s)",
                duration_ms=duration,
                sandbox_mode="subprocess",
            )
        except Exception as e:
            duration = (time.time() - t0) * 1000
            return SandboxResult(
                success=False,
                error=str(e),
                duration_ms=duration,
                sandbox_mode="subprocess",
            )

    # ── 容器清理 ────────────────────────────────────────

    async def cleanup(self, cid: str | None = None) -> int:
        """清理指定容器或所有超时容器，返回清理数量"""
        if cid:
            return self._stop_container(cid)

        now = time.time()
        cleaned = 0
        for cid, created in list(self._containers.items()):
            if now - created > MAX_CONTAINER_AGE:
                self._stop_container(cid)
                cleaned += 1
        return cleaned

    def _stop_container(self, cid: str) -> int:
        """停止单个容器"""
        try:
            subprocess.run(
                ["docker", "stop", "--time", str(SANDBOX_CLEANUP_TIMEOUT), cid],
                capture_output=True,
                timeout=10,
            )
            self._containers.pop(cid, None)
            return 1
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return 0

    async def cleanup_all(self) -> int:
        """清理所有沙箱容器"""
        cleaned = 0
        for cid in list(self._containers.keys()):
            cleaned += self._stop_container(cid)
        return cleaned


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_sandbox_executor: SandboxExecutor | None = None


def get_sandbox_executor() -> SandboxExecutor:
    global _sandbox_executor
    if _sandbox_executor is None:
        _sandbox_executor = SandboxExecutor()
    return _sandbox_executor
