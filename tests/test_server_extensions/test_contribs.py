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
# 第四部分: contributions.py 模块测试
# ══════════════════════════════════════════════════════════


class TestContributionDataclasses:
    """测试贡献点 dataclass 模型"""

    def test_command_contribution_defaults(self):
        """CommandContribution 默认值"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test Command")
        assert cmd.id == "test.cmd"
        assert cmd.title == "Test Command"
        assert cmd.category == ""
        assert cmd.icon == ""
        assert cmd.enablement == ""
        assert cmd.keybinding == ""

    def test_command_contribution_full(self):
        """CommandContribution 完整字段"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(
            id="test.cmd",
            title="Test",
            category="Tools",
            icon="star",
            enablement="editorFocus",
            keybinding="ctrl+t",
        )
        assert cmd.category == "Tools"
        assert cmd.icon == "star"
        assert cmd.keybinding == "ctrl+t"

    def test_setting_contribution_defaults(self):
        """SettingContribution 默认值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.setting", title="Test Setting")
        assert s.id == "test.setting"
        assert s.title == "Test Setting"
        assert s.type == "string"
        assert s.default is None
        assert s.scope == "resource"

    def test_setting_contribution_enum(self):
        """SettingContribution 枚举值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="string",
            enum=["a", "b", "c"],
        )
        assert s.enum == ["a", "b", "c"]

    def test_keybinding_contribution(self):
        """KeybindingContribution 字段"""
        from pycoder.extensions.contributions import KeybindingContribution

        kb = KeybindingContribution(
            key="ctrl+shift+g",
            command="test.cmd",
            when="editorFocus",
            mac="cmd+shift+g",
        )
        assert kb.key == "ctrl+shift+g"
        assert kb.command == "test.cmd"
        assert kb.when == "editorFocus"
        assert kb.mac == "cmd+shift+g"

    def test_view_contribution(self):
        """ViewContribution 字段"""
        from pycoder.extensions.contributions import ViewContribution

        v = ViewContribution(id="test.view", name="Test View", type="webview", when="explorer")
        assert v.id == "test.view"
        assert v.name == "Test View"
        assert v.type == "webview"

    def test_menu_contribution(self):
        """MenuContribution 字段"""
        from pycoder.extensions.contributions import MenuContribution

        m = MenuContribution(command="test.cmd", group="navigation", when="editorFocus")
        assert m.command == "test.cmd"
        assert m.group == "navigation"

    def test_language_contribution(self):
        """LanguageContribution 字段"""
        from pycoder.extensions.contributions import LanguageContribution

        lang = LanguageContribution(
            id="python",
            extensions=[".py", ".pyw"],
            aliases=["Python", "py"],
        )
        assert lang.id == "python"
        assert lang.extensions == [".py", ".pyw"]
        assert lang.aliases == ["Python", "py"]

    def test_extension_contributions_is_empty(self):
        """ExtensionContributions 空判断"""
        from pycoder.extensions.contributions import ExtensionContributions

        ec = ExtensionContributions()
        assert ec.is_empty() is True

    def test_extension_contributions_not_empty(self):
        """ExtensionContributions 非空"""
        from pycoder.extensions.contributions import (
            CommandContribution,
            ExtensionContributions,
        )

        ec = ExtensionContributions()
        ec.commands.append(CommandContribution(id="test", title="Test"))
        assert ec.is_empty() is False


