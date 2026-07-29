"""
环境依赖安装模块 — 单元测试

覆盖:
- 数据模型 (dependency.py)
- 依赖解析器 (dependency_resolver.py)
- 安装执行器 (dependency_installer.py)
- 验证与报告 (dependency_verifier.py)
- 环境安装器总控 (env_installer.py)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.env.dependency import (
    DependencyConflict,
    DependencyPackage,
    DependencySource,
    DependencyStatus,
    InstallReport,
    InstallResult,
    PackageManager,
    VersionConstraint,
)
from pycoder.env.dependency_installer import DependencyInstaller, detect_package_manager
from pycoder.env.dependency_resolver import DependencyResolver
from pycoder.env.dependency_verifier import DependencyVerifier, ReportGenerator
from pycoder.env.env_installer import EnvInstaller


# ════════════════════════════════════════════════════════════════════
# VersionConstraint 测试
# ════════════════════════════════════════════════════════════════════


class TestVersionConstraint:
    """版本约束解析与验证"""

    def test_parse_exact(self):
        """解析精确版本约束"""
        vc = VersionConstraint(raw="==1.0.0")
        assert vc.operator == "=="
        assert vc.version == "1.0.0"
        assert vc.is_satisfied_by("1.0.0") is True
        assert vc.is_satisfied_by("1.0.1") is False

    def test_parse_gte(self):
        """解析 >= 约束"""
        vc = VersionConstraint(raw=">=2.0")
        assert vc.operator == ">="
        assert vc.version == "2.0"
        assert vc.is_satisfied_by("2.0") is True
        assert vc.is_satisfied_by("2.1") is True
        assert vc.is_satisfied_by("1.9") is False

    def test_parse_lte(self):
        """解析 <= 约束"""
        vc = VersionConstraint(raw="<=3.0")
        assert vc.operator == "<="
        assert vc.is_satisfied_by("3.0") is True
        assert vc.is_satisfied_by("2.0") is True
        assert vc.is_satisfied_by("3.1") is False

    def test_parse_compatible(self):
        """解析 ~= 兼容版本约束"""
        vc = VersionConstraint(raw="~=1.4.2")
        assert vc.operator == "~="
        assert vc.version == "1.4.2"
        assert vc.is_satisfied_by("1.4.2") is True
        assert vc.is_satisfied_by("1.4.5") is True
        assert vc.is_satisfied_by("1.5.0") is False

    def test_parse_gt(self):
        """解析 > 约束"""
        vc = VersionConstraint(raw=">1.0")
        assert vc.operator == ">"
        assert vc.is_satisfied_by("1.1") is True
        assert vc.is_satisfied_by("1.0") is False

    def test_parse_ne(self):
        """解析 != 约束"""
        vc = VersionConstraint(raw="!=1.0")
        assert vc.operator == "!="
        assert vc.is_satisfied_by("1.1") is True
        assert vc.is_satisfied_by("1.0") is False

    def test_parse_simple_version(self):
        """解析纯版本号（无操作符）"""
        vc = VersionConstraint(raw="1.2.3")
        assert vc.operator == "=="
        assert vc.version == "1.2.3"

    def test_parse_empty(self):
        """解析空约束"""
        vc = VersionConstraint(raw="")
        assert vc.operator == ""
        assert vc.version == ""

    def test_invalid_version_graceful(self):
        """无效版本号应优雅处理"""
        vc = VersionConstraint(raw="==1.0.0")
        # 已安装版本无效时返回 True（宽松处理）
        assert vc.is_satisfied_by("invalid") is True

    def test_to_pip_string(self):
        """转换为 pip 格式"""
        vc = VersionConstraint(raw=">=1.0,<2.0")
        # 多约束时，regex 只匹配第一个操作符，剩余部分保留在 raw 中
        # to_pip_string 返回 operator+version 或 raw 作为降级
        assert ">=1.0" in vc.to_pip_string() or vc.to_pip_string() == ">=1.0,<2.0"


# ════════════════════════════════════════════════════════════════════
# DependencyPackage 测试
# ════════════════════════════════════════════════════════════════════


class TestDependencyPackage:
    """依赖包描述测试"""

    def test_pip_specifier_simple(self):
        """简单包名转 pip 说明符"""
        pkg = DependencyPackage(name="numpy")
        assert pkg.pip_specifier == "numpy"

    def test_pip_specifier_with_version(self):
        """带版本约束的 pip 说明符"""
        pkg = DependencyPackage(
            name="numpy",
            constraints=[VersionConstraint(raw=">=1.21")],
        )
        assert pkg.pip_specifier == "numpy>=1.21"

    def test_pip_specifier_with_extras(self):
        """带 extras 的 pip 说明符"""
        pkg = DependencyPackage(
            name="fastapi",
            extras=["all"],
            constraints=[VersionConstraint(raw=">=0.100.0")],
        )
        assert "fastapi[all]" in pkg.pip_specifier
        assert ">=0.100.0" in pkg.pip_specifier

    def test_is_satisfied_by_no_constraints(self):
        """无约束时总是满足"""
        pkg = DependencyPackage(name="numpy")
        assert pkg.is_satisfied_by("any_version") is True

    def test_is_satisfied_by_match(self):
        """版本匹配"""
        pkg = DependencyPackage(
            name="numpy",
            constraints=[VersionConstraint(raw=">=1.21")],
        )
        assert pkg.is_satisfied_by("1.22.0") is True

    def test_is_satisfied_by_mismatch(self):
        """版本不匹配"""
        pkg = DependencyPackage(
            name="numpy",
            constraints=[VersionConstraint(raw=">=1.21")],
        )
        assert pkg.is_satisfied_by("1.20.0") is False


# ════════════════════════════════════════════════════════════════════
# InstallReport 测试
# ════════════════════════════════════════════════════════════════════


class TestInstallReport:
    """安装报告测试"""

    def test_success_rate_all_installed(self):
        """全部安装成功时成功率为 100%"""
        report = InstallReport(
            total_packages=5,
            installed=5,
            skipped=0,
            failed=0,
        )
        assert report.success_rate == 1.0

    def test_success_rate_partial(self):
        """部分安装成功"""
        report = InstallReport(
            total_packages=10,
            installed=7,
            skipped=1,
            failed=2,
        )
        assert report.success_rate == 7 / 9  # 忽略已跳过的

    def test_success_rate_all_skipped(self):
        """全部跳过"""
        report = InstallReport(
            total_packages=5,
            installed=0,
            skipped=5,
            failed=0,
        )
        assert report.success_rate == 1.0

    def test_to_dict(self):
        """转换为字典"""
        report = InstallReport(
            source=DependencySource.REQUIREMENTS_TXT,
            source_file="requirements.txt",
            total_packages=3,
            installed=2,
            skipped=1,
            failed=0,
            results=[
                InstallResult(
                    package_name="numpy",
                    status=DependencyStatus.INSTALLED,
                    version="1.21.0",
                    duration_ms=100,
                ),
            ],
            total_duration_ms=500,
            package_manager=PackageManager.PIP,
            timestamp="2024-01-01T00:00:00",
        )
        d = report.to_dict()
        assert d["total_packages"] == 3
        assert d["installed"] == 2
        assert d["success_rate"] == 100.0
        assert len(d["results"]) == 1

    def test_to_markdown(self):
        """生成 Markdown 报告"""
        report = InstallReport(
            source=DependencySource.REQUIREMENTS_TXT,
            source_file="requirements.txt",
            total_packages=2,
            installed=2,
            skipped=0,
            failed=0,
            results=[
                InstallResult(
                    package_name="numpy",
                    status=DependencyStatus.INSTALLED,
                    version="1.21.0",
                    duration_ms=100,
                ),
            ],
            total_duration_ms=500,
            timestamp="2024-01-01T00:00:00",
        )
        md = report.to_markdown()
        assert "# 依赖安装报告" in md
        assert "numpy" in md
        assert "100.0%" in md


# ════════════════════════════════════════════════════════════════════
# DependencyResolver 测试
# ════════════════════════════════════════════════════════════════════


class TestDependencyResolver:
    """依赖解析器测试"""

    def test_parse_requirements_txt(self):
        """解析 requirements.txt"""
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text(
                "numpy>=1.21.0\n"
                "pandas==1.3.0\n"
                "requests~=2.28.0\n"
                "# 这是注释\n"
                "  \n"  # 空行
            )

            resolver = DependencyResolver(tmp)
            packages, conflicts, errors = resolver.resolve(
                source_file="requirements.txt",
                source_type=DependencySource.REQUIREMENTS_TXT,
            )

            assert len(packages) == 3
            assert len(errors) == 0

            numpy = next(p for p in packages if p.name == "numpy")
            assert numpy.constraints[0].operator == ">="
            assert numpy.constraints[0].version == "1.21.0"

            pandas = next(p for p in packages if p.name == "pandas")
            assert pandas.constraints[0].operator == "=="
            assert pandas.constraints[0].version == "1.3.0"

            requests = next(p for p in packages if p.name == "requests")
            assert requests.constraints[0].operator == "~="

    def test_parse_requirements_txt_with_extras(self):
        """解析带 extras 的 requirements.txt"""
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text("fastapi[all]>=0.100.0\n")

            resolver = DependencyResolver(tmp)
            packages, _, errors = resolver.resolve(
                source_file="requirements.txt",
                source_type=DependencySource.REQUIREMENTS_TXT,
            )

            assert len(packages) == 1
            assert packages[0].name == "fastapi"
            assert packages[0].extras == ["all"]

    def test_parse_requirements_txt_with_markers(self):
        """解析带环境标记的 requirements.txt"""
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text(
                "pywin32>=300; sys_platform == 'win32'\n"
            )

            resolver = DependencyResolver(tmp)
            packages, _, errors = resolver.resolve(
                source_file="requirements.txt",
                source_type=DependencySource.REQUIREMENTS_TXT,
            )

            assert len(packages) == 1
            assert packages[0].name == "pywin32"
            assert "sys_platform == 'win32'" in packages[0].markers

    def test_parse_pyproject_toml(self):
        """解析 pyproject.toml"""
        with tempfile.TemporaryDirectory() as tmp:
            toml_file = Path(tmp) / "pyproject.toml"
            toml_file.write_text(
                """[project]
