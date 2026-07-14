"""覆盖率测试: pycoder/server/services/team/agent_tool_loop.py

目标: 行覆盖率 >= 80%
覆盖内容:
  - _parse_files_from_response: 解析 FILE 块
  - _team_execute_tool: asyncio.run 委托 + 异常处理
  - _team_parse_tool_calls: 委托到 agent_tools
  - _agent_tool_loop: LLM ↔ 工具循环（多种分支）
  - _execute_agent_with_files: 上下文构建 + prompt 注入
  - review_code: JSON 解析 + 异常分支
  - AGENT_SYSTEM_PROMPT / REVIEW_SYSTEM_PROMPT: 内容验证

测试策略:
  - mock ChatBridge 的 chat_stream 异步生成器
  - mock _team_execute_tool / _team_parse_tool_calls 避免真实工具调用
  - 用 tmp_path 隔离文件写入
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.server.services.team import agent_tool_loop as atl
from pycoder.server.services.team.agent_tool_loop import (
    AGENT_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    _agent_tool_loop,
    _execute_agent_with_files,
    _parse_files_from_response,
    _team_execute_tool,
    _team_parse_tool_calls,
    review_code,
)


# ══════════════════════════════════════════════════════════
# 提示词常量
# ══════════════════════════════════════════════════════════

class TestPrompts:
    def test_agent_prompt_contains_role_and_tools(self):
        assert "{role_name}" in AGENT_SYSTEM_PROMPT
        assert "{role_description}" in AGENT_SYSTEM_PROMPT
        assert "{task_title}" in AGENT_SYSTEM_PROMPT
        assert "{task_description}" in AGENT_SYSTEM_PROMPT
        assert "{task_deliverables}" in AGENT_SYSTEM_PROMPT
        assert "{review_feedback}" in AGENT_SYSTEM_PROMPT
        assert "{previous_outputs}" in AGENT_SYSTEM_PROMPT

    def test_agent_prompt_mentions_tools(self):
        for tool in ["read_file", "write_file", "list_files", "search_code", "run_command"]:
            assert tool in AGENT_SYSTEM_PROMPT

    def test_review_prompt_mentions_json(self):
        assert "JSON" in REVIEW_SYSTEM_PROMPT or "json" in REVIEW_SYSTEM_PROMPT
        assert "passed" in REVIEW_SYSTEM_PROMPT
        assert "issues" in REVIEW_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════
# _parse_files_from_response 测试
# ══════════════════════════════════════════════════════════

class TestParseFilesFromResponse:
    def test_empty_text(self):
        assert _parse_files_from_response("") == []

    def test_text_no_file_block(self):
        text = "这是普通文本\n```python\nprint('hi')\n```"
        assert _parse_files_from_response(text) == []

    def test_single_file_block(self):
        text = "```FILE:app.py\nprint('hello')\n```END"
        files = _parse_files_from_response(text)
        assert len(files) == 1
        assert files[0]["path"] == "app.py"
        assert "print('hello')" in files[0]["content"]

    def test_multiple_file_blocks(self):
        text = (
            "```FILE:a.py\ncontent_a\n```END\n"
            "中间文本\n"
            "```FILE:b.py\ncontent_b\n```END"
        )
        files = _parse_files_from_response(text)
        assert len(files) == 2
        assert files[0]["path"] == "a.py"
        assert files[1]["path"] == "b.py"

    def test_path_stripped(self):
        """路径两端空格应被去除"""
        text = "```FILE:  spaced.py  \ncontent\n```END"
        files = _parse_files_from_response(text)
        assert files[0]["path"] == "spaced.py"

    def test_multiline_content(self):
        text = "```FILE:app.py\nline1\nline2\nline3\n```END"
        files = _parse_files_from_response(text)
        assert "line1" in files[0]["content"]
        assert "line3" in files[0]["content"]


# ══════════════════════════════════════════════════════════
# _team_execute_tool 测试
# ══════════════════════════════════════════════════════════

class TestTeamExecuteTool:
    @pytest.mark.asyncio
    async def test_returns_result_on_success(self, monkeypatch):
        async def fake_exec(*args, **kwargs):
            return "✅ success"
        # mock execute_agent_tool 模块级函数
        import pycoder.server.services.agent_tools as at_mod
        monkeypatch.setattr(at_mod, "execute_agent_tool", fake_exec)
        result = await _team_execute_tool("read_file", {"path": "x"}, Path("."))
        assert result == "✅ success"

    @pytest.mark.asyncio
    async def test_returns_error_on_exception(self, monkeypatch):
        async def fake_exec(*args, **kwargs):
            raise RuntimeError("tool failed")
        import pycoder.server.services.agent_tools as at_mod
        monkeypatch.setattr(at_mod, "execute_agent_tool", fake_exec)
        result = await _team_execute_tool("bad_tool", {}, Path("."))
        assert "❌" in result
        assert "tool failed" in result or "失败" in result

    @pytest.mark.asyncio
    async def test_returns_error_on_timeout(self, monkeypatch):
        async def fake_exec(*args, **kwargs):
            raise asyncio.TimeoutError()
        import pycoder.server.services.agent_tools as at_mod
        monkeypatch.setattr(at_mod, "execute_agent_tool", fake_exec)
        result = await _team_execute_tool("slow_tool", {}, Path("."))
        assert "❌" in result


# ══════════════════════════════════════════════════════════
# _team_parse_tool_calls 测试
# ══════════════════════════════════════════════════════════

class TestTeamParseToolCalls:
    def test_parses_valid_json(self, monkeypatch):
        """委托到 agent_tools.parse_tool_calls"""
        fake_calls = [{"name": "read_file", "params": {"path": "x"}}]
        import pycoder.server.services.agent_tools as at_mod
        monkeypatch.setattr(at_mod, "parse_tool_calls", lambda text: fake_calls)
        result = _team_parse_tool_calls("any text")
        assert result == fake_calls

    def test_empty_text(self, monkeypatch):
        import pycoder.server.services.agent_tools as at_mod
        monkeypatch.setattr(at_mod, "parse_tool_calls", lambda text: [])
        assert _team_parse_tool_calls("") == []

    def test_multiple_tools(self, monkeypatch):
        fake_calls = [
            {"name": "read_file", "params": {"path": "a"}},
            {"name": "write_file", "params": {"path": "b"}},
        ]
        import pycoder.server.services.agent_tools as at_mod
        monkeypatch.setattr(at_mod, "parse_tool_calls", lambda text: fake_calls)
        result = _team_parse_tool_calls("text")
        assert len(result) == 2


# ══════════════════════════════════════════════════════════
# _agent_tool_loop 测试（async）
# ══════════════════════════════════════════════════════════

def _make_bridge_with_events(events):
    """构造一个 mock bridge，其 chat_stream 返回指定事件序列"""
    bridge = MagicMock()
    bridge.configure = MagicMock()
    bridge.config = MagicMock()
    bridge.config.system_prompt = ""
    bridge.config.max_tokens = 8192
    bridge.config.reasoning_effort = "medium"
    bridge.config.enable_thinking = True
    bridge.config.enable_cache = True

    async def chat_stream(prompt):
        for ev in events:
            yield ev

    bridge.chat_stream = chat_stream
    return bridge


class TestAgentToolLoop:
    @pytest.mark.asyncio
    async def test_no_tool_calls_writes_files(self, tmp_path, monkeypatch):
        """LLM 直接返回 FILE 块 → 写入文件并结束循环"""
        # 模拟事件序列：先 token 后 done
        events = [
            MagicMock(event_type="token", content="开始"),
            MagicMock(event_type="done", content="```FILE:app.py\nprint('hi')\n```END"),
        ]
        bridge = _make_bridge_with_events(events)

        # mock _team_parse_tool_calls 返回空 → 不调用工具
        monkeypatch.setattr(atl, "_team_parse_tool_calls", lambda text: [])

        result, files = await _agent_tool_loop(bridge, "task", tmp_path)
        assert "app.py" in files
        written_file = tmp_path / "app.py"
        assert written_file.exists()
        assert "print('hi')" in written_file.read_text()

    @pytest.mark.asyncio
    async def test_tool_call_executed_and_continues(self, tmp_path, monkeypatch):
        """第一轮调用工具，第二轮直接返回"""
        call_count = {"n": 0}

        def fake_parse(text):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{"name": "read_file", "params": {"path": "x.py"}}]
            return []  # 第二轮无工具调用

        monkeypatch.setattr(atl, "_team_parse_tool_calls", fake_parse)
        # mock _team_execute_tool 异步返回
        async def fake_exec(name, params, ws):
            return "✅ file content"
        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        # 第一次返回工具调用，第二次直接结束
        events_per_call = [
            [MagicMock(event_type="done", content='{"name": "read_file"}')],
            [MagicMock(event_type="done", content="task done")],
        ]
        call_idx = {"i": 0}

        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""

        async def chat_stream(prompt):
            # 注: 必须在 yield 前增量，因为 async for 中的 break 会关闭生成器，
            # 导致 yield 后的代码不执行
            events = events_per_call[call_idx["i"]]
            call_idx["i"] += 1
            for ev in events:
                yield ev

        bridge.chat_stream = chat_stream

        result, files = await _agent_tool_loop(bridge, "task", tmp_path)
        assert call_count["n"] >= 1
        assert "task done" in result or "task done" == result

    @pytest.mark.asyncio
    async def test_write_file_tool_appends_to_files(self, tmp_path, monkeypatch):
        """write_file 工具调用应记入 files"""
        events = [
            MagicMock(
                event_type="done",
                content='{"name": "write_file", "params": {"path": "new.py"}}',
            ),
            MagicMock(event_type="done", content="done"),
        ]
        bridge = _make_bridge_with_events(events)
        # 第一轮返回工具调用，第二轮返回空
        call_count = {"n": 0}
        def fake_parse(text):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{"name": "write_file", "params": {"path": "new.py"}}]
            return []
        monkeypatch.setattr(atl, "_team_parse_tool_calls", fake_parse)
        async def fake_exec(name, params, ws):
            return "✅ wrote"
        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        result, files = await _agent_tool_loop(bridge, "task", tmp_path)
        assert "new.py" in files

    @pytest.mark.asyncio
    async def test_error_event_returns_error(self, tmp_path, monkeypatch):
        """LLM error 事件 → 立即返回错误"""
        events = [MagicMock(event_type="error", content="API failed")]
        bridge = _make_bridge_with_events(events)
        monkeypatch.setattr(atl, "_team_parse_tool_calls", lambda text: [])

        result, files = await _agent_tool_loop(bridge, "task", tmp_path)
        assert "Agent 错误" in result
        assert "API failed" in result

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tmp_path, monkeypatch):
        """FILE 块路径越界 → 不写入"""
        events = [
            MagicMock(
                event_type="done",
                content="```FILE:../escape.py\nbad content\n```END",
            ),
        ]
        bridge = _make_bridge_with_events(events)
        monkeypatch.setattr(atl, "_team_parse_tool_calls", lambda text: [])

        result, files = await _agent_tool_loop(bridge, "task", tmp_path)
        # 路径越界 → 不写入
        assert files == []
        # 验证文件没被创建
        assert not (tmp_path.parent / "escape.py").exists()

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, tmp_path, monkeypatch):
        """达到 max_iterations 仍循环 → 返回最后一次响应"""
        events = [
            MagicMock(
                event_type="done",
                content='{"name": "read_file", "params": {"path": "loop.py"}}',
            ),
        ]
        bridge = _make_bridge_with_events(events)
        # 每轮都返回工具调用，永不停止
        monkeypatch.setattr(
            atl, "_team_parse_tool_calls",
            lambda text: [{"name": "read_file", "params": {"path": "x"}}],
        )
        async def fake_exec(name, params, ws):
            return "result"
        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        result, files = await _agent_tool_loop(bridge, "task", tmp_path, max_iterations=2)
        # 应该执行 2 轮后退出
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_token_event_accumulates(self, tmp_path, monkeypatch):
        """多个 token 事件累积成完整响应"""
        events = [
            MagicMock(event_type="token", content="part1"),
            MagicMock(event_type="token", content="part2"),
            MagicMock(event_type="done", content="part1part2"),
        ]
        bridge = _make_bridge_with_events(events)
        monkeypatch.setattr(atl, "_team_parse_tool_calls", lambda text: [])

        result, files = await _agent_tool_loop(bridge, "task", tmp_path)
        assert "part1part2" in result


# ══════════════════════════════════════════════════════════
# _execute_agent_with_files 测试（async）
# ══════════════════════════════════════════════════════════

class TestExecuteAgentWithFiles:
    async def test_builds_prompt_with_role_and_task(self, tmp_path, monkeypatch):
        """构造的 prompt 应包含角色名、任务标题、描述"""
        from pycoder.server.services.agent_definitions import AgentRole, AgentTask

        role = AgentRole(
            id="dev", name="开发者", description="编码实现",
            system_prompt="sys", tools=[], model="deepseek-chat",
        )
        task = AgentTask(
            id="t1", title="任务1", description="描述1",
            assigned_role="dev", deliverables=["a.py"],
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 8192
        bridge.config.reasoning_effort = "medium"

        # mock _agent_tool_loop 返回固定结果
        async def fake_loop(b, p, ws, max_iterations=10):
            return "result text", []

        monkeypatch.setattr(atl, "_agent_tool_loop", fake_loop)

        result = await _execute_agent_with_files(bridge, role, task, work_dir=tmp_path)
        assert result == "result text"
        # 验证 configure 被调用
        assert bridge.configure.called
        # 验证 system_prompt 被设置（包含角色名）
        assert "开发者" in bridge.config.system_prompt

    async def test_existing_results_in_prompt(self, tmp_path, monkeypatch):
        """existing_results 应注入到 prompt 中"""
        from pycoder.server.services.agent_definitions import AgentRole, AgentTask

        role = AgentRole(
            id="dev", name="开发者", description="编码",
            system_prompt="sys", tools=[], model="deepseek-chat",
        )
        task = AgentTask(
            id="t2", title="任务2", description="描述2",
            assigned_role="dev", deliverables=["a.py"],
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""

        captured_prompt = {"value": ""}

        async def fake_loop(b, p, ws, max_iterations=10):
            captured_prompt["value"] = b.config.system_prompt
            return "result", []

        monkeypatch.setattr(atl, "_agent_tool_loop", fake_loop)

        await _execute_agent_with_files(
            bridge, role, task,
            existing_results={"prev-task": "previous output"},
            work_dir=tmp_path,
        )
        # 注: 源码将 task_id 截断到 8 字符: tid[:8] = "prev-tas"
        assert "prev-tas" in captured_prompt["value"]
        assert "previous output" in captured_prompt["value"]

    async def test_existing_results_with_file_blocks(self, tmp_path, monkeypatch):
        """existing_results 含 FILE 块时，提取文件路径注入 prompt"""
        from pycoder.server.services.agent_definitions import AgentRole, AgentTask

        role = AgentRole(
            id="dev", name="开发者", description="编码",
            system_prompt="sys", tools=[], model="deepseek-chat",
        )
        task = AgentTask(
            id="t3", title="任务3", description="描述3",
            assigned_role="dev", deliverables=["a.py"],
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""

        captured_prompt = {"value": ""}

        async def fake_loop(b, p, ws, max_iterations=10):
            captured_prompt["value"] = b.config.system_prompt
            return "result", []

        monkeypatch.setattr(atl, "_agent_tool_loop", fake_loop)

        await _execute_agent_with_files(
            bridge, role, task,
            existing_results={
                "prev-task": "```FILE:app.py\ncontent\n```END",
            },
            work_dir=tmp_path,
        )
        assert "app.py" in captured_prompt["value"]

    async def test_files_written_attached_to_task(self, tmp_path, monkeypatch):
        """written_files 非空时挂到 task._files_written"""
        from pycoder.server.services.agent_definitions import AgentRole, AgentTask

        role = AgentRole(
            id="dev", name="开发者", description="编码",
            system_prompt="sys", tools=[], model="deepseek-chat",
        )
        task = AgentTask(
            id="t4", title="任务4", description="描述4",
            assigned_role="dev", deliverables=["a.py"],
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""

        async def fake_loop(b, p, ws, max_iterations=10):
            return "result", ["file1.py", "file2.py"]

        monkeypatch.setattr(atl, "_agent_tool_loop", fake_loop)

        await _execute_agent_with_files(bridge, role, task, work_dir=tmp_path)
        assert hasattr(task, "_files_written")
        assert task._files_written == ["file1.py", "file2.py"]

    async def test_reasoner_model_uses_max_effort(self, tmp_path, monkeypatch):
        """role.model == 'deepseek-reasoner' → reasoning_effort='max'"""
        from pycoder.server.services.agent_definitions import AgentRole, AgentTask

        role = AgentRole(
            id="arch", name="架构师", description="设计",
            system_prompt="sys", tools=[], model="deepseek-reasoner",
        )
        task = AgentTask(
            id="t5", title="任务5", description="描述5",
            assigned_role="arch", deliverables=[],
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""

        async def fake_loop(b, p, ws, max_iterations=10):
            return "result", []

        monkeypatch.setattr(atl, "_agent_tool_loop", fake_loop)

        await _execute_agent_with_files(bridge, role, task, work_dir=tmp_path)
        assert bridge.config.reasoning_effort == "max"

    async def test_default_work_dir(self, tmp_path, monkeypatch):
        """未传 work_dir 时使用 get_workspace_root"""
        from pycoder.server.services.agent_definitions import AgentRole, AgentTask

        role = AgentRole(
            id="dev", name="开发者", description="编码",
            system_prompt="sys", tools=[], model="deepseek-chat",
        )
        task = AgentTask(
            id="t6", title="任务6", description="描述6",
            assigned_role="dev", deliverables=[],
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""

        captured_ws = {"value": None}

        async def fake_loop(b, p, ws, max_iterations=10):
            captured_ws["value"] = ws
            return "result", []

        monkeypatch.setattr(atl, "_agent_tool_loop", fake_loop)
        # 注: agent_tool_loop 在模块顶层已 from ... import get_workspace_root，
        # 需 patch 模块属性而非源模块
        monkeypatch.setattr(atl, "get_workspace_root", lambda: tmp_path)

        await _execute_agent_with_files(bridge, role, task)
        assert captured_ws["value"] == tmp_path


# ══════════════════════════════════════════════════════════
# review_code 测试（async）
# ══════════════════════════════════════════════════════════

class TestReviewCode:
    async def test_valid_json_response(self, monkeypatch):
        """LLM 返回有效 JSON → 解析成功"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 4096

        review_json = {
            "passed": True,
            "issues": [],
            "score": 90,
            "summary": "代码质量良好",
        }

        async def chat_stream(prompt):
            yield MagicMock(event_type="token", content=json.dumps(review_json))

        bridge.chat_stream = chat_stream

        result = await review_code(bridge, "def f(): pass")
        assert result["passed"] is True
        assert result["score"] == 90
        assert result["summary"] == "代码质量良好"

    async def test_markdown_wrapped_json(self, monkeypatch):
        """LLM 返回 ```json 包裹的 JSON → 应被剥离"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 4096

        review_json = {"passed": False, "issues": [], "score": 50, "summary": "差"}

        async def chat_stream(prompt):
            yield MagicMock(
                event_type="token",
                content=f"```json\n{json.dumps(review_json)}\n```",
            )

        bridge.chat_stream = chat_stream

        result = await review_code(bridge, "code")
        assert result["passed"] is False
        assert result["score"] == 50

    async def test_invalid_json_returns_failure(self, monkeypatch):
        """LLM 返回非 JSON → 返回失败结果"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 4096

        async def chat_stream(prompt):
            yield MagicMock(event_type="token", content="这不是 JSON")

        bridge.chat_stream = chat_stream

        result = await review_code(bridge, "code")
        assert result["passed"] is False
        assert result["score"] == 0
        assert "解析失败" in result["summary"]
        assert "raw" in result

    async def test_error_event_returns_failure(self, monkeypatch):
        """LLM 错误事件 → 立即返回失败"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 4096

        async def chat_stream(prompt):
            yield MagicMock(event_type="error", content="API 错误")

        bridge.chat_stream = chat_stream

        result = await review_code(bridge, "code")
        assert result["passed"] is False
        assert result["score"] == 0
        assert "审查失败" in result["summary"]
        assert "API 错误" in result["summary"]

    async def test_done_event_content_collected(self, monkeypatch):
        """done 事件内容也应被收集"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 4096

        review_json = {"passed": True, "issues": [], "score": 100, "summary": "ok"}

        async def chat_stream(prompt):
            yield MagicMock(event_type="done", content=json.dumps(review_json))

        bridge.chat_stream = chat_stream

        result = await review_code(bridge, "code")
        assert result["passed"] is True
        assert result["score"] == 100

    async def test_truncates_long_code(self, monkeypatch):
        """代码超 8000 字符应被截断"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.config.system_prompt = ""
        bridge.config.max_tokens = 4096

        captured_prompt = {"value": ""}

        review_json = {"passed": True, "issues": [], "score": 100, "summary": ""}

        async def chat_stream(prompt):
            captured_prompt["value"] = prompt
            yield MagicMock(event_type="token", content=json.dumps(review_json))

        bridge.chat_stream = chat_stream

        long_code = "x" * 10000
        await review_code(bridge, long_code)
        # 验证 prompt 中代码被截断到 8000 字符
        assert long_code not in captured_prompt["value"]
        assert "x" * 8000 in captured_prompt["value"]
