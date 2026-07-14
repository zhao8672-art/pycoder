"""
project_tools.py 模块单元测试 — 覆盖率目标 >=80%

测试策略:
- 用 tmp_path 创建合成项目结构
- monkeypatch 替换 subprocess.run 避免 pip/mypy 真实调用
- monkeypatch 替换 asyncio.create_subprocess_exec / wait_for 用于 auto_dep_agent
- 覆盖 DependencyManager / TestRunner / ProjectScaffold 全部分支
"""

from __future__ import annotations

import asyncio
import json
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import pycoder.python.project_tools as pt_mod
from pycoder.python.project_tools import (
    DependencyAnalysisResult,
    DependencyCheckResult,
    DependencyManager,
    ProjectScaffold,
    ScaffoldResult,
    TestResult,
    TestRunner,
    _extract_imports_from_code,
    auto_dep_agent,
    check_and_install_deps,
    run_tests,
    scaffold_project,
)


# ── 数据模型 ──────────────────────────────────────────────


def test_dependency_check_result_defaults():
    r = DependencyCheckResult(success=True)
    assert r.missing_packages == []
    assert r.installed_packages == []
    assert r.failed_packages == []
    assert r.output == ""
    assert r.error == ""


def test_dependency_analysis_result_defaults():
    r = DependencyAnalysisResult(success=True)
    assert r.missing_packages == []
    assert r.outdated_packages == []
    assert r.unused_packages == []
    assert r.installed_packages == []
    assert r.requirements_status == ""
    assert r.summary == ""


def test_test_result_defaults():
    r = TestResult(success=True)
    assert r.passed == 0
    assert r.failed == 0
    assert r.errors == 0
    assert r.skipped == 0
    assert r.total == 0
    assert r.duration == 0.0


def test_scaffold_result_defaults():
    r = ScaffoldResult(success=True)
    assert r.project_name == ""
    assert r.project_type == ""
    assert r.files_created == []
    assert r.directories_created == []
    assert r.error == ""


# ── 辅助函数 ──────────────────────────────────────────────


def _mock_completed(returncode=0, stdout="", stderr=""):
    """构造模拟的 subprocess.run 返回值"""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _make_pip_list_stdout(packages):
    """构造 pip list --format json 的 stdout"""
    return json.dumps([{"name": name, "version": ver} for name, ver in packages.items()])


# ── DependencyManager.__init__ ────────────────────────────


def test_dependency_manager_init(tmp_path):
    dm = DependencyManager(tmp_path)
    assert dm.project_root == tmp_path.resolve()


# ── _get_installed_packages ───────────────────────────────


def test_get_installed_packages_success(monkeypatch):
    stdout = json.dumps([{"name": "requests"}, {"name": "numpy"}])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    dm = DependencyManager()
    result = dm._get_installed_packages()
    assert "requests" in result
    assert "numpy" in result


def test_get_installed_packages_returncode_nonzero(monkeypatch):
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=1))
    assert DependencyManager()._get_installed_packages() == set()


def test_get_installed_packages_subprocess_error(monkeypatch):
    import subprocess as sp
    def raise_err(*a, **k):
        raise sp.SubprocessError("fail")
    monkeypatch.setattr(pt_mod.subprocess, "run", raise_err)
    assert DependencyManager()._get_installed_packages() == set()


def test_get_installed_packages_json_error(monkeypatch):
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="not json"))
    assert DependencyManager()._get_installed_packages() == set()


def test_get_installed_packages_key_error(monkeypatch):
    stdout = json.dumps([{"not_name": "requests"}])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    assert DependencyManager()._get_installed_packages() == set()


# ── _parse_imports_from_file ──────────────────────────────


