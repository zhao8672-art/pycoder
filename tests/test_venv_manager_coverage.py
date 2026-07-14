"""
venv_manager.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- VirtualEnv 数据类的 activate_script / python_exe 分支 (Windows/Linux, 文件存在与否)
- detect_current_venv 三种环境分支 (VIRTUAL_ENV / CONDA / system)
- list_venvs 扫描多个 search_paths 与 .venv / venv / envs 目录
- create_venv 用 monkeypatch 替换 venv.EnvBuilder.create 与 subprocess.run
- install_package / install_requirements 覆盖成功/失败/异常路径
- get_activate_command / switch_venv 覆盖各 env_type 分支
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python import venv_manager as vm
from pycoder.python.venv_manager import (
    VirtualEnv,
    detect_current_venv,
    list_venvs,
    create_venv,
    install_package,
    install_requirements,
    get_activate_command,
    switch_venv,
)


# ── VirtualEnv 数据类 ───────────────────────────────────────


class TestVirtualEnv:
    def test_defaults(self):
        venv = VirtualEnv(name="x", path=Path("/tmp/x"), env_type="venv")
        assert venv.name == "x"
        assert venv.python_version == ""
        assert venv.python_path == ""
        assert venv.packages == []
        assert venv.active is False

    def test_activate_script_venv_win32(self, tmp_path, monkeypatch):
        # 模拟 Windows 平台
        monkeypatch.setattr(vm.sys, "platform", "win32")
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        (scripts / "activate").write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        result = venv.activate_script()
        assert result == scripts / "activate"

    def test_activate_script_venv_unix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "activate").write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        assert venv.activate_script() == bin_dir / "activate"

    def test_activate_script_virtualenv_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "activate").write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="virtualenv")
        assert venv.activate_script() is not None

    def test_activate_script_not_exists_venv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        # 文件不存在 -> None
        assert venv.activate_script() is None

    def test_activate_script_unknown_type(self, tmp_path):
        venv = VirtualEnv(name="v", path=tmp_path, env_type="conda")
        assert venv.activate_script() is None

    def test_python_exe_win32_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "win32")
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        exe = scripts / "python.exe"
        exe.write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        assert venv.python_exe() == exe

    def test_python_exe_unix_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        py = bin_dir / "python"
        py.write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        assert venv.python_exe() == py

    def test_python_exe_not_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        assert venv.python_exe() is None


# ── detect_current_venv ──────────────────────────────────────


class TestDetectCurrentVenv:
    def test_virtual_env_set(self, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {"VIRTUAL_ENV": "/path/to/venv"})
        venv = detect_current_venv()
        assert venv.env_type == "venv"
        assert venv.name == "venv"
        assert venv.active is True
        assert venv.python_version
        assert venv.python_path

    def test_conda_env_set_with_prefix(self, monkeypatch):
        monkeypatch.setattr(
            vm.os,
            "environ",
            {"CONDA_DEFAULT_ENV": "myenv", "CONDA_PREFIX": "/conda/prefix"},
        )
        venv = detect_current_venv()
        assert venv.env_type == "conda"
        assert venv.name == "myenv"
        # Windows 上 Path 会转换斜杠, 比较时用 Path 对象
        assert venv.path == Path("/conda/prefix")
        assert venv.active is True

    def test_conda_env_no_prefix(self, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {"CONDA_DEFAULT_ENV": "myenv"})
        venv = detect_current_venv()
        assert venv.env_type == "conda"
        assert venv.name == "myenv"
        assert venv.path == Path()

    def test_poetry_active(self, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {"POETRY_ACTIVE": "1"})
        venv = detect_current_venv()
        # poetry 不在 detect_current_venv 的分支中，会走到 system
        assert venv.env_type == "system"
        assert venv.active is False

    def test_system_python(self, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {})
        venv = detect_current_venv()
        assert venv.env_type == "system"
        assert venv.active is False
        assert venv.name == "system"


# ── list_venvs ──────────────────────────────────────────────


class TestListVenvs:
    def test_empty_search_paths(self, monkeypatch):
        # detect_current_venv 返回 system，搜索路径都不存在
        monkeypatch.setattr(vm.os, "environ", {})
        result = list_venvs(search_paths=[])
        assert result == []

    def test_with_active_venv(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vm.os, "environ", {"VIRTUAL_ENV": str(tmp_path)})
        result = list_venvs(search_paths=[])
        assert len(result) == 1
        assert result[0].env_type == "venv"

    def test_scan_conda_envs_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {})
        # 模拟 conda envs 目录
        envs_dir = tmp_path / "envs"
        env1 = envs_dir / "env1"
        env2 = envs_dir / "env2"
        env1.mkdir(parents=True)
        env2.mkdir(parents=True)
        result = list_venvs(search_paths=[envs_dir])
        names = [v.name for v in result]
        assert "env1" in names
        assert "env2" in names
        for v in result:
            assert v.env_type == "conda"

    def test_scan_venv_dir_with_python(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {})
        monkeypatch.setattr(vm.sys, "platform", "linux")
        # 创建带 bin/python 的 venv
        venv_dir = tmp_path / ".venv"
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").write_text("", encoding="utf-8")
        result = list_venvs(search_paths=[tmp_path])
        # 应该找到 .venv
        assert any(v.path == venv_dir for v in result)

    def test_scan_venv_no_python_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.os, "environ", {})
        monkeypatch.setattr(vm.sys, "platform", "linux")
        # 创建 .venv 但无 bin/python
        (tmp_path / ".venv").mkdir()
        result = list_venvs(search_paths=[tmp_path])
        assert result == []

    def test_scan_nonexistent_path_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vm.os, "environ", {})
        result = list_venvs(search_paths=[tmp_path / "nonexistent"])
        assert result == []

    def test_default_search_paths(self, monkeypatch, tmp_path):
        # 使用默认 search_paths (None)
        monkeypatch.setattr(vm.os, "environ", {})
        monkeypatch.setattr(vm.Path, "cwd", lambda: tmp_path)
        # mock Path.home 避免 RuntimeError
        monkeypatch.setattr(vm.Path, "home", lambda: tmp_path)
        result = list_venvs(search_paths=None)
        assert isinstance(result, list)

    def test_nested_venv_directory(self, tmp_path, monkeypatch):
        # 测试嵌套 .venv 目录, parent != base
        monkeypatch.setattr(vm.os, "environ", {})
        monkeypatch.setattr(vm.sys, "platform", "linux")
        nested = tmp_path / "project" / ".venv"
        bin_dir = nested / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").write_text("", encoding="utf-8")
        result = list_venvs(search_paths=[tmp_path])
        # 嵌套 venv 的 name 应包含 parent
        matching = [v for v in result if v.path == nested]
        assert len(matching) == 1
        assert "/" in matching[0].name


# ── create_venv ─────────────────────────────────────────────


class TestCreateVenv:
    def test_create_success_no_deps(self, tmp_path, monkeypatch):
        # mock venv.EnvBuilder.create
        def fake_create(self, path):
            # 模拟创建: 在 tmp_path 创建 Scripts/bin 目录
            if sys.platform == "win32":
                Path(path, "Scripts").mkdir(parents=True, exist_ok=True)
            else:
                Path(path, "bin").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(vm.venv.EnvBuilder, "create", fake_create)
        result = create_venv(name=".venv", path=tmp_path)
        assert result.env_type == "venv"
        assert result.name == ".venv"
        assert result.packages == []
        assert result.active is False

    def test_create_already_exists(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        with pytest.raises(FileExistsError):
            create_venv(name=".venv", path=tmp_path)

    def test_create_with_requirements(self, tmp_path, monkeypatch):
        # mock EnvBuilder.create
        def fake_create(self, path):
            if sys.platform == "win32":
                Path(path, "Scripts").mkdir(parents=True, exist_ok=True)
            else:
                Path(path, "bin").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(vm.venv.EnvBuilder, "create", fake_create)
        # mock subprocess.run
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        # 写一个 requirements.txt
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest\n", encoding="utf-8")
        result = create_venv(name=".venv", path=tmp_path, requirements=req_file)
        # VirtualEnv 没有 success 字段, 验证 packages
        assert len(result.packages) == 1
        assert "requirements" in result.packages[0]

    def test_create_with_requirements_not_exists(self, tmp_path, monkeypatch):
        def fake_create(self, path):
            if sys.platform == "win32":
                Path(path, "Scripts").mkdir(parents=True, exist_ok=True)
            else:
                Path(path, "bin").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(vm.venv.EnvBuilder, "create", fake_create)
        result = create_venv(name=".venv", path=tmp_path, requirements="/nonexistent/req.txt")
        assert result.packages == []

    def test_create_with_packages(self, tmp_path, monkeypatch):
        def fake_create(self, path):
            if sys.platform == "win32":
                Path(path, "Scripts").mkdir(parents=True, exist_ok=True)
            else:
                Path(path, "bin").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(vm.venv.EnvBuilder, "create", fake_create)
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = create_venv(name=".venv", path=tmp_path, packages=["pytest", "flask"])
        assert "pytest" in result.packages
        assert "flask" in result.packages

    def test_create_with_packages_failed(self, tmp_path, monkeypatch):
        def fake_create(self, path):
            if sys.platform == "win32":
                Path(path, "Scripts").mkdir(parents=True, exist_ok=True)
            else:
                Path(path, "bin").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(vm.venv.EnvBuilder, "create", fake_create)
        # returncode != 0 -> packages 不加入
        mock_result = MagicMock(returncode=1, stdout="", stderr="err")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = create_venv(name=".venv", path=tmp_path, packages=["pytest"])
        assert result.packages == []

    def test_create_with_explicit_python(self, tmp_path, monkeypatch):
        called = {}

        def fake_create(self, path):
            called["path"] = path
            if sys.platform == "win32":
                Path(path, "Scripts").mkdir(parents=True, exist_ok=True)
            else:
                Path(path, "bin").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(vm.venv.EnvBuilder, "create", fake_create)
        result = create_venv(name=".venv", path=tmp_path, python="/custom/python")
        assert result.env_type == "venv"


# ── install_package ─────────────────────────────────────────


class TestInstallPackage:
    def test_with_venv_path_success(self, tmp_path, monkeypatch):
        # 创建 fake venv
        if sys.platform == "win32":
            scripts = tmp_path / "Scripts"
            scripts.mkdir()
            pip = scripts / "pip.exe"
        else:
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            pip = bin_dir / "pip"
        pip.write_text("", encoding="utf-8")

        mock_result = MagicMock(returncode=0, stdout="Success", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_package("pytest", venv_path=tmp_path)
        assert result["success"] is True
        assert result["package"] == "pytest"
        assert "Success" in result["output"]

    def test_with_venv_path_failure(self, tmp_path, monkeypatch):
        if sys.platform == "win32":
            (tmp_path / "Scripts").mkdir()
        else:
            (tmp_path / "bin").mkdir()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_package("nonexistent-pkg", venv_path=tmp_path)
        assert result["success"] is False

    def test_with_venv_path_upgrade(self, tmp_path, monkeypatch):
        if sys.platform == "win32":
            (tmp_path / "Scripts").mkdir()
        else:
            (tmp_path / "bin").mkdir()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_package("pytest", venv_path=tmp_path, upgrade=True)
        assert result["success"] is True

    def test_without_venv_path_success(self, monkeypatch):
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_package("pytest")
        assert result["success"] is True

    def test_exception_returns_failure(self, monkeypatch):
        def raise_error(*a, **k):
            raise subprocess.TimeoutExpired(cmd="pip", timeout=10)

        monkeypatch.setattr(vm.subprocess, "run", raise_error)
        result = install_package("pytest")
        assert result["success"] is False
        # str(TimeoutExpired) 包含命令名和超时信息
        assert "pip" in result["output"]


# ── install_requirements ─────────────────────────────────────


class TestInstallRequirements:
    def test_file_not_exists(self, tmp_path):
        result = install_requirements(tmp_path / "nonexistent.txt")
        assert result["success"] is False
        assert "文件不存在" in result["error"]

    def test_success_with_venv(self, tmp_path, monkeypatch):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest\n", encoding="utf-8")
        if sys.platform == "win32":
            (tmp_path / "Scripts").mkdir()
        else:
            (tmp_path / "bin").mkdir()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_requirements(req_file, venv_path=tmp_path)
        assert result["success"] is True
        assert "ok" in result["output"]

    def test_success_without_venv(self, tmp_path, monkeypatch):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest\n", encoding="utf-8")
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_requirements(req_file)
        assert result["success"] is True

    def test_failure_with_stderr(self, tmp_path, monkeypatch):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("bad-package-name-xyz\n", encoding="utf-8")
        mock_result = MagicMock(returncode=1, stdout="", stderr="not found")
        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: mock_result)
        result = install_requirements(req_file)
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_exception_returns_failure(self, tmp_path, monkeypatch):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("pytest\n", encoding="utf-8")

        def raise_error(*a, **k):
            raise subprocess.TimeoutExpired(cmd="pip", timeout=10)

        monkeypatch.setattr(vm.subprocess, "run", raise_error)
        result = install_requirements(req_file)
        assert result["success"] is False
        # str(TimeoutExpired) 包含命令和超时信息, 不含异常类名
        assert "timed out" in result["error"].lower() or "pip" in result["error"]


# ── get_activate_command ─────────────────────────────────────


class TestGetActivateCommand:
    def test_venv_win32(self, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "win32")
        venv = VirtualEnv(name="v", path=Path("C:/venv"), env_type="venv")
        cmd = get_activate_command(venv)
        assert "Scripts" in cmd
        assert "activate" in cmd

    def test_venv_unix(self, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        venv = VirtualEnv(name="v", path=Path("/venv"), env_type="venv")
        cmd = get_activate_command(venv)
        assert cmd.startswith("source")
        assert "/bin/activate" in cmd

    def test_virtualenv_type(self, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        venv = VirtualEnv(name="v", path=Path("/venv"), env_type="virtualenv")
        cmd = get_activate_command(venv)
        assert "activate" in cmd

    def test_conda(self):
        venv = VirtualEnv(name="myenv", path=Path("/conda"), env_type="conda")
        cmd = get_activate_command(venv)
        assert cmd == "conda activate myenv"

    def test_poetry(self):
        venv = VirtualEnv(name="proj", path=Path("/p"), env_type="poetry")
        cmd = get_activate_command(venv)
        assert cmd == "poetry shell"

    def test_system(self):
        venv = VirtualEnv(name="system", path=Path("/"), env_type="system")
        cmd = get_activate_command(venv)
        assert "无需激活" in cmd


# ── switch_venv ──────────────────────────────────────────────


class TestSwitchVenv:
    def test_no_python_exe(self, tmp_path):
        # venv 不存在 python exe
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        result = switch_venv(venv)
        assert result["success"] is False
        assert "Python 解释器" in result["error"]

    def test_success_win32(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "win32")
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        # 保存并恢复环境
        original_env = dict(os.environ)
        try:
            result = switch_venv(venv)
            assert result["success"] is True
            assert result["name"] == "v"
            assert "VIRTUAL_ENV" in os.environ
        finally:
            os.environ.clear()
            for _k, _v in original_env.items():
                try:
                    os.environ[_k] = _v
                except ValueError:
                    pass  # Windows 单环境变量上限 32767 字符，超长变量跳过

    def test_success_unix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm.sys, "platform", "linux")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").write_text("", encoding="utf-8")
        venv = VirtualEnv(name="v", path=tmp_path, env_type="venv")
        original_env = dict(os.environ)
        try:
            result = switch_venv(venv)
            assert result["success"] is True
            assert "activate_cmd" in result
        finally:
            os.environ.clear()
            for _k, _v in original_env.items():
                try:
                    os.environ[_k] = _v
                except ValueError:
                    pass  # Windows 单环境变量上限 32767 字符，超长变量跳过
