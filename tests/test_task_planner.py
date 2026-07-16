"""任务规划器测试 — TaskPlanner 与 ExecutionPlan"""
from __future__ import annotations

import pytest

from pycoder.brain.task_planner import (
    ExecutionPlan,
    ExecutionStrategy,
    Task,
    TaskPlanner,
    TaskStatus,
)


# ══════════════════════════════════════════════════════════
# Task 数据类测试
# ══════════════════════════════════════════════════════════


class TestTask:
    """Task 数据类"""

    def test_create_task_defaults(self):
        """默认值创建任务"""
        task = Task(task_id="1", description="测试任务")
        assert task.task_id == "1"
        assert task.description == "测试任务"
        assert task.status == TaskStatus.PENDING
        assert task.dependencies == []
        assert task.estimated_tokens == 0
        assert task.estimated_minutes == 0.0
        assert task.risk_level == "low"
        assert task.assigned_to == ""
        assert task.result is None
        assert task.error is None
        assert task.retries == 0
        assert task.max_retries == 2

    def test_create_task_full(self):
        """完整参数创建任务"""
        task = Task(
            task_id="2",
            description="实现 API 接口",
            status=TaskStatus.IN_PROGRESS,
            dependencies=["1"],
            estimated_tokens=800,
            estimated_minutes=5.0,
            risk_level="medium",
            assigned_to="developer",
            max_retries=3,
        )
        assert task.task_id == "2"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.dependencies == ["1"]
        assert task.estimated_tokens == 800
        assert task.estimated_minutes == 5.0
        assert task.risk_level == "medium"
        assert task.assigned_to == "developer"
        assert task.max_retries == 3

    def test_task_status_transitions(self):
        """任务状态可变更"""
        task = Task(task_id="1", description="测试")
        task.status = TaskStatus.IN_PROGRESS
        assert task.status == TaskStatus.IN_PROGRESS
        task.status = TaskStatus.COMPLETED
        assert task.status == TaskStatus.COMPLETED
        task.status = TaskStatus.FAILED
        assert task.status == TaskStatus.FAILED

    def test_task_error_tracking(self):
        """任务错误追踪"""
        task = Task(task_id="1", description="测试")
        task.error = "连接超时"
        task.retries = 1
        assert task.error == "连接超时"
        assert task.retries == 1


# ══════════════════════════════════════════════════════════
# TaskStatus 枚举测试
# ══════════════════════════════════════════════════════════


