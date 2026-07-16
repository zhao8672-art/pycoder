"""
智能路由决策中心 — 协调意图分析、Agent 选择、工具规划

作为新的 AI 决策入口，替代旧有的固定模式路由。
整合 IntentAnalyzer + AgentSelector + ToolPlanner 三大模块，
输出统一的 RoutingDecision 供执行引擎使用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pycoder.brain.intent_analyzer import IntentAnalysis, IntentAnalyzer, get_intent_analyzer
from pycoder.brain.agent_selector import AgentSelection, AgentSelector, get_agent_selector
from pycoder.brain.tool_planner import ToolPlan, ToolPlanner, get_tool_planner

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class ExecutionConfig:
    """执行配置"""

    max_iterations: int = 15
    tool_timeout: int = 30
    temperature: float = 0.3
    max_tokens: int = 8192
    enable_rumination: bool = True
    enable_snapshots: bool = False
    enable_qa_review: bool = False
    max_concurrent_tools: int = 5
    strategy: str = "auto"  # simple/team/auto


@dataclass
class RoutingDecision:
    """路由决策结果"""

    intent: IntentAnalysis
    agent: AgentSelection
    tool_plan: ToolPlan
    execution_config: ExecutionConfig
    confidence: float = 0.0
    decision_time_ms: float = 0.0
    decision_method: str = "rule"  # rule/llm/hybrid

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": {
                "domain": self.intent.technical_domain,
                "task_type": self.intent.task_type,
                "complexity": self.intent.complexity,
                "complexity_score": self.intent.complexity_score,
                "normalized": self.intent.normalized_intent,
            },
            "agent": {
                "primary": self.agent.primary_agent,
                "secondary": self.agent.secondary_agents,
                "reason": self.agent.selection_reason,
                "confidence": self.agent.confidence,
            },
            "tool_plan": {
                "estimated_calls": self.tool_plan.estimated_tool_calls,
                "max_calls": self.tool_plan.max_tool_calls,
                "categories": self.tool_plan.tool_categories,
                "allow_direct_answer": self.tool_plan.allow_direct_answer,
            },
            "execution": {
                "max_iterations": self.execution_config.max_iterations,
                "strategy": self.execution_config.strategy,
            },
            "confidence": self.confidence,
            "decision_time_ms": self.decision_time_ms,
        }


# ══════════════════════════════════════════════════════════
# 复杂度 → 执行配置映射
# ══════════════════════════════════════════════════════════

COMPLEXITY_EXECUTION_CONFIG: dict[str, ExecutionConfig] = {
    "trivial": ExecutionConfig(
        max_iterations=1, tool_timeout=10, temperature=0.5,
        max_tokens=2048, enable_rumination=False, enable_snapshots=False,
        enable_qa_review=False, max_concurrent_tools=0, strategy="simple",
    ),
    "simple": ExecutionConfig(
        max_iterations=5, tool_timeout=20, temperature=0.3,
        max_tokens=4096, enable_rumination=False, enable_snapshots=False,
        enable_qa_review=False, max_concurrent_tools=3, strategy="simple",
    ),
    "medium": ExecutionConfig(
        max_iterations=15, tool_timeout=30, temperature=0.3,
        max_tokens=8192, enable_rumination=True, enable_snapshots=False,
        enable_qa_review=False, max_concurrent_tools=5, strategy="simple",
    ),
    "complex": ExecutionConfig(
        max_iterations=50, tool_timeout=60, temperature=0.2,
        max_tokens=16384, enable_rumination=True, enable_snapshots=True,
        enable_qa_review=True, max_concurrent_tools=5, strategy="auto",
    ),
}


# ══════════════════════════════════════════════════════════
# IntelligentRouter
# ══════════════════════════════════════════════════════════


class IntelligentRouter:
    """智能路由决策中心

    协调三大模块完成从用户输入到执行计划的完整决策链:
      1. IntentAnalyzer → 理解用户意图
      2. AgentSelector → 选择最佳 Agent
      3. ToolPlanner → 规划工具调用
      4. 输出统一的 RoutingDecision
    """

    def __init__(
        self,
        intent_analyzer: IntentAnalyzer | None = None,
        agent_selector: AgentSelector | None = None,
        tool_planner: ToolPlanner | None = None,
    ) -> None:
        self._intent_analyzer = intent_analyzer or get_intent_analyzer()
        self._agent_selector = agent_selector or get_agent_selector()
        self._tool_planner = tool_planner or get_tool_planner()
        self._decision_cache: dict[str, RoutingDecision] = {}  # 简单缓存

    def set_llm(self, llm_provider: Any) -> None:
        """设置 LLM 提供商（用于深度分析）"""
        self._intent_analyzer.set_llm(llm_provider)

    def decide(self, message: str, use_deep: bool = False) -> RoutingDecision:
        """根据用户消息做出路由决策

        Args:
            message: 用户原始消息
            use_deep: 是否使用 LLM 深度分析（会增加延迟）

        Returns:
            RoutingDecision 路由决策结果
        """
        import time
        start = time.monotonic()

        # 1. 意图分析
        intent = self._intent_analyzer.analyze(message)

        # 2. Agent 选择
        agent = self._agent_selector.select(intent)

        # 3. 工具规划
        tool_plan = self._tool_planner.plan(intent)

        # 4. 执行配置
        exec_config = self._get_execution_config(intent, agent)

        # 5. 综合置信度
        confidence = (
            intent.confidence * 0.4
            + agent.confidence * 0.4
            + 0.2  # 工具规划基础置信度
        )

        decision = RoutingDecision(
            intent=intent,
            agent=agent,
            tool_plan=tool_plan,
            execution_config=exec_config,
            confidence=confidence,
            decision_time_ms=(time.monotonic() - start) * 1000,
            decision_method="rule",
        )

        logger.info(
            "routing_decision: domain=%s type=%s complexity=%s agent=%s tools=%d confidence=%.2f",
            intent.technical_domain, intent.task_type, intent.complexity,
            agent.primary_agent, tool_plan.estimated_tool_calls, confidence,
        )

        return decision

    async def decide_deep(self, message: str) -> RoutingDecision:
        """使用 LLM 深度分析做路由决策（异步）"""
        import time
        start = time.monotonic()

        # 深度意图分析
        intent = await self._intent_analyzer.analyze_deep(message)

        # Agent 选择
        agent = self._agent_selector.select(intent)

        # 工具规划
        tool_plan = self._tool_planner.plan(intent)

        # 执行配置
        exec_config = self._get_execution_config(intent, agent)

        confidence = (
            intent.confidence * 0.4
            + agent.confidence * 0.4
            + 0.2
        )

        decision = RoutingDecision(
            intent=intent,
            agent=agent,
            tool_plan=tool_plan,
            execution_config=exec_config,
            confidence=confidence,
            decision_time_ms=(time.monotonic() - start) * 1000,
            decision_method="llm",
        )

        logger.info(
            "routing_decision_deep: domain=%s type=%s complexity=%s agent=%s confidence=%.2f",
            intent.technical_domain, intent.task_type, intent.complexity,
            agent.primary_agent, confidence,
        )

        return decision

    def _get_execution_config(self, intent: IntentAnalysis, agent: AgentSelection) -> ExecutionConfig:
        """根据意图和 Agent 选择确定执行配置"""
        config = COMPLEXITY_EXECUTION_CONFIG.get(
            intent.complexity, COMPLEXITY_EXECUTION_CONFIG["medium"]
        )

        # 根据 Agent 模型分层调整
        if agent.model_tier == "premium":
            config = ExecutionConfig(
                max_iterations=config.max_iterations,
                tool_timeout=config.tool_timeout,
                temperature=0.2,
                max_tokens=config.max_tokens,
                enable_rumination=config.enable_rumination,
                enable_snapshots=config.enable_snapshots,
                enable_qa_review=config.enable_qa_review,
                max_concurrent_tools=config.max_concurrent_tools,
                strategy=config.strategy,
            )

        # 多 Agent 协作 → team 策略
        if agent.secondary_agents:
            config = ExecutionConfig(
                max_iterations=config.max_iterations,
                tool_timeout=config.tool_timeout,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                enable_rumination=config.enable_rumination,
                enable_snapshots=config.enable_snapshots,
                enable_qa_review=True,
                max_concurrent_tools=config.max_concurrent_tools,
                strategy="team",
            )

        return config

    def record_feedback(self, message: str, success: bool, agent_id: str) -> None:
        """记录反馈，用于优化后续决策"""
        self._agent_selector.record_result(agent_id, success)

    def get_cache_stats(self) -> dict:
        """获取决策缓存统计"""
        return {
            "cache_size": len(self._decision_cache),
            "cache_keys": list(self._decision_cache.keys())[:10],
        }


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_router_instance: IntelligentRouter | None = None


def get_intelligent_router() -> IntelligentRouter:
    """获取全局智能路由器"""
    global _router_instance
    if _router_instance is None:
        _router_instance = IntelligentRouter()
    return _router_instance