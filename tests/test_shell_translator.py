"""P0-1: 跨平台命令翻译器单元测试"""
from __future__ import annotations

import pytest

from pycoder.core.shell_translator import (
    COMMAND_MAP,
    ShellTranslator,
    TranslationResult,
    detect_platform,
    translate_command,
    translate_to_current_platform,
)


class TestDetectPlatform:
    def test_returns_string(self):
        p = detect_platform()
        assert p in ("windows", "linux", "mac")


class TestShellTranslatorBasic:
    def test_empty_command(self):
        t = ShellTranslator()
        r = t.translate("")
        assert r.original == ""
        assert r.translated == ""
        assert not r.changed

    def test_same_platform_no_translation(self):
        t = ShellTranslator()
        r = t.translate("ls -la", source="linux", target="linux")
        assert not r.changed
        assert r.translated == "ls -la"

    def test_ls_to_windows(self):
        t = ShellTranslator()
        r = t.translate("ls -la", source="linux", target="windows")
        assert r.changed
        assert "dir" in r.translated
        assert "ls" in r.mappings_applied

    def test_cat_to_windows(self):
        t = ShellTranslator()
        r = t.translate("cat README.md", source="linux", target="windows")
        assert r.changed
        assert "type" in r.translated
        assert "cat" in r.mappings_applied

    def test_grep_to_windows(self):
        t = ShellTranslator()
        r = t.translate("grep -r 'TODO' src/", source="linux", target="windows")
        assert r.changed
        assert "findstr" in r.translated

    def test_ps_to_windows(self):
        t = ShellTranslator()
        r = t.translate("ps aux", source="linux", target="windows")
        assert r.changed
        assert "tasklist" in r.translated

    def test_rm_to_windows(self):
        t = ShellTranslator()
        r = t.translate("rm -rf build/", source="linux", target="windows")
        assert r.changed
        assert "del" in r.translated

    def test_pwd_to_windows(self):
        t = ShellTranslator()
        r = t.translate("pwd", source="linux", target="windows")
        assert r.changed
        assert "cd" in r.translated

    def test_clear_to_windows(self):
        t = ShellTranslator()
        r = t.translate("clear", source="linux", target="windows")
        assert r.changed
        assert "cls" in r.translated

    def test_ifconfig_to_windows(self):
        t = ShellTranslator()
        r = t.translate("ifconfig", source="linux", target="windows")
        assert r.changed
        assert "ipconfig" in r.translated

    def test_wget_to_windows(self):
        t = ShellTranslator()
        r = t.translate("wget https://example.com", source="linux", target="windows")
        assert r.changed
        assert "curl" in r.translated


class TestShellTranslatorArgs:
    def test_args_preserved(self):
        t = ShellTranslator()
        r = t.translate("ls -la /home/user", source="linux", target="windows")
        assert "-la" in r.translated
        assert "/home/user" in r.translated

    def test_unknown_command_unchanged(self):
        t = ShellTranslator()
        r = t.translate("my_custom_cmd --flag", source="linux", target="windows")
        assert r.translated == "my_custom_cmd --flag"

    def test_pipe_chains(self):
        t = ShellTranslator()
        r = t.translate("ps aux | grep python", source="linux", target="windows")
        assert r.changed
        assert "tasklist" in r.translated
        assert "findstr" in r.translated

    def test_quoted_args(self):
        t = ShellTranslator()
        r = t.translate('grep "hello world" file.txt', source="linux", target="windows")
        assert '"hello world"' in r.translated


class TestCustomMapping:
    def test_add_custom_mapping(self):
        from pycoder.core.shell_translator import add_custom_mapping
        add_custom_mapping("myapp", {"windows": "myapp.exe", "linux": "myapp"})
        t = ShellTranslator()
        r = t.translate("myapp --run", source="linux", target="windows")
        assert "myapp.exe" in r.translated


class TestConvenienceFunctions:
    def test_translate_command(self):
        r = translate_command("ls", source="linux", target="windows")
        assert isinstance(r, TranslationResult)
        assert r.changed

    def test_translate_to_current_platform(self):
        r = translate_to_current_platform("ls")
        assert isinstance(r, TranslationResult)


class TestCommandMapIntegrity:
    def test_all_commands_have_all_platforms(self):
        for cmd, mapping in COMMAND_MAP.items():
            assert "windows" in mapping, f"{cmd} missing windows"
            assert "linux" in mapping, f"{cmd} missing linux"
            assert "mac" in mapping, f"{cmd} missing mac"
