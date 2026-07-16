"""UnifiedAgentEngine 统一 Agent 执行引擎测试

覆盖:
  - UnifiedAgentEngine: 初始化
  - UnifiedAgentEngine.chat_stream: 无 API Key 错误处理
  - UnifiedAgentEngine.chat_stream: 策略自动选择
  - UnifiedAgentEngine.chat_stream: 策略选择失败降级
  - UnifiedAgentEngine.chat_stream: 自定义 system_prompt 覆盖
  - UnifiedAgentEngine.chat_stream: 难度分级
  - UnifiedAgentEngine.chat_stream: 事件流
  - agent_chat_stream: 兼容入口函数
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.unified_agent import (
    UnifiedAgentEngine,
    agent_chat_stream,
)


# ══════════════════════════════════════════════════════════
# 辅助模拟类
# ══════════════════════════════════════════════════════════


class MockTaskGrade:
    """模拟任务难度分级结果"""

    def __init__(self, level: str = "MEDIUM", score: int = 30):
        self.level = level
        self.score = score

    def to_dict(self) -> dict:
        return {"level": self.level, "score": self.score}


def _make_mock_strategy():
    """创建模拟策略配置"""
    from pycoder.server.services.agent_strategies import AgentStrategy

    return AgentStrategy(
        name="simple",
        description="简单策略",
        max_iterations=10,
        tool_timeout=30,
        max_concurrent_tools=5,
        enable_rumination=False,
        enable_snapshots=False,
        enable_qa_review=False,
        system_prompt="测试系统提示词",
    )


def _make_mock_llm():
    """创建模拟 LLM Provider"""
    llm = MagicMock()
    llm.configure = MagicMock()
    llm.stream = AsyncMock()
    return llm


def _make_mock_loop_events():
    """创建模拟 UnifiedAgentLoop 事件流"""
    async def _events(*args, **kwargs):
        yield {"type": "status", "message": "开始执行"}
        yield {"type": "tool_result", "tool": "read_file", "result": "内容"}
        yield {"type": "agent_result", "content": "任务完成"}

    mock = MagicMock()
    mock.chat_stream = _events
    return mock


# ══════════════════════════════════════════════════════════
# UnifiedAgentEngine 测试
# ══════════════════════════════════════════════════════════


class TestUnifiedAgentEngine:
    """统一 Agent 执行引擎测试"""

    @pytest.fixture
    def engine(self) -> UnifiedAgentEngine:
        """创建 UnifiedAgentEngine 实例"""
        return UnifiedAgentEngine()

    # ── 初始化测试 ──

    def test_init_default_workspace(self) -> None:
        """默认工作区初始化"""
        engine = UnifiedAgentEngine()
        assert engine.workspace is not None

    def test_init_custom_workspace(self, tmp_path) -> None:
        """自定义工作区初始化"""
        engine = UnifiedAgentEngine(workspace=tmp_path)
        assert engine.workspace == tmp_path

    # ── 无 API Key 错误处理 ──

    @pytest.mark.asyncio
    async def test_chat_stream_no_api_key(self, engine: UnifiedAgentEngine) -> None:
        """无 API Key 时返回错误"""
        results = []
        async for ev in engine.chat_stream(
            message="测试消息",
            api_key=None,
        ):
            results.append(ev)

        assert len(results) == 1
        assert results[0]["type"] == "error"
        assert "No API Key" in results[0]["message"]

    @pytest.mark.asyncio
    async def test_chat_stream_empty_api_key(self, engine: UnifiedAgentEngine) -> None:
        """空 API Key 时返回错误"""
        results = []
        async for ev in engine.chat_stream(
            message="测试消息",
            api_key="",
        ):
            results.append(ev)

        assert len(results) == 1
        assert results[0]["type"] == "error"

    # ── 策略自动选择成功 ──

    @pytest.mark.asyncio
    async def test_chat_stream_auto_strategy(self, engine: UnifiedAgentEngine) -> None:
        """自动策略选择成功"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()
        mock_grade = MockTaskGrade()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
            ) as mock_auto:
                mock_auto.return_value = "simple"

                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = mock_grade
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="帮我分析代码",
                                api_key="sk-test",
                            ):
                                results.append(ev)

            # 应包含策略信息和执行结果
            types = [e["type"] for e in results]
            assert "strategy" in types
            assert "agent_result" in types

    # ── 策略选择失败降级 ──

    @pytest.mark.asyncio
    async def test_chat_stream_strategy_fallback(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """策略自动选择失败时降级为 auto"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
            ) as mock_auto:
                mock_auto.side_effect = RuntimeError("策略选择失败")

                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                api_key="sk-test",
                            ):
                                results.append(ev)

            # 策略降级后仍应正常执行
            strategy_event = next(
                (e for e in results if e["type"] == "strategy"), None
            )
            assert strategy_event is not None

    # ── 自定义 system_prompt ──

    @pytest.mark.asyncio
    async def test_chat_stream_custom_system_prompt(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """自定义 system_prompt 覆盖默认"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()
        custom_prompt = "自定义系统提示词"

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                api_key="sk-test",
                                system_prompt=custom_prompt,
                            ):
                                results.append(ev)

            strategy_event = next(
                (e for e in results if e["type"] == "strategy"), None
            )
            assert strategy_event is not None

    # ── 固定策略测试 ──

    @pytest.mark.asyncio
    async def test_chat_stream_fixed_strategy(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """指定固定策略时不自动选择"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
            ) as mock_auto:
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                api_key="sk-test",
                                strategy="team",
                            ):
                                results.append(ev)

                # 固定策略不应调用 auto_select_strategy
                mock_auto.assert_not_called()

            strategy_event = next(
                (e for e in results if e["type"] == "strategy"), None
            )
            assert strategy_event is not None
            assert strategy_event["strategy"] == "team"

    # ── 难度分级失败降级 ──

    @pytest.mark.asyncio
    async def test_chat_stream_grade_failure(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """难度分级失败时降级处理"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.side_effect = RuntimeError(
                            "分级失败"
                        )
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                api_key="sk-test",
                            ):
                                results.append(ev)

            # 分级失败应降级，不应阻塞执行
            strategy_event = next(
                (e for e in results if e["type"] == "strategy"), None
            )
            assert strategy_event is not None
            assert strategy_event["grade"] is None

    # ── 策略事件结构测试 ──

    @pytest.mark.asyncio
    async def test_chat_stream_strategy_event_structure(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """策略事件结构完整性"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                api_key="sk-test",
                            ):
                                results.append(ev)

            strategy_event = next(
                (e for e in results if e["type"] == "strategy"), None
            )
            assert strategy_event is not None
            assert "strategy" in strategy_event
            assert "config" in strategy_event
            assert "max_iterations" in strategy_event
            assert "grade" in strategy_event

    # ── 上下文传递 ──

    @pytest.mark.asyncio
    async def test_chat_stream_with_context(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """带额外上下文执行"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                api_key="sk-test",
                                context="额外上下文信息",
                            ):
                                results.append(ev)

            agent_result = next(
                (e for e in results if e["type"] == "agent_result"), None
            )
            assert agent_result is not None

    # ── 模型参数传递 ──

    @pytest.mark.asyncio
    async def test_chat_stream_custom_model(
        self, engine: UnifiedAgentEngine
    ) -> None:
        """自定义模型参数"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in engine.chat_stream(
                                message="测试",
                                model="deepseek-v3",
                                api_key="sk-test",
                            ):
                                results.append(ev)

            # 验证 LLM 配置使用了自定义模型
            mock_llm.configure.assert_called_once()
            call_kwargs = mock_llm.configure.call_args[1]
            assert call_kwargs["model"] == "deepseek-v3"


# ══════════════════════════════════════════════════════════
# agent_chat_stream 兼容入口测试
# ══════════════════════════════════════════════════════════


class TestAgentChatStream:
    """兼容入口函数测试"""

    @pytest.mark.asyncio
    async def test_agent_chat_stream_calls_engine(self) -> None:
        """agent_chat_stream 调用引擎"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in agent_chat_stream(
                                message="测试任务",
                                api_key="sk-test",
                            ):
                                results.append(ev)

            assert len(results) >= 2
            types = [e["type"] for e in results]
            assert "strategy" in types
            assert "agent_result" in types

    @pytest.mark.asyncio
    async def test_agent_chat_stream_no_api_key(self) -> None:
        """无 API Key 错误"""
        results = []
        async for ev in agent_chat_stream(
            message="测试",
            api_key=None,
        ):
            results.append(ev)

        assert len(results) == 1
        assert results[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_agent_chat_stream_with_context(self) -> None:
        """带上下文执行"""
        mock_llm = _make_mock_llm()
        mock_loop = _make_mock_loop_events()
        mock_strategy = _make_mock_strategy()

        with patch(
            "pycoder.server.services.unified_agent.registry"
        ) as mock_registry:
            mock_registry.resolve.return_value = mock_llm

            with patch(
                "pycoder.server.services.unified_agent.auto_select_strategy",
                new_callable=AsyncMock,
                return_value="simple",
            ):
                with patch(
                    "pycoder.server.services.unified_agent.get_strategy",
                    return_value=mock_strategy,
                ):
                    with patch(
                        "pycoder.server.services.unified_agent.get_task_grader",
                    ) as mock_grader_factory:
                        mock_grader = MagicMock()
                        mock_grader.grade.return_value = MockTaskGrade()
                        mock_grader_factory.return_value = mock_grader

                        with patch(
                            "pycoder.server.services.unified_agent.UnifiedAgentLoop",
                            return_value=mock_loop,
                        ):
                            results = []
                            async for ev in agent_chat_stream(
                                message="测试",
                                api_key="sk-test",
                                context="文件上下文",
                            ):
                                results.append(ev)

            assert len(results) >= 2