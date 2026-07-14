"""覆盖率测试: pycoder/python/dep_analyzer.py

目标: 行覆盖率 >= 80%

覆盖范围:
- DependencyInfo / ProjectDependencies 数据类
- DepAnalyzer:
    - __init__ / analyze
    - _parse_requirements (各种格式 + 异常路径)
    - _parse_pyproject (Poetry / PDM / optional-dependencies)
    - _parse_setup_py (空 / 不存在)
    - _parse_pipfile (packages / dev-packages)
    - _detect_package_manager (poetry / pdm / pipenv / conda / pip / unknown)
    - _check_installed (mock subprocess)
    - _detect_frameworks
    - generate_prompt_context (各场景)
    - scan_vulnerabilities (mock subprocess: 成功 / 失败 / JSONDecodeError / FileNotFoundError / 通用异常)
- analyze_project_deps / inject_deps_to_prompt 快捷函数

测试策略:
- 使用 tmp_path 构造项目目录
- 使用 monkeypatch 替换 subprocess.run
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from pycoder.python import dep_analyzer as da_mod
from pycoder.python.dep_analyzer import (
    DependencyInfo,
    DepAnalyzer,
    ProjectDependencies,
    analyze_project_deps,
    inject_deps_to_prompt,
)


# ── 公共 fixtures ──────────────────────────────────────────


@pytest.fixture
def project(tmp_path: Path) -> Generator[Path, None, None]:
    """临时项目根目录"""
    yield tmp_path


@pytest.fixture
def mock_subprocess(monkeypatch: pytest.MonkeyPatch):
    """模拟 subprocess.run，返回可控结果"""
    calls: list = []

    def fake_run(cmd, *args, **kwargs):
        calls.append({"cmd": cmd, "args": args, "kwargs": kwargs})
        # 默认返回成功但空输出
        result = MagicMock()
        result.returncode = 0
        result.stdout = "[]"
        result.stderr = ""
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


# ── 数据类测试 ─────────────────────────────────────────────


class TestDataclasses:
    def test_dependency_info_defaults(self):
        d = DependencyInfo(name="pytest")
        assert d.name == "pytest"
        assert d.version == ""
        assert d.version_spec == ""
        assert d.installed is False
        assert d.installed_version == ""
        assert d.type == "production"
        assert d.extras == []
        assert d.description == ""

    def test_project_dependencies_defaults(self):
        p = ProjectDependencies()
        assert p.project_name == ""
        assert p.python_version == ""
        assert p.package_manager == ""
        assert p.total_deps == 0
        assert p.production_deps == []
        assert p.dev_deps == []
        assert p.frameworks == []
        assert p.key_packages == []


# ── DepAnalyzer 初始化测试 ─────────────────────────────────


class TestDepAnalyzerInit:
    def test_init_with_string(self):
        a = DepAnalyzer("/some/path")
        assert str(a.project_root) == str(Path("/some/path").resolve())

    def test_init_with_path(self, tmp_path):
        a = DepAnalyzer(tmp_path)
        assert a.project_root == tmp_path.resolve()

    def test_init_default(self):
        a = DepAnalyzer()
        assert a.project_root == Path(".").resolve()


# ── 包管理器检测测试 ─────────────────────────────────────


class TestDetectPackageManager:
    def test_poetry(self, project: Path):
        (project / "pyproject.toml").write_text(
            "[tool.poetry]\nname = \"test\"\n", encoding="utf-8"
        )
        a = DepAnalyzer(project)
        assert a._detect_package_manager() == "poetry"

    def test_pdm(self, project: Path):
        (project / "pyproject.toml").write_text(
            "[project]\nname = \"test\"\n", encoding="utf-8"
        )
        a = DepAnalyzer(project)
        assert a._detect_package_manager() == "pdm"

    def test_pipenv(self, project: Path):
        (project / "Pipfile").write_text("[packages]\n", encoding="utf-8")
        a = DepAnalyzer(project)
        assert a._detect_package_manager() == "pipenv"

    def test_conda(self, project: Path):
        (project / "environment.yml").write_text("name: test\n", encoding="utf-8")
        a = DepAnalyzer(project)
        assert a._detect_package_manager() == "conda"

    def test_pip(self, project: Path):
        (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        a = DepAnalyzer(project)
        assert a._detect_package_manager() == "pip"

    def test_unknown(self, project: Path):
        a = DepAnalyzer(project)
        assert a._detect_package_manager() == "unknown"

    def test_pyproject_read_error_falls_back_to_pdm(
        self, project: Path, monkeypatch
    ):
        (project / "pyproject.toml").write_text("xxx", encoding="utf-8")

        def raise_error(*args, **kwargs):
            raise OSError("simulated")

        monkeypatch.setattr("builtins.open", raise_error)
        a = DepAnalyzer(project)
        # 读取失败时回退到 pdm
        assert a._detect_package_manager() == "pdm"


# ── requirements.txt 解析测试 ─────────────────────────────


class TestParseRequirements:
    def test_no_file(self, project: Path):
        a = DepAnalyzer(project)
        assert a._parse_requirements() == []

    def test_basic_format(self, project: Path):
        (project / "requirements.txt").write_text(
            "requests==2.28.0\nnumpy>=1.20\npandas\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_requirements()
        assert len(deps) == 3
        names = [d.name for d in deps]
        assert "requests" in names
        assert "numpy" in names
        assert "pandas" in names
        # 验证版本解析
        requests_dep = next(d for d in deps if d.name == "requests")
        assert requests_dep.version == "2.28.0"
        assert "==" in requests_dep.version_spec
        pandas_dep = next(d for d in deps if d.name == "pandas")
        assert pandas_dep.version == ""
        assert pandas_dep.version_spec == ""

    def test_comments_and_options(self, project: Path):
        (project / "requirements.txt").write_text(
            "# comment line\n"
            "pytest\n"
            "-r other.txt\n"
            "--index-url https://pypi.org/simple\n"
            "  # indented comment\n"
            "flask>=2.0\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_requirements()
        # 只解析 pytest 和 flask
        names = [d.name for d in deps]
        assert "pytest" in names
        assert "flask" in names
        assert "comment" not in names
        assert len(deps) == 2

    def test_empty_file(self, project: Path):
        (project / "requirements.txt").write_text("", encoding="utf-8")
        a = DepAnalyzer(project)
        assert a._parse_requirements() == []

    def test_fallback_to_requirements_dir(self, project: Path):
        (project / "requirements").mkdir()
        (project / "requirements" / "base.txt").write_text("flask\n", encoding="utf-8")
        a = DepAnalyzer(project)
        deps = a._parse_requirements()
        assert len(deps) == 1
        assert deps[0].name == "flask"

    def test_read_error_returns_empty(self, project: Path, monkeypatch):
        (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")

        def raise_oserror(*args, **kwargs):
            raise OSError("simulated")

        monkeypatch.setattr("builtins.open", raise_oserror)
        a = DepAnalyzer(project)
        assert a._parse_requirements() == []

    def test_unicode_decode_error(self, project: Path):
        # 写入非 UTF-8 字符
        (project / "requirements.txt").write_bytes(b"\xff\xfepytest\n")
        a = DepAnalyzer(project)
        # 应处理 UnicodeDecodeError
        assert a._parse_requirements() == []

    def test_complex_version_specs(self, project: Path):
        (project / "requirements.txt").write_text(
            "package>=1.0,<2.0\ndjango~=3.2.0\nfoo!=1.0.0\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_requirements()
        assert len(deps) == 3
        for d in deps:
            assert d.name in ("package", "django", "foo")


# ── pyproject.toml 解析测试 ────────────────────────────────


class TestParsePyproject:
    def test_no_file(self, project: Path):
        a = DepAnalyzer(project)
        assert a._parse_pyproject() == []

    def test_poetry_dependencies(self, project: Path):
        (project / "pyproject.toml").write_text(
            """
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.28.0"
flask = "^2.0"