class TestTaskStatus:
    """TaskStatus 枚举"""

    def test_all_statuses(self):
        """验证所有状态值"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.BLOCKED.value == "blocked"
        assert TaskStatus.CANCELLED.value == "cancelled"


# ══════════════════════════════════════════════════════════
# ExecutionStrategy 枚举测试
# ══════════════════════════════════════════════════════════


class TestExecutionStrategy:
    """ExecutionStrategy 枚举"""

    def test_all_strategies(self):
        """验证所有策略值"""
        assert ExecutionStrategy.SINGLE_AGENT.value == "single_agent"
        assert ExecutionStrategy.PARALLEL_AGENTS.value == "parallel_agents"
        assert ExecutionStrategy.SDLC_PIPELINE.value == "sdlc_pipeline"
        assert ExecutionStrategy.AUTO.value == "auto"


# ══════════════════════════════════════════════════════════
# ExecutionPlan 数据类测试
# ══════════════════════════════════════════════════════════


class TestExecutionPlan:
    """ExecutionPlan 数据类"""

    def test_create_plan(self):
        """创建执行计划"""
        tasks = [
            Task("1", "分析需求", estimated_tokens=300),
            Task("2", "实现代码", estimated_tokens=800, dependencies=["1"]),
        ]
        plan = ExecutionPlan(
            plan_id="plan_1",
            tasks=tasks,
            strategy=ExecutionStrategy.SINGLE_AGENT,
            total_estimated_tokens=1100,
            total_estimated_minutes=6.0,
            risks=["高风险"],
            original_intent="创建 API",
        )
        assert plan.plan_id == "plan_1"
        assert len(plan.tasks) == 2
        assert plan.strategy == ExecutionStrategy.SINGLE_AGENT
        assert plan.total_estimated_tokens == 1100
        assert plan.original_intent == "创建 API"

    def test_plan_defaults(self):
        """默认值创建计划"""
        plan = ExecutionPlan(
            plan_id="plan_1",
            tasks=[],
            strategy=ExecutionStrategy.AUTO,
        )
        assert plan.total_estimated_tokens == 0
        assert plan.total_estimated_minutes == 0.0
        assert plan.risks == []
        assert plan.original_intent == ""


# ══════════════════════════════════════════════════════════
# TaskPlanner 核心测试
# ══════════════════════════════════════════════════════════


class TestTaskPlanner:
    """任务规划器核心功能"""

    @pytest.fixture
    def planner(self):
        """创建规划器实例"""
        return TaskPlanner()

    # ── plan() ──────────────────────────────────────

    def test_plan_create_api(self, planner):
        """规划创建 API 意图"""
        plan = planner.plan("创建新的 API 接口")
        assert len(plan.tasks) > 0
        assert plan.tasks[0].description == "定义数据模型"
        assert plan.strategy in (
            ExecutionStrategy.SINGLE_AGENT,
            ExecutionStrategy.PARALLEL_AGENTS,
            ExecutionStrategy.SDLC_PIPELINE,
        )
        assert plan.total_estimated_tokens > 0
        assert plan.original_intent == "创建新的 API 接口"

    def test_plan_create_component(self, planner):
        """规划创建组件意图"""
        plan = planner.plan("创建新的页面组件")
        assert len(plan.tasks) == 4
        assert plan.tasks[0].description == "设计组件结构"
        assert plan.tasks[1].dependencies == ["1"]

    def test_plan_fix_bug(self, planner):
        """规划修复 Bug 意图"""
        plan = planner.plan("修复登录页面的错误")
        assert len(plan.tasks) == 4
        assert plan.tasks[0].description == "定位问题根因"
        assert plan.tasks[1].dependencies == ["1"]

    def test_plan_refactor(self, planner):
        """规划重构意图"""
        plan = planner.plan("重构用户模块代码")
        assert len(plan.tasks) == 4
        assert plan.tasks[0].description == "分析现有代码结构"

    def test_plan_generic_intent(self, planner):
        """通用意图分解"""
        plan = planner.plan("帮我分析一下数据库性能")
        assert len(plan.tasks) == 4
        assert plan.tasks[0].description == "理解需求"

    def test_plan_with_context(self, planner):
        """带上下文规划"""
        context = {"project_type": "web", "language": "python"}
        plan = planner.plan("创建新的 API 接口", context=context)
        assert len(plan.tasks) > 0
        assert plan.original_intent == "创建新的 API 接口"

    def test_plan_with_empty_context(self, planner):
        """空上下文规划"""
        plan = planner.plan("添加新功能", context={})
        assert len(plan.tasks) == 4

    def test_plan_generates_unique_id(self, planner):
        """每次规划生成唯一 ID"""
        plan1 = planner.plan("任务 A")
        plan2 = planner.plan("任务 B")
        assert plan1.plan_id != plan2.plan_id

    def test_plan_risks_assessment(self, planner):
        """风险评估"""
        # 创建大量任务以触发风险标记
        plan = planner.plan("创建 API 接口")
        # 验证风险列表被生成
        assert isinstance(plan.risks, list)

    def test_plan_strategy_selection_small(self, planner):
        """小任务选择 SINGLE_AGENT 策略"""
        plan = planner.plan("fix typo")  # 通用意图，4 任务，约 2000 tokens
        assert plan.strategy in (
            ExecutionStrategy.SINGLE_AGENT,
            ExecutionStrategy.PARALLEL_AGENTS,
        )

    # ── get_plan() ─────────────────────────────────

    def test_get_plan_exists(self, planner):
        """获取存在的计划"""
        plan = planner.plan("测试计划")
        retrieved = planner.get_plan(plan.plan_id)
        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id

    def test_get_plan_not_exists(self, planner):
        """获取不存在的计划"""
        retrieved = planner.get_plan("nonexistent")
        assert retrieved is None

    # ── get_next_task() ────────────────────────────

    def test_get_next_task_no_deps(self, planner):
        """获取下一个无依赖任务"""
        plan = planner.plan("创建 API 接口")
        next_task = planner.get_next_task(plan.plan_id)
        assert next_task is not None
        assert next_task.task_id == "1"
        assert next_task.status == TaskStatus.PENDING

    def test_get_next_task_nonexistent_plan(self, planner):
        """不存在的计划返回 None"""
        assert planner.get_next_task("nonexistent") is None

    def test_get_next_task_with_dependencies(self, planner):
        """依赖未满足时返回 None（下一个可执行任务）"""
        plan = planner.plan("创建 API 接口")
        # 标记任务 1 完成
        for t in plan.tasks:
            if t.task_id == "1":
                t.status = TaskStatus.COMPLETED
        next_task = planner.get_next_task(plan.plan_id)
        assert next_task is not None
        # 任务 2 和 3 依赖任务 1，现在都可以执行
        assert next_task.task_id in ("2", "3")

    def test_get_next_task_all_completed(self, planner):
        """所有任务完成时返回 None"""
        plan = planner.plan("创建 API 接口")
        for t in plan.tasks:
            t.status = TaskStatus.COMPLETED
        assert planner.get_next_task(plan.plan_id) is None

    # ── is_plan_complete() ─────────────────────────

    def test_is_plan_complete_false(self, planner):
        """计划未完成"""
        plan = planner.plan("创建 API 接口")
        assert planner.is_plan_complete(plan.plan_id) is False

    def test_is_plan_complete_true(self, planner):
        """计划已完成"""
        plan = planner.plan("创建 API 接口")
        for t in plan.tasks:
            t.status = TaskStatus.COMPLETED
        assert planner.is_plan_complete(plan.plan_id) is True

    def test_is_plan_complete_with_cancelled(self, planner):
        """包含已取消任务也算完成"""
        plan = planner.plan("创建 API 接口")
        plan.tasks[0].status = TaskStatus.COMPLETED
        plan.tasks[1].status = TaskStatus.CANCELLED
        plan.tasks[2].status = TaskStatus.COMPLETED
        plan.tasks[3].status = TaskStatus.CANCELLED
        plan.tasks[4].status = TaskStatus.COMPLETED
        assert planner.is_plan_complete(plan.plan_id) is True

    def test_is_plan_complete_nonexistent(self, planner):
        """不存在的计划视为已完成"""
        assert planner.is_plan_complete("nonexistent") is True

    # ── replan() ───────────────────────────────────

    def test_replan_success(self, planner):
        """重规划成功"""
        plan = planner.plan("创建 API 接口")
        new_plan = planner.replan(plan.plan_id, "2", "依赖模块不存在")
        assert new_plan is not None
        assert new_plan.plan_id != plan.plan_id
        # 原计划中任务 2 应标记为失败
        failed_task = [t for t in plan.tasks if t.task_id == "2"]
        assert len(failed_task) > 0
        assert failed_task[0].status == TaskStatus.FAILED
        assert failed_task[0].error == "依赖模块不存在"

    def test_replan_nonexistent_plan(self, planner):
        """重规划不存在的计划"""
        with pytest.raises(ValueError, match="计划不存在"):
            planner.replan("nonexistent", "1", "错误")

    def test_replan_remaining_tasks(self, planner):
        """重规划后仅包含 PENDING 任务"""
        plan = planner.plan("创建 API 接口")
        # 标记任务 1 完成
        plan.tasks[0].status = TaskStatus.COMPLETED
        # 任务 2 失败触发重规划
        new_plan = planner.replan(plan.plan_id, "2", "失败")
        # 新计划不应包含已完成的任务 1
        new_task_ids = {t.task_id for t in new_plan.tasks}
        assert "1" not in new_task_ids
        # 新计划应包含剩余的 PENDING 任务
        assert len(new_plan.tasks) > 0

    def test_replan_preserves_strategy(self, planner):
        """重规划保留原策略"""
        plan = planner.plan("创建 API 接口")
        original_strategy = plan.strategy
        new_plan = planner.replan(plan.plan_id, "1", "失败")
        assert new_plan.strategy == original_strategy

    def test_replan_preserves_intent(self, planner):
        """重规划保留原始意图"""
        plan = planner.plan("创建 API 接口")
        new_plan = planner.replan(plan.plan_id, "1", "失败")
        assert new_plan.original_intent == plan.original_intent

    # ── _select_strategy ───────────────────────────

    def test_select_strategy_single_agent(self, planner):
        """小任务选择单 Agent 策略"""
        tasks = [Task("1", "小任务", estimated_tokens=500)]
        strategy = TaskPlanner._select_strategy(tasks)
        assert strategy == ExecutionStrategy.SINGLE_AGENT

    def test_select_strategy_parallel(self, planner):
        """中等任务选择并行策略"""
        tasks = [
            Task("1", "任务1", estimated_tokens=500),
            Task("2", "任务2", estimated_tokens=500),
            Task("3", "任务3", estimated_tokens=500),
        ]
        strategy = TaskPlanner._select_strategy(tasks)
        assert strategy == ExecutionStrategy.PARALLEL_AGENTS

    def test_select_strategy_pipeline(self, planner):
        """大任务选择 SDLC 流水线策略"""
        tasks = [Task(str(i), f"任务{i}", estimated_tokens=1000) for i in range(6)]
        strategy = TaskPlanner._select_strategy(tasks)
        assert strategy == ExecutionStrategy.SDLC_PIPELINE

    # ── _assess_risks ──────────────────────────────

    def test_assess_risks_high_tokens(self, planner):
        """高 Token 消耗风险"""
        tasks = [Task("1", "大任务", estimated_tokens=6000)]
        risks = TaskPlanner._assess_risks(tasks)
        assert any("高 Token 消耗" in r for r in risks)

    def test_assess_risks_too_many_tasks(self, planner):
        """任务过多风险"""
        tasks = [Task(str(i), f"任务{i}") for i in range(15)]
        risks = TaskPlanner._assess_risks(tasks)
        assert any("任务数量过多" in r for r in risks)

    def test_assess_risks_high_risk_subtasks(self, planner):
        """高风险子任务警告"""
        tasks = [
            Task("1", "普通任务"),
            Task("2", "高风险任务", risk_level="high"),
        ]
        risks = TaskPlanner._assess_risks(tasks)
        assert any("高风险子任务" in r for r in risks)

    def test_assess_risks_no_risks(self, planner):
        """无风险任务"""
        tasks = [Task("1", "小任务", estimated_tokens=100)]
        risks = TaskPlanner._assess_risks(tasks)
        assert len(risks) == 0