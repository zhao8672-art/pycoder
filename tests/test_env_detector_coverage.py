"""
env_detector.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- EnvironmentInfo 数据类默认值
- detect_environment: 各种环境变量分支 + 项目结构 + git 信息
- _detect_venv: VIRTUAL_ENV / CONDA / POETRY / .venv / venv / system
- _detect_package_manager: poetry.lock / Pipfile.lock / pdm.lock / uv.lock / requirements.txt / unknown
- _detect_project_type: web / data_science / library / script (mock importlib.metadata)
- _has_ipynb_files: 有/无文件 + 异常路径
- _analyze_project_structure: 各种文件类型统计
- _analyze_git_info: 各种 git 命令成功/失败 + 无 .git 目录
- analyze_dependencies / check_outdated: mock subprocess
- print_env_info: 各种分支
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python import env_detector as ed_mod
from pycoder.python.env_detector import (
    EnvironmentInfo,
    detect_environment,
    _detect_venv,
    _detect_package_manager,
    _detect_project_type,
    _has_ipynb_files,
    _analyze_project_structure,
    _analyze_git_info,
    analyze_dependencies,
    check_outdated,
    print_env_info,
)


# ── EnvironmentInfo 数据类 ──────────────────────────────────


class TestEnvironmentInfo:
    def test_defaults(self):
        info = EnvironmentInfo()
        assert info.python_version == ""
        assert info.venv_type == "none"
        assert info.venv_path is None
        assert info.package_manager == "pip"
        assert info.project_type == "unknown"
        assert info.frameworks == []
        assert info.has_requirements is False
        assert info.has_pyproject is False
        assert info.has_setup is False
        assert info.has_jupyter is False
        assert info.dependencies == []
        assert info.direct_deps == []
        assert info.dev_deps == []
        assert info.outdated_packages == []
        assert info.project_structure == {}
        assert info.git_info == {}


# ── _detect_venv ────────────────────────────────────────────


class TestDetectVenv:
    def test_virtual_env(self, monkeypatch):
        info = EnvironmentInfo()
        monkeypatch.setattr(ed_mod.os, "environ", {"VIRTUAL_ENV": "/path/to/venv"})
        _detect_venv(info)
        assert info.venv_type == "venv"
        assert info.venv_path == "/path/to/venv"

    def test_conda(self, monkeypatch):
        info = EnvironmentInfo()
        monkeypatch.setattr(ed_mod.os, "environ", {"CONDA_DEFAULT_ENV": "myenv"})
        _detect_venv(info)
        assert info.venv_type == "conda"
        assert info.venv_path == "myenv"

    def test_poetry(self, monkeypatch):
        info = EnvironmentInfo()
        monkeypatch.setattr(ed_mod.os, "environ", {"POETRY_ACTIVE": "1"})
        _detect_venv(info)
        assert info.venv_type == "poetry"

    def test_dot_venv_in_cwd(self, monkeypatch, tmp_path):
        info = EnvironmentInfo()
        monkeypatch.setattr(ed_mod.os, "environ", {})
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".venv").mkdir()
        _detect_venv(info)
        assert info.venv_type == "venv"
        assert ".venv" in info.venv_path

    def test_venv_in_cwd(self, monkeypatch, tmp_path):
        info = EnvironmentInfo()
        monkeypatch.setattr(ed_mod.os, "environ", {})
        monkeypatch.chdir(tmp_path)
        (tmp_path / "venv").mkdir()
        _detect_venv(info)
        assert info.venv_type == "venv"
        assert "venv" in info.venv_path

    def test_system_when_no_venv(self, monkeypatch, tmp_path):
        info = EnvironmentInfo()
        monkeypatch.setattr(ed_mod.os, "environ", {})
        monkeypatch.chdir(tmp_path)
        _detect_venv(info)
        assert info.venv_type == "none"


# ── _detect_package_manager ────────────────────────────────


class TestDetectPackageManager:
    def test_poetry_lock(self, tmp_path):
        info = EnvironmentInfo()
        (tmp_path / "poetry.lock").write_text("", encoding="utf-8")
        _detect_package_manager(info, tmp_path)
        assert info.package_manager == "poetry"

    def test_pipfile_lock(self, tmp_path):
        info = EnvironmentInfo()
        (tmp_path / "Pipfile.lock").write_text("", encoding="utf-8")
        _detect_package_manager(info, tmp_path)
        assert info.package_manager == "pipenv"

    def test_pdm_lock(self, tmp_path):
        info = EnvironmentInfo()
        (tmp_path / "pdm.lock").write_text("", encoding="utf-8")
        _detect_package_manager(info, tmp_path)
        assert info.package_manager == "pdm"

    def test_uv_lock(self, tmp_path):
        info = EnvironmentInfo()
        (tmp_path / "uv.lock").write_text("", encoding="utf-8")
        _detect_package_manager(info, tmp_path)
        assert info.package_manager == "uv"

    def test_requirements_txt(self, tmp_path):
        info = EnvironmentInfo()
        (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        _detect_package_manager(info, tmp_path)
        assert info.package_manager == "pip"
        assert info.has_requirements is True

    def test_unknown(self, tmp_path):
        info = EnvironmentInfo()
        _detect_package_manager(info, tmp_path)
        # 默认值为 pip (因为 EnvironmentInfo 默认 package_manager="pip")
        assert info.package_manager == "pip"
        assert info.has_requirements is False


# ── _detect_project_type ───────────────────────────────────


class TestDetectProjectType:
    def test_with_pyproject(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        # mock importlib.metadata 返回空集合
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [],
        )
        _detect_project_type(info, tmp_path)
        assert info.has_pyproject is True
        assert info.has_setup is False
        # 没有框架匹配 -> library
        assert info.project_type == "library"

    def test_with_setup(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        (tmp_path / "setup.py").write_text("", encoding="utf-8")
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [],
        )
        _detect_project_type(info, tmp_path)
        assert info.has_setup is True
        assert info.project_type == "library"

    def test_with_setup_cfg(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        (tmp_path / "setup.cfg").write_text("[metadata]\n", encoding="utf-8")
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [],
        )
        _detect_project_type(info, tmp_path)
        assert info.has_setup is True

    def test_web_project_fastapi(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        # mock 一个 FastAPI 包
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": "fastapi"}
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [mock_dist],
        )
        _detect_project_type(info, tmp_path)
        assert "FastAPI" in info.frameworks
        assert info.project_type == "web"

    def test_web_project_django(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": "django"}
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [mock_dist],
        )
        _detect_project_type(info, tmp_path)
        assert "Django" in info.frameworks
        assert info.project_type == "web"

    def test_data_science_pandas(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": "pandas"}
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [mock_dist],
        )
        _detect_project_type(info, tmp_path)
        assert "pandas" in info.frameworks
        assert info.project_type == "data_science"

    def test_data_science_pytorch(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": "torch"}
        # framework_map 中 key 为 "pytorch"
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [mock_dist],
        )
        _detect_project_type(info, tmp_path)
        assert info.project_type == "data_science"

    def test_script_project_type(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        # 没有 pyproject / setup, 没有框架 -> script
        monkeypatch.setattr(
            "importlib.metadata.distributions",
            lambda: [],
        )
        _detect_project_type(info, tmp_path)
        assert info.project_type == "script"

    def test_importlib_exception(self, tmp_path, monkeypatch):
        info = EnvironmentInfo()
        # mock distributions 抛异常
        def raise_error():
            raise RuntimeError("fail")

        monkeypatch.setattr("importlib.metadata.distributions", raise_error)
        _detect_project_type(info, tmp_path)
        # 异常被捕获, project_type 保持默认 "unknown"
        assert info.project_type == "unknown"


# ── _has_ipynb_files ────────────────────────────────────────


class TestHasIpynbFiles:
    def test_with_ipynb(self, tmp_path):
        (tmp_path / "test.ipynb").write_text("{}", encoding="utf-8")
        assert _has_ipynb_files(tmp_path) is True

    def test_without_ipynb(self, tmp_path):
        (tmp_path / "test.py").write_text("x=1", encoding="utf-8")
        assert _has_ipynb_files(tmp_path) is False

    def test_permission_error(self, tmp_path, monkeypatch):
        # 让 rglob 抛 PermissionError
        def raise_error(*args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "rglob", raise_error)
        assert _has_ipynb_files(tmp_path) is False

    def test_os_error(self, tmp_path, monkeypatch):
        def raise_error(*args, **kwargs):
            raise OSError("fail")

        monkeypatch.setattr(Path, "rglob", raise_error)
        assert _has_ipynb_files(tmp_path) is False


# ── _analyze_project_structure ──────────────────────────────


class TestAnalyzeProjectStructure:
    def test_empty_dir(self, tmp_path):
        result = _analyze_project_structure(tmp_path)
        assert result["total_files"] == 0
        assert result["total_dirs"] == 0
        assert result["python_files"] == 0
        assert result["max_depth"] == 0

    def test_with_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
        (tmp_path / "b.py").write_text("x=2", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert result["python_files"] == 2
        assert result["total_files"] == 2

    def test_with_test_files(self, tmp_path):
        (tmp_path / "test_a.py").write_text("x=1", encoding="utf-8")
        (tmp_path / "b_test.py").write_text("x=2", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert result["test_files"] == 2

    def test_with_ipynb_files(self, tmp_path):
        (tmp_path / "a.ipynb").write_text("{}", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert result["notebook_files"] == 1

    def test_with_config_files(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        (tmp_path / "Dockerfile").write_text("", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert result["config_files"] >= 2

    def test_with_subdirectory(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "a.py").write_text("x=1", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert result["total_dirs"] == 1
        assert result["max_depth"] == 1
        assert "subdir" in result["top_dirs"]

    def test_with_package_dir(self, tmp_path):
        # __init__.py 在子目录 -> package_dir
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert "mypkg" in result["package_dirs"]

    def test_skip_venv_dir(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "x.py").write_text("x=1", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        # .venv 应被跳过
        assert result["python_files"] == 0

    def test_skip_pycache_dir(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "x.pyc").write_text("", encoding="utf-8")
        result = _analyze_project_structure(tmp_path)
        assert result["total_files"] == 0

    def test_exception_returns_partial(self, tmp_path, monkeypatch):
        # 让 os.walk 抛异常
        def raise_error(*args, **kwargs):
            raise RuntimeError("fail")

        monkeypatch.setattr(ed_mod.os, "walk", raise_error)
        result = _analyze_project_structure(tmp_path)
        # 异常被捕获, 返回空结构
        assert result["total_files"] == 0


# ── _analyze_git_info ───────────────────────────────────────


class TestAnalyzeGitInfo:
    def test_no_git_dir(self, tmp_path):
        result = _analyze_git_info(tmp_path)
        assert result["is_repo"] is False
        assert result["branch"] == ""
        assert result["remotes"] == []

    def test_with_git_dir_success(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        # mock subprocess.run 返回各种 git 输出
        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if "rev-parse" in cmd:
                result.stdout = "main\n"
            elif "remote" in cmd:
                result.stdout = "origin\thttps://github.com/x/y.git (fetch)\n"
            elif "log" in cmd:
                result.stdout = "abc1234 Initial commit (1 day ago)\n"
            else:
                result.stdout = ""
            return result

        monkeypatch.setattr(ed_mod.subprocess, "run", fake_run)
        result = _analyze_git_info(tmp_path)
        assert result["is_repo"] is True
        assert result["branch"] == "main"
        assert "https://github.com/x/y.git" in result["remotes"]
        assert "Initial commit" in result["last_commit"]

    def test_git_command_failure(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        # returncode != 0 -> 字段为空
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(ed_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = _analyze_git_info(tmp_path)
        assert result["is_repo"] is True
        assert result["branch"] == ""
        assert result["remotes"] == []

    def test_git_remote_no_fetch(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        def fake_run(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if "remote" in cmd:
                # 只有 push, 没 fetch
                result.stdout = "origin\thttps://github.com/x/y.git (push)\n"
            else:
                result.stdout = ""
            return result

        monkeypatch.setattr(ed_mod.subprocess, "run", fake_run)
        result = _analyze_git_info(tmp_path)
        # 只有 push 的 remote 不应被加入 (代码检查 "(fetch)")
        assert result["remotes"] == []

    def test_git_exception(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        def raise_error(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(ed_mod.subprocess, "run", raise_error)
        result = _analyze_git_info(tmp_path)
        # 异常被捕获, 返回基本结构
        assert result["is_repo"] is True


# ── detect_environment 集成 ────────────────────────────────


class TestDetectEnvironment:
    def test_default_path(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        # mock importlib.metadata 防止检测真实环境
        monkeypatch.setattr("importlib.metadata.distributions", lambda: [])
        info = detect_environment()
        assert info.python_version
        assert info.project_structure != {}

    def test_with_project_path(self, monkeypatch, tmp_path):
        (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        monkeypatch.setattr("importlib.metadata.distributions", lambda: [])
        info = detect_environment(str(tmp_path))
        assert info.has_requirements is True
        assert info.package_manager == "pip"


# ── analyze_dependencies ────────────────────────────────────


class TestAnalyzeDependencies:
    def test_returns_list(self, monkeypatch, tmp_path):
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": "pytest"}
        mock_dist.version = "7.0.0"
        monkeypatch.setattr("importlib.metadata.distributions", lambda: [mock_dist])
        result = analyze_dependencies(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "pytest"
        assert result[0]["version"] == "7.0.0"
        assert result[0]["kind"] == "direct"

    def test_skips_empty_name(self, monkeypatch, tmp_path):
        mock_dist = MagicMock()
        mock_dist.metadata = {"Name": ""}
        mock_dist.version = "1.0.0"
        monkeypatch.setattr("importlib.metadata.distributions", lambda: [mock_dist])
        result = analyze_dependencies(tmp_path)
        assert result == []

    def test_exception_returns_empty(self, monkeypatch, tmp_path):
        def raise_error():
            raise RuntimeError("fail")

        monkeypatch.setattr("importlib.metadata.distributions", raise_error)
        result = analyze_dependencies(tmp_path)
        assert result == []

    def test_default_path(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("importlib.metadata.distributions", lambda: [])
        result = analyze_dependencies()
        assert result == []


# ── check_outdated ──────────────────────────────────────────


class TestCheckOutdated:
    def test_success(self, monkeypatch):
        outdated_data = [{"name": "pytest", "version": "7.0", "latest_version": "7.1"}]
        mock_result = MagicMock(returncode=0, stdout=json.dumps(outdated_data), stderr="")
        monkeypatch.setattr(ed_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = check_outdated()
        assert len(result) == 1
        assert result[0]["name"] == "pytest"

    def test_failure_returncode(self, monkeypatch):
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(ed_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = check_outdated()
        assert result == []

    def test_exception(self, monkeypatch):
        def raise_error(*a, **k):
            raise FileNotFoundError("pip not found")

        monkeypatch.setattr(ed_mod.subprocess, "run", raise_error)
        result = check_outdated()
        assert result == []


# ── print_env_info ──────────────────────────────────────────


class TestPrintEnvInfo:
    def test_minimal_info(self):
        info = EnvironmentInfo(python_version="3.14.0")
        result = print_env_info(info)
        assert "Python 3.14.0" in result
        assert "包管理器" in result
        assert "项目类型" in result

    def test_with_frameworks(self):
        info = EnvironmentInfo(
            python_version="3.14.0",
            frameworks=["Django", "FastAPI", "Flask", "pytest", "NumPy", "pandas"],
        )
        result = print_env_info(info)
        assert "框架" in result
        assert "Django" in result

    def test_with_project_structure(self):
        info = EnvironmentInfo(
            python_version="3.14.0",
            project_structure={
                "python_files": 10,
                "test_files": 5,
                "notebook_files": 2,
            },
        )
        result = print_env_info(info)
        assert "10 个.py" in result
        assert "5 个测试" in result
        assert "2 个.ipynb" in result

    def test_with_git_info(self):
        info = EnvironmentInfo(
            python_version="3.14.0",
            git_info={
                "is_repo": True,
                "branch": "main",
                "last_commit": "abc1234 Initial",
            },
        )
        result = print_env_info(info)
        assert "main" in result
        assert "Initial" in result

    def test_without_git_info(self):
        info = EnvironmentInfo(python_version="3.14.0")
        result = print_env_info(info)
        # 没有 git_info 或 is_repo=False -> 不应包含 Git
        assert "Git" not in result