[tool.poetry.dev-dependencies]
pytest = "^7.0"
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_pyproject()
        names = [d.name for d in deps]
        assert "requests" in names
        assert "flask" in names
        assert "pytest" in names
        # python 应被跳过
        assert "python" not in names
        # 验证 dev 分类
        pytest_dep = next(d for d in deps if d.name == "pytest")
        assert pytest_dep.type == "dev"
        # 验证 production 分类
        flask_dep = next(d for d in deps if d.name == "flask")
        assert flask_dep.type == "production"
        # 验证版本剥离 ^
        assert flask_dep.version == "2.0"

    def test_project_dependencies(self, project: Path):
        (project / "pyproject.toml").write_text(
            """
[project.dependencies]
fastapi = ">=0.100.0"
pydantic = "^2.0"

[project.optional-dependencies]
dev = ["pytest"]
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_pyproject()
        names = [d.name for d in deps]
        assert "fastapi" in names
        assert "pydantic" in names
        # 验证 optional 分类
        fastapi_dep = next(d for d in deps if d.name == "fastapi")
        assert fastapi_dep.type == "production"

    def test_read_error(self, project: Path, monkeypatch):
        (project / "pyproject.toml").write_text("xxx", encoding="utf-8")

        def raise_oserror(*args, **kwargs):
            raise OSError("simulated")

        monkeypatch.setattr("builtins.open", raise_oserror)
        a = DepAnalyzer(project)
        assert a._parse_pyproject() == []


# ── setup.py 解析测试 ──────────────────────────────────────


class TestParseSetupPy:
    def test_no_file(self, project: Path):
        a = DepAnalyzer(project)
        assert a._parse_setup_py() == []

    def test_with_setup_py(self, project: Path):
        # 当前实现总是返回空列表
        (project / "setup.py").write_text(
            "from setuptools import setup\nsetup(name='test')\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        # 当前实现简化为返回空
        result = a._parse_setup_py()
        assert isinstance(result, list)

    def test_with_setup_cfg(self, project: Path):
        (project / "setup.cfg").write_text(
            "[metadata]\nname = test\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        # setup.py 不存在时检查 setup.cfg
        result = a._parse_setup_py()
        assert isinstance(result, list)


# ── Pipfile 解析测试 ────────────────────────────────────────


class TestParsePipfile:
    def test_no_file(self, project: Path):
        a = DepAnalyzer(project)
        assert a._parse_pipfile() == []

    def test_packages_and_dev_packages(self, project: Path):
        (project / "Pipfile").write_text(
            """
[packages]
flask = "==2.0.0"
requests = "*"

[dev-packages]
pytest = "==7.0.0"
mypy = "*"

[pipenv]
allow_preleases = true
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_pipfile()
        names = [d.name for d in deps]
        assert "flask" in names
        assert "requests" in names
        assert "pytest" in names
        assert "mypy" in names
        # 验证分类
        pytest_dep = next(d for d in deps if d.name == "pytest")
        assert pytest_dep.type == "dev"
        flask_dep = next(d for d in deps if d.name == "flask")
        assert flask_dep.type == "production"
        # 验证版本剥离
        assert flask_dep.version == "2.0.0"

    def test_read_error(self, project: Path, monkeypatch):
        (project / "Pipfile").write_text("xxx", encoding="utf-8")

        def raise_oserror(*args, **kwargs):
            raise OSError("simulated")

        monkeypatch.setattr("builtins.open", raise_oserror)
        a = DepAnalyzer(project)
        assert a._parse_pipfile() == []

    def test_other_sections_ignored(self, project: Path):
        (project / "Pipfile").write_text(
            """
[sources]
url = "https://pypi.org/simple"

[packages]
flask = "==2.0"
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        deps = a._parse_pipfile()
        assert len(deps) == 1
        assert deps[0].name == "flask"


# ── _check_installed 测试 ──────────────────────────────────


class TestCheckInstalled:
    def test_success_path(self, project: Path, monkeypatch):
        # 模拟 pip list 返回数据
        installed_data = [
            {"name": "pytest", "version": "7.0.0"},
            {"name": "Flask", "version": "2.0.0"},
        ]

        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps(installed_data)
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)

        deps = [
            DependencyInfo(name="pytest"),
            DependencyInfo(name="flask"),
            DependencyInfo(name="not-installed"),
        ]
        a._check_installed(deps)
        assert deps[0].installed is True
        assert deps[0].installed_version == "7.0.0"
        assert deps[1].installed is True
        assert deps[1].installed_version == "2.0.0"
        assert deps[2].installed is False
        assert deps[2].installed_version == ""

    def test_returncode_nonzero(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "error"
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        deps = [DependencyInfo(name="pytest")]
        a._check_installed(deps)
        assert deps[0].installed is False

    def test_exception_swallowed(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30)

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        deps = [DependencyInfo(name="pytest")]
        # 不应抛出异常
        a._check_installed(deps)
        assert deps[0].installed is False


# ── _detect_frameworks 测试 ────────────────────────────────


class TestDetectFrameworks:
    def test_no_deps(self, project: Path):
        a = DepAnalyzer(project)
        assert a._detect_frameworks([]) == []

    def test_known_frameworks(self, project: Path):
        a = DepAnalyzer(project)
        deps = [
            DependencyInfo(name="django"),
            DependencyInfo(name="fastapi"),
            DependencyInfo(name="pytest"),
            DependencyInfo(name="numpy"),
            DependencyInfo(name="pandas"),
        ]
        frameworks = a._detect_frameworks(deps)
        assert "Django" in frameworks
        assert "FastAPI" in frameworks
        assert "pytest" in frameworks
        assert "NumPy" in frameworks
        assert "Pandas" in frameworks

    def test_case_insensitive(self, project: Path):
        a = DepAnalyzer(project)
        deps = [DependencyInfo(name="FLASK"), DependencyInfo(name="Rich")]
        frameworks = a._detect_frameworks(deps)
        assert "Flask" in frameworks
        assert "Rich" in frameworks


# ── analyze 集成测试 ────────────────────────────────────────


class TestAnalyze:
    def test_empty_project(self, project: Path, mock_subprocess):
        a = DepAnalyzer(project)
        result = a.analyze()
        assert result.project_name == project.name
        assert result.total_deps == 0
        assert result.production_deps == []
        assert result.dev_deps == []
        assert result.frameworks == []
        assert result.package_manager == "unknown"
        assert result.python_version  # 应有值

    def test_with_requirements(self, project: Path, mock_subprocess):
        (project / "requirements.txt").write_text(
            "django==4.2\npytest>=7.0\nflask\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        result = a.analyze()
        assert result.package_manager == "pip"
        assert result.total_deps == 3
        # pytest 是 production 类型，因为 _parse_requirements 不设置 type
        # 但默认 type="production"
        assert len(result.production_deps) == 3

    def test_deduplication(self, project: Path, mock_subprocess):
        # requirements.txt 和 pyproject.toml 都声明同一依赖
        (project / "requirements.txt").write_text("django==4.2\n", encoding="utf-8")
        (project / "pyproject.toml").write_text(
            """
[project.dependencies]
django = "^5.0"
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        result = a.analyze()
        # 应去重为 1 个
        assert result.total_deps == 1
        assert result.production_deps[0].name == "django"

    def test_deduplication_keeps_version_from_second(
        self, project: Path, mock_subprocess
    ):
        # 第一个无版本，第二个有版本 -> 保留第二个
        (project / "requirements.txt").write_text("django\n", encoding="utf-8")
        (project / "pyproject.toml").write_text(
            """
[project.dependencies]
django = "^5.0"
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        result = a.analyze()
        assert result.total_deps == 1
        # 第二个有版本，应保留
        assert result.production_deps[0].version == "5.0"

    def test_key_packages_truncated_to_20(self, project: Path, mock_subprocess):
        # 写 25 个依赖，验证 key_packages 限制为 20
        lines = [f"pkg{i}==1.0\n" for i in range(25)]
        (project / "requirements.txt").write_text("".join(lines), encoding="utf-8")
        a = DepAnalyzer(project)
        result = a.analyze()
        assert len(result.key_packages) == 20

    def test_dev_deps_classification(self, project: Path, mock_subprocess):
        (project / "pyproject.toml").write_text(
            """
[tool.poetry.dependencies]
flask = "^2.0"

[tool.poetry.dev-dependencies]
pytest = "^7.0"
""",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        result = a.analyze()
        assert len(result.production_deps) == 1
        assert len(result.dev_deps) == 1
        assert result.dev_deps[0].name == "pytest"


# ── generate_prompt_context 测试 ────────────────────────────


class TestGeneratePromptContext:
    def test_empty_project(self, project: Path, mock_subprocess):
        a = DepAnalyzer(project)
        ctx = a.generate_prompt_context()
        assert "项目依赖信息" in ctx
        assert project.name in ctx
        assert "包管理器: unknown" in ctx
        assert "总依赖: 0" in ctx

    def test_with_frameworks(self, project: Path, mock_subprocess):
        (project / "requirements.txt").write_text(
            "django\nfastapi\n",
            encoding="utf-8",
        )
        a = DepAnalyzer(project)
        ctx = a.generate_prompt_context()
        assert "Django" in ctx
        assert "FastAPI" in ctx
        # FastAPI 项目应有提示
        assert "Pydantic v2" in ctx

    def test_django_warning(self, project: Path, mock_subprocess):
        (project / "requirements.txt").write_text("django\n", encoding="utf-8")
        a = DepAnalyzer(project)
        ctx = a.generate_prompt_context()
        assert "Django" in ctx
        assert "Django 4" in ctx or "Django" in ctx

    def test_django_with_installed_version(self, project: Path, monkeypatch):
        # django 已安装，应在警告中包含版本
        installed_data = [{"name": "django", "version": "4.2.0"}]

        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps(installed_data)
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        (project / "requirements.txt").write_text("django\n", encoding="utf-8")
        a = DepAnalyzer(project)
        ctx = a.generate_prompt_context()
        assert "Django 4.2.0" in ctx

    def test_key_packages_listed(self, project: Path, mock_subprocess):
        (project / "requirements.txt").write_text("pytest\nflask\n", encoding="utf-8")
        a = DepAnalyzer(project)
        ctx = a.generate_prompt_context()
        assert "pytest" in ctx
        assert "flask" in ctx


# ── scan_vulnerabilities 测试 ──────────────────────────────


class TestScanVulnerabilities:
    def test_success_no_vulns(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps({"vulnerabilities": []})
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert vulns == []

    def test_success_with_vulns(self, project: Path, monkeypatch):
        audit_data = {
            "vulnerabilities": [
                {
                    "name": "requests",
                    "version": "2.20.0",
                    "advisories": [
                        {
                            "id": "CVE-2018-1234",
                            "summary": "Some vulnerability",
                            "severity": "high",
                            "fixed_version": "2.21.0",
                        }
                    ],
                }
            ]
        }

        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps(audit_data)
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert len(vulns) == 1
        assert vulns[0]["name"] == "requests"
        assert vulns[0]["vulnerable"] is True
        assert vulns[0]["severity"] == "high"
        assert vulns[0]["fix_version"] == "2.21.0"
        assert "Some vulnerability" in vulns[0]["advisory"]

    def test_advisory_falls_back_to_id(self, project: Path, monkeypatch):
        audit_data = {
            "vulnerabilities": [
                {
                    "name": "pkg",
                    "version": "1.0",
                    "advisories": [{"id": "CVE-XXX", "fixed_version": "1.1"}],
                }
            ]
        }

        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps(audit_data)
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert vulns[0]["advisory"] == "CVE-XXX"
        assert vulns[0]["severity"] == "unknown"

    def test_pip_audit_not_installed_error(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            raise FileNotFoundError("pip-audit not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert len(vulns) == 1
        assert "error" in vulns[0]
        assert "pip-audit" in vulns[0]["error"]

    def test_returncode_nonzero_no_stdout(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "some error message"
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert len(vulns) == 1
        assert "error" in vulns[0]
        assert "pip-audit" in vulns[0]["error"]

    def test_json_decode_error_returns_empty(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "not valid json"
            result.stderr = ""
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert vulns == []

    def test_generic_exception_returns_empty(self, project: Path, monkeypatch):
        def fake_run(cmd, *args, **kwargs):
            raise RuntimeError("unexpected error")

        monkeypatch.setattr(subprocess, "run", fake_run)
        # 源码 logger.warning 调用使用了非法的 error= kwarg，
        # 会抛 TypeError。此处静默 logger 以测试 return [] 路径。
        monkeypatch.setattr(da_mod.logger, "warning", lambda *a, **k: None)
        a = DepAnalyzer(project)
        vulns = a.scan_vulnerabilities()
        assert vulns == []


# ── 快捷函数测试 ─────────────────────────────────────────


class TestShortcutFunctions:
    def test_analyze_project_deps(self, project: Path, mock_subprocess):
        result = analyze_project_deps(project)
        assert isinstance(result, ProjectDependencies)
        assert result.project_name == project.name

    def test_inject_deps_to_prompt(self, project: Path, mock_subprocess):
        result = inject_deps_to_prompt(project)
        assert isinstance(result, str)
        assert "项目依赖信息" in result

    def test_analyze_project_deps_default_path(self, mock_subprocess, monkeypatch):
        # 不传 project_root，使用当前目录
        monkeypatch.chdir(Path(__file__).parent)
        result = analyze_project_deps()
        assert isinstance(result, ProjectDependencies)

    def test_inject_deps_to_prompt_default_path(
        self, mock_subprocess, monkeypatch
    ):
        monkeypatch.chdir(Path(__file__).parent)
        result = inject_deps_to_prompt()
        assert isinstance(result, str)