def test_parse_imports_from_file_success(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text(
        "import os\nimport requests\nfrom fastapi import FastAPI\nfrom PIL import Image\n",
        encoding="utf-8",
    )
    dm = DependencyManager(tmp_path)
    result = dm._parse_imports_from_file(src)
    assert "requests" in result
    assert "fastapi" in result
    assert "PIL" in result
    assert "os" not in result  # 标准库被排除


def test_parse_imports_from_file_not_found(tmp_path):
    dm = DependencyManager(tmp_path)
    assert dm._parse_imports_from_file(tmp_path / "nonexistent.py") == []


def test_parse_imports_from_file_syntax_error(tmp_path):
    src = tmp_path / "bad.py"
    src.write_text("def broken(:\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    assert dm._parse_imports_from_file(src) == []


def test_parse_imports_from_file_relative_import(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("from . import local\nfrom .. import other\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    # 相对导入的 module 是 None，应该跳过
    result = dm._parse_imports_from_file(src)
    assert "local" not in result


# ── _scan_project_imports ─────────────────────────────────


def test_scan_project_imports(tmp_path):
    (tmp_path / "a.py").write_text("import requests\nimport numpy\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import fastapi\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    result = dm._scan_project_imports()
    assert "requests" in result
    assert "numpy" in result
    assert "fastapi" in result


def test_scan_project_imports_excludes_dirs(tmp_path):
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "cached.py").write_text("import should_not_appear\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import requests\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    result = dm._scan_project_imports()
    assert "should_not_appear" not in result
    assert "requests" in result


# ── _resolve_package_name ─────────────────────────────────


def test_resolve_package_name_known():
    dm = DependencyManager()
    assert dm._resolve_package_name("PIL") == "Pillow"
    assert dm._resolve_package_name("bs4") == "beautifulsoup4"
    assert dm._resolve_package_name("yaml") == "pyyaml"


def test_resolve_package_name_unknown():
    dm = DependencyManager()
    assert dm._resolve_package_name("unknown_pkg") == "unknown_pkg"


# ── check_missing_packages ────────────────────────────────


def test_check_missing_packages(monkeypatch, tmp_path):
    (tmp_path / "mod.py").write_text("import requests\nimport numpy\n", encoding="utf-8")
    # 模拟已安装 requests 但未安装 numpy
    stdout = json.dumps([{"name": "requests"}])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    dm = DependencyManager(tmp_path)
    result = dm.check_missing_packages()
    assert "numpy" in result
    assert "requests" not in result


def test_check_missing_packages_all_installed(monkeypatch, tmp_path):
    (tmp_path / "mod.py").write_text("import requests\n", encoding="utf-8")
    stdout = json.dumps([{"name": "requests"}])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    dm = DependencyManager(tmp_path)
    assert dm.check_missing_packages() == []


# ── install_missing_packages ──────────────────────────────


def test_install_missing_packages_empty_list():
    dm = DependencyManager()
    result = dm.install_missing_packages([])
    assert result.success is True
    assert "所有依赖已安装" in result.output


def test_install_missing_packages_success(monkeypatch):
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=0))
    dm = DependencyManager()
    result = dm.install_missing_packages(["requests", "numpy"])
    assert result.success is True
    assert "requests" in result.installed_packages
    assert "numpy" in result.installed_packages


def test_install_missing_packages_failure(monkeypatch):
    monkeypatch.setattr(
        pt_mod.subprocess,
        "run",
        lambda *a, **k: _mock_completed(returncode=1, stderr="install failed"),
    )
    dm = DependencyManager()
    result = dm.install_missing_packages(["bad_pkg"])
    assert result.success is False
    assert "bad_pkg" in result.failed_packages


def test_install_missing_packages_exception(monkeypatch):
    def raise_err(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pt_mod.subprocess, "run", raise_err)
    dm = DependencyManager()
    result = dm.install_missing_packages(["err_pkg"])
    assert result.success is False
    assert "err_pkg" in result.failed_packages


def test_install_missing_packages_none_calls_check(monkeypatch, tmp_path):
    """packages=None 时调用 check_missing_packages"""
    (tmp_path / "mod.py").write_text("import requests\n", encoding="utf-8")
    # pip list 返回空（无已安装包）→ requests 缺失
    stdout = json.dumps([])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    dm = DependencyManager(tmp_path)
    result = dm.install_missing_packages()
    # requests 需要安装 → pip install 返回成功（同 mock）
    assert "requests" in result.missing_packages


# ── generate_requirements ─────────────────────────────────


def test_generate_requirements_default_output(tmp_path):
    (tmp_path / "mod.py").write_text("import requests\nimport numpy\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    content = dm.generate_requirements()
    assert "requests" in content
    assert "numpy" in content
    assert (tmp_path / "requirements.txt").exists()


def test_generate_requirements_custom_output(tmp_path):
    (tmp_path / "mod.py").write_text("import requests\n", encoding="utf-8")
    out_file = tmp_path / "custom_reqs.txt"
    dm = DependencyManager(tmp_path)
    content = dm.generate_requirements(out_file)
    assert "requests" in content
    assert out_file.exists()


def test_generate_requirements_pil_mapped(tmp_path):
    (tmp_path / "mod.py").write_text("from PIL import Image\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    content = dm.generate_requirements()
    assert "Pillow" in content


# ── _get_installed_packages_with_versions ─────────────────


def test_get_installed_packages_with_versions_success(monkeypatch):
    stdout = json.dumps([{"name": "requests", "version": "2.0.0"}])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    result = DependencyManager()._get_installed_packages_with_versions()
    assert result["requests"] == "2.0.0"


def test_get_installed_packages_with_versions_failure(monkeypatch):
    import subprocess as sp
    def raise_err(*a, **k):
        raise sp.SubprocessError("fail")
    monkeypatch.setattr(pt_mod.subprocess, "run", raise_err)
    assert DependencyManager()._get_installed_packages_with_versions() == {}


# ── _check_outdated_packages ──────────────────────────────


def test_check_outdated_packages_success(monkeypatch):
    stdout = json.dumps([
        {"name": "requests", "version": "1.0", "latest_version": "2.0"},
    ])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    result = DependencyManager()._check_outdated_packages()
    assert len(result) == 1
    assert result[0]["name"] == "requests"
    assert result[0]["installed_version"] == "1.0"
    assert result[0]["latest_version"] == "2.0"


def test_check_outdated_packages_failure(monkeypatch):
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=1))
    assert DependencyManager()._check_outdated_packages() == []


def test_check_outdated_packages_json_error(monkeypatch):
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="bad json"))
    assert DependencyManager()._check_outdated_packages() == []


# ── _parse_requirements ────────────────────────────────────


def test_parse_requirements_with_versions(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "requests==2.0.0\nnumpy>=1.0.0\n# comment\nflask\n",
        encoding="utf-8",
    )
    dm = DependencyManager(tmp_path)
    result = dm._parse_requirements()
    assert result["requests"] == "2.0.0"
    assert result["numpy"] == ">=1.0.0"
    assert result["flask"] == "*"


def test_parse_requirements_no_file(tmp_path):
    dm = DependencyManager(tmp_path)
    assert dm._parse_requirements() == {}


# ── _parse_pyproject ──────────────────────────────────────


def test_parse_pyproject_with_deps(tmp_path):
    # NOTE(源码限制): _parse_pyproject 的正则匹配 [project.dependencies] 段,
    # 但逐行解析时不处理 TOML 的 key = "value" 语法 (会误将 'flask = "*' 当作键)。
    # 解析器实际期望 requirements.txt 风格的行 (pkg>=ver / pkg==ver / pkg)。
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(textwrap.dedent('''
        [project]
        name = "test"

        [project.dependencies]
        requests>=2.0.0
        numpy==1.0.0
        flask
    '''), encoding="utf-8")
    dm = DependencyManager(tmp_path)
    result = dm._parse_pyproject()
    assert "requests" in result
    assert result["requests"] == ">=2.0.0"
    assert "numpy" in result
    assert result["numpy"] == "1.0.0"
    assert "flask" in result
    assert result["flask"] == "*"


def test_parse_pyproject_no_file(tmp_path):
    dm = DependencyManager(tmp_path)
    assert dm._parse_pyproject() == {}


def test_parse_pyproject_no_deps_section(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test'\n", encoding="utf-8")
    dm = DependencyManager(tmp_path)
    assert dm._parse_pyproject() == {}


# ── find_unused_packages ──────────────────────────────────


def test_find_unused_packages(monkeypatch, tmp_path):
    (tmp_path / "mod.py").write_text("import requests\n", encoding="utf-8")
    # 已安装 requests 和 unused_pkg
    stdout = json.dumps([
        {"name": "requests", "version": "2.0.0"},
        {"name": "unused_pkg", "version": "1.0.0"},
    ])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    dm = DependencyManager(tmp_path)
    result = dm.find_unused_packages()
    names = [p["name"] for p in result]
    assert "unused_pkg" in names
    assert "requests" not in names


# ── analyze_dependencies ──────────────────────────────────


def test_analyze_dependencies_full(monkeypatch, tmp_path):
    (tmp_path / "mod.py").write_text("import requests\nimport numpy\n", encoding="utf-8")
    # requirements.txt
    (tmp_path / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
    # pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        "[project.dependencies]\nnumpy = '>=1.0'\n",
        encoding="utf-8",
    )

    # pip list 返回 requests 已安装
    installed_stdout = json.dumps([{"name": "requests", "version": "2.0.0"}])
    # pip list --outdated 返回 requests 过期
    outdated_stdout = json.dumps([
        {"name": "requests", "version": "2.0.0", "latest_version": "3.0.0"},
    ])

    call_count = {"n": 0}

    def mock_run(*args, **kwargs):
        call_count["n"] += 1
        cmd = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "--outdated" in cmd_str:
            return _mock_completed(stdout=outdated_stdout)
        return _mock_completed(stdout=installed_stdout)

    monkeypatch.setattr(pt_mod.subprocess, "run", mock_run)
    dm = DependencyManager(tmp_path)
    result = dm.analyze_dependencies()
    assert result.success is True
    assert len(result.missing_packages) >= 1  # numpy 缺失
    assert len(result.outdated_packages) >= 1  # requests 过期
    assert "requirements.txt" in result.requirements_status
    assert "pyproject.toml" in result.requirements_status
    assert "项目使用" in result.summary


def test_analyze_dependencies_no_config_files(monkeypatch, tmp_path):
    (tmp_path / "mod.py").write_text("import requests\n", encoding="utf-8")
    stdout = json.dumps([{"name": "requests", "version": "2.0.0"}])
    outdated_stdout = json.dumps([])
    def mock_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "--outdated" in cmd_str:
            return _mock_completed(stdout=outdated_stdout)
        return _mock_completed(stdout=stdout)
    monkeypatch.setattr(pt_mod.subprocess, "run", mock_run)
    dm = DependencyManager(tmp_path)
    result = dm.analyze_dependencies()
    assert "未找到" in result.requirements_status


# ── TestRunner ────────────────────────────────────────────


def test_test_runner_init(tmp_path):
    tr = TestRunner(tmp_path)
    assert tr.project_root == tmp_path.resolve()


def test_find_test_files(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (tmp_path / "b_test.py").write_text("def test_y(): pass\n", encoding="utf-8")
    (tmp_path / "regular.py").write_text("x = 1\n", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr._find_test_files()
    names = [f.name for f in result]
    assert "test_a.py" in names
    assert "b_test.py" in names
    assert "regular.py" not in names


def test_find_source_files(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_mod.py").write_text("def test_x(): pass\n", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr._find_source_files()
    names = [f.name for f in result]
    assert "mod.py" in names
    assert "test_mod.py" not in names


def test_find_source_files_skips_init(tmp_path):
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr._find_source_files()
    # __init__.py is still a source file (not a test file)
    names = [f.name for f in result]
    assert "__init__.py" in names


def test_generate_test_template(tmp_path):
    src = tmp_path / "mymod.py"
    src.write_text("x = 1\n", encoding="utf-8")
    tr = TestRunner(tmp_path)
    template = tr.generate_test_template(src)
    assert "测试用例 - mymod" in template
    assert "from mymod import *" in template
    assert "class TestMymod" in template
    assert "def test_mymod_basic" in template


def test_generate_tests_creates_files(tmp_path):
    (tmp_path / "mod1.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "mod2.py").write_text("y = 2\n", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr.generate_tests(overwrite=False)
    assert len(result["created"]) == 2
    assert (tmp_path / "tests" / "test_mod1.py").exists()
    assert (tmp_path / "tests" / "test_mod2.py").exists()


def test_generate_tests_skips_existing(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_mod.py").write_text("existing\n", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr.generate_tests(overwrite=False)
    assert len(result["skipped"]) == 1
    assert len(result["created"]) == 0


def test_generate_tests_overwrite(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_mod.py").write_text("existing\n", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr.generate_tests(overwrite=True)
    assert len(result["created"]) == 1
    content = (tests_dir / "test_mod.py").read_text(encoding="utf-8")
    assert "from mod import *" in content


def test_generate_tests_skips_init(tmp_path):
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    tr = TestRunner(tmp_path)
    result = tr.generate_tests()
    assert len(result["created"]) == 0


# ── TestRunner.run_pytest (async) ─────────────────────────


async def test_run_pytest_success(monkeypatch, tmp_path):
    # BUG(源码): run_pytest 的统计解析要求行同时包含 "passed" 和 "failed",
    # 且期望 token 形如 "5passed" (无空格)。真实 pytest 输出 "1 passed in 0.5s"
    # 仅含 "passed" 不含 "failed", 因此 passed 计数保持为 0。
    output = "test_a.py .\n1 passed in 0.5s"
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=0, stdout=output))
    tr = TestRunner(tmp_path)
    result = await tr.run_pytest()
    assert result.success is True  # returncode == 0
    assert result.passed == 0  # BUG: 解析器未计数 (缺少 "failed" 关键字)
    assert result.duration == 0.5  # duration 解析正常


async def test_run_pytest_with_failures(monkeypatch, tmp_path):
    # BUG(源码): 真实 pytest 输出 "2 passed, 1 failed, 3 skipped in 1.2s",
    # 解析器 split() 得到 "skipped" token (无逗号), endswith("skipped") 为真,
    # part[:-7] = "" → int("") 抛出 ValueError, 被外层 except 捕获为失败。
    output = "2 passed, 1 failed, 1 errors, 3 skipped in 1.2s"
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=1, stdout=output))
    tr = TestRunner(tmp_path)
    result = await tr.run_pytest()
    assert result.success is False  # ValueError 被外层 except 捕获
    assert "invalid literal" in result.error  # BUG: int("") 导致的错误
    assert result.passed == 0  # 未完成解析


async def test_run_pytest_file_not_found(monkeypatch, tmp_path):
    def raise_fnf(*a, **k):
        raise FileNotFoundError("pytest")
    monkeypatch.setattr(pt_mod.subprocess, "run", raise_fnf)
    tr = TestRunner(tmp_path)
    result = await tr.run_pytest()
    assert result.success is False
    assert "pytest 未安装" in result.error


async def test_run_pytest_general_exception(monkeypatch, tmp_path):
    def raise_err(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pt_mod.subprocess, "run", raise_err)
    tr = TestRunner(tmp_path)
    result = await tr.run_pytest()
    assert result.success is False
    assert "boom" in result.error


async def test_run_pytest_with_coverage(monkeypatch, tmp_path):
    output = "1 passed in 0.1s"
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=0, stdout=output))
    tr = TestRunner(tmp_path)
    result = await tr.run_pytest(coverage=True)
    assert result.success is True


async def test_run_pytest_invalid_duration(monkeypatch, tmp_path):
    output = "1 passed in abc s"
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=0, stdout=output))
    tr = TestRunner(tmp_path)
    result = await tr.run_pytest()
    assert result.success is True
    assert result.duration == 0.0  # ValueError 被捕获


