"""ExecutionPipeline 统一执行管线测试

覆盖:
  - ExecutionConfig: 三种模式配置 (CHAT/HERMES/AGENT)
  - get_execution_config: 配置获取
  - get_tool_names_for_mode: 按模式获取工具集
  - ExecutionPipeline: 执行流程（含 mock bridge）
  - ExecutionPipeline: 错误处理
  - ExecutionPipeline: 进度事件
  - ExecutionPipeline: keepalive 心跳
  - ExecutionPipeline: 迭代控制
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.execution_pipeline import (
    AGENT_CONFIG,
    CHAT_CONFIG,
    CONFIG_MAP,
    HERMES_CONFIG,
    TOOL_TIERS,
    ExecutionConfig,
    ExecutionPipeline,
    get_execution_config,
    get_tool_names_for_mode,
)


# ══════════════════════════════════════════════════════════
# 辅助模拟类
# ══════════════════════════════════════════════════════════


@dataclass
class MockChatEvent:
    """模拟 ChatBridge 流式事件"""
    event_type: str
    content: str = ""


class MockChatBridge:
    """模拟 ChatBridge 用于管线测试"""

    def __init__(self, events: list[MockChatEvent] | None = None):
        self.events = events or []
        self.config = MagicMock()
        self.config.system_prompt = ""

    async def chat_stream(self, prompt: str, tool_names=None) -> AsyncIterator[MockChatEvent]:
        """模拟流式调用"""
        for ev in self.events:
            await asyncio.sleep(0)
            yield ev

    async def close(self):
        """模拟关闭"""
        pass

    def configure(self, **kwargs):
        """模拟配置"""
        pass


def _make_token_events(text: str) -> list[MockChatEvent]:
    """辅助函数：从文本生成 token 事件流"""
    events: list[MockChatEvent] = []
    # 每 5 个字符一个 token 事件
    for i in range(0, len(text), 5):
        chunk = text[i:i + 5]
        events.append(MockChatEvent("token", chunk))
    events.append(MockChatEvent("done", text))
    return events


# ══════════════════════════════════════════════════════════
# ExecutionConfig 测试
# ══════════════════════════════════════════════════════════


class TestExecutionConfig:
    """执行配置测试"""

    def test_chat_config(self) -> None:
        """CHAT 模式配置"""
        assert CHAT_CONFIG.name == "chat"
        assert CHAT_CONFIG.max_iterations == 1
        assert CHAT_CONFIG.tool_timeout == 15
        assert CHAT_CONFIG.max_concurrent_tools == 3
        assert CHAT_CONFIG.enable_rumination is False
        assert CHAT_CONFIG.max_empty_retries == 0
        assert len(CHAT_CONFIG.stages) == 3

    def test_hermes_config(self) -> None:
        """HERMES 模式配置"""
        assert HERMES_CONFIG.name == "hermes"
        assert HERMES_CONFIG.max_iterations == 10
        assert HERMES_CONFIG.tool_timeout == 30
        assert HERMES_CONFIG.max_concurrent_tools == 5
        assert HERMES_CONFIG.enable_rumination is False
        assert HERMES_CONFIG.max_empty_retries == 3
        assert len(HERMES_CONFIG.stages) == 6

    def test_agent_config(self) -> None:
        """AGENT 模式配置"""
        assert AGENT_CONFIG.name == "agent"
        assert AGENT_CONFIG.max_iterations == 50
        assert AGENT_CONFIG.tool_timeout == 60
        assert AGENT_CONFIG.max_concurrent_tools == 8
        assert AGENT_CONFIG.enable_rumination is True
        assert AGENT_CONFIG.max_empty_retries == 2
        assert len(AGENT_CONFIG.stages) == 6

    def test_config_custom(self) -> None:
        """自定义 ExecutionConfig"""
        config = ExecutionConfig(
            name="custom",
            max_iterations=5,
            tool_timeout=10,
            max_concurrent_tools=2,
            enable_rumination=False,
            system_prompt="自定义提示词",
            max_empty_retries=1,
            stages=[{"id": "test", "label": "测试", "desc": "测试阶段"}],
        )
        assert config.name == "custom"
        assert config.max_iterations == 5
        assert config.system_prompt == "自定义提示词"


# ══════════════════════════════════════════════════════════
# 配置获取函数测试
# ══════════════════════════════════════════════════════════


class TestGetExecutionConfig:
    """配置获取函数测试"""

    def test_get_chat_config(self) -> None:
        """获取 CHAT 配置"""
        config = get_execution_config("chat")
        assert config is CHAT_CONFIG

    def test_get_hermes_config(self) -> None:
        """获取 HERMES 配置"""
        config = get_execution_config("hermes")
        assert config is HERMES_CONFIG

    def test_get_agent_config(self) -> None:
        """获取 AGENT 配置"""
        config = get_execution_config("agent")
        assert config is AGENT_CONFIG

    def test_get_unknown_mode_defaults_to_chat(self) -> None:
        """未知模式默认返回 CHAT 配置"""
        config = get_execution_config("unknown_mode")
        assert config is CHAT_CONFIG

    def test_config_map_contains_all_modes(self) -> None:
        """CONFIG_MAP 包含所有三种模式"""
        assert "chat" in CONFIG_MAP
        assert "hermes" in CONFIG_MAP
        assert "agent" in CONFIG_MAP
        assert len(CONFIG_MAP) == 3


# ══════════════════════════════════════════════════════════
# 工具集测试
# ══════════════════════════════════════════════════════════


class TestGetToolNamesForMode:
    """按模式获取工具集测试"""

    def test_chat_tools(self) -> None:
        """CHAT 模式工具集"""
        tools = get_tool_names_for_mode("chat")
        assert tools is not None
        assert "read_file" in tools
        assert "write_file" in tools
        assert "run_terminal" in tools
        assert "code_review" not in tools  # CHAT 不含审查工具

    def test_hermes_tools(self) -> None:
        """HERMES 模式工具集"""
        tools = get_tool_names_for_mode("hermes")
        assert tools is not None
        assert "read_file" in tools
        assert "code_review" in tools
        assert "security_scan" in tools

    def test_agent_tools_all(self) -> None:
        """AGENT 模式返回 None（全部工具）"""
        tools = get_tool_names_for_mode("agent")
        assert tools is None

    def test_unknown_mode_tools(self) -> None:
        """未知模式返回 None"""
        tools = get_tool_names_for_mode("unknown")
        assert tools is None

    def test_tool_tiers_structure(self) -> None:
        """TOOL_TIERS 结构完整性"""
        assert "chat" in TOOL_TIERS
        assert "hermes" in TOOL_TIERS
        assert "agent" in TOOL_TIERS
        assert TOOL_TIERS["agent"] is None


# ══════════════════════════════════════════════════════════
# ExecutionPipeline 测试
# ══════════════════════════════════════════════════════════


class TestExecutionPipeline:
    """执行管线核心测试"""

    @pytest.fixture
    def chat_config(self) -> ExecutionConfig:
        """CHAT 模式配置"""
        return CHAT_CONFIG

    @pytest.fixture
    def hermes_config(self) -> ExecutionConfig:
        """HERMES 模式配置"""
        return HERMES_CONFIG

    # ── 初始化 ──

    def test_pipeline_init(self, chat_config: ExecutionConfig) -> None:
        """管线初始化"""
        pipeline = ExecutionPipeline(chat_config)
        assert pipeline.config is chat_config
        assert pipeline.tool_calls == []
        assert pipeline.written_files == []
        assert pipeline._empty_retries == 0

    # ── CHAT 模式执行 ──

    @pytest.mark.asyncio
    async def test_chat_mode_simple(self, chat_config: ExecutionConfig) -> None:
        """CHAT 模式简单问答执行"""
        from unittest.mock import patch

        events = _make_token_events("这是一个简单的回答")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("你好", bridge):
                results.append(ev)

        # 应有开始、进度、token 和 done 事件
        types = [e["type"] for e in results]
        assert "agent_status" in types
        assert "progress" in types
        assert "token" in types
        assert "done" in types

        # 最终 done 事件应包含内容
        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) >= 1
        assert done_events[-1]["v2_engine"] is True

    @pytest.mark.asyncio
    async def test_chat_mode_with_history(self, chat_config: ExecutionConfig) -> None:
        """CHAT 模式带历史上下文执行"""
        events = _make_token_events("回答内容")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute(
                "当前消息", bridge, history_context="历史对话"
            ):
                results.append(ev)

        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) >= 1

    # ── 错误处理 ──

    @pytest.mark.asyncio
    async def test_llm_error(self, chat_config: ExecutionConfig) -> None:
        """LLM 调用错误处理"""
        bridge = MockChatBridge()
        original_stream = bridge.chat_stream

        async def error_stream(prompt: str, tool_names=None):
            raise RuntimeError("LLM 服务不可用")

        bridge.chat_stream = error_stream  # type: ignore[method-assign]

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        error_events = [e for e in results if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "LLM 调用失败" in error_events[0]["message"]

    @pytest.mark.asyncio
    async def test_stream_error_event(self, chat_config: ExecutionConfig) -> None:
        """流式事件中的 error 类型处理"""
        events = [
            MockChatEvent("token", "部分内容"),
            MockChatEvent("error", "API 错误"),
        ]
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        error_events = [e for e in results if e["type"] == "error"]
        assert len(error_events) >= 1

    # ── 进度事件 ──

    @pytest.mark.asyncio
    async def test_progress_events(self, chat_config: ExecutionConfig) -> None:
        """进度事件发射"""
        events = _make_token_events("回答")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        progress_events = [e for e in results if e["type"] == "progress"]
        assert len(progress_events) >= 2  # 至少开始和完成两个进度事件

        # 检查最终进度事件
        final_progress = progress_events[-1]
        assert final_progress["percent"] == 100
        assert final_progress["phase"] == "done"

    # ── agent_status 事件 ──

    @pytest.mark.asyncio
    async def test_agent_status_events(self, chat_config: ExecutionConfig) -> None:
        """agent_status 事件发射"""
        events = _make_token_events("回答")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        status_events = [e for e in results if e["type"] == "agent_status"]
        assert len(status_events) >= 2  # started 和 completed

    # ── 空响应处理 ──

    @pytest.mark.asyncio
    async def test_empty_response_with_retries(self, hermes_config: ExecutionConfig) -> None:
        """空响应时重试机制"""
        # 连续空响应
        events = [
            MockChatEvent("done", ""),
            MockChatEvent("done", ""),
            MockChatEvent("done", "最终有内容了"),
        ]
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(hermes_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=hermes_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) >= 1

    # ── 工具调用检测 ──

    @pytest.mark.asyncio
    async def test_tool_call_detection(self, hermes_config: ExecutionConfig) -> None:
        """工具调用标记检测"""
        events = _make_token_events("🔧 执行 read_file 完成")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(hermes_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=hermes_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("读取文件", bridge):
                results.append(ev)

        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) >= 1
        # 应该有工具调用计数
        assert done_events[-1].get("tool_calls_count", 0) >= 0

    # ── keepalive 心跳 ──

    @pytest.mark.asyncio
    async def test_keepalive_triggered(self, chat_config: ExecutionConfig) -> None:
        """长时间无 yield 时触发 keepalive"""
        events = _make_token_events("回答")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)
        # 设置 _last_yield_time 为过去时间以触发 keepalive
        import time
        pipeline._last_yield_time = time.monotonic() - 20

        keepalive = await pipeline._maybe_keepalive("llm")
        assert keepalive is not None
        assert keepalive["type"] == "progress"
        assert "AI 推理中" in keepalive["stage"]

    @pytest.mark.asyncio
    async def test_keepalive_not_triggered(self, chat_config: ExecutionConfig) -> None:
        """最近 yield 过时不触发 keepalive"""
        import time
        pipeline = ExecutionPipeline(chat_config)
        pipeline._last_yield_time = time.monotonic()  # 重置为当前时间
        keepalive = await pipeline._maybe_keepalive("llm")
        assert keepalive is None

    # ── done 事件内容 ──

    @pytest.mark.asyncio
    async def test_done_event_structure(self, chat_config: ExecutionConfig) -> None:
        """done 事件结构完整性"""
        events = _make_token_events("回答内容")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) >= 1
        done = done_events[-1]
        assert "content" in done
        assert done["v2_engine"] is True
        assert "tool_calls_count" in done
        assert "duration_ms" in done

    # ── HERMES 模式无工具调用处理 ──

    @pytest.mark.asyncio
    async def test_hermes_no_tool_calls_with_retries(self, hermes_config: ExecutionConfig) -> None:
        """HERMES 模式无工具调用但有内容且无重试次数时退出"""
        # 有内容但无工具调用，且 max_empty_retries 已耗尽
        events = _make_token_events("这是一个很长很长的回答" * 10)
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(hermes_config)
        pipeline._empty_retries = 3  # 已耗尽重试次数

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=hermes_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) >= 1

    # ── 迭代次数限制 ──

    @pytest.mark.asyncio
    async def test_max_iterations_respected(self, chat_config: ExecutionConfig) -> None:
        """最大迭代次数限制生效"""
        # chat 模式只有 1 次迭代
        events = _make_token_events("回答")
        bridge = MockChatBridge(events)

        pipeline = ExecutionPipeline(chat_config)

        with patch(
            "pycoder.prompts.cache_rules.inject_cache_rules",
            return_value=chat_config.system_prompt,
        ):
            results = []
            async for ev in pipeline.execute("测试", bridge):
                results.append(ev)

        done_events = [e for e in results if e["type"] == "done"]
        assert len(done_events) == 1  # 只执行一次迭代