"""P1-2 测试：工具调用 JSON Schema 校验

验证：
- parse_tool_calls 支持 Markdown JSON / 裸 JSON / 单工具调用
- XML 格式不再被解析（返回空列表）
- Schema 校验拒绝缺失字段或类型错误
- tool_schema 模块的 validate_tool_calls 与构建函数
- parse_tool_calls_legacy_xml 仍可解析 XML（标记废弃）
"""
from __future__ import annotations

import warnings

import pytest


# ══════════════════════════════════════════════════════════
# parse_tool_calls 测试
# ══════════════════════════════════════════════════════════


class TestParseToolCalls:
    def test_markdown_json_block(self):
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '''Thought...
```json
{"tool_calls": [{"name": "read_file", "params": {"path": "/tmp/x"}}]}
```'''
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["params"]["path"] == "/tmp/x"

    def test_bare_json(self):
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '{"tool_calls": [{"name": "ls", "params": {}}]}'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_single_tool_call_without_wrapper(self):
        """LLM 直接返回单个工具调用 {"name": "...", "params": {...}}"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '{"name": "ls", "params": {}}'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_multiple_tool_calls(self):
        """单次响应包含多个工具调用"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '''```json
{"tool_calls": [
    {"name": "read_file", "params": {"path": "a.py"}},
    {"name": "write_file", "params": {"path": "b.py", "content": "x"}}
]}
```'''
        calls = parse_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["name"] == "read_file"
        assert calls[1]["name"] == "write_file"

    def test_empty_text(self):
        from pycoder.server.services.agent_tools import parse_tool_calls
        assert parse_tool_calls("") == []
        assert parse_tool_calls("   ") == []

    def test_no_json_returns_empty(self):
        from pycoder.server.services.agent_tools import parse_tool_calls
        assert parse_tool_calls("no json here, just text") == []

    def test_invalid_json_returns_empty(self):
        from pycoder.server.services.agent_tools import parse_tool_calls
        assert parse_tool_calls("```json\n{invalid\n```") == []

    def test_xml_format_no_longer_supported(self):
        """P1-2: XML 标签格式不再被 parse_tool_calls 解析"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '<tool name="ls"><parameter name="path">/tmp</parameter></tool>'
        calls = parse_tool_calls(text)
        assert calls == []

    def test_schema_validation_rejects_missing_name(self):
        """缺少 name 字段应被 Schema 校验拒绝"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '```json\n{"tool_calls": [{"params": {}}]}\n```'
        calls = parse_tool_calls(text)
        assert calls == []

    def test_schema_validation_rejects_missing_params(self):
        """缺少 params 字段应被 Schema 校验拒绝"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '```json\n{"tool_calls": [{"name": "ls"}]}\n```'
        calls = parse_tool_calls(text)
        assert calls == []

    def test_schema_validation_rejects_non_string_name(self):
        """name 字段类型错误应被拒绝"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '```json\n{"tool_calls": [{"name": 123, "params": {}}]}\n```'
        calls = parse_tool_calls(text)
        assert calls == []

    def test_thought_field_optional(self):
        """thought 字段可选，不影响解析"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '''```json
{"thought": "let me check", "tool_calls": [{"name": "ls", "params": {}}]}
```'''
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_first_valid_json_block_wins(self):
        """存在多个 JSON 代码块时，第一个有效的胜出"""
        from pycoder.server.services.agent_tools import parse_tool_calls
        text = '''```json
{"tool_calls": [{"name": "first", "params": {}}]}
```
```json
{"tool_calls": [{"name": "second", "params": {}}]}
```'''
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "first"


# ══════════════════════════════════════════════════════════
# tool_schema 模块测试
# ══════════════════════════════════════════════════════════


class TestToolSchema:
    def test_validate_tool_calls_accepts_valid(self):
        from pycoder.server.services.tool_schema import validate_tool_calls
        data = {"tool_calls": [{"name": "ls", "params": {}}]}
        calls = validate_tool_calls(data)
        assert len(calls) == 1
        assert calls[0]["name"] == "ls"

    def test_validate_tool_calls_rejects_missing_tool_calls(self):
        from pycoder.server.services.tool_schema import validate_tool_calls
        with pytest.raises(ValueError, match="tool_calls"):
            validate_tool_calls({"thought": "no calls"})

    def test_validate_tool_calls_rejects_unknown_field(self):
        """additionalProperties=False 应拒绝未知字段"""
        from pycoder.server.services.tool_schema import validate_tool_calls
        with pytest.raises(ValueError):
            validate_tool_calls({
                "tool_calls": [],
                "unknown_field": "x",
            })

    def test_build_tool_calls_json(self):
        from pycoder.server.services.tool_schema import build_tool_calls_json
        call = build_tool_calls_json("ls", {"path": "."})
        assert call == {"name": "ls", "params": {"path": "."}}

    def test_build_tool_calls_response(self):
        from pycoder.server.services.tool_schema import (
            build_tool_calls_response, build_tool_calls_json,
        )
        calls = [build_tool_calls_json("ls", {})]
        response = build_tool_calls_response(calls, thought="checking")
        assert response["thought"] == "checking"
        assert response["tool_calls"] == calls


# ══════════════════════════════════════════════════════════
# parse_tool_calls_legacy_xml 测试
# ══════════════════════════════════════════════════════════


class TestParseToolCallsLegacyXml:
    def test_legacy_xml_still_parses(self):
        """旧 XML 解析函数仍可工作（向后兼容）"""
        from pycoder.server.services.agent_tools import parse_tool_calls_legacy_xml
        text = '<tool name="write_file"><parameter name="path">a.py</parameter><parameter name="content">c</parameter></tool>'
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            calls = parse_tool_calls_legacy_xml(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "write_file"
        assert calls[0]["params"]["path"] == "a.py"
        # 应触发废弃警告
        assert any(issubclass(wi.category, DeprecationWarning) for wi in w), (
            "parse_tool_calls_legacy_xml 应触发 DeprecationWarning"
        )

    def test_legacy_xml_returns_empty_on_no_match(self):
        from pycoder.server.services.agent_tools import parse_tool_calls_legacy_xml
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert parse_tool_calls_legacy_xml("no xml here") == []
