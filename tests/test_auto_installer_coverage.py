"""auto_installer.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - install_package: pip / npm / system / auto / 未知源
  - search_package: pypi / npm / github / all
  - ensure_tool: 已存在 / 安装成功 / 安装失败
  - detect_missing_imports / install_missing_imports
  - detect_requirements_file / install_requirements
  - _detect_source 各分支
  - _install_pip: 成功 / 失败重试 --user / 双失败 / 超时 / 异常
  - _install_npm: 未安装 / 成功 / 失败 / 超时 / 异常
  - _install_system: Windows(winget/choco/scoop) / Linux(apt/brew) / 无管理器
  - _search_pypi / _search_npm / _search_github
  - Agent 工具函数: agent_install_package / agent_search_package /
    agent_ensure_tool / agent_install_deps

测试策略:
  - monkeypatch asyncio.create_subprocess_exec / asyncio.wait_for (subprocess mock)
  - monkeypatch shutil.which (工具检测)
  - monkeypatch os.name (Windows/Linux 分支)
  - monkeypatch httpx.AsyncClient (搜索 HTTP)
  - tmp_path 隔离 requirements.txt
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from pycoder.server.services import auto_installer as ai


# ══════════════════════════════════════════════════════════
# Mock 辅助
# ══════════════════════════════════════════════════════════

class MockProcess:
    """模拟 asyncio 子进程"""
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return (self._stdout, self._stderr)


class MockResp:
    """模拟 httpx 响应"""
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class MockSearchClient:
    """模拟 httpx.AsyncClient (搜索用)"""
    def __init__(self, responses=None):
        self._responses = responses or []
        self._idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None, timeout=None):
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            if isinstance(r, Exception):
                raise r
            return r
        return MockResp(status_code=404)

    async def aclose(self):
        pass


def make_subprocess_factory(returncodes, stdouts=None, stderrs=None):
    """创建按顺序返回的 create_subprocess_exec mock"""
    calls = [0]
    stdouts = stdouts or [b""] * len(returncodes)
    stderrs = stderrs or [b""] * len(returncodes)

    async def fake_exec(*args, **kwargs):
        i = min(calls[0], len(returncodes) - 1)
        calls[0] += 1
        return MockProcess(returncode=returncodes[i],
                          stdout=stdouts[i], stderr=stderrs[i])

    fake_exec.call_count = lambda: calls[0]
    return fake_exec


def make_raising_subprocess(exc):
    async def fake_exec(*args, **kwargs):
        raise exc
    return fake_exec


@pytest.fixture
def installer():
    return ai.AutoInstaller()


# ══════════════════════════════════════════════════════════
# _detect_source
# ══════════════════════════════════════════════════════════

def test_detect_source_npm(installer):
    assert installer._detect_source("react") == "npm"


def test_detect_source_pip_via_mapping(installer):
    # "requests" 在 _IMPORT_TO_PACKAGE 中
    assert installer._detect_source("requests") == "pip"


def test_detect_source_pip_via_import(installer):
    # "json" 可导入 → pip
    assert installer._detect_source("json") == "pip"


def test_detect_source_system_tool(installer, monkeypatch):
    # docker 不可导入
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    assert installer._detect_source("docker") == "system"


def test_detect_source_default_pip(installer, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    assert installer._detect_source("unknown-pkg") == "pip"


def test_detect_source_python_prefix(installer, monkeypatch):
    # "python-foo" 以 python- 开头，跳过 npm 检查
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    assert installer._detect_source("python-foo") == "pip"


# ══════════════════════════════════════════════════════════
# install_package
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_package_pip(installer, monkeypatch):
    async def fake_pip(name, version):
        return {"success": True, "message": "ok", "source": "pip"}
    monkeypatch.setattr(installer, "_install_pip", fake_pip)
    result = await installer.install_package("requests", source="pip")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_install_package_npm(installer, monkeypatch):
    async def fake_npm(name):
        return {"success": True, "message": "ok", "source": "npm"}
    monkeypatch.setattr(installer, "_install_npm", fake_npm)
    result = await installer.install_package("react", source="npm")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_install_package_system(installer, monkeypatch):
    async def fake_system(name):
        return {"success": True, "message": "ok", "source": "system"}
    monkeypatch.setattr(installer, "_install_system", fake_system)
    result = await installer.install_package("docker", source="system")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_install_package_auto_detect(installer, monkeypatch):
    async def fake_npm(name):
        return {"success": True, "message": "ok", "source": "npm"}
    monkeypatch.setattr(installer, "_install_npm", fake_npm)
    result = await installer.install_package("react", source="auto")
    assert result["source"] == "npm"


@pytest.mark.asyncio
async def test_install_package_unknown_source(installer):
    result = await installer.install_package("x", source="unknown")
    assert result["success"] is False
    assert "未知安装源" in result["message"]


@pytest.mark.asyncio
async def test_install_package_with_version(installer, monkeypatch):
    captured = {}

    async def fake_pip(name, version):
        captured["name"] = name
        captured["version"] = version
        return {"success": True, "message": "ok", "source": "pip"}

    monkeypatch.setattr(installer, "_install_pip", fake_pip)
    await installer.install_package("requests", source="pip", version=">=2.0")
    assert captured["version"] == ">=2.0"


# ══════════════════════════════════════════════════════════
# _install_pip
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_pip_success(installer, monkeypatch):
    fake = make_subprocess_factory([0], stdouts=[b"installed"])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_pip("requests")
    assert result["success"] is True
    assert result["source"] == "pip"


@pytest.mark.asyncio
async def test_install_pip_fail_then_user_success(installer, monkeypatch):
    fake = make_subprocess_factory([1, 0], stderrs=[b"permission denied", b""])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_pip("requests")
    assert result["success"] is True
    assert "--user" in result["message"]


@pytest.mark.asyncio
async def test_install_pip_fail_both(installer, monkeypatch):
    fake = make_subprocess_factory([1, 1], stderrs=[b"err1", b"err2"])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_pip("nonexistent-pkg-xyz")
    assert result["success"] is False
    assert "失败" in result["message"]


@pytest.mark.asyncio
async def test_install_pip_timeout(installer, monkeypatch):
    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()
    monkeypatch.setattr(ai.asyncio, "wait_for", fake_wait_for)
    result = await installer._install_pip("slow-pkg")
    assert result["success"] is False
    assert "超时" in result["message"]


@pytest.mark.asyncio
async def test_install_pip_exception(installer, monkeypatch):
    fake = make_raising_subprocess(RuntimeError("subprocess broken"))
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_pip("x")
    assert result["success"] is False
    assert "异常" in result["message"]


@pytest.mark.asyncio
async def test_install_pip_with_version(installer, monkeypatch):
    fake = make_subprocess_factory([0])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_pip("requests", ">=2.0")
    assert result["success"] is True


# ══════════════════════════════════════════════════════════
# _install_npm
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_npm_not_installed(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    result = await installer._install_npm("react")
    assert result["success"] is False
    assert "npm 未安装" in result["message"]


@pytest.mark.asyncio
async def test_install_npm_success(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/npm" if name in ("npm", "npm.cmd") else None)
    fake = make_subprocess_factory([0])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_npm("react")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_install_npm_fail(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/npm" if name in ("npm", "npm.cmd") else None)
    fake = make_subprocess_factory([1])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_npm("react")
    assert result["success"] is False
    assert "失败" in result["message"]


@pytest.mark.asyncio
async def test_install_npm_timeout(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/npm" if name in ("npm", "npm.cmd") else None)

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()
    monkeypatch.setattr(ai.asyncio, "wait_for", fake_wait_for)
    result = await installer._install_npm("react")
    assert result["success"] is False
    assert "超时" in result["message"]


@pytest.mark.asyncio
async def test_install_npm_exception(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/npm" if name in ("npm", "npm.cmd") else None)
    fake = make_raising_subprocess(RuntimeError("boom"))
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_npm("react")
    assert result["success"] is False
    assert "异常" in result["message"]


# ══════════════════════════════════════════════════════════
# _install_system
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_system_windows_winget_success(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "nt")

    def fake_which(name):
        if name in ("winget", "winget.exe"):
            return "C:/winget.exe"
        return None
    monkeypatch.setattr(ai.shutil, "which", fake_which)

    fake = make_subprocess_factory([0])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_system("docker")
    assert result["success"] is True
    assert "winget" in result["message"]


@pytest.mark.asyncio
async def test_install_system_windows_choco_fallback(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "nt")

    def fake_which(name):
        # winget 不存在，choco 存在
        if name in ("choco", "choco.exe"):
            return "C:/choco.exe"
        return None
    monkeypatch.setattr(ai.shutil, "which", fake_which)

    fake = make_subprocess_factory([0])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_system("docker")
    assert result["success"] is True
    assert "choco" in result["message"]


@pytest.mark.asyncio
async def test_install_system_windows_all_fail(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "nt")
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    result = await installer._install_system("docker")
    assert result["success"] is False
    assert "无可用包管理器" in result["message"]


@pytest.mark.asyncio
async def test_install_system_windows_subprocess_exception(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "nt")

    def fake_which(name):
        if name in ("winget", "winget.exe"):
            return "C:/winget.exe"
        return None
    monkeypatch.setattr(ai.shutil, "which", fake_which)

    fake = make_raising_subprocess(RuntimeError("boom"))
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_system("docker")
    # 异常被捕获，继续到下一个管理器，最终失败
    assert result["success"] is False


@pytest.mark.asyncio
async def test_install_system_linux_apt_success(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "posix")

    def fake_which(name):
        if name == "apt-get":
            return "/usr/bin/apt-get"
        return None
    monkeypatch.setattr(ai.shutil, "which", fake_which)

    fake = make_subprocess_factory([0])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_system("docker")
    assert result["success"] is True
    assert "apt-get" in result["message"]


@pytest.mark.asyncio
async def test_install_system_linux_brew_success(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "posix")

    def fake_which(name):
        if name == "brew":
            return "/usr/local/bin/brew"
        return None
    monkeypatch.setattr(ai.shutil, "which", fake_which)

    fake = make_subprocess_factory([0])
    monkeypatch.setattr(ai.asyncio, "create_subprocess_exec", fake)
    result = await installer._install_system("docker")
    assert result["success"] is True
    assert "brew" in result["message"]


@pytest.mark.asyncio
async def test_install_system_linux_no_manager(installer, monkeypatch):
    monkeypatch.setattr(ai.os, "name", "posix")
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    result = await installer._install_system("docker")
    assert result["success"] is False


# ══════════════════════════════════════════════════════════
# _search_pypi / _search_npm / _search_github
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_pypi_success(installer, monkeypatch):
    resp = MockResp(200, {"info": {"name": "requests", "summary": "HTTP lib",
                                    "version": "2.31.0"}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer._search_pypi("requests")
    assert len(result) == 1
    assert result[0]["name"] == "requests"
    assert result[0]["source"] == "pypi"


@pytest.mark.asyncio
async def test_search_pypi_fallback_search(installer, monkeypatch):
    resp1 = MockResp(404)
    resp2 = MockResp(200, {"results": [{"name": "req", "description": "d", "version": "1.0"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp1, resp2]))
    result = await installer._search_pypi("req")
    assert len(result) == 1
    assert result[0]["name"] == "req"


@pytest.mark.asyncio
async def test_search_pypi_final_fallback(installer, monkeypatch):
    resp1 = MockResp(404)
    resp2 = MockResp(404)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp1, resp2]))
    result = await installer._search_pypi("unknownpkg")
    assert len(result) == 1
    assert result[0]["name"] == "unknownpkg"
    assert "PyPI" in result[0]["description"]


@pytest.mark.asyncio
async def test_search_npm_success(installer, monkeypatch):
    resp = MockResp(200, {"objects": [
        {"package": {"name": "react", "description": "UI lib", "version": "18.0"}},
    ]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer._search_npm("react")
    assert len(result) == 1
    assert result[0]["name"] == "react"
    assert result[0]["source"] == "npm"


@pytest.mark.asyncio
async def test_search_npm_exception(installer, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kwargs: MockSearchClient([ConnectionError("boom")]))
    result = await installer._search_npm("react")
    assert result == []


@pytest.mark.asyncio
async def test_search_github_success(installer, monkeypatch):
    resp = MockResp(200, {"items": [
        {"full_name": "user/repo", "description": "a repo",
         "html_url": "https://github.com/user/repo", "stargazers_count": 100},
    ]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer._search_github("repo")
    assert len(result) == 1
    assert result[0]["name"] == "user/repo"
    assert result[0]["stars"] == 100
    assert result[0]["source"] == "github"


@pytest.mark.asyncio
async def test_search_github_exception(installer, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kwargs: MockSearchClient([ConnectionError("boom")]))
    result = await installer._search_github("repo")
    assert result == []


# ══════════════════════════════════════════════════════════
# search_package
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_package_all(installer, monkeypatch):
    pypi_resp = MockResp(200, {"info": {"name": "x", "summary": "s", "version": "1.0"}})
    npm_resp = MockResp(200, {"objects": [{"package": {"name": "y", "description": "d", "version": "1.0"}}]})
    gh_resp = MockResp(200, {"items": [{"full_name": "z/r", "description": "d",
                                         "html_url": "u", "stargazers_count": 5}]})

    call_count = [0]
    responses = [pypi_resp, npm_resp, gh_resp]

    def fake_client(**kwargs):
        c = MockSearchClient([responses[call_count[0]]])
        call_count[0] += 1
        return c
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    result = await installer.search_package("test", source="all")
    assert result["total"] == 3
    assert len(result["results"]) == 3


@pytest.mark.asyncio
async def test_search_package_pypi_only(installer, monkeypatch):
    resp = MockResp(200, {"info": {"name": "x", "summary": "s", "version": "1.0"}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer.search_package("test", source="pypi")
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_search_package_npm_only(installer, monkeypatch):
    resp = MockResp(200, {"objects": [{"package": {"name": "y", "description": "d", "version": "1.0"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer.search_package("test", source="npm")
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_search_package_github_only(installer, monkeypatch):
    resp = MockResp(200, {"items": [{"full_name": "z/r", "description": "d",
                                      "html_url": "u", "stargazers_count": 5}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer.search_package("test", source="github")
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_search_package_exception_handled(installer, monkeypatch):
    """搜索异常被捕获，返回空结果"""
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kwargs: MockSearchClient([ConnectionError("boom")]))
    result = await installer.search_package("test", source="all")
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_search_package_results_capped(installer, monkeypatch):
    """结果限制为 20"""
    items = [{"full_name": f"r{i}", "description": "d", "html_url": "u", "stargazers_count": i}
             for i in range(30)]
    resp = MockResp(200, {"items": items})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockSearchClient([resp]))
    result = await installer.search_package("test", source="github")
    assert len(result["results"]) <= 20


# ══════════════════════════════════════════════════════════
# ensure_tool
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ensure_tool_already_exists_via_which(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/python")
    result = await installer.ensure_tool("python")
    assert result["success"] is True
    assert result["action"] == "already_exists"


@pytest.mark.asyncio
async def test_ensure_tool_already_exists_via_import(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    # importlib.import_module 成功
    result = await installer.ensure_tool("json")
    assert result["success"] is True
    assert result["action"] == "already_exists"


@pytest.mark.asyncio
async def test_ensure_tool_install_success(installer, monkeypatch):
    which_results = {"nonexist-tool": None}  # 初始不存在
    monkeypatch.setattr(ai.shutil, "which", lambda name: which_results.get(name))
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)

    async def fake_install(name, source="auto", version=""):
        which_results["nonexist-tool"] = "/usr/bin/nonexist-tool"  # 安装后可用
        return {"success": True, "message": "ok", "source": "system"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await installer.ensure_tool("nonexist-tool")
    assert result["success"] is True
    assert result["action"] == "installed"


@pytest.mark.asyncio
async def test_ensure_tool_install_fail_but_which_succeeds(installer, monkeypatch):
    which_results = {"nonexist-tool": None}
    monkeypatch.setattr(ai.shutil, "which", lambda name: which_results.get(name))
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)

    async def fake_install(name, source="auto", version=""):
        # 安装报告失败，但实际工具已可用
        which_results["nonexist-tool"] = "/usr/bin/nonexist-tool"
        return {"success": False, "message": "install failed", "source": "system"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await installer.ensure_tool("nonexist-tool")
    assert result["success"] is True
    assert result["action"] == "installed"


@pytest.mark.asyncio
async def test_ensure_tool_complete_fail(installer, monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)

    async def fake_install(name, source="auto"):
        return {"success": False, "message": "cannot install", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await installer.ensure_tool("nonexistent-tool")
    assert result["success"] is False
    assert result["action"] == "failed"


# ══════════════════════════════════════════════════════════
# detect_missing_imports
# ══════════════════════════════════════════════════════════

def test_detect_missing_imports_stdlib_only(installer):
    code = "import os\nimport sys\nfrom pathlib import Path"
    assert installer.detect_missing_imports(code) == []


def test_detect_missing_imports_with_installed(installer):
    code = "import json\nimport os"
    # json 和 os 都是 stdlib
    assert installer.detect_missing_imports(code) == []


def test_detect_missing_imports_with_missing(installer, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    code = "import nonexist_pkg_x\nfrom another_missing import something"
    result = installer.detect_missing_imports(code)
    assert "nonexist_pkg_x" in result
    assert "another_missing" in result


def test_detect_missing_imports_from_dotted(installer, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    code = "from pkg.sub import func"
    result = installer.detect_missing_imports(code)
    assert "pkg" in result


def test_detect_missing_imports_empty_code(installer):
    assert installer.detect_missing_imports("") == []


# ══════════════════════════════════════════════════════════
# install_missing_imports
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_missing_imports_none(installer):
    code = "import os\nimport sys"
    result = await installer.install_missing_imports(code)
    assert result == []


@pytest.mark.asyncio
async def test_install_missing_imports_some(installer, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)

    async def fake_install(name, source="auto", version=""):
        return {"success": True, "message": "ok", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    code = "import nonexist_xyz\nimport another_missing"
    result = await installer.install_missing_imports(code)
    assert len(result) == 2
    modules = {r["module"] for r in result}
    assert "nonexist_xyz" in modules
    assert "another_missing" in modules


@pytest.mark.asyncio
async def test_install_missing_imports_with_mapping(installer, monkeypatch):
    """yaml → pyyaml 映射"""
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    captured = []

    async def fake_install(name, source="auto", version=""):
        captured.append(name)
        return {"success": True, "message": "ok", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    code = "import yaml"
    result = await installer.install_missing_imports(code)
    assert "pyyaml" in captured


# ══════════════════════════════════════════════════════════
# detect_requirements_file
# ══════════════════════════════════════════════════════════

def test_detect_requirements_file_missing(installer, tmp_path):
    result = installer.detect_requirements_file(tmp_path)
    assert result == []


def test_detect_requirements_file_empty(installer, tmp_path):
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    result = installer.detect_requirements_file(tmp_path)
    assert result == []


def test_detect_requirements_file_comments_and_options(installer, tmp_path):
    content = "# comment\n-r other.txt\n--index-url http://x\n\nos\n"
    (tmp_path / "requirements.txt").write_text(content, encoding="utf-8")
    # os 是 stdlib，可导入 → 不在 missing 中
    result = installer.detect_requirements_file(tmp_path)
    assert result == []


def test_detect_requirements_file_with_missing(installer, tmp_path, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    content = "requests>=2.0\n# comment\nflake8\n"
    (tmp_path / "requirements.txt").write_text(content, encoding="utf-8")
    result = installer.detect_requirements_file(tmp_path)
    assert "requests>=2.0" in result
    assert "flake8" in result


# ══════════════════════════════════════════════════════════
# install_requirements
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_install_requirements_no_missing(installer, tmp_path):
    (tmp_path / "requirements.txt").write_text("os\nsys\n", encoding="utf-8")
    result = await installer.install_requirements(tmp_path)
    assert result["success"] is True
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_install_requirements_with_missing(installer, tmp_path, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    (tmp_path / "requirements.txt").write_text("requests\nflask\n", encoding="utf-8")

    async def fake_install(name, source="auto", version=""):
        return {"success": True, "message": "ok", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await installer.install_requirements(tmp_path)
    assert result["success"] is True
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_install_requirements_partial_failure(installer, tmp_path, monkeypatch):
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)
    (tmp_path / "requirements.txt").write_text("good-pkg\nbad-pkg\n", encoding="utf-8")

    async def fake_install(name, source="auto", version=""):
        if name == "bad-pkg":
            return {"success": False, "message": "fail", "source": "pip"}
        return {"success": True, "message": "ok", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await installer.install_requirements(tmp_path)
    assert result["success"] is False
    assert "失败" in result["message"]


# ══════════════════════════════════════════════════════════
# get_installer 单例
# ══════════════════════════════════════════════════════════

def test_get_installer_singleton():
    ai._INSTALLER = None
    i1 = ai.get_installer()
    i2 = ai.get_installer()
    assert i1 is i2


# ══════════════════════════════════════════════════════════
# Agent 工具函数
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_agent_install_package(installer, monkeypatch):
    ai._INSTALLER = None
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    async def fake_install(name, source="auto", version=""):
        return {"success": True, "message": "✅ installed", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await ai.agent_install_package({"name": "requests", "source": "pip"})
    assert "installed" in result


@pytest.mark.asyncio
async def test_agent_install_package_empty(monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    async def fake_install(name, source="auto", version=""):
        return {"success": False, "message": "failed", "source": "pip"}
    monkeypatch.setattr(installer, "install_package", fake_install)

    result = await ai.agent_install_package({})
    assert result == "failed"


@pytest.mark.asyncio
async def test_agent_search_package_with_results(monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    async def fake_search(query, source="all"):
        return {
            "results": [
                {"name": "pkg1", "description": "desc1", "source": "pypi", "version": "1.0"},
                {"name": "pkg2", "description": "desc2", "source": "github", "stars": 100},
            ],
            "total": 2,
            "query": query,
        }
    monkeypatch.setattr(installer, "search_package", fake_search)

    result = await ai.agent_search_package({"query": "pkg"})
    assert "找到 2 个结果" in result
    assert "pkg1" in result


@pytest.mark.asyncio
async def test_agent_search_package_no_results(monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    async def fake_search(query, source="all"):
        return {"results": [], "total": 0, "query": query}
    monkeypatch.setattr(installer, "search_package", fake_search)

    result = await ai.agent_search_package({"query": "nothing"})
    assert "未找到" in result


@pytest.mark.asyncio
async def test_agent_ensure_tool(monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    async def fake_ensure(tool_name):
        return {"success": True, "message": "✅ ready", "action": "already_exists"}
    monkeypatch.setattr(installer, "ensure_tool", fake_ensure)

    result = await ai.agent_ensure_tool({"name": "python"})
    assert "ready" in result


@pytest.mark.asyncio
async def test_agent_install_deps_file_not_found(monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    result = await ai.agent_install_deps({"file": "/nonexistent/path/file.py"})
    assert "无法读取文件" in result


@pytest.mark.asyncio
async def test_agent_install_deps_no_missing(tmp_path, monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    f = tmp_path / "code.py"
    f.write_text("import os\nimport sys\n", encoding="utf-8")

    result = await ai.agent_install_deps({"file": str(f)})
    assert "没有缺失" in result


@pytest.mark.asyncio
async def test_agent_install_deps_with_missing(tmp_path, monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)
    monkeypatch.setattr(importlib, "import_module", _raise_import_error)

    async def fake_install_missing(code):
        return [
            {"module": "missing_pkg", "package": "missing-pkg", "success": True, "message": "ok"},
            {"module": "bad_pkg", "package": "bad-pkg", "success": False, "message": "fail"},
        ]
    monkeypatch.setattr(installer, "install_missing_imports", fake_install_missing)

    f = tmp_path / "code.py"
    f.write_text("import missing_pkg\nimport bad_pkg\n", encoding="utf-8")

    result = await ai.agent_install_deps({"file": str(f)})
    assert "安装 1/2" in result
    assert "missing_pkg" in result


@pytest.mark.asyncio
async def test_agent_install_deps_all_success(tmp_path, monkeypatch):
    ai._INSTALLER = None
    installer = ai.AutoInstaller()
    monkeypatch.setattr(ai, "AutoInstaller", lambda: installer)

    async def fake_install_missing(code):
        return [
            {"module": "pkg1", "package": "pkg1", "success": True, "message": "ok"},
        ]
    monkeypatch.setattr(installer, "install_missing_imports", fake_install_missing)

    f = tmp_path / "code.py"
    f.write_text("import pkg1\n", encoding="utf-8")

    result = await ai.agent_install_deps({"file": str(f)})
    assert "安装 1/1" in result


# ── 辅助函数 ──

def _raise_import_error(name):
    raise ImportError(f"cannot import {name}")
