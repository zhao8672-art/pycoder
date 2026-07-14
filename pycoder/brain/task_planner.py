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
    SINGLE_AGENT = "single_agent"        # 单 Agent 顺序执行
    PARALLEL_AGENTS = "parallel_agents"  # 多 Agent 并行
    SDLC_PIPELINE = "sdlc_pipeline"      # 全 SDLC 流水线
    AUTO = "auto"                        # 自动选择


@dataclass
class Task:
    """单个任务"""
    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    estimated_minutes: float = 0.0
    risk_level: str = "low"     # low / medium / high
    assigned_to: str = ""       # 分配的 Agent 角色
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
                tasks.extend([
                    Task("1", "定义数据模型", estimated_tokens=500, estimated_minutes=2),
                    Task("2", "创建 API 路由", estimated_tokens=800, estimated_minutes=3, dependencies=["1"]),
                    Task("3", "实现业务逻辑", estimated_tokens=1000, estimated_minutes=5, dependencies=["1"]),
                    Task("4", "添加输入验证", estimated_tokens=400, estimated_minutes=2, dependencies=["2"]),
                    Task("5", "编写测试用例", estimated_tokens=600, estimated_minutes=5, dependencies=["2", "3"]),
                ])
            elif any(w in intent_lower for w in ["组件", "component", "页面", "page"]):
                tasks.extend([
                    Task("1", "设计组件结构", estimated_tokens=300, estimated_minutes=2),
                    Task("2", "实现组件逻辑", estimated_tokens=800, estimated_minutes=5, dependencies=["1"]),
                    Task("3", "添加样式", estimated_tokens=300, estimated_minutes=3, dependencies=["2"]),
                    Task("4", "编写测试", estimated_tokens=400, estimated_minutes=3, dependencies=["2"]),
                ])
            else:
                tasks.extend([
                    Task("1", "分析需求和影响范围", estimated_tokens=300, estimated_minutes=1),
                    Task("2", "实现功能代码", estimated_tokens=800, estimated_minutes=5, dependencies=["1"]),
                    Task("3", "编写测试", estimated_tokens=500, estimated_minutes=3, dependencies=["2"]),
                    Task("4", "运行测试验证", estimated_tokens=100, estimated_minutes=2, dependencies=["3"]),
                ])
        elif any(w in intent_lower for w in ["修复", "fix", "bug", "错误"]):
            tasks.extend([
                Task("1", "定位问题根因", estimated_tokens=400, estimated_minutes=2),
                Task("2", "生成修复方案", estimated_tokens=500, estimated_minutes=3, dependencies=["1"]),
                Task("3", "实施修复", estimated_tokens=400, estimated_minutes=2, dependencies=["2"]),
                Task("4", "验证修复 + 回归测试", estimated_tokens=300, estimated_minutes=3, dependencies=["3"]),
            ])
        elif any(w in intent_lower for w in ["重构", "refactor", "优化", "optimize"]):
            tasks.extend([
                Task("1", "分析现有代码结构", estimated_tokens=500, estimated_minutes=3),
                Task("2", "设计重构方案", estimated_tokens=600, estimated_minutes=3, dependencies=["1"]),
                Task("3", "分步实施重构", estimated_tokens=1200, estimated_minutes=8, dependencies=["2"]),
                Task("4", "验证重构结果", estimated_tokens=500, estimated_minutes=5, dependencies=["3"]),
            ])
        else:
            # 通用分解
            tasks.extend([
                Task("1", "理解需求", estimated_tokens=300, estimated_minutes=1),
                Task("2", "设计方案", estimated_tokens=500, estimated_minutes=2, dependencies=["1"]),
                Task("3", "实现方案", estimated_tokens=800, estimated_minutes=5, dependencies=["2"]),
                Task("4", "测试验证", estimated_tokens=400, estimated_minutes=3, dependencies=["3"]),
            ])

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
