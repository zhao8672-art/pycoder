"""multilang_tools 模块覆盖率测试 — MCP 多语言执行工具

覆盖 pycoder.server.mcp.multilang_tools.register_all 注册的两个工具：
- execute_multilang: 编译并运行多语言代码（委托给 multilang_executor）
- list_languages: 列出可用语言运行时

测试策略：mock execute_multilang / list_available / LANG_CONFIG 模块级名称，
避免触发真实的编译器检测。
"""
from __future__ import annotations

import pytest

import pycoder.server.mcp.multilang_tools as multilang_mod
from pycoder.server.mcp.multilang_tools import register_all


@pytest.fixture
def captured_handlers():
    """捕获注册的 handler"""
    handlers: dict[str, object] = {}

    def register_fn(**kwargs):
        handlers[kwargs["name"]] = kwargs["handler"]

    register_all(register_fn)
    return handlers


class TestRegisterAll:
    def test_registers_two_tools(self):
        names: list[str] = []

        def register_fn(**kwargs):
            names.append(kwargs["name"])

        register_all(register_fn)
        assert set(names) == {"execute_multilang", "list_languages"}


class TestExecuteMultilang:
    async def test_execute_success(self, captured_handlers, monkeypatch):
        async def fake_exec(language, code, timeout):
            return {"success": True, "language": language, "stdout": "result"}

        monkeypatch.setattr(multilang_mod, "execute_multilang", fake_exec)
        result = await captured_handlers["execute_multilang"](
            {"language": "python", "code": "print('hi')"}
        )
        assert result["success"] is True
        assert result["language"] == "python"

    async def test_execute_uses_defaults(self, captured_handlers, monkeypatch):
        """未提供参数时使用默认值：language=python, code='', timeout=30"""
        captured: dict = {}

        async def fake_exec(language, code, timeout):
            captured.update(language=language, code=code, timeout=timeout)
            return {"success": True}

        monkeypatch.setattr(multilang_mod, "execute_multilang", fake_exec)
        result = await captured_handlers["execute_multilang"]({})
        assert result["success"] is True
        assert captured["language"] == "python"
        assert captured["code"] == ""
        assert captured["timeout"] == 30

    async def test_execute_custom_timeout(self, captured_handlers, monkeypatch):
        captured: dict = {}

        async def fake_exec(language, code, timeout):
            captured["timeout"] = timeout
            return {"success": True}

        monkeypatch.setattr(multilang_mod, "execute_multilang", fake_exec)
        await captured_handlers["execute_multilang"](
            {"language": "go", "code": "x", "timeout": 60}
        )
        assert captured["timeout"] == 60

    async def test_execute_failure(self, captured_handlers, monkeypatch):
        async def fake_exec(language, code, timeout):
            return {"success": False, "error": "compile error"}

        monkeypatch.setattr(multilang_mod, "execute_multilang", fake_exec)
        result = await captured_handlers["execute_multilang"](
            {"language": "rust", "code": "fn main() {}"}
        )
        assert result["success"] is False
        assert "compile error" in result["error"]

    async def test_execute_delegates_returned_dict_intact(
        self, captured_handlers, monkeypatch
    ):
        """handler 应直接返回 execute_multilang 的结果，不做修改"""
        expected = {"success": True, "language": "bash", "stdout": "ok", "exit_code": 0}

        async def fake_exec(language, code, timeout):
            return expected

        monkeypatch.setattr(multilang_mod, "execute_multilang", fake_exec)
        result = await captured_handlers["execute_multilang"](
            {"language": "bash", "code": "echo ok"}
        )
        assert result == expected


class TestListLanguages:
    async def test_list_success(self, captured_handlers, monkeypatch):
        monkeypatch.setattr(multilang_mod, "list_available", lambda: ["python", "go"])
        monkeypatch.setattr(
            multilang_mod,
            "LANG_CONFIG",
            {"python": {}, "go": {}, "rust": {}},
        )
        result = await captured_handlers["list_languages"]({})
        assert result["success"] is True
        assert "python" in result["languages"]
        assert result["count"] == 2
        # all_supported 应包含所有 LANG_CONFIG 键
        assert set(result["all_supported"]) == {"python", "go", "rust"}

    async def test_list_empty(self, captured_handlers, monkeypatch):
        monkeypatch.setattr(multilang_mod, "list_available", lambda: [])
        monkeypatch.setattr(multilang_mod, "LANG_CONFIG", {})
        result = await captured_handlers["list_languages"]({})
        assert result["success"] is True
        assert result["count"] == 0
        assert result["languages"] == []

    async def test_list_ignores_args(self, captured_handlers, monkeypatch):
        """list_languages 不接受任何参数，args 不影响结果"""
        monkeypatch.setattr(multilang_mod, "list_available", lambda: ["python"])
        monkeypatch.setattr(multilang_mod, "LANG_CONFIG", {"python": {}})
        result = await captured_handlers["list_languages"]({"foo": "bar", "baz": 1})
        assert result["success"] is True
        assert result["count"] == 1

    async def test_list_count_matches_languages(self, captured_handlers, monkeypatch):
        langs = ["python", "javascript", "go", "rust"]
        monkeypatch.setattr(multilang_mod, "list_available", lambda: list(langs))
        monkeypatch.setattr(
            multilang_mod, "LANG_CONFIG", {k: {} for k in langs}
        )
        result = await captured_handlers["list_languages"]({})
        assert result["count"] == len(result["languages"])
