"""覆盖率测试: pycoder/server/routers/extensions.py

目标: 行覆盖率 >= 80%

覆盖端点:
    GET  /api/extensions/search
    GET  /api/extensions/installed
    GET  /api/extensions/recommended
    POST /api/extensions/install        — 含来源安全校验
    POST /api/extensions/uninstall
    POST /api/extensions/enable
    POST /api/extensions/disable
    POST /api/extensions/update
    GET  /api/extensions/config/{ext_id}
    POST /api/extensions/config/{ext_id}
    GET  /api/extensions/verify/{ext_id}
    POST /api/extensions/run            — 动态加载扩展并执行函数

测试策略:
    - 用 FastAPI TestClient 调用端点
    - 用 monkeypatch 替换模块级 _manager（ExtensionManager）与 search_extensions
    - 用 tmp_path / monkeypatch Path.home() 隔离文件系统副作用
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import extensions as ext_mod


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def mock_manager():
    """构造一个 MagicMock 的 ExtensionManager，覆盖所有方法"""
    mgr = MagicMock()
    # 默认行为
    mgr.is_installed.return_value = False
    mgr.is_enabled.return_value = False
    mgr.get_installed.return_value = []
    mgr.install = AsyncMock(return_value=True)
    mgr.uninstall.return_value = True
    mgr.enable.return_value = True
    mgr.disable.return_value = True
    mgr.update.return_value = True
    mgr.get_config.return_value = None
    mgr.set_config.return_value = True
    # async 方法必须用 AsyncMock
    mgr.execute_extension_function = AsyncMock(
        return_value={"success": False, "error": "not configured"}
    )
    mgr.activate_extension = AsyncMock(return_value=True)
    return mgr


@pytest.fixture
def client(mock_manager, monkeypatch):
    """创建仅包含 extensions 路由的 FastAPI 应用，并替换模块级 _manager"""
    monkeypatch.setattr(ext_mod, "_manager", mock_manager)
    app = FastAPI()
    app.include_router(ext_mod.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """隔离 Path.home() 到 tmp_path"""
    home = tmp_path / "fake_home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


# ══════════════════════════════════════════════════════════
# 1. search 端点
# ══════════════════════════════════════════════════════════


class TestSearch:
    """GET /api/extensions/search"""

    def test_search_default(self, client, monkeypatch):
        """默认搜索 — 返回的扩展会标记 installed=False"""
        async def fake_search(q, category, limit, offset):
            return {
                "extensions": [
                    {"id": "ext.a", "name": "A"},
                    {"id": "ext.b", "name": "B"},
                ],
                "total": 2,
            }
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.get("/api/extensions/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for ext in data["extensions"]:
            assert ext["installed"] is False

    def test_search_with_installed_ext(self, client, mock_manager, monkeypatch):
        """已安装扩展应标记 installed=True 且 enabled 字段"""
        mock_manager.is_installed.return_value = True
        mock_manager.is_enabled.return_value = True

        async def fake_search(q, category, limit, offset):
            return {"extensions": [{"id": "ext.a", "name": "A"}], "total": 1}
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.get("/api/extensions/search?q=test")
        assert resp.status_code == 200
        ext = resp.json()["extensions"][0]
        assert ext["installed"] is True
        assert ext["enabled"] is True

    def test_search_with_params(self, client, monkeypatch):
        """带 q/category/limit/offset 参数"""
        captured = {}

        async def fake_search(q, category, limit, offset):
            captured.update(q=q, category=category, limit=limit, offset=offset)
            return {"extensions": [], "total": 0}

        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.get(
            "/api/extensions/search",
            params={"q": "git", "category": "tools", "limit": 5, "offset": 1},
        )
        assert resp.status_code == 200
        assert captured["q"] == "git"
        assert captured["category"] == "tools"
        assert captured["limit"] == 5
        assert captured["offset"] == 1


# ══════════════════════════════════════════════════════════
# 2. installed / recommended 端点
# ══════════════════════════════════════════════════════════


class TestInstalledRecommended:
    def test_list_installed(self, client, mock_manager):
        mock_manager.get_installed.return_value = [{"id": "ext.a", "name": "A"}]
        resp = client.get("/api/extensions/installed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["extensions"] == [{"id": "ext.a", "name": "A"}]

    def test_list_recommended_default(self, client, mock_manager):
        """推荐列表 — 未安装"""
        resp = client.get("/api/extensions/recommended")
        assert resp.status_code == 200
        data = resp.json()
        assert "extensions" in data
        # 种子扩展应有内容
        assert len(data["extensions"]) > 0
        for ext in data["extensions"]:
            assert ext["installed"] is False

    def test_list_recommended_with_installed(self, client, mock_manager):
        """推荐列表 — 部分已安装且启用"""
        mock_manager.is_installed.return_value = True
        mock_manager.is_enabled.return_value = True
        resp = client.get("/api/extensions/recommended")
        assert resp.status_code == 200
        for ext in resp.json()["extensions"]:
            assert ext["installed"] is True
            assert ext["enabled"] is True


# ══════════════════════════════════════════════════════════
# 3. install 端点 — 含安全校验
# ══════════════════════════════════════════════════════════


class TestInstall:
    def test_install_no_id(self, client):
        """缺少 id 应返回 400"""
        resp = client.post("/api/extensions/install", json={})
        assert resp.status_code == 400

    def test_install_already_installed(self, client, mock_manager):
        """已安装返回 success=False"""
        mock_manager.is_installed.return_value = True
        resp = client.post("/api/extensions/install", json={"id": "ext.a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "already installed"

    def test_install_seed_package(self, client, mock_manager, monkeypatch):
        """安装种子扩展 — 从 _SEED_PACKAGES 补全元数据"""
        mock_manager.is_installed.return_value = False
        mock_manager.install.return_value = True

        # search_extensions 返回空（GitHub 不可用）
        async def fake_search(q):
            return {"extensions": []}
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.post(
            "/api/extensions/install",
            json={"id": "pycoder.gitlens"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # install 应被调用，且 ext_data 含种子元数据
        args, kwargs = mock_manager.install.call_args
        ext_id, ext_data = args
        assert ext_id == "pycoder.gitlens"
        assert ext_data.get("is_seed") is True
        assert ext_data.get("name") == "GitLens for PyCoder"

    def test_install_from_search_results(self, client, mock_manager, monkeypatch):
        """安装时从搜索结果补全元数据"""
        mock_manager.is_installed.return_value = False
        mock_manager.install.return_value = True

        async def fake_search(q):
            return {
                "extensions": [
                    {"id": "ext.found", "name": "Found", "version": "2.0.0"}
                ]
            }
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.post(
            "/api/extensions/install",
            json={"id": "ext.found"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["name"] == "Found"

    def test_install_search_fails_silently(self, client, mock_manager, monkeypatch):
        """search 抛异常时使用 req 中的基础数据"""
        mock_manager.is_installed.return_value = False
        mock_manager.install.return_value = True

        async def fake_search(q):
            raise RuntimeError("network error")
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.post(
            "/api/extensions/install",
            json={"id": "ext.basic", "name": "Basic"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_install_permission_error(self, client, mock_manager, monkeypatch):
        """install 抛 PermissionError 应返回 403"""
        mock_manager.is_installed.return_value = False
        mock_manager.install.side_effect = PermissionError("unsafe source")

        async def fake_search(q):
            return {"extensions": []}
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        resp = client.post(
            "/api/extensions/install",
            json={"id": "ext.bad", "url": "http://evil.com/x"},
        )
        assert resp.status_code == 403

    def test_install_generic_exception(self, client, mock_manager, monkeypatch):
        """install 抛一般异常应被 FastAPI 默认处理器转为 500"""
        mock_manager.is_installed.return_value = False
        mock_manager.install.side_effect = RuntimeError("boom")

        async def fake_search(q):
            return {"extensions": []}
        monkeypatch.setattr(ext_mod, "search_extensions", fake_search)

        # 关闭 raise_server_exceptions 让 FastAPI 返回 500 而非抛出
        app = FastAPI()
        app.include_router(ext_mod.router)
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/extensions/install", json={"id": "ext.fail"})
        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════
# 4. uninstall / enable / disable / update 端点
# ══════════════════════════════════════════════════════════


class TestSimpleOps:
    def test_uninstall(self, client, mock_manager):
        mock_manager.uninstall.return_value = True
        resp = client.post("/api/extensions/uninstall", json={"id": "ext.a"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["id"] == "ext.a"

    def test_uninstall_missing_id(self, client, mock_manager):
        """无 id 字段时 req.get 返回空字符串 — 仍然调用 uninstall"""
        resp = client.post("/api/extensions/uninstall", json={})
        assert resp.status_code == 200
        mock_manager.uninstall.assert_called_once()

    def test_enable(self, client, mock_manager):
        mock_manager.enable.return_value = True
        resp = client.post("/api/extensions/enable", json={"id": "ext.a"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_disable(self, client, mock_manager):
        mock_manager.disable.return_value = True
        resp = client.post("/api/extensions/disable", json={"id": "ext.a"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update(self, client, mock_manager):
        mock_manager.update.return_value = True
        resp = client.post("/api/extensions/update", json={"id": "ext.a"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ══════════════════════════════════════════════════════════
# 5. config 端点
# ══════════════════════════════════════════════════════════


class TestConfig:
    def test_get_config_default(self, client, mock_manager):
        """获取配置（无 key）"""
        mock_manager.get_config.return_value = {"theme": "dark"}
        resp = client.get("/api/extensions/config/ext.a")
        assert resp.status_code == 200
        assert resp.json()["config"] == {"theme": "dark"}

    def test_get_config_with_key(self, client, mock_manager):
        """获取配置（带 key 查询参数）"""
        mock_manager.get_config.return_value = "dark"
        resp = client.get("/api/extensions/config/ext.a?key=theme")
        assert resp.status_code == 200
        assert resp.json()["config"] == "dark"

    def test_set_config(self, client, mock_manager):
        """设置配置"""
        mock_manager.set_config.return_value = True
        resp = client.post(
            "/api/extensions/config/ext.a",
            json={"key": "theme", "value": "light"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_manager.set_config.assert_called_once_with("ext.a", "theme", "light")


# ══════════════════════════════════════════════════════════
# 6. verify 端点
# ══════════════════════════════════════════════════════════


class TestVerify:
    def test_verify_not_installed(self, client, fake_home):
        """扩展目录不存在 — 返回 installed=False"""
        resp = client.get("/api/extensions/verify/ext.missing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is False
        assert data["reason"] == "directory missing"

    def test_verify_installed_with_manifest(self, client, fake_home):
        """已安装且有 manifest.json"""
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "manifest.json").write_text(
            json.dumps({"name": "Ext A", "version": "1.2.3"}),
            encoding="utf-8",
        )
        (ext_dir / "extension.py").write_text("# code\n", encoding="utf-8")
        (ext_dir / "README.md").write_text("# README\n", encoding="utf-8")

        resp = client.get("/api/extensions/verify/ext_a")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is True
        assert data["name"] == "Ext A"
        assert data["version"] == "1.2.3"
        assert "extension.py" in data["files"]
        assert data["code_size"] > 0

    def test_verify_installed_no_manifest(self, client, fake_home):
        """已安装但无 manifest.json — manifest 为 {}"""
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_b"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text("x = 1\n", encoding="utf-8")

        resp = client.get("/api/extensions/verify/ext_b")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is True
        assert data["name"] == "?"
        assert data["version"] == "?"

    def test_verify_ext_id_with_dot(self, client, fake_home):
        """ext_id 含点号 — 应原样作为目录名"""
        ext_dir = fake_home / ".pycoder" / "extensions" / "pycoder.gitlens"
        ext_dir.mkdir(parents=True)
        (ext_dir / "manifest.json").write_text(
            json.dumps({"name": "GitLens", "version": "1.0.0"}),
            encoding="utf-8",
        )
        resp = client.get("/api/extensions/verify/pycoder.gitlens")
        assert resp.status_code == 200
        assert resp.json()["installed"] is True
        assert resp.json()["name"] == "GitLens"


# ══════════════════════════════════════════════════════════
# 7. run 端点 — 动态加载扩展
# ══════════════════════════════════════════════════════════


class TestRunExtension:
    def test_run_no_id(self, client):
        """缺少 id 应返回 400"""
        resp = client.post("/api/extensions/run", json={})
        assert resp.status_code == 400

    def test_run_disabled(self, client, mock_manager):
        """扩展未启用"""
        mock_manager.is_enabled.return_value = False
        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a", "function": "foo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "禁用" in data["error"]

    def test_run_not_installed(self, client, mock_manager, fake_home):
        """扩展目录不存在"""
        mock_manager.is_enabled.return_value = True
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": False, "error": "not installed: ext.missing"}
        )
        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext.missing", "function": "foo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not installed" in data["error"]

    def test_run_no_extension_py(self, client, mock_manager, fake_home):
        """扩展目录存在但无 extension.py"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": False, "error": "extension.py not found"}
        )

        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a", "function": "foo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "extension.py not found" in data["error"]

    def test_run_attr_not_found(self, client, mock_manager, fake_home):
        """function 不存在 — 返回 available_functions"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text(
            "name = 'Ext A'\nversion = '1.0'\n",
            encoding="utf-8",
        )
        mock_manager.execute_extension_function = AsyncMock(
            return_value={
                "success": False,
                "error": "function 'nonexistent' not found",
                "available_functions": ["name", "version"],
            }
        )

        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a", "function": "nonexistent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "available_functions" in data
        assert "name" in data["available_functions"]

    def test_run_attr_not_callable(self, client, mock_manager, fake_home):
        """属性存在但不可调用 — 返回字符串值"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text(
            "name = 'Ext A'\nversion = '1.0'\n",
            encoding="utf-8",
        )
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": True, "result": "Ext A", "type": "str"}
        )

        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a", "function": "name"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == "Ext A"
        assert data["type"] == "str"

    def test_run_callable_no_args(self, client, mock_manager, fake_home):
        """调用无参函数"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text(
            "def greet():\n    return 'hello'\n",
            encoding="utf-8",
        )
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": True, "result": "hello"}
        )

        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a", "function": "greet"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == "hello"

    def test_run_callable_with_args(self, client, mock_manager, fake_home):
        """调用带参函数"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": True, "result": 7}
        )

        resp = client.post(
            "/api/extensions/run",
            json={
                "id": "ext_a",
                "function": "add",
                "args": {"a": 3, "b": 4},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == 7

    def test_run_callable_raises(self, client, mock_manager, fake_home):
        """函数抛异常 — 返回 success=False"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text(
            "def boom():\n    raise ValueError('kaboom')\n",
            encoding="utf-8",
        )
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": False, "error": "ValueError: kaboom"}
        )

        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a", "function": "boom"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "kaboom" in data["error"]

    def test_run_default_function_name(self, client, mock_manager, fake_home):
        """未提供 function 时默认 'name'"""
        mock_manager.is_enabled.return_value = True
        ext_dir = fake_home / ".pycoder" / "extensions" / "ext_a"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.py").write_text(
            "name = 'Ext A'\n",
            encoding="utf-8",
        )
        mock_manager.execute_extension_function = AsyncMock(
            return_value={"success": True, "result": "Ext A"}
        )

        resp = client.post(
            "/api/extensions/run",
            json={"id": "ext_a"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == "Ext A"