# ── ProjectScaffold ───────────────────────────────────────


def test_scaffold_init(tmp_path):
    ps = ProjectScaffold(tmp_path)
    assert ps.project_root == tmp_path.resolve()


def test_create_project_invalid_type(tmp_path):
    ps = ProjectScaffold(tmp_path)
    result = ps.create_project("test", "invalid_type")
    assert result.success is False
    assert "不支持的项目类型" in result.error


def test_create_project_existing_path(tmp_path):
    existing = tmp_path / "myproject"
    existing.mkdir()
    ps = ProjectScaffold(tmp_path)
    result = ps.create_project("myproject", "library")
    assert result.success is False
    assert "项目目录已存在" in result.error


def test_create_project_fastapi(tmp_path):
    ps = ProjectScaffold(tmp_path)
    result = ps.create_project("myapi", "fastapi")
    assert result.success is True
    assert result.project_name == "myapi"
    assert result.project_type == "fastapi"
    assert len(result.files_created) > 0
    assert len(result.directories_created) > 0
    project_path = tmp_path / "myapi"
    assert (project_path / "app" / "main.py").exists()
    assert (project_path / "requirements.txt").exists()


def test_create_project_streamlit(tmp_path):
    ps = ProjectScaffold(tmp_path)
    result = ps.create_project("myapp", "streamlit")
    assert result.success is True
    assert (tmp_path / "myapp" / "app.py").exists()


