from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 4. agent_react_loop.py 测试
# ═══════════════════════════════════════════════════════════════


class TestReActStep:
    """ReActStep 数据类测试"""

    def test_react_step_creation(self):
        """ReActStep 应正确创建"""
        from pycoder.server.services.agent_react_loop import ReActStep

        step = ReActStep(
            thought="需要读取文件",
            action="read_file",
            action_input={"path": "test.py"},
            observation="文件内容...",
            iteration=1,
        )
        assert step.thought == "需要读取文件"
        assert step.action == "read_file"
        assert step.iteration == 1

    def test_react_step_to_dict(self):
        """to_dict 应返回正确的字典"""
        from pycoder.server.services.agent_react_loop import ReActStep

        step = ReActStep(
            thought="测试",
            action="FINISH",
            action_input={},
            observation="obs" * 200,
            iteration=3,
        )
        d = step.to_dict()
        assert d["iteration"] == 3
        assert d["thought"] == "测试"
        assert d["action"] == "FINISH"
        assert len(d["observation"]) <= 500


class TestReActResult:
    """ReActResult 数据类测试"""

    def test_result_success_when_finished(self):
        """terminated_by='finish' 且无 error 时 success 应为 True"""
        from pycoder.server.services.agent_react_loop import ReActResult

        result = ReActResult(final_answer="完成", terminated_by="finish")
        assert result.success is True

    def test_result_not_success_when_max_iterations(self):
        """terminated_by='max_iterations' 时 success 应为 False"""
        from pycoder.server.services.agent_react_loop import ReActResult

        result = ReActResult(final_answer="超时", terminated_by="max_iterations")
        assert result.success is False

    def test_result_not_success_when_error(self):
        """有 error 时 success 应为 False"""
        from pycoder.server.services.agent_react_loop import ReActResult

        result = ReActResult(
            final_answer="失败", terminated_by="finish", error="something went wrong"
        )
        assert result.success is False

    def test_result_to_dict(self):
        """to_dict 应返回正确结构"""
        from pycoder.server.services.agent_react_loop import ReActResult, ReActStep

        step = ReActStep(thought="t", action="a", action_input={}, iteration=1)
        result = ReActResult(
            final_answer="done",
            steps=[step],
            iterations=1,
            terminated_by="finish",
        )
        d = result.to_dict()
        assert d["final_answer"] == "done"
        assert d["iterations"] == 1
        assert d["success"] is True
        assert len(d["steps"]) == 1


class TestExtractJsonCandidates:
    """JSON 候选提取测试"""

    def test_extract_from_markdown_code_block(self):
        """应从 Markdown 代码块中提取 JSON"""
        from pycoder.server.services.agent_react_loop import _extract_json_candidates

        text = '```json\n{"thought": "test", "action": "read", "action_input": {}}\n```'
        candidates = _extract_json_candidates(text)
        assert len(candidates) >= 1
        assert "test" in candidates[0]

    def test_extract_bare_json(self):
        """应从裸文本中提取 JSON"""
        from pycoder.server.services.agent_react_loop import _extract_json_candidates

        text = 'some prefix {"thought": "test", "action": "read", "action_input": {}} suffix'
        candidates = _extract_json_candidates(text)
        assert len(candidates) >= 1

    def test_extract_no_json(self):
        """无 JSON 时应返回空列表"""
        from pycoder.server.services.agent_react_loop import _extract_json_candidates

        text = "just plain text without braces"
        candidates = _extract_json_candidates(text)
        # 只有 Markdown 代码块候选，没有裸 JSON
        assert all("{" not in c for c in candidates)