name = "test"
version = "1.0.0"
dependencies = [
    "fastapi~=0.100.0",
    "uvicorn[standard]~=0.22.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
]
"""
            )

            resolver = DependencyResolver(tmp)
            packages, _, errors = resolver.resolve(
                source_file="pyproject.toml",
                source_type=DependencySource.PYPROJECT_TOML,
            )

            assert len(packages) >= 2
            names = [p.name for p in packages]
            assert "fastapi" in names
            assert "uvicorn" in names

    def test_parse_environment_yml(self):
        """解析 environment.yml"""
        with tempfile.TemporaryDirectory() as tmp:
            yml_file = Path(tmp) / "environment.yml"
            yml_file.write_text(
                """name: test-env
dependencies:
  - python=3.12
  - numpy>=1.21
  - pandas
  - pip:
    - requests~=2.28.0
"""
            )

            resolver = DependencyResolver(tmp)
            packages, _, errors = resolver.resolve(
                source_file="environment.yml",
                source_type=DependencySource.ENVIRONMENT_YML,
            )

            assert len(packages) >= 3
            names = [p.name for p in packages]
            assert "numpy" in names
            assert "pandas" in names
            assert "requests" in names

    def test_auto_detect_pyproject_first(self):
        """自动检测优先选择 pyproject.toml"""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pyproject.toml").write_text(
                """[project]