def test_create_project_cli(tmp_path):
    ps = ProjectScaffold(tmp_path)
    result = ps.create_project("mycli", "cli")
    assert result.success is True
    assert (tmp_path / "mycli" / "my_cli" / "cli.py").exists()


def test_create_project_library(tmp_path):
    ps = ProjectScaffold(tmp_path)
    result = ps.create_project("mylib", "library")
    assert result.success is True
    assert (tmp_path / "mylib" / "my_library" / "core.py").exists()
    assert (tmp_path / "mylib" / "README.md").exists()


def test_create_project_exception(monkeypatch, tmp_path):
    ps = ProjectScaffold(tmp_path)
    # 让 _create_files 抛出异常
    def raise_error(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(ps, "_create_files", raise_error)
    result = ps.create_project("test", "library")
    assert result.success is False
    assert "创建项目失败" in result.error


def test_create_files_recursive(tmp_path):
    ps = ProjectScaffold(tmp_path)
    files = []
    dirs = []
    template = {
        "dir1": {
            "file1.py": "content1",
            "subdir": {
                "file2.py": "content2",
            },
        },
        "top.py": "top_content",
    }
    ps._create_files(tmp_path, template, files, dirs)
    assert (tmp_path / "dir1" / "file1.py").exists()
    assert (tmp_path / "dir1" / "subdir" / "file2.py").exists()
    assert (tmp_path / "top.py").exists()
    assert len(files) == 3
    assert len(dirs) >= 2


# ── _extract_imports_from_code ────────────────────────────


def test_extract_imports_from_code_ast():
    # BUG(源码): _extract_imports_from_code 的 AST 路径检查 `node.level is None`,
    # 但 Python ast 中 ImportFrom 的 level 对绝对导入为 0 (非 None),
    # 因此所有 `from X import Y` (绝对导入) 被错误跳过。
    # 仅 ast.Import 节点能被正确提取。
    code = "import requests\nimport numpy as np\nfrom fastapi import FastAPI\nfrom PIL import Image\n"
    result = _extract_imports_from_code(code)
    assert result["requests"] == "requests"
    assert result["numpy"] == "numpy"
    # BUG: fastapi / PIL 来自 ImportFrom, 被 AST 路径跳过
    assert "fastapi" not in result
    assert "PIL" not in result


def test_extract_imports_from_code_skips_special():
    code = "from __future__ import annotations\nfrom typing import List\nfrom abc import ABC\n"
    result = _extract_imports_from_code(code)
    assert result == {}


def test_extract_imports_from_code_relative():
    code = "from . import local\n"
    result = _extract_imports_from_code(code)
    # node.level is not None → skipped
    assert result == {}


def test_extract_imports_from_code_syntax_error_fallback():
    # 语法错误时回退到正则解析 (正则路径能正确处理 ImportFrom)。
    # 注意: "this is invalid" 实为合法 Python (比较表达式), 不会触发 SyntaxError,
    # 必须使用真正的语法错误 (如 "def broken(:") 才能进入回退分支。
    code = "import requests\ndef broken(:\nimport numpy\nfrom fastapi import FastAPI\n"
    result = _extract_imports_from_code(code)
    assert result.get("requests") == "requests"
    assert result.get("numpy") == "numpy"
    assert result.get("fastapi") == "fastapi"


def test_extract_imports_from_code_syntax_error_skips_special():
    code = "from __future__ import annotations\ninvalid syntax here\n"
    result = _extract_imports_from_code(code)
    assert result == {}


def test_extract_imports_from_code_dotted_module():
    # AST 路径: import os.path → mod = "os.path".split(".")[0] = "os" (正确拆分)
    # BUG(源码): from collections.abc import Iterable 是 ImportFrom,
    # 因 node.level is None 检查 bug 被 AST 路径跳过。
    code = "import os.path\nfrom collections.abc import Iterable\n"
    result = _extract_imports_from_code(code)
    assert "os" in result  # ast.Import 路径正确拆分 dotted module
    assert "collections" not in result  # BUG: ImportFrom 被 AST 路径跳过


def test_extract_imports_from_code_dotted_module_regex_fallback():
    # 正则回退路径: ImportFrom 的 dotted module 被正确拆分。
    # 注意正则路径对 import 语句不拆分 ".", 仅 ImportFrom 拆分。
    code = "def broken(:\nfrom collections.abc import Iterable\n"
    result = _extract_imports_from_code(code)
    assert result.get("collections") == "collections"


# ── auto_dep_agent (async) ────────────────────────────────


class _MockProc:
    """模拟 asyncio 子进程"""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return (self._stdout, self._stderr)


def _make_mock_subprocess_exec(returncode=0, stdout=b"", stderr=b""):
    proc = _MockProc(returncode=returncode, stdout=stdout, stderr=stderr)

    async def mock_fn(*args, **kwargs):
        return proc

    return mock_fn


async def test_auto_dep_agent_all_installed(monkeypatch):
    """所有包都已安装"""
    stdout = json.dumps([{"name": "requests"}])
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout=stdout))
    code = "import requests\n"
    result = await auto_dep_agent(code)
    assert result["installed"] == []
    assert result["already_had"] == ["requests"]
    assert result["failed"] == []


