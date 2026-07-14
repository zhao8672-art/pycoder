"""AgentOrchestrator 单元测试 — 配置常量 + agent_chat_stream

注意: _execute_tool / _execute_tool_with_retry / _parse_tool_calls 已迁移
到 UnifiedAgentEngine（unified_agent.py），不再在 agent_orchestrator 模块层暴露。
本测试聚焦于仍在 agent_orchestrator 中导出的配置常量和 agent_chat_stream 入口。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.agent_orchestrator import (
    AGENT_SYSTEM_PROMPT,
    ALLOWED_COMMANDS,
    MAX_ITERATIONS,
    MAX_RETRIES,
    TOOL_TIMEOUT,
    WORKSPACE,
    agent_chat_stream,
)


# ── 配置常量测试 ──────────────────────────────────────────


class TestConfigConstants:
    """配置常量验证"""

    def test_allowed_commands_includes_essentials(self):
        for cmd in ["python", "pip", "git", "pytest", "ruff"]:
            assert cmd in ALLOWED_COMMANDS

    def test_allowed_commands_excludes_dangerous(self):
        for cmd in ["rm", "del", "format", "shutdown", "reboot"]:
            assert cmd not in ALLOWED_COMMANDS

    def test_workspace_is_path(self):
        assert isinstance(WORKSPACE, Path)

    def test_max_iterations_reasonable(self):
        assert 5 <= MAX_ITERATIONS <= 50

    def test_tool_timeout_positive(self):
        assert TOOL_TIMEOUT > 0

    def test_max_retries_positive(self):
        assert MAX_RETRIES >= 1


# ── _parse_tool_calls 测试（通过 agent_tools 间接验证）────────


class TestParseToolCalls:
    """parse_tool_calls — 委托到 agent_tools.parse_tool_calls"""

    def test_parses_valid_json(self):
        from pycoder.server.services.agent_tools import parse_tool_calls

        text = '```json\n{"tool_calls": [{"name": "read_file", "params": {"path": "test.py"}}]}\n```'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"

    def test_returns_empty_for_no_json(self):
        from pycoder.server.services.agent_tools import parse_tool_calls

        assert parse_tool_calls("just plain text") == []

    def test_parses_multiple_tools(self):
        from pycoder.server.services.agent_tools import parse_tool_calls

        text = '''```json
{"tool_calls": [
    {"name": "read_file", "params": {"path": "a.py"}},
    {"name": "list_files", "params": {"path": "."}}
]}
```'''
        calls = parse_tool_calls(text)
        assert len(calls) == 2

    def test_parses_bare_json(self):
        from pycoder.server.services.agent_tools import parse_tool_calls

        text = '{"tool_calls": [{"name": "search_code", "params": {"query": "test"}}]}'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "search_code"


# ── agent_chat_stream 测试 ────────────────────────────────


class TestAgentChatStream:
    """agent_chat_stream — 异步聊天流主循环"""

    @pytest.mark.asyncio
    async def test_no_api_key_returns_error(self):
        events = []
        async for event in agent_chat_stream("test", api_key=""):
            events.append(event)
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "API Key" in events[0]["message"]