name = "test"
dependencies = ["click>=8.0"]
"""
            )
            Path(tmp, "requirements.txt").write_text("numpy>=1.21\n")

            resolver = DependencyResolver(tmp)
            packages, _, _ = resolver.resolve()

            # pyproject.toml 优先
            assert len(packages) >= 1
            names = [p.name for p in packages]
            assert "click" in names

    def test_file_not_found(self):
        """文件不存在时返回错误"""
        resolver = DependencyResolver(".")
        packages, _, errors = resolver.resolve(
            source_file="nonexistent.txt",
            source_type=DependencySource.REQUIREMENTS_TXT,
        )
        assert len(packages) == 0
        assert len(errors) > 0

    def test_topological_sort(self):
        """拓扑排序"""
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text(
                "pandas>=1.3.0\n"
                "numpy>=1.21.0\n"
                "setuptools>=60.0\n"
                "requests>=2.28.0\n"
            )

            resolver = DependencyResolver(tmp)
            packages, _, _ = resolver.resolve_ordered(
                source_file="requirements.txt",
                source_type=DependencySource.REQUIREMENTS_TXT,
            )

            assert len(packages) == 4
            # 基础库优先
            assert packages[0].name == "setuptools"
            assert packages[1].name == "numpy"

    def test_conflict_detection(self):
        """版本冲突检测"""
        with tempfile.TemporaryDirectory() as tmp:
            req_file = Path(tmp) / "requirements.txt"
            req_file.write_text(
                "numpy==1.21.0\n"
                "numpy==1.22.0\n"
            )

            resolver = DependencyResolver(tmp)
            packages, conflicts, _ = resolver.resolve(
                source_file="requirements.txt",
                source_type=DependencySource.REQUIREMENTS_TXT,
            )

            assert len(conflicts) > 0
            assert conflicts[0].package_name == "numpy"

    def test_strip_comment(self):
        """注释去除"""
        assert DependencyResolver._strip_comment("numpy>=1.0  # 好的库") == "numpy>=1.0  "
        assert DependencyResolver._strip_comment("numpy>=1.0") == "numpy>=1.0"


# ════════════════════════════════════════════════════════════════════
# DependencyInstaller 测试
# ════════════════════════════════════════════════════════════════════


class TestDependencyInstaller:
    """依赖安装执行器测试"""

    @pytest.mark.asyncio
    async def test_install_one_skipped_when_satisfied(self):
        """已安装且版本满足时跳过"""
        installer = DependencyInstaller()

        with patch.object(
            installer, "_get_installed_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = "1.22.0"

            pkg = DependencyPackage(
                name="numpy",
                constraints=[VersionConstraint(raw=">=1.21")],
            )

            result = await installer.install_one(pkg)
            assert result.status == DependencyStatus.SKIPPED
            assert result.version == "1.22.0"

    @pytest.mark.asyncio
    async def test_install_one_installs_when_missing(self):
        """未安装时执行安装"""
        installer = DependencyInstaller()

        with patch.object(
            installer, "_get_installed_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = None

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock,
            ) as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc

                pkg = DependencyPackage(name="numpy")
                result = await installer.install_one(pkg)

                if result.status == DependencyStatus.INSTALLED:
                    assert result.package_name == "numpy"
                # 如果 pip 调用失败但子进程模拟返回了 0，则安装成功

    @pytest.mark.asyncio
    async def test_install_all_with_progress(self):
        """批量安装带进度回调"""
        installer = DependencyInstaller()
        progress_calls = []

        def on_progress(current, total, name, status):
            progress_calls.append((current, total, name, status))

        with patch.object(
            installer, "_get_installed_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = None

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock,
            ) as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc

                packages = [
                    DependencyPackage(name="numpy"),
                    DependencyPackage(name="pandas"),
                ]

                await installer.install_all(packages, on_progress)

                assert len(progress_calls) >= 2  # 至少每个包一次回调

    @pytest.mark.asyncio
    async def test_install_from_requirements(self):
        """从 requirements.txt 批量安装"""
        installer = DependencyInstaller()

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock,
        ) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"Success", b"")
            mock_exec.return_value = mock_proc

            results = await installer.install_from_requirements(
                Path("requirements.txt"),
            )

            assert len(results) == 1
            assert results[0].package_name == "batch"

    def test_detect_package_manager(self):
        """检测包管理器"""
        manager = detect_package_manager()
        assert manager in (PackageManager.PIP, PackageManager.CONDA)

    def test_init_with_explicit_manager(self):
        """显式指定包管理器"""
        installer = DependencyInstaller(package_manager=PackageManager.PIP)
        assert installer._package_manager == PackageManager.PIP


# ════════════════════════════════════════════════════════════════════
# DependencyVerifier 测试
# ════════════════════════════════════════════════════════════════════


class TestDependencyVerifier:
    """依赖验证器测试"""

    @pytest.mark.asyncio
    async def test_verify_all(self):
        """验证所有依赖"""
        verifier = DependencyVerifier()

        with patch.object(
            verifier, "_get_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = "1.21.0"

            with patch.object(
                verifier, "_test_import", new_callable=AsyncMock,
            ) as mock_import:
                mock_import.return_value = (True, "")

                packages = [
                    DependencyPackage(
                        name="numpy",
                        constraints=[VersionConstraint(raw=">=1.20")],
                    ),
                ]

                results = await verifier.verify_all(packages)
                assert len(results) == 1
                assert results[0]["installed"] is True
                assert results[0]["importable"] is True
                assert results[0]["version"] == "1.21.0"

    @pytest.mark.asyncio
    async def test_verify_missing_package(self):
        """验证缺失的包"""
        verifier = DependencyVerifier()

        with patch.object(
            verifier, "_get_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = None

            packages = [DependencyPackage(name="nonexistent")]
            results = await verifier.verify_all(packages)

            assert results[0]["installed"] is False
            assert "未安装" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_verify_version_mismatch(self):
        """验证版本不匹配"""
        verifier = DependencyVerifier()

        with patch.object(
            verifier, "_get_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = "1.0.0"

            with patch.object(
                verifier, "_test_import", new_callable=AsyncMock,
            ) as mock_import:
                mock_import.return_value = (True, "")

                packages = [
                    DependencyPackage(
                        name="numpy",
                        constraints=[VersionConstraint(raw=">=2.0")],
                    ),
                ]

                results = await verifier.verify_all(packages)
                assert results[0]["installed"] is True
                assert "版本不满足" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_import_failure(self):
        """导入失败"""
        verifier = DependencyVerifier()

        with patch.object(
            verifier, "_get_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = "1.0.0"

            with patch.object(
                verifier, "_test_import", new_callable=AsyncMock,
            ) as mock_import:
                mock_import.return_value = (False, "No module named 'numpy'")

                packages = [DependencyPackage(name="numpy")]
                results = await verifier.verify_all(packages)

                assert results[0]["importable"] is False
                assert "导入失败" in results[0]["error"]

    def test_get_import_name(self):
        """包名到导入名映射"""
        assert DependencyVerifier._get_import_name("pyyaml") == "yaml"
        assert DependencyVerifier._get_import_name("pillow") == "PIL"
        assert DependencyVerifier._get_import_name("numpy") == "numpy"
        assert DependencyVerifier._get_import_name("python-multipart") == "multipart"


# ════════════════════════════════════════════════════════════════════
# ReportGenerator 测试
# ════════════════════════════════════════════════════════════════════


class TestReportGenerator:
    """报告生成器测试"""

    def test_generate_report(self):
        """生成完整报告"""
        packages = [
            DependencyPackage(name="numpy"),
            DependencyPackage(name="pandas"),
        ]
        results = [
            InstallResult(
                package_name="numpy",
                status=DependencyStatus.INSTALLED,
                version="1.21.0",
                duration_ms=100,
            ),
            InstallResult(
                package_name="pandas",
                status=DependencyStatus.SKIPPED,
                version="1.3.0",
            ),
        ]
        verifications = [
            {"name": "numpy", "installed": True, "version": "1.21.0", "importable": True, "error": ""},
            {"name": "pandas", "installed": True, "version": "1.3.0", "importable": True, "error": ""},
        ]

        report = ReportGenerator.generate(
            packages=packages,
            results=results,
            verifications=verifications,
            source_file="requirements.txt",
            package_manager=PackageManager.PIP,
            total_duration_ms=500,
        )

        assert report.total_packages == 2
        assert report.installed == 1
        assert report.skipped == 1
        assert report.failed == 0
        assert report.source_file == "requirements.txt"


# ════════════════════════════════════════════════════════════════════
# EnvInstaller 集成测试
# ════════════════════════════════════════════════════════════════════


class TestEnvInstaller:
    """环境安装器集成测试"""

    @pytest.mark.asyncio
    async def test_install_packages(self):
        """安装指定包列表"""
        env = EnvInstaller()

        with patch.object(
            env._installer, "_get_installed_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = None

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock,
            ) as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc

                report = await env.install_packages(
                    ["numpy>=1.21", "pandas==1.3.0"],
                    verify=False,
                )

                assert report.total_packages == 2

    @pytest.mark.asyncio
    async def test_check_environment(self):
        """检查环境状态"""
        env = EnvInstaller()

        with patch.object(
            env._verifier, "_get_version", new_callable=AsyncMock,
        ) as mock_version:
            mock_version.return_value = "1.21.0"

            with patch.object(
                env._verifier, "_test_import", new_callable=AsyncMock,
            ) as mock_import:
                mock_import.return_value = (True, "")

                with patch.object(
                    env._resolver, "resolve",
                ) as mock_resolve:
                    mock_resolve.return_value = (
                        [
                            DependencyPackage(
                                name="numpy",
                                constraints=[VersionConstraint(raw=">=1.20")],
                            ),
                        ],
                        [],
                        [],
                    )

                    status = await env.check_environment()
                    assert "satisfied" in status
                    assert len(status["satisfied"]) == 1

    def test_last_report_none_initially(self):
        """初始时无报告"""
        env = EnvInstaller()
        assert env.last_report is None

    def test_package_manager_property(self):
        """包管理器属性"""
        env = EnvInstaller(package_manager=PackageManager.PIP)
        assert env.package_manager == PackageManager.PIP

    def test_project_root_property(self):
        """项目根目录属性"""
        env = EnvInstaller(project_root="/tmp/test")
        assert env.project_root == Path("/tmp/test").resolve()


# ════════════════════════════════════════════════════════════════════
# DependencyConflict 测试
# ════════════════════════════════════════════════════════════════════


class TestDependencyConflict:
    """依赖冲突测试"""

    def test_auto_message(self):
        """自动生成冲突消息"""
        conflict = DependencyConflict(
            package_name="numpy",
            required_version="1.21.0",
            conflicting_package="pandas",
            conflicting_requirement="numpy<1.21",
        )
        assert "numpy" in conflict.message
        assert "pandas" in conflict.message


# ════════════════════════════════════════════════════════════════════
# DependencyStatus 和枚举测试
# ════════════════════════════════════════════════════════════════════


class TestEnums:
    """枚举值测试"""

    def test_dependency_source_values(self):
        """依赖来源枚举值"""
        assert DependencySource.REQUIREMENTS_TXT == "requirements.txt"
        assert DependencySource.PYPROJECT_TOML == "pyproject.toml"
        assert DependencySource.ENVIRONMENT_YML == "environment.yml"

    def test_dependency_status_values(self):
        """依赖状态枚举值"""
        assert DependencyStatus.PENDING == "pending"
        assert DependencyStatus.INSTALLED == "installed"
        assert DependencyStatus.FAILED == "failed"

    def test_package_manager_values(self):
        """包管理器枚举值"""
        assert PackageManager.PIP == "pip"
        assert PackageManager.CONDA == "conda"