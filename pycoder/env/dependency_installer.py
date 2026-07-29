"""
依赖安装执行器 — 通过 pip/conda 安装依赖

支持:
- pip 安装（含批量安装优化）
- conda 安装
- 进度回调通知
- 超时控制
- 错误重试
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pycoder.env.dependency import (
    DependencyPackage,
    DependencyStatus,
    InstallResult,
    PackageManager,
)

logger = logging.getLogger(__name__)

# 进度回调类型: (current: int, total: int, package_name: str, status: str) -> None
ProgressCallback = Callable[[int, int, str, str], None]


class DependencyInstaller:
    """依赖安装执行器"""

    def __init__(
        self,
        python_path: str | None = None,
        package_manager: PackageManager = PackageManager.AUTO,
        max_parallel: int = 1,
        timeout_per_package: float = 300.0,
        retry_count: int = 2,
    ):
        self._python_path = python_path or sys.executable
        self._package_manager = self._detect_manager(package_manager)
        self._max_parallel = max_parallel
        self._timeout = timeout_per_package
        self._retry_count = retry_count
        self._results: list[InstallResult] = []

    # ── 公共 API ──────────────────────────────────

    async def install_all(
        self,
        packages: list[DependencyPackage],
        on_progress: ProgressCallback | None = None,
    ) -> list[InstallResult]:
        """
        按顺序安装所有依赖包

        Args:
            packages: 要安装的包列表（已按依赖顺序排序）
            on_progress: 进度回调

        Returns:
            安装结果列表
        """
        self._results = []
        total = len(packages)

        for i, pkg in enumerate(packages):
            self._notify(on_progress, i, total, pkg.name, "installing")

            result = await self.install_one(pkg)
            self._results.append(result)

            if result.status == DependencyStatus.FAILED:
                self._notify(on_progress, i + 1, total, pkg.name, "failed")
                logger.error("安装失败: %s - %s", pkg.name, result.error)
            elif result.status == DependencyStatus.SKIPPED:
                self._notify(on_progress, i + 1, total, pkg.name, "skipped")
            else:
                self._notify(on_progress, i + 1, total, pkg.name, "installed")

        return self._results

    async def install_one(self, pkg: DependencyPackage) -> InstallResult:
        """
        安装单个依赖包

        先检查是否已安装且版本满足，满足则跳过。
        """
        # 检查已安装版本
        installed_version = await self._get_installed_version(pkg.name)
        if installed_version and pkg.is_satisfied_by(installed_version):
            return InstallResult(
                package_name=pkg.name,
                status=DependencyStatus.SKIPPED,
                version=installed_version,
            )

        # 安装
        for attempt in range(self._retry_count + 1):
            result = await self._do_install(pkg)
            if result.status == DependencyStatus.INSTALLED:
                return result
            if attempt < self._retry_count:
                logger.warning(
                    "重试安装 %s (第 %d/%d 次)",
                    pkg.name, attempt + 1, self._retry_count,
                )
                await asyncio.sleep(1)

        return result

    async def install_from_requirements(
        self,
        file_path: str | Path,
        on_progress: ProgressCallback | None = None,
    ) -> list[InstallResult]:
        """
        直接从 requirements.txt 文件批量安装（使用 pip install -r）
        这是最快的安装方式，利用 pip 自身的依赖解析。
        """
        file_path = Path(file_path)
        result = InstallResult(
            package_name="batch",
            status=DependencyStatus.PENDING,
        )

        start = time.time()
        try:
            cmd = [
                self._python_path, "-m", "pip", "install",
                "-r", str(file_path),
                "--quiet", "--disable-pip-version-check",
            ]
            self._notify(on_progress, 0, 1, "batch", "installing")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout * 2,
                )
            except TimeoutError:
                proc.kill()
                result.status = DependencyStatus.FAILED
                result.error = "批量安装超时"
                result.duration_ms = (time.time() - start) * 1000
                return [result]

            result.duration_ms = (time.time() - start) * 1000
            result.stdout = stdout.decode("utf-8", errors="replace")
            result.stderr = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                result.status = DependencyStatus.INSTALLED
                self._notify(on_progress, 1, 1, "batch", "installed")
            else:
                result.status = DependencyStatus.FAILED
                result.error = result.stderr[-500:] if result.stderr else "未知错误"
                self._notify(on_progress, 1, 1, "batch", "failed")

        except Exception as e:
            result.status = DependencyStatus.FAILED
            result.error = str(e)
            result.duration_ms = (time.time() - start) * 1000

        return [result]

    # ── 内部方法 ──────────────────────────────────

    async def _do_install(self, pkg: DependencyPackage) -> InstallResult:
        """执行 pip install"""
        result = InstallResult(package_name=pkg.name)
        start = time.time()

        specifier = pkg.pip_specifier
        cmd = [
            self._python_path, "-m", "pip", "install",
            specifier,
            "--quiet", "--disable-pip-version-check",
            "--no-deps",  # 单独安装，不递归安装依赖
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout,
                )
            except TimeoutError:
                proc.kill()
                result.status = DependencyStatus.FAILED
                result.error = f"安装超时 ({self._timeout}s)"
                result.duration_ms = (time.time() - start) * 1000
                return result

            result.duration_ms = (time.time() - start) * 1000
            result.stdout = stdout.decode("utf-8", errors="replace")
            result.stderr = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                result.status = DependencyStatus.INSTALLED
                # 获取安装后的版本
                version = await self._get_installed_version(pkg.name)
                result.version = version or ""
            else:
                result.status = DependencyStatus.FAILED
                error_text = result.stderr or result.stdout
                result.error = error_text[-300:] if error_text else f"退出码 {proc.returncode}"

        except FileNotFoundError:
            result.status = DependencyStatus.FAILED
            result.error = f"找不到 pip（{self._python_path}）"
            result.duration_ms = (time.time() - start) * 1000
        except Exception as e:
            result.status = DependencyStatus.FAILED
            result.error = str(e)
            result.duration_ms = (time.time() - start) * 1000

        return result

    async def _get_installed_version(self, package_name: str) -> str | None:
        """查询已安装包的版本"""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._python_path, "-m", "pip", "show", package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode("utf-8", errors="replace")

            for line in output.splitlines():
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _detect_manager(preferred: PackageManager) -> PackageManager:
        """检测可用的包管理器"""
        if preferred != PackageManager.AUTO:
            return preferred

        # 优先检测 conda
        if shutil.which("conda"):
            return PackageManager.CONDA
        return PackageManager.PIP

    @staticmethod
    def _notify(
        callback: ProgressCallback | None,
        current: int, total: int, name: str, status: str,
    ) -> None:
        """安全调用进度回调"""
        if callback:
            try:
                callback(current, total, name, status)
            except Exception:
                pass


def detect_package_manager() -> PackageManager:
    """检测当前环境使用的包管理器"""
    if shutil.which("conda"):
        # 检查是否在 conda 环境中
        try:
            result = subprocess.run(
                ["conda", "info", "--json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return PackageManager.CONDA
        except Exception:
            pass
    return PackageManager.PIP