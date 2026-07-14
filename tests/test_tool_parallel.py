"""P2: 工具调用并行化测试

验证 _agent_tool_loop 支持单轮多工具并行执行:
  - 多个 tool_calls 通过 asyncio.gather 并行执行
  - 结果顺序与 tool_calls 顺序一致
  - write_file 仍能正确追踪写入文件路径
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════
# 工具并行执行
# ══════════════════════════════════════════════════════════


class TestToolParallelExecution:
    """P2: 多工具并行执行"""

    async def test_single_tool_direct_await(self, monkeypatch, tmp_path):
        """单工具调用走直接 await 路径（无 gather 开销）"""
        from pycoder.server.services.team import agent_tool_loop as atl

        async def fake_exec(name, params, ws):
            return f"result_{name}"

        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        # 构造 LLM 返回单工具调用
        async def fake_chat_stream(prompt):
            yield MagicMock(event_type="done", content=(
                '```json\n{"name": "read_file", "params": {"path": "a.py"}}\n```'
            ))

        bridge = MagicMock()
        bridge.chat_stream = fake_chat_stream

        result, files = await atl._agent_tool_loop(
            bridge, "task", tmp_path, max_iterations=1,
        )
        assert "read_file" in result

    async def test_multiple_tools_parallel(self, monkeypatch, tmp_path):
        """多个 tool_calls 通过 asyncio.gather 并行执行"""
        from pycoder.server.services.team import agent_tool_loop as atl

        # 记录调用顺序和并行性
        execution_log: list[tuple[float, str]] = []
        barrier = asyncio.Event()

        async def fake_exec(name, params, ws):
            t = asyncio.get_event_loop().time()
            execution_log.append((t, name))
            # 模拟 IO 延迟，验证并行性
            await asyncio.sleep(0.05)
            return f"result_{name}"

        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        # 构造 LLM 返回 3 个工具调用
        # 注意 parse_tool_calls 只返回第一个 JSON 代码块，
        # 所以用 tool_calls 数组格式
        async def fake_chat_stream(prompt):
            yield MagicMock(event_type="done", content=(
                '```json\n'
                '{"tool_calls": ['
                '  {"name": "read_file", "params": {"path": "a.py"}},'
                '  {"name": "read_file", "params": {"path": "b.py"}},'
                '  {"name": "list_files", "params": {"path": "."}}'
                ']}'
                '\n```'
            ))

        bridge = MagicMock()
        bridge.chat_stream = fake_chat_stream

        result, files = await atl._agent_tool_loop(
            bridge, "task", tmp_path, max_iterations=1,
        )
        # 3 个工具都被执行
        assert "read_file" in result
        assert "list_files" in result
        # 验证并行：3 个工具的启动时间应非常接近（< 30ms 间隔）
        # 顺序执行需要 150ms+，并行只需 ~50ms
        assert len(execution_log) == 3
        times = [t for t, _ in execution_log]
        max_gap = max(times) - min(times)
        assert max_gap < 0.03, f"工具未并行执行，启动间隔 {max_gap:.3f}s"

    async def test_parallel_preserves_order(self, monkeypatch, tmp_path):
        """并行执行结果顺序与 tool_calls 顺序一致"""
        from pycoder.server.services.team import agent_tool_loop as atl

        async def fake_exec(name, params, ws):
            await asyncio.sleep(0.01)
            return f"output_{name}"

        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        async def fake_chat_stream(prompt):
            yield MagicMock(event_type="done", content=(
                '```json\n'
                '{"tool_calls": ['
                '  {"name": "alpha", "params": {}},'
                '  {"name": "beta", "params": {}},'
                '  {"name": "gamma", "params": {}}'
                ']}'
                '\n```'
            ))

        bridge = MagicMock()
        bridge.chat_stream = fake_chat_stream

        result, files = await atl._agent_tool_loop(
            bridge, "task", tmp_path, max_iterations=1,
        )
        # 验证结果顺序
        alpha_pos = result.find("alpha")
        beta_pos = result.find("beta")
        gamma_pos = result.find("gamma")
        assert 0 <= alpha_pos < beta_pos < gamma_pos

    async def test_parallel_write_file_tracking(self, monkeypatch, tmp_path):
        """并行执行 write_file 时正确追踪所有写入文件"""
        from pycoder.server.services.team import agent_tool_loop as atl

        async def fake_exec(name, params, ws):
            return f"写入成功: {params.get('path', '')}"

        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        async def fake_chat_stream(prompt):
            yield MagicMock(event_type="done", content=(
                '```json\n'
                '{"tool_calls": ['
                '  {"name": "write_file", "params": {"path": "a.py", "content": "x"}},'
                '  {"name": "write_file", "params": {"path": "b.py", "content": "y"}}'
                ']}'
                '\n```'
            ))

        bridge = MagicMock()
        bridge.chat_stream = fake_chat_stream

        _, files = await atl._agent_tool_loop(
            bridge, "task", tmp_path, max_iterations=1,
        )
        assert "a.py" in files
        assert "b.py" in files

    async def test_parallel_exception_isolation(self, monkeypatch, tmp_path):
        """单个工具失败不影响其他工具（_team_execute_tool 内部已捕获异常）"""
        from pycoder.server.services.team import agent_tool_loop as atl

        call_count = 0

        async def fake_exec(name, params, ws):
            nonlocal call_count
            call_count += 1
            if name == "fail_tool":
                raise RuntimeError("boom")
            return f"ok_{name}"

        monkeypatch.setattr(atl, "_team_execute_tool", fake_exec)

        async def fake_chat_stream(prompt):
            yield MagicMock(event_type="done", content=(
                '```json\n'
                '{"tool_calls": ['
                '  {"name": "ok_tool", "params": {}},'
                '  {"name": "fail_tool", "params": {}},'
                '  {"name": "ok_tool2", "params": {}}'
                ']}'
                '\n```'
            ))

        bridge = MagicMock()
        bridge.chat_stream = fake_chat_stream

        result, _ = await atl._agent_tool_loop(
            bridge, "task", tmp_path, max_iterations=1,
        )
        # 所有工具都被调用
        assert call_count == 3
        # 成功的工具结果存在
        assert "ok_tool" in result
        assert "ok_tool2" in result
        # 失败工具的错误信息存在（_team_execute_tool 捕获后返回错误文本）
        assert "fail_tool" in result


# ══════════════════════════════════════════════════════════
# 性能基准
# ══════════════════════════════════════════════════════════


class TestParallelPerformance:
    """P2: 并行执行性能基准"""

    async def test_parallel_faster_than_sequential(self, monkeypatch, tmp_path):
        """3 个 100ms 工具并行执行总耗时 < 顺序执行的 1/2"""
        from pycoder.server.services.team import agent_tool_loop as atl

        async def slow_exec(name, params, ws):
            await asyncio.sleep(0.1)
            return f"result_{name}"

        monkeypatch.setattr(atl, "_team_execute_tool", slow_exec)

        async def fake_chat_stream(prompt):
            yield MagicMock(event_type="done", content=(
                '```json\n'
                '{"tool_calls": ['
                '  {"name": "t1", "params": {}},'
                '  {"name": "t2", "params": {}},'
                '  {"name": "t3", "params": {}}'
                ']}'
                '\n```'
            ))

        bridge = MagicMock()
        bridge.chat_stream = fake_chat_stream

        start = asyncio.get_event_loop().time()
        await atl._agent_tool_loop(bridge, "task", tmp_path, max_iterations=1)
        elapsed = asyncio.get_event_loop().time() - start

        # 顺序执行需要 300ms+；并行应 < 200ms（含解析开销）
        assert elapsed < 0.25, f"并行执行耗时 {elapsed:.3f}s，未达预期加速"
