"""
multilang_debugger.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- MultiLangDebugger.debug: 各语言分支 + 不支持的语言
- list_debuggable: 返回可调试语言列表
- _debug_python: mock subprocess.run, 覆盖成功/失败 + 断点插入
- _debug_java: chdir 到 tmp_path 避免污染, mock subprocess.run
- _debug_go: mock subprocess.run, 覆盖成功/失败
- _debug_js: mock subprocess.run, 覆盖成功/失败 + 断点插入
- _debug_ts: 直接返回固定信息
- get_multilang_debugger: 单例
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python import multilang_debugger as md_mod
from pycoder.python.multilang_debugger import (
    MultiLangDebugger,
    get_multilang_debugger,
)


# ── list_debuggable ────────────────────────────────────────


class TestListDebuggable:
    def test_returns_all_languages(self):
        dbg = MultiLangDebugger()
        langs = dbg.list_debuggable()
        assert "python" in langs
        assert "java" in langs
        assert "go" in langs
        assert "javascript" in langs
        assert "typescript" in langs
        assert len(langs) == 5


# ── debug (dispatcher) ─────────────────────────────────────


class TestDebugDispatcher:
    def test_unsupported_language(self):
        dbg = MultiLangDebugger()
        result = dbg.debug("ruby", "puts 'hi'", [1])
        assert result["success"] is False
        assert "不支持 ruby" in result["error"]

    def test_dispatches_to_python(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg.debug("python", "print('hi')", [])
        assert result["language"] == "python"

    def test_dispatches_to_java(self, monkeypatch, tmp_path):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        monkeypatch.chdir(tmp_path)
        result = dbg.debug("java", "class Main {}", [])
        assert result["language"] == "java"

    def test_dispatches_to_go(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg.debug("go", "package main", [])
        assert result["language"] == "go"

    def test_dispatches_to_javascript(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg.debug("javascript", "console.log('hi')", [])
        assert result["language"] == "javascript"

    def test_dispatches_to_typescript(self):
        dbg = MultiLangDebugger()
        result = dbg.debug("typescript", "console.log('hi')", [])
        assert result["language"] == "typescript"
        assert result["success"] is True


# ── _debug_python ──────────────────────────────────────────


class TestDebugPython:
    def test_success_no_breakpoints(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg._debug_python("print('hi')", [])
        assert result["success"] is True
        assert "ok" in result["output"]
        assert result["language"] == "python"
        assert result["breakpoints"] == []

    def test_failure(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg._debug_python("invalid code", [])
        assert result["success"] is False
        assert "error" in result["error"]

    def test_with_breakpoints(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        # 在第 2 行设置断点
        code = "line1\nline2\nline3\n"
        result = dbg._debug_python(code, [2])
        assert result["success"] is True
        assert 2 in result["breakpoints"]

    def test_breakpoint_out_of_range_skipped(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        code = "line1\n"
        # 断点行号 99 超出代码行数 -> 应被跳过
        result = dbg._debug_python(code, [99])
        assert result["success"] is True

    def test_multiple_breakpoints_inserted_in_desc_order(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        code = "a\nb\nc\nd\n"
        # 多个断点
        result = dbg._debug_python(code, [2, 4])
        assert result["success"] is True
        assert 2 in result["breakpoints"]
        assert 4 in result["breakpoints"]


# ── _debug_java ────────────────────────────────────────────


class TestDebugJava:
    def test_compile_success(self, monkeypatch, tmp_path):
        dbg = MultiLangDebugger()
        # mock javac 成功
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        monkeypatch.chdir(tmp_path)
        result = dbg._debug_java("class Main { public static void main(String[] a) {} }", [])
        assert result["success"] is True
        assert result["language"] == "java"
        assert "jdb" in result["hint"]
        # 应已创建 Main.java
        assert (tmp_path / "Main.java").exists()

    def test_compile_failure(self, monkeypatch, tmp_path):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=1, stdout="", stderr="syntax error")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        monkeypatch.chdir(tmp_path)
        result = dbg._debug_java("invalid java", [])
        assert result["success"] is False
        assert "编译失败" in result["error"]

    def test_main_java_already_exists(self, monkeypatch, tmp_path):
        dbg = MultiLangDebugger()
        # 预先创建 Main.java
        (tmp_path / "Main.java").write_text("class Main {}", encoding="utf-8")
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        monkeypatch.chdir(tmp_path)
        result = dbg._debug_java("new code", [])
        # 应不覆盖已存在的 Main.java (代码检查 not exists)
        assert result["success"] is True


# ── _debug_go ──────────────────────────────────────────────


class TestDebugGo:
    def test_compile_success(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg._debug_go("package main", [])
        assert result["success"] is True
        assert result["language"] == "go"
        assert "dlv" in result["hint"]

    def test_compile_failure(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=1, stdout="", stderr="syntax error")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg._debug_go("invalid go", [])
        assert result["success"] is False
        assert "编译失败" in result["error"]


# ── _debug_js ──────────────────────────────────────────────


class TestDebugJs:
    def test_success_no_breakpoints(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg._debug_js("console.log('hi')", [])
        assert result["success"] is True
        assert "ok" in result["output"]
        assert result["language"] == "javascript"

    def test_failure(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = dbg._debug_js("invalid code", [])
        assert result["success"] is False
        assert "error" in result["error"]

    def test_with_breakpoints(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        code = "console.log('a')\nconsole.log('b')\n"
        # 在第 1 行设置断点
        result = dbg._debug_js(code, [1])
        assert result["success"] is True

    def test_breakpoint_out_of_range(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        code = "console.log('a')\n"
        # bp=99 超出范围 -> 跳过
        result = dbg._debug_js(code, [99])
        assert result["success"] is True

    def test_multiple_breakpoints(self, monkeypatch):
        dbg = MultiLangDebugger()
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(md_mod.subprocess, "run", lambda *a, **k: mock_result)
        code = "a\nb\nc\nd\n"
        # 多个断点
        result = dbg._debug_js(code, [1, 3])
        assert result["success"] is True


# ── _debug_ts ──────────────────────────────────────────────


class TestDebugTs:
    def test_returns_info(self):
        dbg = MultiLangDebugger()
        result = dbg._debug_ts("any code", [1, 2])
        assert result["success"] is True
        assert result["language"] == "typescript"
        assert "tsc" in result["output"]
        assert "ts-node" in result["hint"]


# ── get_multilang_debugger 单例 ─────────────────────────────


class TestGetMultilangDebugger:
    def test_returns_instance(self):
        # 重置单例
        md_mod._debugger = None
        dbg = get_multilang_debugger()
        assert isinstance(dbg, MultiLangDebugger)
        # 再次调用返回同一实例
        dbg2 = get_multilang_debugger()
        assert dbg is dbg2
        # 清理
        md_mod._debugger = None
