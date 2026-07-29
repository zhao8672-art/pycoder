"""
任务规划器 — 将用户意图分解为可执行的步骤

流程:
1. 理解与分解: 语义分析 → 任务依赖图 (DAG)
2. 策略选择: 简单/中等/复杂 → 对应的执行策略
3. 资源评估: Token 预算 + 时间估算 + 风险标记
4. 动态重规划: 子任务失败 → 重新规划剩余
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ExecutionStrategy(enum.StrEnum):
    """执行策略"""

    SINGLE_AGENT = "single_agent"  # 单 Agent 顺序执行
    PARALLEL_AGENTS = "parallel_agents"  # 多 Agent 并行
    SDLC_PIPELINE = "sdlc_pipeline"  # 全 SDLC 流水线
    AUTO = "auto"  # 自动选择


@dataclass
class Task:
    """单个任务"""

    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    estimated_minutes: float = 0.0
    risk_level: str = "low"  # low / medium / high
    assigned_to: str = ""  # 分配的 Agent 角色
    result: Any = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 2


@dataclass
class ExecutionPlan:
    """执行计划"""

    plan_id: str
    tasks: list[Task]
    strategy: ExecutionStrategy
    total_estimated_tokens: int = 0
    total_estimated_minutes: float = 0.0
    risks: list[str] = field(default_factory=list)
    original_intent: str = ""


class TaskPlanner:
    """
    任务规划器

    AI 大脑的核心决策组件。
    根据用户意图生成最优执行计划。
    """

    def __init__(self):
        self._plans: dict[str, ExecutionPlan] = {}

    def plan(self, intent: str, context: dict[str, Any] | None = None) -> ExecutionPlan:
        """
        根据用户意图生成执行计划

        Args:
            intent: 用户意图描述
            context: 项目上下文（项目结构、已有代码等）

        Returns:
            ExecutionPlan 包含任务列表和执行策略
        """
        ctx = context or {}
        plan_id = f"plan_{len(self._plans) + 1}"

        # 1. 理解意图 → 分解任务
        tasks = self._decompose(intent, ctx)

        # 2. 评估复杂度 → 选择策略
        strategy = self._select_strategy(tasks)

        # 3. 资源估算
        total_tokens = sum(t.estimated_tokens for t in tasks)
        total_minutes = sum(t.estimated_minutes for t in tasks)

        # 4. 风险标记
        risks = self._assess_risks(tasks)

        plan = ExecutionPlan(
            plan_id=plan_id,
            tasks=tasks,
            strategy=strategy,
            total_estimated_tokens=total_tokens,
            total_estimated_minutes=total_minutes,
            risks=risks,
            original_intent=intent,
        )

        self._plans[plan_id] = plan
        logger.info("规划完成: %s, %d 个任务, 策略: %s", plan_id, len(tasks), strategy.value)
        return plan

    def replan(self, plan_id: str, failed_task_id: str, error: str) -> ExecutionPlan:
        """
        动态重规划 —— 子任务失败后重新规划剩余任务

        Args:
            plan_id: 原计划 ID
            failed_task_id: 失败的任务 ID
            error: 失败原因

        Returns:
            新的执行计划
        """
        old_plan = self._plans.get(plan_id)
        if old_plan is None:
            raise ValueError(f"计划不存在: {plan_id}")

        # 标记失败任务
        for task in old_plan.tasks:
            if task.task_id == failed_task_id:
                task.status = TaskStatus.FAILED
                task.error = error
                break

        # 重新规划剩余任务
        remaining = [t for t in old_plan.tasks if t.status == TaskStatus.PENDING]
        logger.info("重规划: 剩余 %d 个任务", len(remaining))

        new_plan = ExecutionPlan(
            plan_id=f"{plan_id}_r{old_plan.tasks[0].retries + 1}",
            tasks=remaining,
            strategy=old_plan.strategy,
            original_intent=old_plan.original_intent,
        )

        self._plans[new_plan.plan_id] = new_plan
        return new_plan

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        """获取计划"""
        return self._plans.get(plan_id)

    def get_next_task(self, plan_id: str) -> Task | None:
        """获取下一个可执行的任务（依赖已满足的）"""
        plan = self._plans.get(plan_id)
        if plan is None:
            return None

        completed = {t.task_id for t in plan.tasks if t.status == TaskStatus.COMPLETED}

        for task in plan.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in completed for dep in task.dependencies):
                return task

        return None

    def is_plan_complete(self, plan_id: str) -> bool:
        """检查计划是否完成"""
        plan = self._plans.get(plan_id)
        if plan is None:
            return True

        return all(t.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED) for t in plan.tasks)

    def _decompose(self, intent: str, context: dict[str, Any]) -> list[Task]:
        """
        将意图分解为可执行的任务列表

        基于关键词和模式的启发式分解。
        复杂场景由 AI LLM 驱动。
        """
        intent_lower = intent.lower()
        tasks: list[Task] = []

        # 检测意图模式
        if any(w in intent_lower for w in ["创建", "新建", "添加", "add", "create"]):
            if any(w in intent_lower for w in ["api", "接口", "endpoint"]):
                tasks.extend(
                    [
                        Task("1", "定义数据模型", estimated_tokens=500, estimated_minutes=2),
                        Task(
                            "2",
                            "创建 API 路由",
                            estimated_tokens=800,
                            estimated_minutes=3,
                            dependencies=["1"],
                        ),
                        Task(
                            "3",
                            "实现业务逻辑",
                            estimated_tokens=1000,
                            estimated_minutes=5,
                            dependencies=["1"],
                        ),
                        Task(
                            "4",
                            "添加输入验证",
                            estimated_tokens=400,
                            estimated_minutes=2,
                            dependencies=["2"],
                        ),
                        Task(
                            "5",
                            "编写测试用例",
                            estimated_tokens=600,
                            estimated_minutes=5,
                            dependencies=["2", "3"],
                        ),
                    ]
                )
            elif any(w in intent_lower for w in ["组件", "component", "页面", "page"]):
                tasks.extend(
                    [
                        Task("1", "设计组件结构", estimated_tokens=300, estimated_minutes=2),
                        Task(
                            "2",
                            "实现组件逻辑",
                            estimated_tokens=800,
                            estimated_minutes=5,
                            dependencies=["1"],
                        ),
                        Task(
                            "3",
                            "添加样式",
                            estimated_tokens=300,
                            estimated_minutes=3,
                            dependencies=["2"],
                        ),
                        Task(
                            "4",
                            "编写测试",
                            estimated_tokens=400,
                            estimated_minutes=3,
                            dependencies=["2"],
                        ),
                    ]
                )
            else:
                tasks.extend(
                    [
                        Task("1", "分析需求和影响范围", estimated_tokens=300, estimated_minutes=1),
                        Task(
                            "2",
                            "实现功能代码",
                            estimated_tokens=800,
                            estimated_minutes=5,
                            dependencies=["1"],
                        ),
                        Task(
                            "3",
                            "编写测试",
                            estimated_tokens=500,
                            estimated_minutes=3,
                            dependencies=["2"],
                        ),
                        Task(
                            "4",
                            "运行测试验证",
                            estimated_tokens=100,
                            estimated_minutes=2,
                            dependencies=["3"],
                        ),
                    ]
                )
        elif any(w in intent_lower for w in ["修复", "fix", "bug", "错误"]):
            tasks.extend(
                [
                    Task("1", "定位问题根因", estimated_tokens=400, estimated_minutes=2),
                    Task(
                        "2",
                        "生成修复方案",
                        estimated_tokens=500,
                        estimated_minutes=3,
                        dependencies=["1"],
                    ),
                    Task(
                        "3",
                        "实施修复",
                        estimated_tokens=400,
                        estimated_minutes=2,
                        dependencies=["2"],
                    ),
                    Task(
                        "4",
                        "验证修复 + 回归测试",
                        estimated_tokens=300,
                        estimated_minutes=3,
                        dependencies=["3"],
                    ),
                ]
            )
        elif any(w in intent_lower for w in ["重构", "refactor", "优化", "optimize"]):
            tasks.extend(
                [
                    Task("1", "分析现有代码结构", estimated_tokens=500, estimated_minutes=3),
                    Task(
                        "2",
                        "设计重构方案",
                        estimated_tokens=600,
                        estimated_minutes=3,
                        dependencies=["1"],
                    ),
                    Task(
                        "3",
                        "分步实施重构",
                        estimated_tokens=1200,
                        estimated_minutes=8,
                        dependencies=["2"],
                    ),
                    Task(
                        "4",
                        "验证重构结果",
                        estimated_tokens=500,
                        estimated_minutes=5,
                        dependencies=["3"],
                    ),
                ]
            )
        else:
            # 通用分解
            tasks.extend(
                [
                    Task("1", "理解需求", estimated_tokens=300, estimated_minutes=1),
                    Task(
                        "2",
                        "设计方案",
                        estimated_tokens=500,
                        estimated_minutes=2,
                        dependencies=["1"],
                    ),
                    Task(
                        "3",
                        "实现方案",
                        estimated_tokens=800,
                        estimated_minutes=5,
                        dependencies=["2"],
                    ),
                    Task(
                        "4",
                        "测试验证",
                        estimated_tokens=400,
                        estimated_minutes=3,
                        dependencies=["3"],
                    ),
                ]
            )

        return tasks

    @staticmethod
    def _select_strategy(tasks: list[Task]) -> ExecutionStrategy:
        """根据任务复杂度选择执行策略"""
        total_tokens = sum(t.estimated_tokens for t in tasks)

        if len(tasks) <= 2 and total_tokens < 1000:
            return ExecutionStrategy.SINGLE_AGENT
        elif len(tasks) <= 5 and total_tokens < 3000:
            return ExecutionStrategy.PARALLEL_AGENTS
        else:
            return ExecutionStrategy.SDLC_PIPELINE

    @staticmethod
    def _assess_risks(tasks: list[Task]) -> list[str]:
        """评估任务风险"""
        risks: list[str] = []

        if sum(t.estimated_tokens for t in tasks) > 5000:
            risks.append("高 Token 消耗（> 5000 tokens）")

        if len(tasks) > 10:
            risks.append("任务数量过多（> 10）")

        critical_tasks = [t for t in tasks if t.risk_level == "high"]
        if critical_tasks:
            risks.append(f"包含 {len(critical_tasks)} 个高风险子任务")

        return risks


# ══════════════════════════════════════════════════════════
# 正反可行性分析（补充方案2）
# ══════════════════════════════════════════════════════════


@dataclass
class FeasibilityReport:
    """可行性分析报告 — 正反双向评估"""

    # 正向评估
    feasibility: bool = True  # 整体可行
    reasonableness: float = 0.8  # 合理性 0-1
    resource_adequacy: float = 0.8  # 资源充足度 0-1
    technical_feasibility: float = 0.8  # 技术可行性 0-1
    expected_benefit: str = ""  # 预期收益描述

    # 反向评估
    risks: list[str] = field(default_factory=list)  # 潜在风险
    obstacles: list[str] = field(default_factory=list)  # 执行障碍
    resource_limits: list[str] = field(default_factory=list)  # 资源限制
    negative_outcomes: list[str] = field(default_factory=list)  # 可能的负面结果

    # 综合建议
    recommendation: str = "proceed"  # proceed / caution / abort
    mitigation: list[str] = field(default_factory=list)  # 风险缓解措施

    @property
    def overall_score(self) -> float:
        """综合评分 = 正向均值 - 风险扣分"""
        positive = (self.reasonableness + self.resource_adequacy + self.technical_feasibility) / 3
        risk_penalty = min(len(self.risks) * 0.1 + len(self.obstacles) * 0.15, 0.5)
        return max(positive - risk_penalty, 0.0)

    def to_dict(self) -> dict[str, Any]:
        """转为字典"""
        return {
            "feasibility": self.feasibility,
            "reasonableness": round(self.reasonableness, 2),
            "resource_adequacy": round(self.resource_adequacy, 2),
            "technical_feasibility": round(self.technical_feasibility, 2),
            "expected_benefit": self.expected_benefit,
            "risks": self.risks,
            "obstacles": self.obstacles,
            "resource_limits": self.resource_limits,
            "negative_outcomes": self.negative_outcomes,
            "recommendation": self.recommendation,
            "mitigation": self.mitigation,
            "overall_score": round(self.overall_score, 2),
        }


class FeasibilityAnalyzer:
    """正反双向可行性分析器

    正向：合理性、资源需求、预期收益、技术可行性
    反向：潜在风险、执行障碍、资源限制、负面结果
    """

    # 高风险关键词 → 风险描述
    _HIGH_RISK_PATTERNS: dict[str, str] = {
        "删除": "涉及删除操作，可能造成数据丢失",
        "rm -rf": "危险命令，可能导致文件系统损坏",
        "drop table": "数据库表删除操作，不可逆",
        "format": "格式化操作，数据不可恢复",
        "shutdown": "关机/停服操作，影响系统可用性",
        "部署": "部署操作影响生产环境",
        "deploy": "部署操作影响生产环境",
        "迁移": "数据迁移可能导致数据不一致",
        "migrate": "数据迁移可能导致数据不一致",
    }

    # 技术可行性评估：任务关键词 → 可行性权重
    _TECH_FEASIBILITY_HINTS: dict[str, float] = {
        "创建": 0.95,
        "create": 0.95,
        "添加": 0.9,
        "add": 0.9,
        "修改": 0.8,
        "update": 0.8,
        "修复": 0.75,
        "fix": 0.75,
        "重构": 0.6,
        "refactor": 0.6,
        "迁移": 0.5,
        "migrate": 0.5,
    }

    def analyze(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any] | None = None,
    ) -> FeasibilityReport:
        """执行正反可行性分析

        Args:
            plan: 执行计划
            context: 额外上下文（项目结构、已有代码等）

        Returns:
            FeasibilityReport 可行性报告
        """
        ctx = context or {}
        intent_lower = plan.original_intent.lower()
        all_descriptions = " ".join(t.description for t in plan.tasks).lower()
        combined_text = f"{intent_lower} {all_descriptions}"

        report = FeasibilityReport()

        # ── 正向分析 ──
        report.reasonableness = self._assess_reasonableness(plan)
        report.resource_adequacy = self._assess_resource_adequacy(plan)
        report.technical_feasibility = self._assess_technical_feasibility(combined_text)
        report.expected_benefit = self._estimate_benefit(plan)

        # ── 反向分析 ──
        report.risks = self._identify_risks(combined_text, plan)
        report.obstacles = self._identify_obstacles(plan)
        report.resource_limits = self._identify_resource_limits(plan)
        report.negative_outcomes = self._identify_negative_outcomes(combined_text, plan)

        # ── 综合建议 ──
        report.feasibility = report.overall_score >= 0.4
        report.recommendation = self._make_recommendation(report)
        report.mitigation = self._generate_mitigation(report)

        logger.info(
            "可行性分析完成: score=%.2f recommendation=%s risks=%d obstacles=%d",
            report.overall_score,
            report.recommendation,
            len(report.risks),
            len(report.obstacles),
        )
        return report

    def _assess_reasonableness(self, plan: ExecutionPlan) -> float:
        """评估计划合理性"""
        score = 0.8  # 基础分
        # 任务数量合理性
        n = len(plan.tasks)
        if 1 <= n <= 5:
            score += 0.15
        elif 6 <= n <= 10:
            score += 0.05
        elif n > 10:
            score -= 0.2
        # 策略匹配
        if plan.strategy == ExecutionStrategy.SINGLE_AGENT and n <= 3:
            score += 0.05
        if plan.strategy == ExecutionStrategy.PARALLEL_AGENTS and n > 3:
            score += 0.05
        return min(score, 1.0)

    def _assess_resource_adequacy(self, plan: ExecutionPlan) -> float:
        """评估资源充足度"""
        total_tokens = plan.total_estimated_tokens
        if total_tokens == 0:
            return 0.9
        if total_tokens < 2000:
            return 0.95
        if total_tokens < 5000:
            return 0.8
        if total_tokens < 10000:
            return 0.6
        return 0.4

    def _assess_technical_feasibility(self, text: str) -> float:
        """评估技术可行性"""
        scores = []
        for keyword, weight in self._TECH_FEASIBILITY_HINTS.items():
            if keyword in text:
                scores.append(weight)
        if not scores:
            return 0.75  # 默认
        return sum(scores) / len(scores)

    def _estimate_benefit(self, plan: ExecutionPlan) -> str:
        """估算预期收益"""
        n = len(plan.tasks)
        if plan.strategy == ExecutionStrategy.SDLC_PIPELINE:
            return f"完成完整SDLC流程，交付 {n} 个任务成果"
        if n <= 3:
            return f"完成 {n} 个核心任务，快速交付"
        return f"完成 {n} 个任务，系统性解决问题"

    def _identify_risks(self, text: str, plan: ExecutionPlan) -> list[str]:
        """识别潜在风险"""
        risks: list[str] = []
        for pattern, desc in self._HIGH_RISK_PATTERNS.items():
            if pattern in text:
                risks.append(desc)
        # 高风险任务
        high_risk_tasks = [t for t in plan.tasks if t.risk_level == "high"]
        if high_risk_tasks:
            risks.append(f"包含 {len(high_risk_tasks)} 个高风险子任务")
        # Token超支风险
        if plan.total_estimated_tokens > 5000:
            risks.append(f"Token消耗较高（预估 {plan.total_estimated_tokens}）")
        return risks

    def _identify_obstacles(self, plan: ExecutionPlan) -> list[str]:
        """识别执行障碍"""
        obstacles: list[str] = []
        # 依赖链过长
        max_depth = self._max_dependency_depth(plan)
        if max_depth > 3:
            obstacles.append(f"依赖链过深（{max_depth}层），串行瓶颈")
        # 无依赖的任务过多（可能需要协调）
        independent = [t for t in plan.tasks if not t.dependencies]
        if len(independent) > 5:
            obstacles.append(f"独立任务过多（{len(independent)}个），需并行协调")
        return obstacles

    def _identify_resource_limits(self, plan: ExecutionPlan) -> list[str]:
        """识别资源限制"""
        limits: list[str] = []
        if plan.total_estimated_tokens > 8000:
            limits.append("Token预算可能超出单次会话限制")
        if plan.total_estimated_minutes > 30:
            limits.append(f"预估耗时较长（{plan.total_estimated_minutes:.0f}分钟）")
        return limits

    def _identify_negative_outcomes(self, text: str, plan: ExecutionPlan) -> list[str]:
        """识别可能的负面结果"""
        outcomes: list[str] = []
        if "删除" in text or "drop" in text or "rm " in text:
            outcomes.append("数据丢失风险")
        if "重构" in text or "refactor" in text:
            outcomes.append("重构可能引入新Bug")
        if "部署" in text or "deploy" in text:
            outcomes.append("部署可能影响在线服务")
        if len(plan.tasks) > 8:
            outcomes.append("任务过多可能导致部分未完成")
        return outcomes

    def _make_recommendation(self, report: FeasibilityReport) -> str:
        """生成综合建议"""
        score = report.overall_score
        risk_count = len(report.risks) + len(report.negative_outcomes)
        if score >= 0.7 and risk_count <= 2:
            return "proceed"
        if score >= 0.4 or risk_count <= 4:
            return "caution"
        return "abort"

    def _generate_mitigation(self, report: FeasibilityReport) -> list[str]:
        """生成风险缓解措施"""
        mitigations: list[str] = []
        if any("删除" in r or "丢失" in r for r in report.risks + report.negative_outcomes):
            mitigations.append("执行前创建备份或git stash")
        if any("Token" in r for r in report.risks + report.resource_limits):
            mitigations.append("分批执行，控制单次Token消耗")
        if any("依赖" in o for o in report.obstacles):
            mitigations.append("按依赖顺序执行，避免跳步")
        if any("部署" in r for r in report.risks):
            mitigations.append("部署前在测试环境验证")
        if not mitigations and report.risks:
            mitigations.append("执行中密切监控，出现异常立即暂停")
        return mitigations

    @staticmethod
    def _max_dependency_depth(plan: ExecutionPlan) -> int:
        """计算最大依赖深度"""
        task_map = {t.task_id: t for t in plan.tasks}

        def depth(tid: str, visited: set[str]) -> int:
            if tid not in task_map:
                return 0
            if tid in visited:
                return 0  # 循环依赖保护
            visited.add(tid)
            deps = task_map[tid].dependencies
            if not deps:
                return 1
            return 1 + max(depth(d, visited.copy()) for d in deps)

        return max((depth(t.task_id, set()) for t in plan.tasks), default=0)


# ══════════════════════════════════════════════════════════
# 计划级预算控制（补充方案5）
# ══════════════════════════════════════════════════════════


@dataclass
class PlanBudget:
    """计划级预算"""

    estimated_tokens: int  # 预估Token
    budget_tokens: int  # 预算Token（含余量）
    estimated_minutes: float  # 预估耗时

    # 阈值比例
    warn_ratio: float = 0.8  # 80%告警
    replan_ratio: float = 1.0  # 100%触发重规划
    cutoff_ratio: float = 1.2  # 120%熔断

    # 运行时状态
    actual_tokens: int = 0
    actual_iterations: int = 0

    @property
    def usage_ratio(self) -> float:
        """当前使用比例"""
        if self.budget_tokens == 0:
            return 0.0
        return self.actual_tokens / self.budget_tokens

    @property
    def status(self) -> str:
        """预算状态: ok / warning / replan / cutoff"""
        ratio = self.usage_ratio
        if ratio >= self.cutoff_ratio:
            return "cutoff"
        if ratio >= self.replan_ratio:
            return "replan"
        if ratio >= self.warn_ratio:
            return "warning"
        return "ok"

    @classmethod
    def from_plan(cls, plan: ExecutionPlan, margin: float = 1.5) -> PlanBudget:
        """从执行计划生成预算

        Args:
            plan: 执行计划
            margin: 余量倍数（默认1.5倍）
        """
        estimated = plan.total_estimated_tokens
        return cls(
            estimated_tokens=estimated,
            budget_tokens=int(estimated * margin),
            estimated_minutes=plan.total_estimated_minutes,
        )

    def consume(self, tokens: int) -> None:
        """消耗Token"""
        self.actual_tokens += tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_tokens": self.estimated_tokens,
            "budget_tokens": self.budget_tokens,
            "actual_tokens": self.actual_tokens,
            "usage_ratio": round(self.usage_ratio, 2),
            "status": self.status,
        }
