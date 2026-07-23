from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════
# 第五部分: host.py 模块测试
# ══════════════════════════════════════════════════════════


class TestExtensionAPI:
    """测试扩展 API"""

    @pytest.fixture
    def api(self):
        from pycoder.extensions.host import ExtensionAPI

        return ExtensionAPI("test.ext", {"version": "2.0.0"})

    def test_api_id(self, api):
        """ExtensionAPI.id 属性"""
        assert api.id == "test.ext"

    def test_api_version(self, api):
        """ExtensionAPI.version 属性"""
        assert api.version == "2.0.0"

    def test_api_version_default(self):
        """ExtensionAPI.version 默认值"""
        from pycoder.extensions.host import ExtensionAPI

        api = ExtensionAPI("test.ext", {})
        assert api.version == "0.0.0"

    def test_api_extension_path(self, api, monkeypatch, tmp_path):
        """ExtensionAPI.extension_path 属性"""
        from pycoder.extensions.host import ExtensionAPI

        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        api2 = ExtensionAPI("test.ext", {"version": "1.0.0"})
        expected = str(tmp_path / "test.ext")
        assert api2.extension_path == expected

    def test_api_context_set_get(self, api):
        """ExtensionAPI 上下文存储"""
        api.set_context("key1", "value1")
        assert api.get_context("key1") == "value1"

    def test_api_context_default(self, api):
        """get_context 默认值"""
        assert api.get_context("missing", "default") == "default"

    def test_api_subscribe_and_dispose(self, api):
        """ExtensionAPI subscribe 和 dispose"""
        callback = MagicMock()
        api.subscribe(callback)
        api.dispose()
        callback.assert_called_once()

    def test_api_dispose_multiple_callbacks(self, api):
        """dispose 调用所有订阅回调"""
        cb1 = MagicMock()
        cb2 = MagicMock()
        api.subscribe(cb1)
        api.subscribe(cb2)
        api.dispose()
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_api_dispose_callback_exception(self, api):
        """dispose 回调异常不阻止其他回调"""
        cb1 = MagicMock(side_effect=RuntimeError("boom"))
        cb2 = MagicMock()
        api.subscribe(cb1)
        api.subscribe(cb2)
        api.dispose()  # 不应抛出异常
        cb2.assert_called_once()

    def test_api_info_log(self, api, caplog):
        """ExtensionAPI.info 日志"""
        import logging

        with caplog.at_level(logging.INFO):
            api.info("测试消息")
        assert "测试消息" in caplog.text

    def test_api_warn_log(self, api, caplog):
        """ExtensionAPI.warn 日志"""
        import logging

        with caplog.at_level(logging.WARNING):
            api.warn("警告消息")
        assert "警告消息" in caplog.text

    def test_api_error_log(self, api, caplog):
        """ExtensionAPI.error 日志"""
        import logging

        with caplog.at_level(logging.ERROR):
            api.error("错误消息")
        assert "错误消息" in caplog.text

    def test_api_log_custom_level(self, api, caplog):
        """ExtensionAPI.log 自定义级别"""
        import logging

        with caplog.at_level(logging.DEBUG):
            api.log("DEBUG", "调试消息")
        assert "调试消息" in caplog.text

    def test_api_read_file(self, api, monkeypatch, tmp_path):
        """ExtensionAPI.read_file 读取扩展内文件"""
        from pycoder.extensions.host import ExtensionAPI

        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        (ext_dir / "data.txt").write_text("hello", encoding="utf-8")

        api2 = ExtensionAPI("test.ext", {})
        content = api2.read_file("data.txt")
        assert content == "hello"

    def test_api_read_file_nonexistent(self, api):
        """ExtensionAPI.read_file 文件不存在返回 None"""
        content = api.read_file("nonexistent.txt")
        assert content is None

    def test_api_list_files(self, api, monkeypatch, tmp_path):
        """ExtensionAPI.list_files 列出扩展内文件"""
        from pycoder.extensions.host import ExtensionAPI

        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        (ext_dir / "a.py").write_text("a", encoding="utf-8")
        (ext_dir / "b.py").write_text("b", encoding="utf-8")

        api2 = ExtensionAPI("test.ext", {})
        files = api2.list_files()
        assert len(files) == 2

    def test_api_list_files_empty(self, api):
        """ExtensionAPI.list_files 空目录"""
        files = api.list_files()
        assert files == []


