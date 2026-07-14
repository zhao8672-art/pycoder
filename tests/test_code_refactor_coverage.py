"""
code_refactor.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- RefactorResult: 数据类默认值
- RefactorEngine:
    - rename_symbol: 成功 / 文件不存在 / 符号未找到 / 语法错误 / 异常
    - extract_function: 成功 / 文件不存在 / 行号越界 / 异常
    - move_module: 成功 / 源文件不存在 / 异常; mock shutil.move, 检查 changes 列表
    - add_type_annotations: 无注解 / 文件不存在 / ImportError(astor) / 已有注解 / 异常
- get_refactor_engine: 单例
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python import code_refactor as refactor_mod
from pycoder.python.code_refactor import (
    RefactorResult,
    RefactorEngine,
    get_refactor_engine,
)


# ── RefactorResult ─────────────────────────────────────────


class TestRefactorResult:
    def test_defaults(self):
        r = RefactorResult(success=True)
        assert r.success is True
        assert r.file_path == ""
        assert r.operation == ""
        assert r.changes == []
        assert r.error == ""

    def test_with_fields(self):
        r = RefactorResult(
            success=False,
            error="err",
            file_path="/x",
            operation="op",
            changes=[{"a": 1}],
        )
        assert r.error == "err"
        assert r.file_path == "/x"
        assert r.operation == "op"
        assert r.changes == [{"a": 1}]


# ── rename_symbol ──────────────────────────────────────────


class TestRenameSymbol:
    def test_file_not_exists(self, tmp_path):
        engine = RefactorEngine()
        result = engine.rename_symbol(str(tmp_path / "nope.py"), "old", "new")
        assert result.success is False
        assert "文件不存在" in result.error

    def test_rename_success(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("def old_func():\n    return 1\n\n\nclass OldClass:\n    pass\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "old_func", "new_func")
        assert result.success is True
        assert result.operation == "rename"
        assert len(result.changes) >= 1
        # 验证文件已被修改
        content = path.read_text(encoding="utf-8")
        assert "new_func" in content
        assert "old_func" not in content

    def test_rename_class(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("class OldClass:\n    pass\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "OldClass", "NewClass")
        assert result.success is True
        content = path.read_text(encoding="utf-8")
        assert "NewClass" in content

    def test_rename_variable(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("old_var = 1\nprint(old_var)\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "old_var", "new_var")
        assert result.success is True
        content = path.read_text(encoding="utf-8")
        assert "new_var" in content

    def test_rename_arg(self, tmp_path):
        # 函数参数 arg 节点
        path = tmp_path / "mod.py"
        path.write_text("def f(old_arg):\n    return old_arg\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "old_arg", "new_arg")
        assert result.success is True

    def test_symbol_not_found(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("def func():\n    return 1\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "nonexistent", "new")
        assert result.success is False
        assert "未找到符号" in result.error

    def test_syntax_error(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("def broken(:\n    pass\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "broken", "fixed")
        assert result.success is False
        assert "语法错误" in result.error

    def test_general_exception(self, tmp_path, monkeypatch):
        path = tmp_path / "mod.py"
        path.write_text("def f():\n    return 1\n", encoding="utf-8")
        # 让 path.read_text 抛异常
        def raise_error(*args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "read_text", raise_error)
        engine = RefactorEngine()
        result = engine.rename_symbol(str(path), "f", "g")
        assert result.success is False


# ── extract_function ────────────────────────────────────────


class TestExtractFunction:
    def test_file_not_exists(self, tmp_path):
        engine = RefactorEngine()
        result = engine.extract_function(str(tmp_path / "nope.py"), 1, 3, "new_func")
        assert result.success is False
        assert "文件不存在" in result.error

    def test_extract_success(self, tmp_path):
        path = tmp_path / "mod.py"
        # 缩进 4 空格
        path.write_text(
            "def f():\n    a = 1\n    b = 2\n    c = a + b\n    return c\n",
            encoding="utf-8",
        )
        engine = RefactorEngine()
        # 提取 a=1, b=2, c=a+b 三行 (lines 2-4)
        result = engine.extract_function(str(path), 2, 4, "extracted")
        assert result.success is True
        assert result.operation == "extract_function"
        content = path.read_text(encoding="utf-8")
        assert "def extracted():" in content
        assert "extracted()" in content

    def test_extract_out_of_range(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("def f():\n    pass\n", encoding="utf-8")
        engine = RefactorEngine()
        # 行号超出范围
        result = engine.extract_function(str(path), 1, 100, "new_func")
        assert result.success is False
        assert "行号超出范围" in result.error

    def test_extract_start_line_too_small(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("x = 1\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.extract_function(str(path), 0, 1, "new_func")
        assert result.success is False
        assert "行号超出范围" in result.error

    def test_extract_exception(self, tmp_path, monkeypatch):
        path = tmp_path / "mod.py"
        path.write_text("def f():\n    a = 1\n", encoding="utf-8")
        # 让 Path.write_text 抛异常
        def raise_error(*args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "write_text", raise_error)
        engine = RefactorEngine()
        result = engine.extract_function(str(path), 1, 2, "new_func")
        assert result.success is False


# ── move_module ─────────────────────────────────────────────


class TestMoveModule:
    def test_source_not_exists(self, tmp_path):
        engine = RefactorEngine()
        result = engine.move_module(str(tmp_path / "nope.py"), str(tmp_path / "dest"))
        assert result.success is False
        assert "源文件不存在" in result.error

    def test_move_success(self, tmp_path, monkeypatch):
        # 准备源文件
        src = tmp_path / "oldmodule.py"
        src.write_text("x = 1\n", encoding="utf-8")
        dest = tmp_path / "dest"
        # mock shutil.move
        moved = {}

        def fake_move(src_path, dest_path):
            moved["src"] = src_path
            moved["dest"] = dest_path

        monkeypatch.setattr("shutil.move", fake_move)
        # mock project root rglob -> 空列表, 避免污染
        monkeypatch.chdir(tmp_path)
        # 创建一个引用 oldmodule 的文件
        (tmp_path / "main.py").write_text("from oldmodule import x\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.move_module(str(src), str(dest))
        assert result.success is True
        assert result.operation == "move_module"
        assert len(result.changes) >= 1
        assert "main.py" in result.changes[0]["file"]

    def test_move_no_imports(self, tmp_path, monkeypatch):
        src = tmp_path / "oldmodule.py"
        src.write_text("x = 1\n", encoding="utf-8")
        dest = tmp_path / "dest"
        monkeypatch.setattr("shutil.move", lambda s, d: None)
        monkeypatch.chdir(tmp_path)
        # 没有 .py 文件引用
        engine = RefactorEngine()
        result = engine.move_module(str(src), str(dest))
        assert result.success is True
        assert result.changes == []

    def test_move_with_unreadable_file(self, tmp_path, monkeypatch):
        src = tmp_path / "oldmodule.py"
        src.write_text("x = 1\n", encoding="utf-8")
        dest = tmp_path / "dest"
        monkeypatch.setattr("shutil.move", lambda s, d: None)
        monkeypatch.chdir(tmp_path)
        # 创建一个不可读的 .py 文件
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("from oldmodule import x\n", encoding="utf-8")
        # mock read_text 抛 UnicodeDecodeError
        original_read_text = Path.read_text

        def fake_read_text(self, *args, **kwargs):
            if self == bad_file:
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)
        engine = RefactorEngine()
        result = engine.move_module(str(src), str(dest))
        # 应静默跳过 bad_file, 仍成功
        assert result.success is True

    def test_move_exception(self, tmp_path, monkeypatch):
        src = tmp_path / "oldmodule.py"
        src.write_text("x = 1\n", encoding="utf-8")

        def raise_error(*args, **kwargs):
            raise RuntimeError("move failed")

        # mock Path.mkdir 抛异常 -> 通用 except 分支
        monkeypatch.setattr(Path, "mkdir", raise_error)
        engine = RefactorEngine()
        result = engine.move_module(str(src), str(tmp_path / "dest"))
        assert result.success is False


# ── add_type_annotations ────────────────────────────────────


class TestAddTypeAnnotations:
    def test_file_not_exists(self, tmp_path):
        engine = RefactorEngine()
        result = engine.add_type_annotations(str(tmp_path / "nope.py"))
        assert result.success is False
        assert "文件不存在" in result.error

    def test_add_annotations_no_astor(self, tmp_path, monkeypatch):
        # astor 未安装 -> ImportError
        path = tmp_path / "mod.py"
        path.write_text("def f(x):\n    return x\n", encoding="utf-8")
        # 让 import astor 失败
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "astor":
                raise ImportError("no astor")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        engine = RefactorEngine()
        result = engine.add_type_annotations(str(path))
        assert result.success is False
        assert "astor" in result.error

    def test_add_annotations_success(self, tmp_path, monkeypatch):
        # 测试 add_type_annotations 在 astor 可用时的情况
        pytest.importorskip("astor")
        path = tmp_path / "mod.py"
        path.write_text("def f(x):\n    return x\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.add_type_annotations(str(path))
        assert result.success is True
        assert result.operation == "add_types"
        assert result.changes[0]["annotations_added"] >= 1
        content = path.read_text(encoding="utf-8")
        assert "None" in content  # returns 被设为 None

    def test_add_annotations_already_typed(self, tmp_path, monkeypatch):
        pytest.importorskip("astor")
        path = tmp_path / "mod.py"
        path.write_text("def f(x: int) -> int:\n    return x\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.add_type_annotations(str(path))
        assert result.success is True
        assert result.changes[0]["annotations_added"] == 0

    def test_add_annotations_syntax_error(self, tmp_path):
        path = tmp_path / "mod.py"
        path.write_text("def broken(:\n    pass\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.add_type_annotations(str(path))
        assert result.success is False

    def test_add_annotations_with_async_function(self, tmp_path, monkeypatch):
        pytest.importorskip("astor")
        path = tmp_path / "mod.py"
        path.write_text("async def f(x):\n    return x\n", encoding="utf-8")
        engine = RefactorEngine()
        result = engine.add_type_annotations(str(path))
        assert result.success is True
        assert result.changes[0]["annotations_added"] >= 1


# ── get_refactor_engine 单例 ────────────────────────────────


class TestGetRefactorEngine:
    def test_returns_instance(self):
        # 重置单例
        import pycoder.python.code_refactor as mod
        mod._refactor = None
        engine = get_refactor_engine()
        assert isinstance(engine, RefactorEngine)
        # 再次调用应返回同一实例
        engine2 = get_refactor_engine()
        assert engine is engine2
        # 清理
        mod._refactor = None
