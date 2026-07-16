"""
Agent 策略定义单元测试

测试 AgentStrategy、策略配置、辅助函数：
- AgentStrategy 数据类创建
- 三种预定义策略（SIMPLE / TEAM / AUTO）
- STRATEGY_MAP 映射
- get_strategy() 按名称获取
- resolve_iterations_for_grade() 难度档迭代预算
- auto_select_strategy() 自动策略选择
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.agent_strategies import (
    SIMPLE_STRATEGY,
    TEAM_STRATEGY,
    AUTO_STRATEGY,
    STRATEGY_MAP,
    UNIFIED_SYSTEM_PROMPT,
    GRADE_ITERATION_BUDGET,
    AgentStrategy,
    get_strategy,
    resolve_iterations_for_grade,
    auto_select_strategy,
)


# ══════════════════════════════════════════════════════════
# 测试：AgentStrategy 数据类
# ══════════════════════════════════════════════════════════


class TestAgentStrategy:
    """AgentStrategy 数据类测试"""

    def test_create_default_strategy(self):
        """创建默认策略配置"""
        strategy = AgentStrategy(
            name="test",
            description="测试策略",
            max_iterations=10,
            tool_timeout=30,
            max_concurrent_tools=5,
            enable_rumination=False,
            enable_snapshots=False,
            enable_qa_review=False,
        )
        assert strategy.name == "test"
        assert strategy.description == "测试策略"
        assert strategy.max_iterations == 10
        assert strategy.tool_timeout == 30
        assert strategy.max_concurrent_tools == 5
        assert strategy.enable_rumination is False
        assert strategy.enable_snapshots is False
        assert strategy.enable_qa_review is False
        assert strategy.system_prompt == UNIFIED_SYSTEM_PROMPT
        assert strategy.roles == []

    def test_create_strategy_with_roles(self):
        """创建带角色的策略（team 模式）"""
        roles = [
            {"id": "pm", "name": "项目经理", "model": "deepseek-chat"},
            {"id": "dev", "name": "开发者", "model": "deepseek-chat"},
        ]
        strategy = AgentStrategy(
            name="team_custom",
            description="自定义团队",
            max_iterations=20,
            tool_timeout=60,
            max_concurrent_tools=3,
            enable_rumination=True,
            enable_snapshots=True,
            enable_qa_review=True,
            roles=roles,
        )
        assert strategy.roles == roles
        assert len(strategy.roles) == 2

    def test_create_strategy_with_custom_prompt(self):
        """创建自定义系统提示词的策略"""
        custom_prompt = "你是自定义 AI 助手"
        strategy = AgentStrategy(
            name="custom",
            description="自定义策略",
            max_iterations=5,
            tool_timeout=10,
            max_concurrent_tools=2,
            enable_rumination=False,
            enable_snapshots=False,
            enable_qa_review=False,
            system_prompt=custom_prompt,
        )
        assert strategy.system_prompt == custom_prompt

    def test_strategy_dataclass_fields(self):
        """策略包含所有必要字段"""
        strategy = AgentStrategy(
            name="x",
            description="x",
            max_iterations=1,
            tool_timeout=1,
            max_concurrent_tools=1,
            enable_rumination=False,
            enable_snapshots=False,
            enable_qa_review=False,
        )
        fields = asdict(strategy)
        expected_keys = {
            "name",
            "description",
            "max_iterations",
            "tool_timeout",
            "max_concurrent_tools",
            "enable_rumination",
            "enable_snapshots",
            "enable_qa_review",
            "system_prompt",
            "roles",
        }
        assert set(fields.keys()) == expected_keys


# ══════════════════════════════════════════════════════════
# 测试：预定义策略
# ══════════════════════════════════════════════════════════


class TestPredefinedStrategies:
    """预定义策略测试"""

    def test_simple_strategy(self):
        """SIMPLE_STRATEGY 配置正确"""
        assert SIMPLE_STRATEGY.name == "simple"
        assert SIMPLE_STRATEGY.max_iterations == 15
        assert SIMPLE_STRATEGY.tool_timeout == 30
        assert SIMPLE_STRATEGY.max_concurrent_tools == 5
        assert SIMPLE_STRATEGY.enable_rumination is True
        assert SIMPLE_STRATEGY.enable_snapshots is False
        assert SIMPLE_STRATEGY.enable_qa_review is False
        assert "单 Agent 交互" in SIMPLE_STRATEGY.description

    def test_team_strategy(self):
        """TEAM_STRATEGY 配置正确"""
        assert TEAM_STRATEGY.name == "team"
        assert TEAM_STRATEGY.max_iterations == 10
        assert TEAM_STRATEGY.tool_timeout == 60
        assert TEAM_STRATEGY.max_concurrent_tools == 3
        assert TEAM_STRATEGY.enable_rumination is True
        assert TEAM_STRATEGY.enable_snapshots is True
        assert TEAM_STRATEGY.enable_qa_review is True
        assert "多 Agent 团队协作" in TEAM_STRATEGY.description
        assert len(TEAM_STRATEGY.roles) == 4
        role_ids = {r["id"] for r in TEAM_STRATEGY.roles}
        assert role_ids == {"pm", "architect", "developer", "qa"}

    def test_auto_strategy(self):
        """AUTO_STRATEGY 配置正确"""
        assert AUTO_STRATEGY.name == "auto"
        assert AUTO_STRATEGY.max_iterations == 50
        assert AUTO_STRATEGY.tool_timeout == 60
        assert AUTO_STRATEGY.max_concurrent_tools == 5
        assert AUTO_STRATEGY.enable_rumination is True
        assert AUTO_STRATEGY.enable_snapshots is True
        assert AUTO_STRATEGY.enable_qa_review is True
        assert "全自主流水线" in AUTO_STRATEGY.description

    def test_strategy_map_contains_all(self):
        """STRATEGY_MAP 包含所有三种策略"""
        assert "simple" in STRATEGY_MAP
        assert "team" in STRATEGY_MAP
        assert "auto" in STRATEGY_MAP
        assert STRATEGY_MAP["simple"] is SIMPLE_STRATEGY
        assert STRATEGY_MAP["team"] is TEAM_STRATEGY
        assert STRATEGY_MAP["auto"] is AUTO_STRATEGY


# ══════════════════════════════════════════════════════════
# 测试：get_strategy()
# ══════════════════════════════════════════════════════════


class TestGetStrategy:
    """get_strategy() 函数测试"""

    def test_get_simple(self):
        """获取 simple 策略"""
        strategy = get_strategy("simple")
        assert strategy is SIMPLE_STRATEGY

    def test_get_team(self):
        """获取 team 策略"""
        strategy = get_strategy("team")
        assert strategy is TEAM_STRATEGY

    def test_get_auto(self):
        """获取 auto 策略"""
        strategy = get_strategy("auto")
        assert strategy is AUTO_STRATEGY

    def test_get_unknown_returns_simple(self):
        """未知策略名称返回 SIMPLE_STRATEGY"""
        strategy = get_strategy("nonexistent")
        assert strategy is SIMPLE_STRATEGY

    def test_get_empty_string_returns_simple(self):
        """空字符串返回 SIMPLE_STRATEGY"""
        strategy = get_strategy("")
        assert strategy is SIMPLE_STRATEGY

    def test_get_case_sensitive(self):
        """策略名称大小写敏感（大写不匹配）"""
        strategy = get_strategy("SIMPLE")
        assert strategy is SIMPLE_STRATEGY  # 兜底为 SIMPLE


# ══════════════════════════════════════════════════════════
# 测试：resolve_iterations_for_grade()
# ══════════════════════════════════════════════════════════


class TestResolveIterationsForGrade:
    """resolve_iterations_for_grade() 函数测试"""

    def test_low_grade(self):
        """低难度返回 5"""
        assert resolve_iterations_for_grade("low") == 5

    def test_medium_grade(self):
        """中难度返回 15"""
        assert resolve_iterations_for_grade("medium") == 15

    def test_high_grade(self):
        """高难度返回 50"""
        assert resolve_iterations_for_grade("high") == 50

    def test_unknown_grade_returns_base(self):
        """未知难度返回 base 默认值"""
        assert resolve_iterations_for_grade("unknown") == 50

    def test_unknown_grade_custom_base(self):
        """未知难度返回自定义 base"""
        assert resolve_iterations_for_grade("unknown", base=30) == 30

    def test_empty_grade_returns_base(self):
        """空字符串返回 base"""
        assert resolve_iterations_for_grade("") == 50

    def test_grade_budget_mapping(self):
        """GRADE_ITERATION_BUDGET 映射完整性"""
        assert GRADE_ITERATION_BUDGET["low"] == 5
        assert GRADE_ITERATION_BUDGET["medium"] == 15
        assert GRADE_ITERATION_BUDGET["high"] == 50


# ══════════════════════════════════════════════════════════
# 测试：auto_select_strategy()
# ══════════════════════════════════════════════════════════


class TestAutoSelectStrategy:
    """auto_select_strategy() 函数测试"""

    @pytest.mark.asyncio
    async def test_auto_select_simple(self):
        """简单任务选择 simple 策略"""

        @dataclass
        class FakeEvent:
            event_type: str
            content: str = ""

        async def mock_llm(prompt: str):
            yield FakeEvent("token", "simple")
            yield FakeEvent("done", "simple")

        result = await auto_select_strategy("如何定义 Python 变量？", mock_llm)
        assert result == "simple"

    @pytest.mark.asyncio
    async def test_auto_select_team(self):
        """复杂任务选择 team 策略"""

        @dataclass
        class FakeEvent:
            event_type: str
            content: str = ""

        async def mock_llm(prompt: str):
            yield FakeEvent("token", "team")
            yield FakeEvent("done", "team")

        result = await auto_select_strategy("开发一个完整的用户管理系统", mock_llm)
        assert result == "team"

    @pytest.mark.asyncio
    async def test_auto_select_auto(self):
        """大型任务选择 auto 策略"""

        @dataclass
        class FakeEvent:
            event_type: str
            content: str = ""

        async def mock_llm(prompt: str):
            yield FakeEvent("token", "auto")
            yield FakeEvent("done", "auto")

        result = await auto_select_strategy("从零搭建一个微服务架构", mock_llm)
        assert result == "auto"

    @pytest.mark.asyncio
    async def test_auto_select_partial_match(self):
        """LLM 返回多词但包含策略名"""

        @dataclass
        class FakeEvent:
            event_type: str
            content: str = ""

        async def mock_llm(prompt: str):
            yield FakeEvent("token", "根据分析，建议使用 simple 策略")
            yield FakeEvent("done", "根据分析，建议使用 simple 策略")

        result = await auto_select_strategy("简单任务", mock_llm)
        assert result == "simple"

    @pytest.mark.asyncio
    async def test_auto_select_llm_error_fallback(self):
        """LLM 调用出错时回退到 auto"""

        async def mock_llm(prompt: str):
            raise RuntimeError("LLM 服务不可用")
            yield  # 使成为生成器

        result = await auto_select_strategy("测试任务", mock_llm)
        assert result == "auto"

    @pytest.mark.asyncio
    async def test_auto_select_empty_response_fallback(self):
        """LLM 返回空内容时回退到 auto"""

        @dataclass
        class FakeEvent:
            event_type: str
            content: str = ""

        async def mock_llm(prompt: str):
            yield FakeEvent("done", "")

        result = await auto_select_strategy("测试任务", mock_llm)
        assert result == "auto"

    @pytest.mark.asyncio
    async def test_auto_select_priority_order(self):
        """auto > team > simple 优先级顺序"""

        @dataclass
        class FakeEvent:
            event_type: str
            content: str = ""

        async def mock_llm(prompt: str):
            # 同时包含多个策略名
            yield FakeEvent("token", "可能是 simple 或 team 或 auto")
            yield FakeEvent("done", "可能是 simple 或 team 或 auto")

        result = await auto_select_strategy("综合任务", mock_llm)
        # auto 优先级最高，先匹配到
        assert result == "auto"