class TestCommandRegistry:
    """测试命令注册中心"""

    @pytest.fixture
    def registry(self):
        from pycoder.extensions.contributions import CommandRegistry

        return CommandRegistry()

    def test_register_command(self, registry):
        """注册命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        registry.register(cmd, ext_id="test_ext")
        assert registry.get("test.cmd") is not None

    def test_register_with_handler(self, registry):
        """注册命令并绑定处理器"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        handler = MagicMock(return_value="result")
        registry.register(cmd, handler=handler)
        result = registry.execute("test.cmd")
        assert result == "result"
        handler.assert_called_once()

    def test_execute_not_registered(self, registry):
        """执行未注册的命令抛出 KeyError"""
        with pytest.raises(KeyError, match="命令未注册"):
            registry.execute("nonexistent.cmd")

    def test_execute_no_handler(self, registry):
        """执行无处理器的命令抛出 KeyError"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        registry.register(cmd)
        with pytest.raises(KeyError, match="命令无处理器"):
            registry.execute("test.cmd")

    def test_get_nonexistent(self, registry):
        """获取不存在的命令返回 None"""
        assert registry.get("nonexistent") is None

    def test_list_commands(self, registry):
        """列出所有命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd1 = CommandContribution(id="test.cmd1", title="Test 1")
        cmd2 = CommandContribution(id="test.cmd2", title="Test 2")
        registry.register(cmd1, ext_id="ext1")
        registry.register(cmd2, ext_id="ext2")

        all_cmds = registry.list()
        assert len(all_cmds) == 2

    def test_list_commands_filtered(self, registry):
        """按扩展 ID 过滤命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd1 = CommandContribution(id="ext1.cmd", title="Cmd 1")
        cmd2 = CommandContribution(id="ext2.cmd", title="Cmd 2")
        registry.register(cmd1, ext_id="ext1")
        registry.register(cmd2, ext_id="ext2")

        filtered = registry.list(ext_id="ext1")
        assert len(filtered) == 1
        assert filtered[0].id == "ext1.cmd"

    def test_search_commands(self, registry):
        """搜索命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(
            id="pycoder.gitlens.blame",
            title="Git: 查看 Blame",
            category="Git",
        )
        registry.register(cmd, ext_id="pycoder.gitlens")

        results = registry.search("blame")
        assert len(results) == 1
        assert results[0]["id"] == "pycoder.gitlens.blame"

    def test_search_empty_query(self, registry):
        """空查询返回所有命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        registry.register(cmd, ext_id="test")
        results = registry.search("")
        assert len(results) == 1

    def test_count(self, registry):
        """统计命令数量"""
        from pycoder.extensions.contributions import CommandContribution

        assert registry.count() == 0
        registry.register(CommandContribution(id="test.cmd", title="Test"))
        assert registry.count() == 1

    def test_clear_extension(self, registry):
        """清除扩展的所有命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd1 = CommandContribution(id="ext1.cmd", title="Cmd 1")
        cmd2 = CommandContribution(id="ext2.cmd", title="Cmd 2")
        registry.register(cmd1, ext_id="ext1")
        registry.register(cmd2, ext_id="ext2")

        removed = registry.clear_extension("ext1")
        assert removed == 1
        assert registry.get("ext1.cmd") is None
        assert registry.get("ext2.cmd") is not None

    def test_execute_with_args(self, registry):
        """执行命令时传递参数"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        handler = MagicMock(return_value="done")
        registry.register(cmd, handler=handler)

        registry.execute("test.cmd", "arg1", key="value")
        handler.assert_called_once_with("arg1", key="value")


class TestSettingsRegistry:
    """测试设置注册中心"""

    @pytest.fixture
    def registry(self):
        from pycoder.extensions.contributions import SettingsRegistry

        return SettingsRegistry()

    def test_register_setting(self, registry):
        """注册设置项"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test Setting",
            type="boolean",
            default=True,
        )
        registry.register(s, ext_id="test_ext")
        assert registry.get("test.setting") is True

    def test_get_default_value(self, registry):
        """获取设置默认值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="string",
            default="hello",
        )
        registry.register(s)
        assert registry.get("test.setting") == "hello"

    def test_get_unregistered_returns_none(self, registry):
        """获取未注册的设置返回 None"""
        assert registry.get("nonexistent") is None

    def test_set_valid_value(self, registry):
        """设置有效值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="string",
            default="old",
        )
        registry.register(s)
        assert registry.set("test.setting", "new") is True
        assert registry.get("test.setting") == "new"

    def test_set_unregistered_key(self, registry):
        """设置未注册的 key 返回 False"""
        assert registry.set("nonexistent", "value") is False

    def test_set_type_mismatch(self, registry):
        """类型不匹配时设置失败"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="boolean",
            default=True,
        )
        registry.register(s)
        assert registry.set("test.setting", "not-a-bool") is False

    def test_set_number_type(self, registry):
        """number 类型接受 int 和 float"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.num",
            title="Test",
            type="number",
            default=0,
        )
        registry.register(s)
        assert registry.set("test.num", 42) is True
        assert registry.set("test.num", 3.14) is True

    def test_set_enum_validation(self, registry):
        """枚举值校验"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.enum",
            title="Test",
            type="string",
            enum=["a", "b", "c"],
            default="a",
        )
        registry.register(s)
        assert registry.set("test.enum", "b") is True
        assert registry.set("test.enum", "d") is False

    def test_set_range_validation_min(self, registry):
        """最小值校验"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.range",
            title="Test",
            type="number",
            minimum=0,
            maximum=100,
            default=50,
        )
        registry.register(s)
        assert registry.set("test.range", -1) is False
        assert registry.set("test.range", 50) is True

    def test_set_range_validation_max(self, registry):
        """最大值校验"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.range",
            title="Test",
            type="number",
            minimum=0,
            maximum=100,
            default=50,
        )
        registry.register(s)
        assert registry.set("test.range", 101) is False
        assert registry.set("test.range", 100) is True

    def test_list_settings(self, registry):
        """列出设置项"""
        from pycoder.extensions.contributions import SettingContribution

        s1 = SettingContribution(id="ext1.setting", title="S1", type="boolean", default=True)
        s2 = SettingContribution(id="ext2.setting", title="S2", type="string", default="x")
        registry.register(s1, ext_id="ext1")
        registry.register(s2, ext_id="ext2")

        all_settings = registry.list_settings()
        assert len(all_settings) == 2

    def test_list_settings_filtered(self, registry):
        """按扩展过滤设置"""
        from pycoder.extensions.contributions import SettingContribution

        s1 = SettingContribution(id="ext1.setting", title="S1", type="boolean", default=True)
        s2 = SettingContribution(id="ext2.setting", title="S2", type="string", default="x")
        registry.register(s1, ext_id="ext1")
        registry.register(s2, ext_id="ext2")

        filtered = registry.list_settings(ext_id="ext1")
        assert len(filtered) == 1
        assert filtered[0]["id"] == "ext1.setting"

    def test_export_json(self, registry):
        """导出设置为 JSON"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.s", title="Test", type="string", default="v")
        registry.register(s)
        registry.set("test.s", "custom")

        exported = registry.export_json()
        assert exported["test.s"] == "custom"

    def test_import_json(self, registry):
        """从 JSON 导入设置"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.s", title="Test", type="string", default="v")
        registry.register(s)

        count = registry.import_json({"test.s": "imported"})
        assert count == 1
        assert registry.get("test.s") == "imported"

    def test_clear_extension(self, registry):
        """清除扩展的所有设置"""
        from pycoder.extensions.contributions import SettingContribution

        s1 = SettingContribution(id="ext1.s", title="S1", type="string", default="a")
        s2 = SettingContribution(id="ext2.s", title="S2", type="string", default="b")
        registry.register(s1, ext_id="ext1")
        registry.register(s2, ext_id="ext2")

        removed = registry.clear_extension("ext1")
        assert removed == 1
        assert registry.get("ext1.s") is None
        assert registry.get("ext2.s") == "b"

    def test_register_preserves_existing_value(self, registry):
        """注册设置时保留已有值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.s", title="Test", type="string", default="default")
        registry.register(s)
        registry.set("test.s", "custom")

        # 重新注册（模拟重新加载）
        s2 = SettingContribution(id="test.s", title="Test", type="string", default="new_default")
        registry.register(s2)
        assert registry.get("test.s") == "custom"  # 保留旧值