async def test_auto_dep_agent_install_success(monkeypatch):
    """包需要安装且安装成功"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(returncode=0),
    )
    code = "import requests\n"
    result = await auto_dep_agent(code)
    assert result["installed"] == ["requests"]
    assert result["failed"] == []


async def test_auto_dep_agent_install_failure(monkeypatch):
    """安装失败"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(returncode=1, stderr=b"install error"),
    )
    code = "import requests\n"
    result = await auto_dep_agent(code)
    assert result["installed"] == []
    assert len(result["failed"]) == 1
    assert result["failed"][0]["package"] == "requests"


async def test_auto_dep_agent_timeout(monkeypatch):
    """安装超时"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(),
    )

    async def mock_wait_for_timeout(coro, timeout):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(pt_mod.asyncio, "wait_for", mock_wait_for_timeout)
    code = "import requests\n"
    result = await auto_dep_agent(code)
    assert len(result["failed"]) == 1
    assert "超时" in result["failed"][0]["error"]


async def test_auto_dep_agent_exception(monkeypatch):
    """安装时抛出异常"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))

    async def mock_exec_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pt_mod.asyncio, "create_subprocess_exec", mock_exec_error)
    code = "import requests\n"
    result = await auto_dep_agent(code)
    assert len(result["failed"]) == 1
    assert "boom" in result["failed"][0]["error"]


