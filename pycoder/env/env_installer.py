"""
自动化依赖环境安装器 — 一站式依赖安装解决方案

核心功能:
- 自动检测项目中的依赖配置文件
- 解析依赖及其版本约束
- 检测版本冲突
- 按正确顺序安装依赖
- 验证安装结果
- 生成安装报告

使用方式:
    from pycoder.env.env_installer import EnvInstaller

    installer = EnvInstaller()

    # 自动检测并安装
    report = await installer.auto_install()

    # 或指定文件
    report = await installer.install_from_file("requirements.txt")

    # 获取报告
    print(report.to_markdown())
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pycoder.env.dependency import (
    DependencyConflict,
    DependencyPackage,
    DependencySource,
    DependencyStatus,
    InstallReport,
    InstallResult,
    PackageManager,
)
from pycoder.env.dependency_installer import (
    DependencyInstaller,
    ProgressCallback,
    detect_package_manager,
)
from pycoder.env.dependency_resolver import DependencyResolver
from pycoder.env.dependency_verifier import DependencyVerifier, ReportGenerator

logger = logging.getLogger(__name__)


class EnvInstaller:
    """
    自动化依赖环境安装器

    一站式管理项目的依赖安装全流程:
    解析 → 冲突检测 → 排序 → 安装 → 验证 → 报告
    """

    def __init__(
        self,
        project_root: str | Path = ".",
        python_path: str | None = None,
        package_manager: PackageManager = PackageManager.AUTO,
    ):
        self._project_root = Path(project_root).resolve()
        self._python_path = python_path
        self._package_manager = (
            package_manager
            if package_manager != PackageManager.AUTO
            else detect_package_manager()
        )

        self._resolver = DependencyResolver(self._project_root)
        self._installer = DependencyInstaller(
            python_path=self._python_path,
            package_manager=self._package_manager,
        )
        self._verifier = DependencyVerifier(python_path=self._python_path)

        self._last_report: InstallReport | None = None

    # ── 公共 API ──────────────────────────────────

    async def auto_install(
        self,
        on_progress: ProgressCallback | None = None,
        verify: bool = True,
    ) -> InstallReport:
        """
        自动检测项目依赖文件并安装

        Args:
            on_progress: 进度回调
            verify: 是否在安装后验证

        Returns:
            InstallReport 安装报告
        """
        logger.info("开始自动检测依赖文件...")

        # 1. 解析
        packages, conflicts, errors = self._resolver.resolve_ordered()
        if errors:
            logger.warning("解析依赖时出现警告: %s", errors)

        if not packages:
            return InstallReport(
                total_packages=0,
                conflicts=conflicts,
            )

        # 2. 安装
        logger.info("检测到 %d 个依赖，开始安装...", len(packages))
        start = time.time()
        results = await self._installer.install_all(packages, on_progress)
        duration = (time.time() - start) * 1000

        # 3. 验证
        verifications = []
        if verify:
            logger.info("正在验证安装结果...")
            verifications = await self._verifier.verify_all(packages, results)

        # 4. 生成报告
        package_source = packages[0].source if packages else DependencySource.AUTO_DETECT
        source_file = packages[0].source_file if packages else ""

        report = ReportGenerator.generate(
            packages=packages,
            results=results,
            verifications=verifications,
            source_file=source_file,
            package_manager=self._package_manager,
            total_duration_ms=duration,
        )

        # 附加冲突和验证信息
        report.conflicts = conflicts

        self._last_report = report
        return report

    async def install_from_file(
        self,
        source_file: str,
        source_type: DependencySource = DependencySource.AUTO_DETECT,
        on_progress: ProgressCallback | None = None,
        verify: bool = True,
    ) -> InstallReport:
        """
        从指定依赖文件安装

        Args:
            source_file: 依赖文件路径
            source_type: 文件类型
            on_progress: 进度回调
            verify: 是否验证

        Returns:
            InstallReport 安装报告
        """
        logger.info("从文件安装依赖: %s", source_file)

        # 1. 解析
        packages, conflicts, errors = self._resolver.resolve_ordered(
            source_file=source_file, source_type=source_type,
        )
        if errors:
            logger.warning("解析依赖时出现警告: %s", errors)

        if not packages:
            return InstallReport(
                total_packages=0,
                source_file=source_file,
                conflicts=conflicts,
            )

        # 2. 安装
        logger.info("解析到 %d 个依赖，开始安装...", len(packages))
        start = time.time()

        # 对于 requirements.txt，优先使用批量安装
        if source_type == DependencySource.REQUIREMENTS_TXT or (
            source_type == DependencySource.AUTO_DETECT
            and source_file.endswith(".txt")
        ):
            results = await self._installer.install_from_requirements(
                Path(source_file), on_progress,
            )
        else:
            results = await self._installer.install_all(packages, on_progress)

        duration = (time.time() - start) * 1000

        # 3. 验证
        verifications = []
        if verify:
            verifications = await self._verifier.verify_all(packages, results)

        # 4. 生成报告
        report = ReportGenerator.generate(
            packages=packages,
            results=results,
            verifications=verifications,
            source_file=source_file,
            package_manager=self._package_manager,
            total_duration_ms=duration,
        )
        report.conflicts = conflicts

        self._last_report = report
        return report

    async def install_packages(
        self,
        package_specs: list[str],
        on_progress: ProgressCallback | None = None,
        verify: bool = True,
    ) -> InstallReport:
        """
        安装指定的包列表

        Args:
            package_specs: 包说明符列表，如 ["numpy>=1.21", "pandas==1.3.0"]
            on_progress: 进度回调
            verify: 是否验证

        Returns:
            InstallReport 安装报告
        """
        # 解析为 DependencyPackage
        packages = []
        for spec in package_specs:
            pkg = self._resolver._parse_requirement_line(
                spec, self._project_root / "manual"
            )
            if pkg:
                packages.append(pkg)

        if not packages:
            return InstallReport(total_packages=0)

        # 安装
        start = time.time()
        results = await self._installer.install_all(packages, on_progress)
        duration = (time.time() - start) * 1000

        # 验证
        verifications = []
        if verify:
            verifications = await self._verifier.verify_all(packages, results)

        report = ReportGenerator.generate(
            packages=packages,
            results=results,
            verifications=verifications,
            source_file="manual",
            package_manager=self._package_manager,
            total_duration_ms=duration,
        )
        self._last_report = report
        return report

    async def check_environment(
        self,
        source_file: str | None = None,
        source_type: DependencySource = DependencySource.AUTO_DETECT,
    ) -> dict[str, Any]:
        """
        检查环境状态 — 不安装，仅检查哪些依赖缺失/版本不满足

        Returns:
            环境状态字典，包含 missing, outdated, satisfied 列表
        """
        packages, conflicts, errors = self._resolver.resolve(
            source_file=source_file, source_type=source_type,
        )

        verifications = await self._verifier.verify_all(packages)

        missing = []
        outdated = []
        satisfied = []

        for v in verifications:
            if not v["installed"]:
                missing.append({"name": v["name"], "error": v.get("error", "")})
            elif v.get("error"):
                outdated.append({
                    "name": v["name"],
                    "version": v["version"],
                    "error": v["error"],
                })
            else:
                satisfied.append({"name": v["name"], "version": v["version"]})

        return {
            "total": len(packages),
            "missing": missing,
            "outdated": outdated,
            "satisfied": satisfied,
            "conflicts": [
                {"package": c.package_name, "message": c.message}
                for c in conflicts
            ],
            "errors": errors,
        }

    # ── 属性 ──────────────────────────────────────

    @property
    def last_report(self) -> InstallReport | None:
        """获取最后一次安装的报告"""
        return self._last_report

    @property
    def project_root(self) -> Path:
        """获取项目根目录"""
        return self._project_root

    @property
    def package_manager(self) -> PackageManager:
        """获取当前使用的包管理器"""
        return self._package_manager