class TestParseContributions:
    """测试从 manifest 解析贡献点"""

    def test_parse_empty_manifest(self):
        """空 manifest 返回空贡献"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        result = parse_contributions_from_manifest({})
        assert result.is_empty() is True

    def test_parse_no_contributes(self):
        """无 contributes 字段返回空"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        result = parse_contributions_from_manifest({"id": "test"})
        assert result.is_empty() is True

    def test_parse_commands(self):
        """解析 commands"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "commands": [
                    {"command": "test.cmd", "title": "Test", "category": "Tools"},
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.commands) == 1
        assert result.commands[0].id == "test.cmd"
        assert result.commands[0].title == "Test"
        assert result.commands[0].category == "Tools"

    def test_parse_settings(self):
        """解析 settings"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "settings": [
                    {
                        "id": "test.enabled",
                        "title": "Enable",
                        "type": "boolean",
                        "default": True,
                    },
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.settings) == 1
        assert result.settings[0].id == "test.enabled"
        assert result.settings[0].type == "boolean"
        assert result.settings[0].default is True

    def test_parse_keybindings(self):
        """解析 keybindings"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "keybindings": [
                    {
                        "key": "ctrl+shift+g",
                        "command": "test.cmd",
                        "when": "editorFocus",
                    },
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.keybindings) == 1
        assert result.keybindings[0].key == "ctrl+shift+g"

    def test_parse_views(self):
        """解析 views"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "views": [
                    {"id": "test.view", "name": "Test View", "type": "tree"},
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.views) == 1
        assert result.views[0].id == "test.view"

    def test_parse_menus(self):
        """解析 menus"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "menus": [
                    {"command": "test.cmd", "group": "navigation"},
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.menus) == 1
        assert result.menus[0].command == "test.cmd"

    def test_parse_languages(self):
        """解析 languages"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "languages": [
                    {
                        "id": "python",
                        "extensions": [".py"],
                        "aliases": ["Python"],
                    },
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.languages) == 1
        assert result.languages[0].id == "python"