class TestExtensionSandbox:
    """测试扩展沙箱"""

    @pytest.fixture
    def sandbox_dir(self, tmp_path, monkeypatch):
        """创建沙箱测试目录"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        return ext_dir

    def test_sandbox_is_installed_false(self, tmp_path, monkeypatch):
        """扩展未安装时 is_installed 返回 False"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("nonexistent.ext")
        assert sandbox.is_installed() is False

    def test_sandbox_is_installed_true(self, sandbox_dir):
        """扩展已安装时 is_installed 返回 True"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        # 创建 extension.py
        (sandbox_dir / "extension.py").write_text("# test", encoding="utf-8")
        assert sandbox.is_installed() is True

    def test_sandbox_load_manifest(self, sandbox_dir):
        """加载 manifest.json"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        sandbox = ExtensionSandbox("test.ext")
        result = sandbox.load_manifest()
        assert result is not None
        assert result["id"] == "test.ext"

    def test_sandbox_load_manifest_missing(self, sandbox_dir):
        """manifest 文件不存在返回 None"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.load_manifest() is None

    def test_sandbox_load_manifest_corrupted(self, sandbox_dir):
        """损坏的 manifest 返回 None"""
        from pycoder.extensions.host import ExtensionSandbox

        (sandbox_dir / "manifest.json").write_text("bad json", encoding="utf-8")

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.load_manifest() is None

    def test_sandbox_manifest_path_property(self, sandbox_dir):
        """manifest_path 属性"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.manifest_path.name == "manifest.json"

    def test_sandbox_code_path_property(self, sandbox_dir):
        """code_path 属性"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.code_path.name == "extension.py"

    @pytest.mark.asyncio
    async def test_sandbox_activate_not_installed(self, tmp_path, monkeypatch):
        """未安装扩展激活失败"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("nonexistent.ext")
        result = await sandbox.activate()
        assert result is False

    @pytest.mark.asyncio
    async def test_sandbox_activate_no_manifest(self, sandbox_dir):
        """无 manifest 激活失败"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        (sandbox_dir / "extension.py").write_text("# empty", encoding="utf-8")
        result = await sandbox.activate()
        assert result is False

    @pytest.mark.asyncio
    async def test_sandbox_activate_success(self, sandbox_dir):
        """成功激活扩展"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        result = await sandbox.activate()
        assert result is True

    @pytest.mark.asyncio
    async def test_sandbox_activate_with_activate_func(self, sandbox_dir):
        """激活扩展时调用 activate 函数"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            '''
name = "Test"
version = "1.0.0"
activated = False

def activate(api):
    global activated
    activated = True
    api.info("activated")
''',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        result = await sandbox.activate()
        assert result is True

    @pytest.mark.asyncio
    async def test_sandbox_deactivate(self, sandbox_dir):
        """停用扩展"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = sandbox.deactivate()
        assert result is True

    @pytest.mark.asyncio
    async def test_sandbox_get_available_functions(self, sandbox_dir):
        """获取扩展的公开函数列表"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            '''
name = "Test"
version = "1.0.0"

def my_func():
    return "hello"

def another_func(x):
    return x * 2
''',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        funcs = sandbox.get_available_functions()
        assert "my_func" in funcs
        assert "another_func" in funcs
        assert "activate" not in funcs
        assert "deactivate" not in funcs

    @pytest.mark.asyncio
    async def test_sandbox_execute_function(self, sandbox_dir):
        """执行扩展函数"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            '''
name = "Test"
version = "1.0.0"

def greet(name="World"):
    return f"Hello, {name}!"