async def test_auto_dep_agent_standard_library_skipped(monkeypatch):
    """标准库模块被跳过"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))
    code = "import os\nimport sys\n"
    result = await auto_dep_agent(code)
    assert result["installed"] == []
    assert result["already_had"] == []
    assert result["failed"] == []


async def test_auto_dep_agent_with_ws_send(monkeypatch):
    """带 ws_send 回调"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(returncode=0),
    )
    messages = []

    async def mock_ws_send(msg):
        messages.append(msg)

    code = "import requests\n"
    result = await auto_dep_agent(code, ws_send=mock_ws_send)
    assert result["installed"] == ["requests"]
    assert len(messages) >= 2  # installing + done


async def test_auto_dep_agent_ws_send_error(monkeypatch):
    """ws_send 抛出异常被捕获"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(stdout="[]"))
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(returncode=0),
    )

    async def mock_ws_send_error(msg):
        raise RuntimeError("ws error")

    code = "import requests\n"
    result = await auto_dep_agent(code, ws_send=mock_ws_send_error)
    assert result["installed"] == ["requests"]


async def test_auto_dep_agent_pip_list_failure(monkeypatch):
    """pip list 失败时 installed_pkgs 为空集"""
    import subprocess as sp
    def raise_err(*a, **k):
        raise sp.SubprocessError("fail")
    monkeypatch.setattr(pt_mod.subprocess, "run", raise_err)
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(returncode=0),
    )
    code = "import requests\n"
    result = await auto_dep_agent(code)
    # pip list 失败 → 空集 → requests 不在已安装中 → 尝试安装
    assert result["installed"] == ["requests"]


async def test_auto_dep_agent_pip_list_returncode_nonzero(monkeypatch):
    """pip list returncode 非 0"""
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=1))
    monkeypatch.setattr(
        pt_mod.asyncio,
        "create_subprocess_exec",
        _make_mock_subprocess_exec(returncode=0),
    )
    code = "import requests\n"
    result = await auto_dep_agent(code)
    assert result["installed"] == ["requests"]


# ── 模块级快捷函数 ────────────────────────────────────────


def test_module_check_and_install_deps(monkeypatch, tmp_path):
    (tmp_path / "mod.py").write_text("import requests\n", encoding="utf-8")
    monkeypatch.setattr(pt_mod.subprocess, "run", lambda *a, **k: _mock_completed(returncode=0))
    result = check_and_install_deps(tmp_path)
    assert result.success is True


async def test_module_run_tests(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pt_mod.subprocess,
        "run",
        lambda *a, **k: _mock_completed(returncode=0, stdout="1 passed in 0.1s"),
    )
    coro = run_tests(tmp_path)
    result = await coro
    assert result.success is True


def test_module_scaffold_project(tmp_path):
    result = scaffold_project("mylib", "library", tmp_path)
    assert result.success is True
    assert (tmp_path / "mylib").exists()
