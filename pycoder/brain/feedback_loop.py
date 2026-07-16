"""
反馈学习循环 — 实时收集执行信号，持续优化决策模型

特性:
  - 即时学习: 每次执行后更新统计
  - 批量学习: 定期汇总分析趋势
  - 自适应权重: 根据反馈调整 Agent 选择和工具规划策略
  - 持久化存储: 学习数据写入 signals.jsonl，跨会话保持
  - 隐式反馈: 工具成功率、任务完成率、响应延迟
  - 显式反馈: 用户满意度评分、👍/👎

与现有模块协作:
  - IntentAnalyzer → 提供意图分析准确率反馈
  - AgentSelector → 更新历史成功率
  - ToolPlanner → 优化工具调用策略
  - IntelligentRouter → 调整决策置信度阈值
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycoder.brain.intent_analyzer import IntentAnalysis
from pycoder.brain.agent_selector import AgentSelection
from pycoder.brain.tool_planner import ToolPlan

logger = logging.getLogger(__name__)

# 默认信号存储路径
DEFAULT_SIGNALS_PATH = Path(__file__).resolve().parents[2] / "data" / "signals.jsonl"
DEFAULT_EXPERIENCES_PATH = Path(__file__).resolve().parents[2] / "data" / "experiences"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "adaptive_config.json"


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class ExecutionSignal:
    """单次执行信号"""

    timestamp: float = field(default_factory=time.time)
    session_id: str = ""

    # 意图
    intent_domain: str = ""
    intent_task_type: str = ""
    intent_complexity: str = ""
    intent_complexity_score: int = 0
    intent_confidence: float = 0.0

    # Agent
    agent_id: str = ""
    agent_confidence: float = 0.0
    agent_secondary: list[str] = field(default_factory=list)

    # 工具
    tool_plan_estimated: int = 0
    tool_plan_max: int = 0
    tool_actual_calls: int = 0
    tool_success_calls: int = 0
    tool_failure_calls: int = 0
    tool_categories: list[str] = field(default_factory=list)

    # 执行
    strategy: str = ""
    max_iterations: int = 0
    actual_iterations: int = 0
    execution_time_ms: float = 0.0
    total_tokens: int = 0

    # 结果
    task_completed: bool = False
    completion_reason: str = ""  # "done" | "max_iterations" | "error" | "user_cancelled"
    error_message: str = ""

    # 用户反馈
    user_rating: int = 0  # 0=未评价, 1=差, 2=中, 3=好, 4=很好, 5=完美
    user_feedback_text: str = ""
    reaction: str = ""  # "thumbs_up" | "thumbs_down" | ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.timestamp,
            "session": self.session_id,
            "intent": {
                "domain": self.intent_domain,
                "task_type": self.intent_task_type,
                "complexity": self.intent_complexity,
                "score": self.intent_complexity_score,
                "confidence": self.intent_confidence,
            },
            "agent": {
                "id": self.agent_id,
                "confidence": self.agent_confidence,
                "secondary": self.agent_secondary,
            },
            "tool": {
                "estimated": self.tool_plan_estimated,
                "max": self.tool_plan_max,
                "actual": self.tool_actual_calls,
                "success": self.tool_success_calls,
                "failure": self.tool_failure_calls,
                "categories": self.tool_categories,
            },
            "execution": {
                "strategy": self.strategy,
                "max_iterations": self.max_iterations,
                "actual_iterations": self.actual_iterations,
                "time_ms": self.execution_time_ms,
                "tokens": self.total_tokens,
            },
            "result": {
                "completed": self.task_completed,
                "reason": self.completion_reason,
                "error": self.error_message,
            },
            "feedback": {
                "rating": self.user_rating,
                "text": self.user_feedback_text,
                "reaction": self.reaction,
            },
        }


@dataclass
class AdaptiveWeights:
    """自适应决策权重"""

    # Agent 选择维度权重
    agent_domain_weight: float = 0.30
    agent_task_type_weight: float = 0.25
    agent_complexity_weight: float = 0.20
    agent_history_weight: float = 0.15
    agent_speed_weight: float = 0.10

    # 工具规划策略
    tool_parallel_threshold: int = 5  # 并行读操作的最小数量
    tool_retry_max: int = 2  # 工具失败最大重试次数
    tool_timeout_scale: float = 1.0  # 超时缩放因子

    # 决策阈值
    min_confidence_threshold: float = 0.5  # 最低置信度阈值
    deep_analysis_threshold: float = 0.7  # 低于此置信度触发 LLM 深度分析
    max_iter_buffer: int = 5  # 迭代预算缓冲

    # 学习率
    learning_rate: float = 0.1  # 权重更新学习率

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_weights": {
                "domain": self.agent_domain_weight,
                "task_type": self.agent_task_type_weight,
                "complexity": self.agent_complexity_weight,
                "history": self.agent_history_weight,
                "speed": self.agent_speed_weight,
            },
            "tool": {
                "parallel_threshold": self.tool_parallel_threshold,
                "retry_max": self.tool_retry_max,
                "timeout_scale": self.tool_timeout_scale,
            },
            "thresholds": {
                "min_confidence": self.min_confidence_threshold,
                "deep_analysis": self.deep_analysis_threshold,
                "max_iter_buffer": self.max_iter_buffer,
            },
            "learning_rate": self.learning_rate,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AdaptiveWeights:
        aw = cls()
        if "agent_weights" in data:
            aw.agent_domain_weight = data["agent_weights"].get("domain", aw.agent_domain_weight)
            aw.agent_task_type_weight = data["agent_weights"].get("task_type", aw.agent_task_type_weight)
            aw.agent_complexity_weight = data["agent_weights"].get("complexity", aw.agent_complexity_weight)
            aw.agent_history_weight = data["agent_weights"].get("history", aw.agent_history_weight)
            aw.agent_speed_weight = data["agent_weights"].get("speed", aw.agent_speed_weight)
        if "tool" in data:
            aw.tool_parallel_threshold = data["tool"].get("parallel_threshold", aw.tool_parallel_threshold)
            aw.tool_retry_max = data["tool"].get("retry_max", aw.tool_retry_max)
            aw.tool_timeout_scale = data["tool"].get("timeout_scale", aw.tool_timeout_scale)
        if "thresholds" in data:
            aw.min_confidence_threshold = data["thresholds"].get("min_confidence", aw.min_confidence_threshold)
            aw.deep_analysis_threshold = data["thresholds"].get("deep_analysis", aw.deep_analysis_threshold)
            aw.max_iter_buffer = data["thresholds"].get("max_iter_buffer", aw.max_iter_buffer)
        if "learning_rate" in data:
            aw.learning_rate = data["learning_rate"]
        return aw


@dataclass
class AggregatedStats:
    """聚合统计"""

    total_executions: int = 0
    total_completed: int = 0
    total_tokens: int = 0
    total_time_ms: float = 0.0

    # 按 domain 统计
    domain_stats: dict[str, dict] = field(default_factory=dict)

    # 按 agent 统计
    agent_stats: dict[str, dict] = field(default_factory=dict)

    # 按策略统计
    strategy_stats: dict[str, dict] = field(default_factory=dict)

    # 工具统计
    avg_tool_success_rate: float = 0.0
    avg_tool_calls_per_task: float = 0.0

    # 用户满意度
    avg_user_rating: float = 0.0
    thumbs_up_rate: float = 0.0

    @property
    def completion_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_completed / self.total_executions

    @property
    def avg_time_ms(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_time_ms / self.total_executions

    @property
    def avg_tokens(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_tokens / self.total_executions


# ══════════════════════════════════════════════════════════
# FeedbackLoop
# ══════════════════════════════════════════════════════════


class FeedbackLoop:
    """反馈学习循环

    实时收集执行信号，持续优化决策模型。
    支持即时学习、批量分析、自适应权重调整。

    用法:
        loop = FeedbackLoop()
        signal = loop.start_signal(session_id="abc123")
        # ... 执行任务 ...
        loop.end_signal(signal, completed=True, iterations=5, tool_calls=3, tool_success=3)
        loop.record_user_rating(signal, rating=4, text="很好")
        loop.learn()  # 触发学习更新
    """

    def __init__(
        self,
        signals_path: Path | None = None,
        experiences_path: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._signals_path = signals_path or DEFAULT_SIGNALS_PATH
        self._experiences_path = experiences_path or DEFAULT_EXPERIENCES_PATH
        self._config_path = config_path or DEFAULT_CONFIG_PATH

        # 运行时信号缓冲
        self._pending_signals: list[ExecutionSignal] = []
        self._signal_buffer_max: int = 50  # 攒够多少条后批量写入

        # 自适应权重
        self.weights = self._load_weights()

        # 运行时统计
        self._recent_signals: list[ExecutionSignal] = []  # 最近 100 条
        self._recent_max: int = 100

        # 确保目录存在
        self._signals_path.parent.mkdir(parents=True, exist_ok=True)
        self._experiences_path.mkdir(parents=True, exist_ok=True)

        logger.info("feedback_loop_initialized signals=%s", self._signals_path)

    # ── 信号生命周期 ───────────────────────────────

    def start_signal(
        self,
        session_id: str = "",
        intent: IntentAnalysis | None = None,
        agent: AgentSelection | None = None,
        tool_plan: ToolPlan | None = None,
        strategy: str = "",
        max_iterations: int = 0,
    ) -> ExecutionSignal:
        """开始记录一次执行信号

        Args:
            session_id: 会话 ID
            intent: 意图分析结果
            agent: Agent 选择结果
            tool_plan: 工具调用计划
            strategy: 执行策略
            max_iterations: 最大迭代次数

        Returns:
            ExecutionSignal 信号对象
        """
        signal = ExecutionSignal(
            timestamp=time.time(),
            session_id=session_id,
        )

        if intent:
            signal.intent_domain = intent.technical_domain
            signal.intent_task_type = intent.task_type
            signal.intent_complexity = intent.complexity
            signal.intent_complexity_score = intent.complexity_score
            signal.intent_confidence = intent.confidence

        if agent:
            signal.agent_id = agent.primary_agent
            signal.agent_confidence = agent.confidence
            signal.agent_secondary = agent.secondary_agents

        if tool_plan:
            signal.tool_plan_estimated = tool_plan.estimated_tool_calls
            signal.tool_plan_max = tool_plan.max_tool_calls
            signal.tool_categories = tool_plan.tool_categories

        signal.strategy = strategy
        signal.max_iterations = max_iterations

        return signal

    def end_signal(
        self,
        signal: ExecutionSignal,
        completed: bool = False,
        completion_reason: str = "",
        iterations: int = 0,
        tool_calls: int = 0,
        tool_success: int = 0,
        tool_failure: int = 0,
        execution_time_ms: float = 0.0,
        total_tokens: int = 0,
        error_message: str = "",
    ) -> None:
        """结束信号记录并保存

        Args:
            signal: 信号对象
            completed: 任务是否完成
            completion_reason: 完成原因
            iterations: 实际迭代次数
            tool_calls: 实际工具调用次数
            tool_success: 成功工具调用次数
            tool_failure: 失败工具调用次数
            execution_time_ms: 执行耗时
            total_tokens: Token 消耗
            error_message: 错误信息
        """
        signal.task_completed = completed
        signal.completion_reason = completion_reason
        signal.actual_iterations = iterations
        signal.tool_actual_calls = tool_calls
        signal.tool_success_calls = tool_success
        signal.tool_failure_calls = tool_failure
        signal.execution_time_ms = execution_time_ms
        signal.total_tokens = total_tokens
        signal.error_message = error_message

        self._pending_signals.append(signal)
        self._recent_signals.append(signal)

        # 维护最近信号窗口
        if len(self._recent_signals) > self._recent_max:
            self._recent_signals = self._recent_signals[-self._recent_max:]

        # 批量持久化
        if len(self._pending_signals) >= self._signal_buffer_max:
            self._flush_signals()

        logger.debug(
            "signal_recorded: agent=%s completed=%s tools=%d/%d time=%.0fms",
            signal.agent_id, signal.task_completed,
            signal.tool_success_calls, signal.tool_actual_calls,
            signal.execution_time_ms,
        )

    def record_user_rating(
        self,
        signal: ExecutionSignal,
        rating: int = 0,
        text: str = "",
        reaction: str = "",
    ) -> None:
        """记录用户反馈

        Args:
            signal: 信号对象
            rating: 评分 1-5
            text: 反馈文本
            reaction: 快捷反应 "thumbs_up" | "thumbs_down"
        """
        signal.user_rating = max(0, min(5, rating))
        signal.user_feedback_text = text
        signal.reaction = reaction

        logger.info(
            "user_feedback: rating=%d reaction=%s text=%s",
            rating, reaction, text[:100] if text else "",
        )

    # ── 学习与优化 ─────────────────────────────────

    def learn(self) -> dict[str, Any]:
        """触发一轮学习，更新自适应权重

        基于近期信号分析，调整:
          - Agent 选择维度权重
          - 工具规划策略
          - 决策阈值

        Returns:
            学习结果摘要
        """
        if not self._recent_signals:
            return {"status": "no_data", "message": "无近期信号数据"}

        changes: dict[str, Any] = {}
        old_weights = self.weights.to_dict()

        # 1. 分析 Agent 选择准确率，调整各维度权重
        agent_accuracy = self._analyze_agent_accuracy()
        if agent_accuracy:
            changes["agent_weights"] = self._adjust_agent_weights(agent_accuracy)

        # 2. 分析工具调用效率
        tool_efficiency = self._analyze_tool_efficiency()
        if tool_efficiency:
            changes["tool"] = self._adjust_tool_strategy(tool_efficiency)

        # 3. 分析置信度与成功率的关系
        confidence_analysis = self._analyze_confidence_correlation()
        if confidence_analysis:
            changes["thresholds"] = self._adjust_thresholds(confidence_analysis)

        # 4. 保存更新后的权重
        self._save_weights()

        changes["previous"] = old_weights
        changes["current"] = self.weights.to_dict()
        changes["status"] = "updated"
        changes["signals_analyzed"] = len(self._recent_signals)

        logger.info(
            "feedback_learned: signals=%d agent_weight_changes=%s",
            len(self._recent_signals),
            changes.get("agent_weights", "none"),
        )

        return changes

    def get_stats(self) -> AggregatedStats:
        """获取聚合统计"""
        stats = AggregatedStats()
        signals = self._recent_signals

        if not signals:
            return stats

        stats.total_executions = len(signals)
        stats.total_completed = sum(1 for s in signals if s.task_completed)
        stats.total_tokens = sum(s.total_tokens for s in signals)
        stats.total_time_ms = sum(s.execution_time_ms for s in signals)

        # 按 domain 统计
        for s in signals:
            domain = s.intent_domain or "unknown"
            if domain not in stats.domain_stats:
                stats.domain_stats[domain] = {"total": 0, "completed": 0}
            stats.domain_stats[domain]["total"] += 1
            if s.task_completed:
                stats.domain_stats[domain]["completed"] += 1

        # 按 agent 统计
        for s in signals:
            agent = s.agent_id or "unknown"
            if agent not in stats.agent_stats:
                stats.agent_stats[agent] = {"total": 0, "completed": 0, "avg_rating": 0.0}
            stats.agent_stats[agent]["total"] += 1
            if s.task_completed:
                stats.agent_stats[agent]["completed"] += 1
            if s.user_rating > 0:
                prev = stats.agent_stats[agent].get("rating_sum", 0)
                cnt = stats.agent_stats[agent].get("rating_count", 0)
                stats.agent_stats[agent]["rating_sum"] = prev + s.user_rating
                stats.agent_stats[agent]["rating_count"] = cnt + 1

        # 计算 agent 平均评分
        for agent, data in stats.agent_stats.items():
            if data.get("rating_count", 0) > 0:
                data["avg_rating"] = data["rating_sum"] / data["rating_count"]

        # 按策略统计
        for s in signals:
            st = s.strategy or "unknown"
            if st not in stats.strategy_stats:
                stats.strategy_stats[st] = {"total": 0, "completed": 0}
            stats.strategy_stats[st]["total"] += 1
            if s.task_completed:
                stats.strategy_stats[st]["completed"] += 1

        # 工具统计
        if stats.total_executions > 0:
            total_success = sum(s.tool_success_calls for s in signals)
            total_actual = sum(s.tool_actual_calls for s in signals)
            stats.avg_tool_success_rate = total_success / max(total_actual, 1)
            stats.avg_tool_calls_per_task = total_actual / stats.total_executions

        # 用户满意度
        rated = [s for s in signals if s.user_rating > 0]
        if rated:
            stats.avg_user_rating = sum(s.user_rating for s in rated) / len(rated)

        # 👍 率
        with_reaction = [s for s in signals if s.reaction]
        if with_reaction:
            thumbs_up = sum(1 for s in with_reaction if s.reaction == "thumbs_up")
            stats.thumbs_up_rate = thumbs_up / len(with_reaction)

        return stats

    def get_recommendations(self) -> list[str]:
        """基于学习数据生成优化建议"""
        stats = self.get_stats()
        recommendations: list[str] = []

        if stats.total_executions < 5:
            recommendations.append("数据量不足，建议积累更多执行数据后再优化")
            return recommendations

        # 完成率分析
        if stats.completion_rate < 0.7:
            recommendations.append(
                f"任务完成率偏低 ({stats.completion_rate:.0%})，"
                "建议增加迭代预算或降低复杂度评估阈值"
            )

        # Agent 分析
        for agent, data in stats.agent_stats.items():
            if data["total"] >= 5:
                rate = data["completed"] / data["total"]
                if rate < 0.5:
                    recommendations.append(
                        f"Agent '{agent}' 完成率偏低 ({rate:.0%})，"
                        "建议调整其能力矩阵或降低匹配权重"
                    )

        # 工具成功率
        if stats.avg_tool_success_rate < 0.8:
            recommendations.append(
                f"工具成功率偏低 ({stats.avg_tool_success_rate:.0%})，"
                "建议检查工具执行环境或增加重试机制"
            )

        # 策略分析
        for st, data in stats.strategy_stats.items():
            if data["total"] >= 3:
                rate = data["completed"] / data["total"]
                if rate < 0.6:
                    recommendations.append(
                        f"策略 '{st}' 完成率偏低 ({rate:.0%})，"
                        "建议调整策略配置或增加工具预算"
                    )

        # 用户满意度
        if stats.avg_user_rating < 3.0 and stats.avg_user_rating > 0:
            recommendations.append(
                f"用户满意度偏低 ({stats.avg_user_rating:.1f}/5)，"
                "建议优化回答质量和交互体验"
            )

        if not recommendations:
            recommendations.append("当前系统运行良好，各项指标正常")

        return recommendations

    # ── 内部分析 ───────────────────────────────────

    def _analyze_agent_accuracy(self) -> dict[str, float]:
        """分析 Agent 选择准确率"""
        signals = self._recent_signals
        if not signals:
            return {}

        agent_perf: dict[str, dict] = {}
        for s in signals:
            a = s.agent_id or "none"
            if a not in agent_perf:
                agent_perf[a] = {"total": 0, "completed": 0, "avg_rating": 0.0}
            agent_perf[a]["total"] += 1
            if s.task_completed:
                agent_perf[a]["completed"] += 1
            if s.user_rating > 0:
                agent_perf[a]["avg_rating"] = (
                    (agent_perf[a]["avg_rating"] * (agent_perf[a]["total"] - 1) + s.user_rating)
                    / agent_perf[a]["total"]
                )

        result: dict[str, float] = {}
        for a, perf in agent_perf.items():
            if perf["total"] >= 3:
                result[a] = perf["completed"] / perf["total"]
        return result

    def _analyze_tool_efficiency(self) -> dict[str, Any]:
        """分析工具调用效率"""
        signals = self._recent_signals
        if not signals:
            return {}

        total_estimated = sum(s.tool_plan_estimated for s in signals)
        total_actual = sum(s.tool_actual_calls for s in signals)
        total_success = sum(s.tool_success_calls for s in signals)
        total_failure = sum(s.tool_failure_calls for s in signals)

        return {
            "estimated_vs_actual_ratio": total_actual / max(total_estimated, 1),
            "success_rate": total_success / max(total_actual, 1),
            "failure_rate": total_failure / max(total_actual, 1),
            "avg_calls": total_actual / max(len(signals), 1),
        }

    def _analyze_confidence_correlation(self) -> dict[str, Any]:
        """分析置信度与成功率的相关性"""
        signals = self._recent_signals
        if not signals:
            return {}

        high_conf = [s for s in signals if s.intent_confidence >= 0.8]
        low_conf = [s for s in signals if s.intent_confidence < 0.8]

        high_success = sum(1 for s in high_conf if s.task_completed) / max(len(high_conf), 1)
        low_success = sum(1 for s in low_conf if s.task_completed) / max(len(low_conf), 1)

        return {
            "high_confidence_success_rate": high_success,
            "low_confidence_success_rate": low_success,
            "high_conf_count": len(high_conf),
            "low_conf_count": len(low_conf),
            "deep_analysis_needed": low_success < 0.5 and len(low_conf) >= 3,
        }

    # ── 权重调整 ───────────────────────────────────

    def _adjust_agent_weights(self, agent_accuracy: dict[str, float]) -> dict[str, Any]:
        """根据 Agent 准确率调整选择权重"""
        lr = self.weights.learning_rate
        changes: dict[str, Any] = {}

        # 整体准确率
        if agent_accuracy:
            avg_acc = sum(agent_accuracy.values()) / len(agent_accuracy)
            if avg_acc < 0.6:
                # 准确率低 → 增加历史权重（更依赖经验）
                delta = lr * 0.05
                self.weights.agent_history_weight = min(0.35, self.weights.agent_history_weight + delta)
                self.weights.agent_domain_weight = max(0.15, self.weights.agent_domain_weight - delta / 2)
                self.weights.agent_task_type_weight = max(0.10, self.weights.agent_task_type_weight - delta / 2)
                changes = {
                    "action": "increase_history_weight",
                    "reason": f"Agent 准确率 ({avg_acc:.1%}) 偏低，增加历史成功率权重",
                    "new_history_weight": self.weights.agent_history_weight,
                }
            elif avg_acc > 0.85:
                # 准确率高 → 降低历史权重，更多信任实时分析
                delta = lr * 0.03
                self.weights.agent_history_weight = max(0.10, self.weights.agent_history_weight - delta)
                self.weights.agent_domain_weight = min(0.40, self.weights.agent_domain_weight + delta / 2)
                self.weights.agent_task_type_weight = min(0.35, self.weights.agent_task_type_weight + delta / 2)
                changes = {
                    "action": "decrease_history_weight",
                    "reason": f"Agent 准确率 ({avg_acc:.1%}) 高，减少历史依赖",
                    "new_history_weight": self.weights.agent_history_weight,
                }

        # 归一化
        total = (
            self.weights.agent_domain_weight
            + self.weights.agent_task_type_weight
            + self.weights.agent_complexity_weight
            + self.weights.agent_history_weight
            + self.weights.agent_speed_weight
        )
        if abs(total - 1.0) > 0.001:
            scale = 1.0 / total
            self.weights.agent_domain_weight *= scale
            self.weights.agent_task_type_weight *= scale
            self.weights.agent_complexity_weight *= scale
            self.weights.agent_history_weight *= scale
            self.weights.agent_speed_weight *= scale

        return changes

    def _adjust_tool_strategy(self, tool_efficiency: dict[str, Any]) -> dict[str, Any]:
        """根据工具效率调整策略"""
        changes: dict[str, Any] = {}
        lr = self.weights.learning_rate

        success_rate = tool_efficiency.get("success_rate", 1.0)
        if success_rate < 0.7:
            # 成功率低 → 增加重试次数
            self.weights.tool_retry_max = min(5, self.weights.tool_retry_max + 1)
            changes["retry_max"] = self.weights.tool_retry_max
            changes["reason"] = f"工具成功率低 ({success_rate:.1%})，增加重试次数"
        elif success_rate > 0.95:
            # 成功率高 → 可减少重试，提升速度
            self.weights.tool_retry_max = max(1, self.weights.tool_retry_max - 1)
            changes["retry_max"] = self.weights.tool_retry_max
            changes["reason"] = f"工具成功率高 ({success_rate:.1%})，减少重试提升速度"

        # 预估 vs 实际 比例
        ratio = tool_efficiency.get("estimated_vs_actual_ratio", 1.0)
        if ratio > 2.0:
            # 实际调用远超预估 → 增加预估
            changes["estimated_vs_actual"] = f"高 {ratio:.1f}x，建议提高预估"
        elif ratio < 0.5:
            changes["estimated_vs_actual"] = f"低 {ratio:.1f}x，建议降低预估"

        return changes

    def _adjust_thresholds(self, confidence_analysis: dict[str, Any]) -> dict[str, Any]:
        """调整决策阈值"""
        changes: dict[str, Any] = {}
        lr = self.weights.learning_rate

        high_rate = confidence_analysis.get("high_confidence_success_rate", 0.0)
        low_rate = confidence_analysis.get("low_confidence_success_rate", 0.0)

        if low_rate < 0.4 and confidence_analysis.get("low_conf_count", 0) >= 3:
            # 低置信度任务成功率低 → 降低触发深度分析的阈值
            self.weights.deep_analysis_threshold = min(0.85, self.weights.deep_analysis_threshold + 0.05)
            changes["deep_analysis_threshold"] = self.weights.deep_analysis_threshold
            changes["reason"] = "低置信度任务成功率低，更多触发深度分析"

        if high_rate > 0.9 and confidence_analysis.get("high_conf_count", 0) >= 3:
            # 高置信度任务成功率高 → 可适当提高阈值，减少不必要的深度分析
            self.weights.deep_analysis_threshold = max(0.5, self.weights.deep_analysis_threshold - 0.02)
            changes["deep_analysis_threshold"] = self.weights.deep_analysis_threshold
            changes["reason"] = "高置信度准确率高，减少不必要的深度分析"

        return changes

    # ── 持久化 ─────────────────────────────────────

    def _flush_signals(self) -> None:
        """批量写入信号到文件"""
        if not self._pending_signals:
            return
        try:
            with open(self._signals_path, "a", encoding="utf-8") as f:
                for signal in self._pending_signals:
                    f.write(json.dumps(signal.to_dict(), ensure_ascii=False) + "\n")
            count = len(self._pending_signals)
            self._pending_signals.clear()
            logger.debug("signals_flushed: count=%d", count)
        except OSError as e:
            logger.warning("signals_flush_failed: %s", e)

    def _load_weights(self) -> AdaptiveWeights:
        """从文件加载自适应权重"""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                return AdaptiveWeights.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning("weights_load_failed: %s, using defaults", e)
        return AdaptiveWeights()

    def _save_weights(self) -> None:
        """保存自适应权重到文件"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                json.dumps(self.weights.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("weights_save_failed: %s", e)

    def flush(self) -> None:
        """强制刷新所有待写入数据"""
        self._flush_signals()

    def load_history(self, limit: int = 1000) -> list[dict]:
        """加载历史信号数据（用于分析）"""
        signals: list[dict] = []
        if not self._signals_path.exists():
            return signals
        try:
            with open(self._signals_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            signals.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                    if len(signals) >= limit:
                        break
        except OSError as e:
            logger.warning("history_load_failed: %s", e)
        return signals


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_feedback_instance: FeedbackLoop | None = None


def get_feedback_loop() -> FeedbackLoop:
    """获取全局反馈学习循环"""
    global _feedback_instance
    if _feedback_instance is None:
        _feedback_instance = FeedbackLoop()
    return _feedback_instance