class TestTryParseReActJson:
    """ReAct JSON 解析测试"""

    def test_parse_valid_react_json(self):
        """有效的 ReAct JSON 应正确解析"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"thought": "需要读文件", "action": "read_file", "action_input": {"path": "test.py"}})
        step = _try_parse_react_json(data, 1)
        assert step is not None
        assert step.thought == "需要读文件"
        assert step.action == "read_file"
        assert step.action_input == {"path": "test.py"}
        assert step.iteration == 1

    def test_parse_missing_thought(self):
        """缺少 thought 字段应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"action": "read_file", "action_input": {}})
        step = _try_parse_react_json(data, 1)
        assert step is None

    def test_parse_missing_action(self):
        """缺少 action 字段应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"thought": "test", "action_input": {}})
        step = _try_parse_react_json(data, 1)
        assert step is None

    def test_parse_invalid_json(self):
        """无效 JSON 应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        step = _try_parse_react_json("not valid json", 1)
        assert step is None

    def test_parse_non_dict_json(self):
        """非字典 JSON 应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        step = _try_parse_react_json("[1, 2, 3]", 1)
        assert step is None

    def test_parse_action_input_not_dict(self):
        """action_input 非字典时应转换为空字典"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"thought": "test", "action": "read", "action_input": "not a dict"})
        step = _try_parse_react_json(data, 1)
        assert step is not None
        assert step.action_input == {}


class TestTryParseToolCallsCompat:
    """旧格式兼容解析测试"""

    def test_parse_valid_tool_calls(self):
        """有效的 tool_calls 格式应正确解析"""
        from pycoder.server.services.agent_react_loop import _try_parse_tool_calls_compat

        data = json.dumps({
            "thought": "需要读文件",
            "tool_calls": [{"name": "read_file", "params": {"path": "test.py"}}],
        })
        step = _try_parse_tool_calls_compat(data, 1)
        assert step is not None
        assert step.action == "read_file"
        assert step.action_input == {"path": "test.py"}

    def test_parse_tool_calls_missing_name(self):
        """tool_calls 缺少 name 应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_tool_calls_compat

        data = json.dumps({"tool_calls": [{"params": {}}]})
        step = _try_parse_tool_calls_compat(data, 1)
        assert step is None

    def test_parse_tool_calls_not_list(self):
        """tool_calls 非列表应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_tool_calls_compat

        data = json.dumps({"tool_calls": "not a list"})
        step = _try_parse_tool_calls_compat(data, 1)
        assert step is None


class TestReActLoop:
    """ReActLoop 循环测试"""

    @pytest.fixture
    def mock_llm(self):
        """创建模拟 LLMProvider"""
        from pycoder.core.ports.llm_provider import LLMResponse

        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=LLMResponse(
                content='{"thought": "任务完成", "action": "FINISH", "action_input": {}}',
                model="test-model",
            )
        )
        return llm

    @pytest.fixture
    def mock_tool_executor(self):
        """创建模拟工具执行器"""
        return AsyncMock(return_value="工具执行成功")

    @pytest.fixture
    def react_loop(self, mock_llm, mock_tool_executor):
        """创建 ReActLoop 实例"""
        from pycoder.server.services.agent_react_loop import ReActLoop

        loop = ReActLoop(
            llm=mock_llm,
            tool_executor=mock_tool_executor,
            max_iterations=5,
        )
        return loop

    def test_react_loop_init(self, react_loop):
        """ReActLoop 初始化应设置默认值"""
        assert react_loop.max_iterations == 5
        assert react_loop.tools is not None
        assert len(react_loop.tools) > 0

    def test_react_loop_default_tools(self, mock_llm, mock_tool_executor):
        """默认工具列表应包含常用工具"""
        from pycoder.server.services.agent_react_loop import ReActLoop

        loop = ReActLoop(llm=mock_llm, tool_executor=mock_tool_executor)
        tool_names = [t["name"] for t in loop.tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "FINISH" not in tool_names  # FINISH 是动作不是工具

    async def test_run_finish_immediately(self, react_loop, mock_llm):
        """LLM 直接返回 FINISH 时应立即结束"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "已完成", "action": "FINISH", "action_input": {}}',
            model="test",
        )

        result = await react_loop.run("测试任务")
        assert result.success is True
        assert result.terminated_by == "finish"
        assert result.iterations == 1
        assert "已完成" in result.final_answer

    async def test_run_with_tool_call_then_finish(self, react_loop, mock_llm):
        """先调用工具再 FINISH 的流程"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.side_effect = [
            LLMResponse(
                content='{"thought": "需要读文件", "action": "read_file", "action_input": {"path": "test.py"}}',
                model="test",
            ),
            LLMResponse(
                content='{"thought": "已读取文件，任务完成", "action": "FINISH", "action_input": {}}',
                model="test",
            ),
        ]

        result = await react_loop.run("读取文件")
        assert result.success is True
        assert result.iterations == 2
        assert len(result.steps) == 2
        assert result.steps[0].action == "read_file"
        assert result.steps[1].action == "FINISH"

    async def test_run_max_iterations_exceeded(self, react_loop, mock_llm):
        """超过最大迭代次数应终止"""
        from pycoder.core.ports.llm_provider import LLMResponse

        # 一直返回非 FINISH 动作
        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "继续", "action": "read_file", "action_input": {"path": "test.py"}}',
            model="test",
        )

        result = await react_loop.run("测试")
        assert result.terminated_by == "max_iterations"
        assert result.iterations == react_loop.max_iterations
        assert result.success is False

    async def test_run_llm_failure_returns_error(self, react_loop, mock_llm):
        """LLM 调用失败应返回错误结果"""
        mock_llm.generate.side_effect = ConnectionError("连接失败")

        result = await react_loop.run("测试")
        assert result.terminated_by == "error"
        assert "连接失败" in result.final_answer
        assert result.success is False

    async def test_run_parse_failure_continues(self, react_loop, mock_llm):
        """解析失败应继续下一轮"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.side_effect = [
            LLMResponse(content="not json at all", model="test"),
            LLMResponse(
                content='{"thought": "完成", "action": "FINISH", "action_input": {}}',
                model="test",
            ),
        ]

        result = await react_loop.run("测试")
        assert result.success is True
        assert result.iterations == 2
        # 第一步是解析失败
        assert result.steps[0].action == "(parse_error)"

    async def test_run_tool_execution_failure(self, react_loop, mock_llm, mock_tool_executor):
        """工具执行失败应记录错误并继续"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_tool_executor.side_effect = RuntimeError("工具执行错误")
        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "完成", "action": "FINISH", "action_input": {}}',
            model="test",
        )

        result = await react_loop.run("测试")
        assert result.success is True
        # 工具执行失败不影响后续步骤

    async def test_run_with_context(self, react_loop, mock_llm):
        """带初始上下文的执行"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "完成", "action": "FINISH", "action_input": {}}',
            model="test",
        )

        result = await react_loop.run("测试", context="初始上下文信息")
        assert result.success is True

    def test_build_prompt(self, react_loop):
        """_build_prompt 应包含任务、工具和历史"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [
            ReActStep(thought="思考1", action="read_file", action_input={"path": "a.py"}, observation="内容", iteration=1)
        ]
        prompt = react_loop._build_prompt("测试任务", steps, ["初始观察"])

        assert "测试任务" in prompt
        assert "read_file" in prompt
        assert "思考1" in prompt
        assert "初始上下文" in prompt

    def test_compute_rumination_interval_zero_steps(self, react_loop):
        """零步时默认间隔 5"""
        interval = react_loop._compute_rumination_interval([], 0)
        assert interval == 5

    def test_compute_rumination_interval_no_errors(self, react_loop):
        """无错误时间隔 5"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(5)]
        interval = react_loop._compute_rumination_interval(steps, 0)
        assert interval == 5

    def test_compute_rumination_interval_high_errors(self, react_loop):
        """高错误率时间隔 2"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(5)]
        interval = react_loop._compute_rumination_interval(steps, 2)  # 2/5 = 40%
        assert interval == 2

    def test_compute_rumination_interval_persistent_errors(self, react_loop):
        """持续错误（>=3）时间隔 1"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(10)]
        interval = react_loop._compute_rumination_interval(steps, 3)
        assert interval == 1

    def test_compute_rumination_interval_low_errors(self, react_loop):
        """低错误率（<20% 但 >0）时间隔 3"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(10)]
        interval = react_loop._compute_rumination_interval(steps, 1)  # 1/10 = 10%
        assert interval == 3