''',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = await sandbox.execute_function("greet", {"name": "Tester"})
        assert result["success"] is True
        assert "Hello, Tester" in str(result["result"])

    @pytest.mark.asyncio
    async def test_sandbox_execute_nonexistent_function(self, sandbox_dir):
        """执行不存在的函数"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = await sandbox.execute_function("nonexistent_func")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_sandbox_execute_non_callable(self, sandbox_dir):
        """执行非可调用属性时返回其值"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = await sandbox.execute_function("name")
        assert result["success"] is True
        assert result["result"] == "Test"


class TestExtensionHostManager:
    """测试扩展主机管理器"""

    @pytest.fixture
    def host(self):
        from pycoder.extensions.host import ExtensionHostManager

        return ExtensionHostManager()

    def test_get_extension_host_singleton(self):
        """get_extension_host 返回单例"""
        from pycoder.extensions.host import get_extension_host

        h1 = get_extension_host()
        h2 = get_extension_host()
        assert h1 is h2

    def test_is_activated_initially_false(self, host):
        """初始状态扩展未激活"""
        assert host.is_activated("test.ext") is False

    def test_list_activated_empty(self, host):
        """初始状态激活列表为空"""
        assert host.list_activated() == []

    def test_count_activated_zero(self, host):
        """初始状态激活计数为 0"""
        assert host.count_activated() == 0

    def test_deactivate_not_activated(self, host):
        """停用未激活的扩展返回 False"""
        assert host.deactivate_extension("nonexistent") is False

    @pytest.mark.asyncio
    async def test_activate_extension(self, host, tmp_path, monkeypatch):
        """激活扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        result = await host.activate_extension("test.ext")
        assert result is True
        assert host.is_activated("test.ext") is True
        assert host.count_activated() == 1

    @pytest.mark.asyncio
    async def test_activate_already_activated(self, host, tmp_path, monkeypatch):
        """重复激活返回 True"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        await host.activate_extension("test.ext")
        result = await host.activate_extension("test.ext")
        assert result is True

    @pytest.mark.asyncio
    async def test_deactivate_extension(self, host, tmp_path, monkeypatch):
        """停用扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        await host.activate_extension("test.ext")
        result = host.deactivate_extension("test.ext")
        assert result is True
        assert host.is_activated("test.ext") is False

    @pytest.mark.asyncio
    async def test_activate_all(self, host, tmp_path, monkeypatch):
        """激活所有已启用的扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        for ext_id in ["ext1.test", "ext2.test"]:
            ext_dir = tmp_path / ext_id.replace("/", "_")
            ext_dir.mkdir()
            manifest = {"id": ext_id, "name": ext_id, "version": "1.0.0"}
            (ext_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (ext_dir / "extension.py").write_text(
                f'name = "{ext_id}"\nversion = "1.0.0"\n',
                encoding="utf-8",
            )

        installed = [
            {"id": "ext1.test", "enabled": True},
            {"id": "ext2.test", "enabled": True},
            {"id": "ext3.test", "enabled": False},  # 禁用，不应激活
        ]
        results = await host.activate_all(installed)
        assert len(results) == 2
        assert results["ext1.test"] is True
        assert results["ext2.test"] is True
        assert host.count_activated() == 2

    @pytest.mark.asyncio
    async def test_activate_all_disabled_skipped(self, host, tmp_path, monkeypatch):
        """禁用的扩展不被激活"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        ext_dir = tmp_path / "ext1.test"
        ext_dir.mkdir()
        manifest = {"id": "ext1.test", "name": "ext1", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ext_dir / "extension.py").write_text(
            'name = "ext1"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        installed = [{"id": "ext1.test", "enabled": False}]
        results = await host.activate_all(installed)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_deactivate_all(self, host, tmp_path, monkeypatch):
        """停用所有扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        ext_dir = tmp_path / "ext1.test"
        ext_dir.mkdir()
        manifest = {"id": "ext1.test", "name": "ext1", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ext_dir / "extension.py").write_text(
            'name = "ext1"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        await host.activate_extension("ext1.test")
        results = host.deactivate_all()
        assert results["ext1.test"] is True
        assert host.count_activated() == 0

    @pytest.mark.asyncio
    async def test_reload_extension(self, host, tmp_path, monkeypatch):
        """重新加载扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        ext_dir = tmp_path / "ext1.test"
        ext_dir.mkdir()
        manifest = {"id": "ext1.test", "name": "ext1", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ext_dir / "extension.py").write_text(
            'name = "ext1"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        await host.activate_extension("ext1.test")
        result = await host.reload_extension("ext1.test")
        assert result is True

    def test_get_sandbox(self, host):
        """获取扩展沙箱"""
        sandbox = host.get_sandbox("nonexistent")
        assert sandbox is None

    @pytest.mark.asyncio
    async def test_execute_not_activated(self, host):
        """执行未激活扩展的函数"""
        result = await host.execute("nonexistent", "func")
        assert result["success"] is False
        assert "未激活" in result["error"]

    @pytest.mark.asyncio
    async def test_activate_all_no_id_field(self, host):
        """activate_all 跳过无 id 的扩展"""
        installed = [{"enabled": True}]  # 无 id 字段
        results = await host.activate_all(installed)
        assert results == {}


