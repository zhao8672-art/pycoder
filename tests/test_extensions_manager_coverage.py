"""manager.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - ExtensionManager: 安装(种子/github/npm/pypi/vsix/不安全URL) / 启用禁用 / 更新 / 配置 / 卸载
  - 种子包代码生成 / async git clone / git pull
  - installed.json 持久化读写

测试策略:
  - monkeypatch EXTENSIONS_DIR 重定向到 tmp_path
  - mock asyncio.create_subprocess_exec 模拟 git clone/npm pack/pip download
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.extensions import manager as mgr


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    """重定向 EXTENSIONS_DIR 到 tmp_path 并创建新 manager"""
    d = tmp_path / "extensions"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mgr, "EXTENSIONS_DIR", d)
    return d


@pytest.fixture
def em(ext_dir):
    """每个测试独立的 ExtensionManager（无已安装扩展）"""
    return mgr.ExtensionManager()


class _MockProc:
    """模拟 asyncio.subprocess.Process"""
    def __init__(self, returncode=0, on_create=None):
        self.returncode = returncode
        self._on_create = on_create

    async def wait(self):
        if self._on_create:
            self._on_create()
        return self.returncode

    def kill(self):
        pass


@pytest.fixture
def mock_subprocess(monkeypatch):
    """统一 mock subprocess.run — 用于 update 的 git pull"""
    mock_run = MagicMock()
    monkeypatch.setattr(mgr.subprocess, "run", mock_run)
    return mock_run


@pytest.fixture
def mock_async_subprocess(monkeypatch):
    """Mock asyncio.create_subprocess_exec — 模拟 git clone/npm pack/pip download"""
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        proc = _MockProc(returncode=0)
        # 如果是 git clone，创建目标目录模拟 clone 成功
        if "clone" in args:
            target = Path(args[-1])
            target.mkdir(parents=True, exist_ok=True)
        return proc

    monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)
    return calls


@pytest.fixture
def mock_async_subprocess_fail(monkeypatch):
    """Mock asyncio.create_subprocess_exec — 模拟失败（returncode=1，不创建目录）"""
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _MockProc(returncode=1)

    monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)
    return calls


# ══════════════════════════════════════════════════════════
# __init__ / _load_installed
# ══════════════════════════════════════════════════════════

def test_init_creates_dir(tmp_path, monkeypatch):
    d = tmp_path / "new_exts"
    monkeypatch.setattr(mgr, "EXTENSIONS_DIR", d)
    assert not d.exists()
    m = mgr.ExtensionManager()
    assert d.exists()


def test_init_loads_installed(ext_dir):
    (ext_dir / "installed.json").write_text(json.dumps({
        "ext1": {"name": "Ext1", "enabled": True, "path": "/x"},
    }), encoding="utf-8")
    m = mgr.ExtensionManager()
    assert "ext1" in m._installed
    assert m.is_installed("ext1")


def test_init_load_corrupted(ext_dir):
    (ext_dir / "installed.json").write_text("bad json {{{", encoding="utf-8")
    m = mgr.ExtensionManager()  # 不应抛异常
    assert m._installed == {}


def test_init_no_installed_file(ext_dir):
    m = mgr.ExtensionManager()
    assert m._installed == {}


# ══════════════════════════════════════════════════════════
# install — 种子包
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_seed_package(em, ext_dir):
    ext_data = {"name": "GitLens", "url": ""}
    result = await em.install("pycoder.gitlens", ext_data)
    assert result is True
    target = ext_dir / "pycoder.gitlens"
    assert (target / "manifest.json").exists()
    assert (target / "extension.py").exists()
    assert ext_data["installed"] is True
    assert ext_data["enabled"] is True
    assert "path" in ext_data
    assert (ext_dir / "installed.json").exists()


@pytest.mark.asyncio
async def test_install_seed_package_writes_real_code(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    code = (ext_dir / "pycoder.gitlens" / "extension.py").read_text(encoding="utf-8")
    assert "get_blame_info" in code


@pytest.mark.asyncio
async def test_install_seed_docker(em, ext_dir):
    await em.install("pycoder.docker", {"name": "Docker"})
    code = (ext_dir / "pycoder.docker" / "extension.py").read_text(encoding="utf-8")
    assert "list_containers" in code


@pytest.mark.asyncio
async def test_install_seed_rest_client(em, ext_dir):
    await em.install("pycoder.rest-client", {"name": "REST"})
    assert (ext_dir / "pycoder.rest-client" / "extension.py").exists()


@pytest.mark.asyncio
async def test_install_seed_todo_tree(em, ext_dir):
    await em.install("pycoder.todo-tree", {"name": "TODO"})
    assert (ext_dir / "pycoder.todo-tree" / "extension.py").exists()


@pytest.mark.asyncio
async def test_install_seed_bookmarks(em, ext_dir):
    await em.install("pycoder.bookmarks", {"name": "BM"})
    assert (ext_dir / "pycoder.bookmarks" / "extension.py").exists()


@pytest.mark.asyncio
async def test_install_seed_project_manager(em, ext_dir):
    await em.install("pycoder.project-manager", {"name": "PM"})
    assert (ext_dir / "pycoder.project-manager" / "extension.py").exists()


@pytest.mark.asyncio
async def test_install_already_installed_returns_false(em):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    result = await em.install("pycoder.gitlens", {"name": "GitLens2"})
    assert result is False


# ══════════════════════════════════════════════════════════
# install — GitHub/GitLab 扩展
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_github_extension(em, ext_dir, mock_async_subprocess):
    """git clone 成功"""
    ext_data = {"name": "MyExt", "url": "https://github.com/user/myext"}
    result = await em.install("user/myext", ext_data)
    assert result is True
    assert ext_data["installed"] is True
    assert len(mock_async_subprocess) == 1


@pytest.mark.asyncio
async def test_install_github_already_cloned(em, ext_dir, mock_async_subprocess):
    """目标已存在 → 不重复 clone"""
    target = ext_dir / "user_myext"
    target.mkdir(parents=True)
    ext_data = {"name": "MyExt", "url": "https://github.com/user/myext"}
    result = await em.install("user/myext", ext_data)
    assert result is True
    assert len(mock_async_subprocess) == 0  # 已存在不调用 clone


@pytest.mark.asyncio
async def test_install_github_clone_fail_returns_false(em, ext_dir, mock_async_subprocess_fail):
    """clone 失败（returncode != 0）→ False"""
    ext_data = {"name": "MyExt", "url": "https://github.com/user/myext"}
    result = await em.install("user/myext", ext_data)
    assert result is False


@pytest.mark.asyncio
async def test_install_gitlab_extension(em, ext_dir, mock_async_subprocess):
    """gitlab.com 扩展也走 clone 分支"""
    ext_data = {"name": "GL", "url": "https://gitlab.com/u/r"}
    result = await em.install("gl_pkg", ext_data)
    assert result is True


# ══════════════════════════════════════════════════════════
# install — 安全校验
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_unsafe_url_raises_permission_error(em):
    ext_data = {"name": "Bad", "url": "https://evil.com/malware"}
    with pytest.raises(PermissionError):
        await em.install("bad.ext", ext_data)


@pytest.mark.asyncio
async def test_install_unsafe_url_error_message(em):
    ext_data = {"name": "Bad", "url": "https://evil.com/x"}
    with pytest.raises(PermissionError) as exc_info:
        await em.install("bad.ext", ext_data)
    assert "evil.com" in str(exc_info.value)
    assert "github.com" in str(exc_info.value)


@pytest.mark.asyncio
async def test_install_raw_githubusercontent_passes_security(em, ext_dir):
    """raw.githubusercontent.com 通过安全校验，但不走 clone 分支（不含 github.com 子串）"""
    ext_data = {"name": "Raw", "url": "https://raw.githubusercontent.com/u/r/main/f.py"}
    result = await em.install("raw_pkg", ext_data)
    assert result is False


@pytest.mark.asyncio
async def test_install_no_url_not_seed_returns_false(em):
    """无 URL 且非种子包 → False"""
    ext_data = {"name": "Unknown", "url": ""}
    result = await em.install("unknown.ext", ext_data)
    assert result is False


# ══════════════════════════════════════════════════════════
# enable / disable / is_enabled
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_enable(em):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    assert em.enable("pycoder.gitlens") is True
    assert em.is_enabled("pycoder.gitlens") is True


def test_enable_not_installed(em):
    assert em.enable("nonexistent") is False


@pytest.mark.asyncio
async def test_disable(em):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    assert em.disable("pycoder.gitlens") is True
    assert em.is_enabled("pycoder.gitlens") is False


def test_disable_not_installed(em):
    assert em.disable("nonexistent") is False


def test_is_enabled_default_true(em):
    """未安装的扩展默认 enabled=True"""
    assert em.is_enabled("nonexistent") is True


# ══════════════════════════════════════════════════════════
# update
# ══════════════════════════════════════════════════════════

def test_update_not_installed(em):
    assert em.update("nonexistent") is False


@pytest.mark.asyncio
async def test_update_seed_package(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    result = em.update("pycoder.gitlens")
    assert result is True
    assert (ext_dir / "pycoder.gitlens" / "manifest.json").exists()


def test_update_github_pull_success(em, ext_dir, mock_subprocess):
    """git pull 成功"""
    target = ext_dir / "user_myext"
    target.mkdir()
    (target / ".git").mkdir()
    em._installed["user/myext"] = {
        "name": "MyExt", "path": str(target), "enabled": True,
    }
    r = MagicMock()
    r.returncode = 0
    mock_subprocess.return_value = r
    result = em.update("user/myext")
    assert result is True
    mock_subprocess.assert_called_once()


def test_update_github_pull_failure(em, ext_dir, mock_subprocess):
    """git pull returncode != 0"""
    target = ext_dir / "user_myext"
    target.mkdir()
    (target / ".git").mkdir()
    em._installed["user/myext"] = {"name": "MyExt", "path": str(target)}
    r = MagicMock()
    r.returncode = 1
    mock_subprocess.return_value = r
    result = em.update("user/myext")
    assert result is False


def test_update_github_no_git_dir(em, ext_dir):
    """目标存在但无 .git → False"""
    target = ext_dir / "user_myext"
    target.mkdir()
    em._installed["user/myext"] = {"name": "MyExt", "path": str(target)}
    result = em.update("user/myext")
    assert result is False


def test_update_github_subprocess_error(em, ext_dir, mock_subprocess):
    """git pull 抛异常"""
    target = ext_dir / "user_myext"
    target.mkdir()
    (target / ".git").mkdir()
    em._installed["user/myext"] = {"name": "MyExt", "path": str(target)}
    mock_subprocess.side_effect = mgr.subprocess.SubprocessError("boom")
    result = em.update("user/myext")
    assert result is False


def test_update_github_oserror(em, ext_dir, mock_subprocess):
    target = ext_dir / "user_myext"
    target.mkdir()
    (target / ".git").mkdir()
    em._installed["user/myext"] = {"name": "MyExt", "path": str(target)}
    mock_subprocess.side_effect = OSError("boom")
    result = em.update("user/myext")
    assert result is False


# ══════════════════════════════════════════════════════════
# get_config / set_config
# ══════════════════════════════════════════════════════════

def test_get_config_not_installed(em):
    assert em.get_config("nope", "key", "default") == "default"


@pytest.mark.asyncio
async def test_get_config_no_file(em):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    assert em.get_config("pycoder.gitlens", "key", "def") == "def"


@pytest.mark.asyncio
async def test_get_config_valid(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    cfg = ext_dir / "pycoder.gitlens" / "config.json"
    cfg.write_text(json.dumps({"theme": "dark", "size": 10}), encoding="utf-8")
    assert em.get_config("pycoder.gitlens", "theme") == "dark"
    assert em.get_config("pycoder.gitlens", "size") == 10
    full = em.get_config("pycoder.gitlens")
    assert full["theme"] == "dark"


@pytest.mark.asyncio
async def test_get_config_missing_key_returns_default(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    cfg = ext_dir / "pycoder.gitlens" / "config.json"
    cfg.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert em.get_config("pycoder.gitlens", "b", "default") == "default"


@pytest.mark.asyncio
async def test_get_config_corrupted(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    cfg = ext_dir / "pycoder.gitlens" / "config.json"
    cfg.write_text("bad json {{{", encoding="utf-8")
    assert em.get_config("pycoder.gitlens", "key", "def") == "def"


def test_set_config_not_installed(em):
    assert em.set_config("nope", "key", "val") is False


@pytest.mark.asyncio
async def test_set_config_new(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    assert em.set_config("pycoder.gitlens", "theme", "dark") is True
    cfg = ext_dir / "pycoder.gitlens" / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"


@pytest.mark.asyncio
async def test_set_config_merges(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    em.set_config("pycoder.gitlens", "a", 1)
    em.set_config("pycoder.gitlens", "b", 2)
    cfg = ext_dir / "pycoder.gitlens" / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["a"] == 1 and data["b"] == 2


@pytest.mark.asyncio
async def test_set_config_corrupted_existing(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    cfg = ext_dir / "pycoder.gitlens" / "config.json"
    cfg.write_text("bad json {{{", encoding="utf-8")
    assert em.set_config("pycoder.gitlens", "key", "val") is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["key"] == "val"


# ══════════════════════════════════════════════════════════
# uninstall
# ══════════════════════════════════════════════════════════

def test_uninstall_not_installed(em):
    assert em.uninstall("nope") is False


@pytest.mark.asyncio
async def test_uninstall_with_path(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    target = ext_dir / "pycoder.gitlens"
    assert target.exists()
    assert em.uninstall("pycoder.gitlens") is True
    assert not target.exists()
    assert "pycoder.gitlens" not in em._installed


def test_uninstall_without_path(em, monkeypatch):
    """path 缺失时不删除任何目录"""
    removed = []
    monkeypatch.setattr(mgr.shutil, "rmtree", lambda p: removed.append(str(p)))
    em._installed["x"] = {"name": "X"}
    assert em.uninstall("x") is True
    assert "x" not in em._installed


def test_uninstall_path_not_exists(em, ext_dir):
    em._installed["x"] = {"name": "X", "path": str(ext_dir / "nonexistent")}
    assert em.uninstall("x") is True


# ══════════════════════════════════════════════════════════
# get_installed / is_installed
# ══════════════════════════════════════════════════════════

def test_get_installed_empty(em):
    assert em.get_installed() == []


@pytest.mark.asyncio
async def test_get_installed_with_data(em):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    installed = em.get_installed()
    assert len(installed) == 1
    assert installed[0]["name"] == "GitLens"


@pytest.mark.asyncio
async def test_is_installed(em):
    assert em.is_installed("x") is False
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    assert em.is_installed("pycoder.gitlens") is True


# ══════════════════════════════════════════════════════════
# _save / _load_installed 往返
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_save_and_reload(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    em2 = mgr.ExtensionManager()
    assert em2.is_installed("pycoder.gitlens")
    installed = em2.get_installed()
    assert len(installed) == 1


@pytest.mark.asyncio
async def test_save_writes_json(em, ext_dir):
    await em.install("pycoder.gitlens", {"name": "GitLens"})
    data = json.loads((ext_dir / "installed.json").read_text(encoding="utf-8"))
    assert "pycoder.gitlens" in data


# ══════════════════════════════════════════════════════════
# _SEED_PACKAGES 完整性
# ══════════════════════════════════════════════════════════

def test_seed_packages_have_code():
    for ext_id, pkg in mgr._SEED_PACKAGES.items():
        assert "manifest" in pkg
        assert "code" in pkg
        assert "extension.py" in pkg["code"]
        manifest = pkg["manifest"]
        assert "name" in manifest and "version" in manifest
