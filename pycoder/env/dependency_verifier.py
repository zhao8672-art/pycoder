"""
依赖验证器 — 验证已安装依赖的正确性

功能:
- 验证所有已安装包及其版本
- 导入测试（检查包能否正常导入）
- 生成安装验证报告
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pycoder.env.dependency import (
    DependencyPackage,
    DependencyStatus,
    InstallResult,
    InstallReport,
    PackageManager,
)

logger = logging.getLogger(__name__)


class DependencyVerifier:
    """依赖验证器"""

    def __init__(self, python_path: str | None = None):
        self._python_path = python_path or sys.executable

    async def verify_all(
        self,
        packages: list[DependencyPackage],
        results: list[InstallResult] | None = None,
    ) -> list[dict[str, Any]]:
        """
        验证所有依赖包

        Args:
            packages: 要验证的包列表
            results: 安装结果（可选，用于对比）

        Returns:
            验证结果列表，每个元素包含 name, installed, version, importable, error
        """
        verifications = []
        result_map = {}
        if results:
            result_map = {r.package_name: r for r in results}

        tasks = [self._verify_one(pkg, result_map.get(pkg.name)) for pkg in packages]
        verifications = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        validated = []
        for i, v in enumerate(verifications):
            if isinstance(v, Exception):
                validated.append({
                    "name": packages[i].name if i < len(packages) else "unknown",
                    "installed": False,
                    "version": "",
                    "importable": False,
                    "error": str(v),
                })
            else:
                validated.append(v)

        return validated

    async def _verify_one(
        self, pkg: DependencyPackage, install_result: InstallResult | None = None,
    ) -> dict[str, Any]:
        """验证单个包"""
        name = pkg.name
        result: dict[str, Any] = {
            "name": name,
            "installed": False,
            "version": "",
            "importable": False,
            "error": "",
        }

        # 1. pip show 检查
        version = await self._get_version(name)
        if version:
            result["installed"] = True
            result["version"] = version

            # 2. 版本约束检查
            if not pkg.is_satisfied_by(version):
                result["error"] = (
                    f"版本不满足: 已安装 {version}，"
                    f"要求 {', '.join(c.raw for c in pkg.constraints)}"
                )
        else:
            result["error"] = "未安装"

        # 3. 导入测试
        if result["installed"]:
            importable, import_error = await self._test_import(name)
            result["importable"] = importable
            if not importable:
                result["error"] = result["error"] or f"导入失败: {import_error}"

        return result

    async def _get_version(self, package_name: str) -> str | None:
        """通过 pip show 获取版本"""
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

    async def _test_import(self, package_name: str) -> tuple[bool, str]:
        """测试能否导入包"""
        # 将包名映射到导入名
        import_name = self._get_import_name(package_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                self._python_path, "-c",
                f"import {import_name}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

            if proc.returncode == 0:
                return True, ""
            else:
                return False, stderr.decode("utf-8", errors="replace")[:200]
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _get_import_name(package_name: str) -> str:
        """将 pip 包名映射到 Python import 名"""
        # 常见映射
        known_mappings: dict[str, str] = {
            "python-multipart": "multipart",
            "python-dotenv": "dotenv",
            "pyyaml": "yaml",
            "pillow": "PIL",
            "opencv-python-headless": "cv2",
            "scikit-learn": "sklearn",
            "google-generativeai": "google.generativeai",
            "python-dateutil": "dateutil",
            "pytesseract": "pytesseract",
            "sentry-sdk": "sentry_sdk",
            "python-jose": "jose",
            "email-validator": "email_validator",
        }
        return known_mappings.get(package_name.lower(), package_name.replace("-", "_"))


class ReportGenerator:
    """安装报告生成器"""

    @staticmethod
    def generate(
        packages: list[DependencyPackage],
        results: list[InstallResult],
        verifications: list[dict[str, Any]],
        source_file: str = "",
        package_manager: PackageManager = PackageManager.AUTO,
        total_duration_ms: float = 0.0,
    ) -> InstallReport:
        """
        生成安装报告

        Args:
            packages: 原始依赖列表
            results: 安装结果列表
            verifications: 验证结果列表
            source_file: 来源文件
            package_manager: 包管理器
            total_duration_ms: 总耗时

        Returns:
            InstallReport 实例
        """
        from datetime import datetime, timezone

        installed = sum(1 for r in results if r.status == DependencyStatus.INSTALLED)
        skipped = sum(1 for r in results if r.status == DependencyStatus.SKIPPED)
        failed = sum(1 for r in results if r.status == DependencyStatus.FAILED)

        return InstallReport(
            source=packages[0].source if packages else DependencySource.AUTO_DETECT,
            source_file=source_file,
            total_packages=len(packages),
            installed=installed,
            skipped=skipped,
            failed=failed,
            results=results,
            total_duration_ms=total_duration_ms,
            package_manager=package_manager,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )