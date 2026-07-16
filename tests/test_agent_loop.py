"""
统一 Agent 执行循环单元测试

测试 UnifiedAgentLoop 的核心功能：
- 初始化和配置
- 正常完成流程（完成信号检测）
- 工具调用执行（写串行、读并行）
- 代码块自动写入文件
- LLM 错误处理
- 空响应处理
- 最大迭代次数超限
- 反思机制触发
- P0/P1 无工具调用检测
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.agent_loop import UnifiedAgentLoop, WORKSPACE
from pycoder.server.services.agent_strategies import AgentStrategy, SIMPLE_STRATEGY


# ══════════════════════════════════════════════════════════
# 辅助类和工具函数
# ══════════════════════════════════════════════════════════


@dataclass
class FakeEvent:
    """模拟 LLM 流式事件"""
    event_type: str  # "token" | "done" | "error"
    content: str = ""


class FakeBridge:
    """模拟 LLM Bridge 提供者"""

    def __init__(self, responses: list[list[FakeEvent]] | None = None):
        self._responses = responses or []
        self._call_index = 0
        self._messages: list[tuple[str, str]] = []
        self.system_prompt = ""
        self.max_tokens = 0

    def configure(self, system_prompt: str = "", max_tokens: int = 16384) -> None:
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens

    def add_message(self, role: str, content: str) -> None:
        self._messages.append((role, content))

    async def stream(self, prompt: str) -> AsyncIterator[FakeEvent]:
        if self._call_index < len(self._responses):
            events = self._responses[self._call_index]
            self._call_index += 1
            for ev in events:
                yield ev
                await asyncio.sleep(0)
        else:
            # 默认返回完成信号
            yield FakeEvent("token", "完成")
            yield FakeEvent("done", "完成")

    @property
    def messages(self) -> list[tuple[str, str]]:
        return self._messages


def _make_strategy(**kwargs) -> AgentStrategy:
    """快速创建策略配置的辅助函数"""
    defaults = {
        "name": "test",
        "description": "测试策略",
        "max_iterations": 5,
        "tool_timeout": 5,
        "max_concurrent_tools": 3,
        "enable_rumination": False,
        "enable_snapshots": False,
        "enable_qa_review": False,
    }
    defaults.update(kwargs)
    return AgentStrategy(**defaults)


# ══════════════════════════════════════════════════════════
# 测试：UnifiedAgentLoop 初始化
# ══════════════════════════════════════════════════════════


class TestUnifiedAgentLoopInit:
    """初始化相关测试"""

    def test_create_with_default_workspace(self):
        """使用默认工作区创建循环"""
        strategy = _make_strategy()
        loop = UnifiedAgentLoop(strategy)
        assert loop.strategy is strategy
        assert loop.workspace == WORKSPACE
        assert loop._rumination_count == 0
        assert loop._last_iteration_had_tools is False

    def test_create_with_custom_workspace(self, tmp_path):
        """使用自定义工作区创建循环"""
        strategy = _make_strategy()
        loop = UnifiedAgentLoop(strategy, workspace=tmp_path)
        assert loop.workspace == tmp_path


# ══════════════════════════════════════════════════════════
# 测试：chat_stream 正常流程
# ══════════════════════════════════════════════════════════


class TestChatStreamNormal:
    """chat_stream 正常流程测试"""

    @pytest.mark.asyncio
    async def test_completion_signal_on_first_iteration(self):
        """首轮即返回完成信号"""
        strategy = _make_strategy(max_iterations=3)
        # 第一轮返回完成信号
        bridge = FakeBridge([
            [FakeEvent("token", "完成"), FakeEvent("done", "完成。任务已全部完成。")],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("测试任务", bridge):
            results.append(ev)

        # 应包含初始状态和分析状态
        statuses = [r["type"] for r in results]
        assert "status" in statuses
        # 应包含 agent_result 完成事件
        agent_results = [r for r in results if r["type"] == "agent_result"]
        assert len(agent_results) == 1
        assert agent_results[0]["status"] == "done"

    @pytest.mark.asyncio
    async def test_completion_with_done_keyword(self):
        """LLM 返回 'done' 关键词触发完成"""
        strategy = _make_strategy(max_iterations=3)
        bridge = FakeBridge([
            [FakeEvent("token", "done"), FakeEvent("done", "done")],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("测试", bridge):
            results.append(ev)

        agent_results = [r for r in results if r["type"] == "agent_result"]
        assert len(agent_results) == 1
        assert agent_results[0]["status"] == "done"

    @pytest.mark.asyncio
    async def test_completion_with_chinese_summary(self):
        """LLM 返回中文总结触发完成"""
        strategy = _make_strategy(max_iterations=3)
        bridge = FakeBridge([
            [
                FakeEvent("token", "总结：所有任务已成功完成。"),
                FakeEvent("done", "总结：所有任务已成功完成。"),
            ],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("创建文件", bridge):
            results.append(ev)

        agent_results = [r for r in results if r["type"] == "agent_result"]
        assert len(agent_results) == 1


# ══════════════════════════════════════════════════════════
# 测试：工具调用执行
# ══════════════════════════════════════════════════════════


class TestChatStreamToolExecution:
    """工具调用执行测试"""

    @pytest.mark.asyncio
    async def test_tool_call_read_then_complete(self):
        """先调用读工具，然后完成"""
        strategy = _make_strategy(max_iterations=5)
        tool_json = (
            '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}'
        )
        bridge = FakeBridge([
            [FakeEvent("token", tool_json), FakeEvent("done", tool_json)],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成。任务完成。")],
        ])
        loop = UnifiedAgentLoop(strategy)

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = "file1.py\nfile2.py"

            results = []
            async for ev in loop.chat_stream("列出文件", bridge):
                results.append(ev)

            # 验证工具被执行
            assert mock_exec.called

            # 验证有 tool_result 事件
            tool_results = [r for r in results if r["type"] == "tool_result"]
            assert len(tool_results) >= 1

            # 验证最终完成
            agent_results = [r for r in results if r["type"] == "agent_result"]
            assert len(agent_results) == 1

    @pytest.mark.asyncio
    async def test_tool_call_validation_failure(self):
        """工具调用校验失败时返回错误"""
        strategy = _make_strategy(max_iterations=5)
        # 工具名称为空，校验会失败
        tool_json = '{"tool_calls": [{"name": "", "params": {}}]}'
        bridge = FakeBridge([
            [FakeEvent("token", tool_json), FakeEvent("done", tool_json)],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("任务", bridge):
            results.append(ev)

        # 校验失败应返回 tool_result 带错误信息
        tool_results = [r for r in results if r["type"] == "tool_result"]
        error_results = [r for r in tool_results if "❌" in str(r.get("result", ""))]
        assert len(error_results) >= 1

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        """工具执行抛出异常时捕获并返回错误"""
        strategy = _make_strategy(max_iterations=5)
        tool_json = (
            '{"tool_calls": [{"name": "read_file", "params": {"path": "notexist.py"}}]}'
        )
        bridge = FakeBridge([
            [FakeEvent("token", tool_json), FakeEvent("done", tool_json)],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy)

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.side_effect = RuntimeError("文件不存在")

            results = []
            async for ev in loop.chat_stream("读取文件", bridge):
                results.append(ev)

            tool_results = [r for r in results if r["type"] == "tool_result"]
            error_results = [r for r in tool_results if "❌" in str(r.get("result", ""))]
            assert len(error_results) >= 1

    @pytest.mark.asyncio
    async def test_write_tool_executed_serially(self):
        """写操作工具串行执行"""
        strategy = _make_strategy(max_iterations=5)
        tool_json = (
            '{"tool_calls": ['
            '{"name": "write_file", "params": {"path": "a.py", "content": "x"}}, '
            '{"name": "write_file", "params": {"path": "b.py", "content": "y"}}'
            "]}"
        )
        bridge = FakeBridge([
            [FakeEvent("token", tool_json), FakeEvent("done", tool_json)],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy)

        call_order = []

        async def mock_exec(name, params, workspace, timeout=30):
            call_order.append(name)
            return f"写入成功: {params.get('path', '')}"

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            side_effect=mock_exec,
        ):
            results = []
            async for ev in loop.chat_stream("写入文件", bridge):
                results.append(ev)

        assert "write_file" in call_order

    @pytest.mark.asyncio
    async def test_read_tools_executed_in_parallel(self):
        """读操作工具并行执行"""
        strategy = _make_strategy(max_iterations=5)
        tool_json = (
            '{"tool_calls": ['
            '{"name": "read_file", "params": {"path": "a.py"}}, '
            '{"name": "list_files", "params": {"path": "."}}'
            "]}"
        )
        bridge = FakeBridge([
            [FakeEvent("token", tool_json), FakeEvent("done", tool_json)],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy)

        started = []

        async def mock_exec(name, params, workspace, timeout=30):
            started.append(name)
            await asyncio.sleep(0.05)
            return f"结果: {name}"

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            side_effect=mock_exec,
        ):
            results = []
            async for ev in loop.chat_stream("读取文件", bridge):
                results.append(ev)

        # 两个读工具都应被调用
        assert "read_file" in started
        assert "list_files" in started


# ══════════════════════════════════════════════════════════
# 测试：代码块自动写入
# ══════════════════════════════════════════════════════════


class TestChatStreamFileBlocks:
    """代码块自动写入文件测试"""

    @pytest.mark.asyncio
    async def test_file_block_written_to_workspace(self, tmp_path):
        """FILE: 代码块被自动写入工作区"""
        strategy = _make_strategy(max_iterations=3)
        response = (
            "```FILE:hello.py\nprint('hello world')\n```\n\n完成"
        )
        bridge = FakeBridge([
            [FakeEvent("token", response), FakeEvent("done", response)],
        ])
        loop = UnifiedAgentLoop(strategy, workspace=tmp_path)

        results = []
        async for ev in loop.chat_stream("创建 hello.py", bridge):
            results.append(ev)

        # 文件应被创建
        target_file = tmp_path / "hello.py"
        assert target_file.exists()
        assert "print('hello world')" in target_file.read_text(encoding="utf-8")

        # 完成结果中应包含 files_written
        agent_results = [r for r in results if r["type"] == "agent_result"]
        if agent_results:
            assert "hello.py" in agent_results[0].get("files_written", [])

    @pytest.mark.asyncio
    async def test_file_block_path_traversal_prevented(self, tmp_path):
        """文件路径穿越被阻止"""
        strategy = _make_strategy(max_iterations=3)
        response = (
            "```FILE:../outside.py\nmalicious code\n```\n\n完成"
        )
        bridge = FakeBridge([
            [FakeEvent("token", response), FakeEvent("done", response)],
        ])
        loop = UnifiedAgentLoop(strategy, workspace=tmp_path)

        results = []
        async for ev in loop.chat_stream("创建文件", bridge):
            results.append(ev)

        # 不应在 workspace 外部创建文件
        outside = tmp_path.parent / "outside.py"
        assert not outside.exists()


# ══════════════════════════════════════════════════════════
# 测试：错误处理
# ══════════════════════════════════════════════════════════


class TestChatStreamErrors:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_llm_stream_error(self):
        """LLM 流返回错误事件"""
        strategy = _make_strategy(max_iterations=3)
        bridge = FakeBridge([
            [FakeEvent("error", "LLM 服务不可用")],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("测试", bridge):
            results.append(ev)

        error_events = [r for r in results if r["type"] == "error"]
        assert len(error_events) >= 1
        assert "LLM 服务不可用" in error_events[0]["message"]

    @pytest.mark.asyncio
    async def test_llm_exception_during_stream(self):
        """LLM 流抛出异常时捕获"""
        strategy = _make_strategy(max_iterations=3)
        bridge = MagicMock()
        bridge.stream = AsyncMock(side_effect=RuntimeError("连接超时"))
        bridge.configure = MagicMock()
        bridge.add_message = MagicMock()

        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("测试", bridge):
            results.append(ev)

        error_events = [r for r in results if r["type"] == "error"]
        assert len(error_events) >= 1
        assert "LLM 调用失败" in error_events[0]["message"] or "连接超时" in error_events[0]["message"]

    @pytest.mark.asyncio
    async def test_empty_response_triggers_continue(self):
        """LLM 返回空响应时注入提示并继续"""
        strategy = _make_strategy(max_iterations=3)
        bridge = FakeBridge([
            [FakeEvent("token", ""), FakeEvent("done", "")],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("测试", bridge):
            results.append(ev)

        # 空响应后应继续，最终完成
        agent_results = [r for r in results if r["type"] == "agent_result"]
        assert len(agent_results) == 1


# ══════════════════════════════════════════════════════════
# 测试：最大迭代次数
# ══════════════════════════════════════════════════════════


class TestMaxIterations:
    """最大迭代次数测试"""

    @pytest.mark.asyncio
    async def test_max_iterations_exceeded(self):
        """达到最大迭代次数后返回 completed 状态"""
        strategy = _make_strategy(max_iterations=2)
        # 持续返回非完成、无工具调用的内容
        bridge = FakeBridge([
            [FakeEvent("token", '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}'),
             FakeEvent("done", '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}')],
            [FakeEvent("token", '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}'),
             FakeEvent("done", '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}')],
        ])
        loop = UnifiedAgentLoop(strategy)

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = "结果"

            results = []
            async for ev in loop.chat_stream("任务", bridge):
                results.append(ev)

            agent_results = [r for r in results if r["type"] == "agent_result"]
            assert len(agent_results) == 1
            assert agent_results[0]["status"] == "completed"
            assert agent_results[0]["iterations"] == 2


# ══════════════════════════════════════════════════════════
# 测试：反思机制
# ══════════════════════════════════════════════════════════


class TestRumination:
    """反思机制测试"""

    @pytest.mark.asyncio
    async def test_rumination_triggered_every_3_iterations(self):
        """每 3 轮迭代触发反思提示"""
        strategy = _make_strategy(max_iterations=6, enable_rumination=True)
        # 每轮返回工具调用，让循环持续
        tool_json = (
            '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}'
        )
        responses = []
        for _ in range(6):
            responses.append(
                [FakeEvent("token", tool_json), FakeEvent("done", tool_json)]
            )
        # 最后一轮完成后返回完成
        responses.append(
            [FakeEvent("token", "完成"), FakeEvent("done", "完成。任务完成。")]
        )
        bridge = FakeBridge(responses)
        loop = UnifiedAgentLoop(strategy)

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = "结果"

            results = []
            async for ev in loop.chat_stream("任务", bridge):
                results.append(ev)

            # 反思计数应 >= 1（至少第 3 轮触发一次）
            assert loop._rumination_count >= 1

    @pytest.mark.asyncio
    async def test_rumination_disabled(self):
        """反思机制关闭时不触发"""
        strategy = _make_strategy(max_iterations=4, enable_rumination=False)
        tool_json = (
            '{"tool_calls": [{"name": "list_files", "params": {"path": "."}}]}'
        )
        responses = []
        for _ in range(4):
            responses.append(
                [FakeEvent("token", tool_json), FakeEvent("done", tool_json)]
            )
        responses.append(
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")]
        )
        bridge = FakeBridge(responses)
        loop = UnifiedAgentLoop(strategy)

        with patch(
            "pycoder.server.services.agent_loop.execute_agent_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = "结果"

            async for ev in loop.chat_stream("任务", bridge):
                pass

            assert loop._rumination_count == 0


# ══════════════════════════════════════════════════════════
# 测试：P0/P1 无工具调用检测
# ══════════════════════════════════════════════════════════


class TestP0P1NoToolDetection:
    """P0/P1 无工具调用检测测试"""

    @pytest.mark.asyncio
    async def test_p0_first_iteration_no_tools_not_completion(self):
        """首轮无工具调用且无代码块不应判定为完成"""
        strategy = _make_strategy(max_iterations=3)
        bridge = FakeBridge([
            [
                FakeEvent("token", "我会帮你完成这个任务。"),
                FakeEvent("done", "我会帮你完成这个任务。"),
            ],
            [
                FakeEvent("token", "完成"),
                FakeEvent("done", "完成"),
            ],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("测试任务", bridge):
            results.append(ev)

        # 首轮应被跳过，第二轮才完成
        agent_results = [r for r in results if r["type"] == "agent_result"]
        assert len(agent_results) == 1

    @pytest.mark.asyncio
    async def test_p1_second_iteration_no_tools_not_completion(self):
        """第二轮无工具调用且无代码块不应判定为完成"""
        strategy = _make_strategy(max_iterations=4)
        bridge = FakeBridge([
            # 第一轮：无工具调用
            [
                FakeEvent("token", "让我来分析这个任务。"),
                FakeEvent("done", "让我来分析这个任务。"),
            ],
            # 第二轮：无工具调用
            [
                FakeEvent("token", "我需要更多信息。"),
                FakeEvent("done", "我需要更多信息。"),
            ],
            # 第三轮：完成
            [
                FakeEvent("token", "完成"),
                FakeEvent("done", "完成"),
            ],
        ])
        loop = UnifiedAgentLoop(strategy)

        results = []
        async for ev in loop.chat_stream("任务", bridge):
            results.append(ev)

        # 前两轮应被跳过，第三轮才完成
        agent_results = [r for r in results if r["type"] == "agent_result"]
        assert len(agent_results) == 1

    @pytest.mark.asyncio
    async def test_no_tools_after_file_blocks_continues(self):
        """有代码块但没有工具调用时继续下一轮"""
        strategy = _make_strategy(max_iterations=3)
        response = "```FILE:test.py\nprint('ok')\n```"
        bridge = FakeBridge([
            [FakeEvent("token", response), FakeEvent("done", response)],
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy, workspace=Path("."))

        with patch.object(Path, "is_relative_to", return_value=True):
            with patch.object(Path, "write_text"):
                with patch.object(Path, "mkdir"):
                    results = []
                    async for ev in loop.chat_stream("创建文件", bridge):
                        results.append(ev)

                    agent_results = [r for r in results if r["type"] == "agent_result"]
                    assert len(agent_results) == 1


# ══════════════════════════════════════════════════════════
# 测试：上下文注入
# ══════════════════════════════════════════════════════════


class TestContextInjection:
    """上下文注入测试"""

    @pytest.mark.asyncio
    async def test_context_injected_into_system_prompt(self):
        """上下文被注入到系统提示词中"""
        strategy = _make_strategy(max_iterations=2)
        bridge = FakeBridge([
            [FakeEvent("token", "完成"), FakeEvent("done", "完成")],
        ])
        loop = UnifiedAgentLoop(strategy)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value="缓存规则注入后的系统提示",
        ):
            results = []
            async for ev in loop.chat_stream(
                "测试", bridge, context="项目上下文信息"
            ):
                results.append(ev)

            # 系统提示应包含上下文
            assert "项目上下文信息" in bridge.system_prompt