class TestGlobalRegistries:
    """测试全局注册中心单例"""

    def test_get_command_registry_returns_singleton(self):
        """get_command_registry 返回同一个实例"""
        from pycoder.extensions.contributions import get_command_registry

        r1 = get_command_registry()
        r2 = get_command_registry()
        assert r1 is r2

    def test_get_settings_registry_returns_singleton(self):
        """get_settings_registry 返回同一个实例"""
        from pycoder.extensions.contributions import get_settings_registry

        r1 = get_settings_registry()
        r2 = get_settings_registry()
        assert r1 is r2

    def test_register_extension_contributions(self):
        """register_extension_contributions 将贡献注册到全局注册中心"""
        from pycoder.extensions.contributions import (
            get_command_registry,
            get_settings_registry,
            register_extension_contributions,
        )

        manifest = {
            "contributes": {
                "commands": [
                    {"command": "test.cmd", "title": "Test Command"},
                ],
                "settings": [
                    {
                        "id": "test.setting",
                        "title": "Test Setting",
                        "type": "boolean",
                        "default": True,
                    },
                ],
            }
        }

        result = register_extension_contributions("test_ext", manifest)
        assert len(result.commands) == 1
        assert len(result.settings) == 1

        cmd_reg = get_command_registry()
        assert cmd_reg.get("test.cmd") is not None

        set_reg = get_settings_registry()
        assert set_reg.get("test.setting") is True

        # 清理
        cmd_reg.clear_extension("test_ext")
        set_reg.clear_extension("test_ext")

    def test_unregister_extension_contributions(self):
        """unregister_extension_contributions 清除扩展贡献"""
        from pycoder.extensions.contributions import (
            get_command_registry,
            get_settings_registry,
            register_extension_contributions,
            unregister_extension_contributions,
        )

        manifest = {
            "contributes": {
                "commands": [
                    {"command": "test.cmd", "title": "Test"},
                ],
                "settings": [
                    {
                        "id": "test.setting",
                        "title": "Test",
                        "type": "string",
                        "default": "x",
                    },
                ],
            }
        }

        register_extension_contributions("test_ext", manifest)
        result = unregister_extension_contributions("test_ext")
        assert result["commands_removed"] == 1
        assert result["settings_removed"] == 1

        cmd_reg = get_command_registry()
        assert cmd_reg.get("test.cmd") is None


