"""Agent 集群编排器测试 — AgentSwarmOrchestrator"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.brain.agent_swarm import (
    AgentResult,
    AgentRole,
    AgentSwarmOrchestrator,
    AgentTask,
)


# ══════════════════════════════════════════════════════════
# AgentRole 枚举测试
# ══════════════════════════════════════════════════════════


class TestAgentRole:
    """AgentRole 枚举"""

    def test_all_roles_exist(self):
        """验证所有角色定义"""
        assert AgentRole.ARCHITECT.value == "architect"
        assert AgentRole.DEVELOPER.value == "developer"
        assert AgentRole.REVIEWER.value == "reviewer"
        assert AgentRole.TESTER.value == "tester"
        assert AgentRole.DEVOPS.value == "devops"
        assert AgentRole.ANALYST.value == "analyst"

    def test_role_is_string(self):
        """验证角色是字符串类型"""
        role = AgentRole.DEVELOPER
        assert isinstance(role, str)
        assert role == "developer"


# ══════════════════════════════════════════════════════════
# AgentTask 数据类测试
# ══════════════════════════════════════════════════════════


class TestAgentTask:
    """AgentTask 数据类"""

    def test_create_task_defaults(self):
        """默认值创建 AgentTask"""
        task = AgentTask(
            task_id="1",
            role=AgentRole.DEVELOPER,
            prompt="编写测试代码",
        )
        assert task.task_id == "1"
        assert task.role == AgentRole.DEVELOPER
        assert task.prompt == "编写测试代码"
        assert task.dependencies == []
        assert task.context == {}

    def test_create_task_with_dependencies(self):
        """带依赖的 AgentTask"""
        task = AgentTask(
            task_id="2",
            role=AgentRole.ARCHITECT,
            prompt="设计系统架构",
            dependencies=["1"],
            context={"project": "pycoder"},
        )
        assert task.dependencies == ["1"]
        assert task.context == {"project": "pycoder"}


# ══════════════════════════════════════════════════════════
# AgentResult 数据类测试
# ══════════════════════════════════════════════════════════


class TestAgentResult:
    """AgentResult 数据类"""

    def test_success_result(self):
        """成功结果"""
        result = AgentResult(
            task_id="1",
            role=AgentRole.DEVELOPER,
            success=True,
            output="代码已完成",
            files_modified=["src/main.py"],
            tokens_used=500,
            duration_seconds=2.5,
        )
        assert result.success is True
        assert result.output == "代码已完成"
        assert result.files_modified == ["src/main.py"]
        assert result.error is None

    def test_failure_result(self):
        """失败结果"""
        result = AgentResult(
            task_id="2",
            role=AgentRole.TESTER,
            success=False,
            error="测试超时",
        )
        assert result.success is False
        assert result.error == "测试超时"
        assert result.output == ""

    def test_result_defaults(self):
        """默认值结果"""
        result = AgentResult(
            task_id="1",
            role=AgentRole.DEVELOPER,
            success=True,
        )
        assert result.output == ""
        assert result.error is None
        assert result.files_modified == []
        assert result.tokens_used == 0
        assert result.duration_seconds == 0.0


# ══════════════════════════════════════════════════════════
# AgentSwarmOrchestrator 核心测试
# ══════════════════════════════════════════════════════════


class TestAgentSwarmOrchestrator:
    """Agent 集群编排器核心功能"""

    @pytest.fixture
    def orchestrator(self):
        """创建编排器实例"""
        return AgentSwarmOrchestrator()

    # ── execute() ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_execute_empty_tasks(self, orchestrator):
        """空任务列表返回空结果"""
        results = await orchestrator.execute([])
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_single_task(self, orchestrator):
        """执行单个任务"""
        task = AgentTask(
            task_id="1",
            role=AgentRole.DEVELOPER,
            prompt="编写 main.py 的功能代码",
        )
        results = await orchestrator.execute([task], parallel=False)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].task_id == "1"
        assert results[0].role == AgentRole.DEVELOPER
        assert "main.py" in results[0].output

    @pytest.mark.asyncio
    async def test_execute_multiple_sequential(self, orchestrator):
        """顺序执行多个任务"""
        tasks = [
            AgentTask("1", AgentRole.ARCHITECT, "设计系统架构"),
            AgentTask("2", AgentRole.DEVELOPER, "实现核心模块"),
            AgentTask("3", AgentRole.TESTER, "编写单元测试"),
        ]
        results = await orchestrator.execute(tasks, parallel=False)
        assert len(results) == 3
        assert all(r.success for r in results)
        task_ids = {r.task_id for r in results}
        assert task_ids == {"1", "2", "3"}

    @pytest.mark.asyncio
    async def test_execute_multiple_parallel(self, orchestrator):
        """并行执行多个任务"""
        tasks = [
            AgentTask("1", AgentRole.DEVELOPER, "实现功能 A"),
            AgentTask("2", AgentRole.DEVELOPER, "实现功能 B"),
            AgentTask("3", AgentRole.TESTER, "测试功能 C"),
        ]
        results = await orchestrator.execute(tasks, parallel=True)
        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_execute_with_dependencies(self, orchestrator):
        """带依赖关系的任务执行"""
        tasks = [
            AgentTask("1", AgentRole.ARCHITECT, "设计架构"),
            AgentTask(
                "2",
                AgentRole.DEVELOPER,
                "实现代码",
                dependencies=["1"],
            ),
            AgentTask(
                "3",
                AgentRole.TESTER,
                "运行测试",
                dependencies=["2"],
            ),
        ]
        results = await orchestrator.execute(tasks, parallel=False)
        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_execute_with_dependencies_parallel(self, orchestrator):
        """并行模式下带依赖的任务执行"""
        tasks = [
            AgentTask("1", AgentRole.ARCHITECT, "设计架构"),
            AgentTask("2", AgentRole.DEVELOPER, "实现模块 A", dependencies=["1"]),
            AgentTask("3", AgentRole.DEVELOPER, "实现模块 B", dependencies=["1"]),
            AgentTask("4", AgentRole.TESTER, "集成测试", dependencies=["2", "3"]),
        ]
        results = await orchestrator.execute(tasks, parallel=True)
        assert len(results) == 4
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_execute_on_progress_callback(self, orchestrator):
        """进度回调测试"""
        progress_calls = []

        def on_progress(task_id, result):
            progress_calls.append((task_id, result.success))

        tasks = [
            AgentTask("1", AgentRole.DEVELOPER, "任务 1"),
            AgentTask("2", AgentRole.DEVELOPER, "任务 2"),
        ]
        results = await orchestrator.execute(
            tasks, parallel=False, on_progress=on_progress
        )
        assert len(results) == 2
        # 顺序执行时每个任务完成都会调用回调
        assert len(progress_calls) == 2

    @pytest.mark.asyncio
    async def test_execute_deadlock_detection(self, orchestrator):
        """死锁检测 — 无法满足的依赖"""
        tasks = [
            AgentTask(
                "1",
                AgentRole.DEVELOPER,
                "任务 1",
                dependencies=["2"],  # 依赖不存在的任务 2
            ),
        ]
        results = await orchestrator.execute(tasks, parallel=False)
        # 死锁时应返回空结果或部分结果
        assert len(results) == 0

    # ── get_result() ───────────────────────────────

    @pytest.mark.asyncio
    async def test_get_result_exists(self, orchestrator):
        """获取已存在的任务结果"""
        task = AgentTask("1", AgentRole.DEVELOPER, "测试任务")
        await orchestrator.execute([task], parallel=False)

        result = orchestrator.get_result("1")
        assert result is not None
        assert result.task_id == "1"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_result_not_exists(self, orchestrator):
        """获取不存在的任务结果"""
        result = orchestrator.get_result("nonexistent")
        assert result is None

    # ── get_all_results() ──────────────────────────

    @pytest.mark.asyncio
    async def test_get_all_results(self, orchestrator):
        """获取所有结果"""
        tasks = [
            AgentTask("1", AgentRole.DEVELOPER, "任务 1"),
            AgentTask("2", AgentRole.TESTER, "任务 2"),
        ]
        await orchestrator.execute(tasks, parallel=False)

        all_results = orchestrator.get_all_results()
        assert len(all_results) == 2
        assert "1" in all_results
        assert "2" in all_results

    @pytest.mark.asyncio
    async def test_get_all_results_empty(self, orchestrator):
        """空结果"""
        all_results = orchestrator.get_all_results()
        assert all_results == {}

    # ── cancel_task() ──────────────────────────────

    @pytest.mark.asyncio
    async def test_cancel_task(self, orchestrator):
        """取消任务"""
        task = AgentTask("1", AgentRole.DEVELOPER, "测试任务")
        await orchestrator.execute([task], parallel=False)

        orchestrator.cancel_task("1")
        # 取消后结果仍保留
        result = orchestrator.get_result("1")
        assert result is not None

    def test_cancel_nonexistent_task(self, orchestrator):
        """取消不存在的任务不报错"""
        orchestrator.cancel_task("nonexistent")
        # 不抛出异常即通过

    # ── assign_roles() ─────────────────────────────

    def test_assign_roles_architect(self):
        """设计类任务分配为架构师"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "设计系统架构")
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert len(agent_tasks) == 1
        assert agent_tasks[0].role == AgentRole.ARCHITECT

    def test_assign_roles_tester(self):
        """测试类任务分配为测试"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "编写测试用例验证功能")
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert len(agent_tasks) == 1
        assert agent_tasks[0].role == AgentRole.TESTER

    def test_assign_roles_reviewer(self):
        """审查类任务分配为审查者"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "审查代码质量")
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert len(agent_tasks) == 1
        assert agent_tasks[0].role == AgentRole.REVIEWER

    def test_assign_roles_devops(self):
        """部署类任务分配为运维"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "部署到生产环境")
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert len(agent_tasks) == 1
        assert agent_tasks[0].role == AgentRole.DEVOPS

    def test_assign_roles_analyst(self):
        """分析类任务分配为分析师"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "分析需求文档")
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert len(agent_tasks) == 1
        assert agent_tasks[0].role == AgentRole.ANALYST

    def test_assign_roles_default_developer(self):
        """默认分配为开发者"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "实现用户登录功能")
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert len(agent_tasks) == 1
        assert agent_tasks[0].role == AgentRole.DEVELOPER

    def test_assign_roles_multiple_tasks(self):
        """多个任务分配不同角色"""
        from pycoder.brain.task_planner import Task

        ptasks = [
            Task("1", "设计数据库架构"),
            Task("2", "实现 API 接口"),
            Task("3", "编写测试"),
            Task("4", "审查代码"),
        ]
        agent_tasks = AgentSwarmOrchestrator.assign_roles(ptasks)
        assert len(agent_tasks) == 4
        assert agent_tasks[0].role == AgentRole.ARCHITECT
        assert agent_tasks[1].role == AgentRole.DEVELOPER
        assert agent_tasks[2].role == AgentRole.TESTER
        assert agent_tasks[3].role == AgentRole.REVIEWER

    def test_assign_roles_preserves_dependencies(self):
        """分配角色时保留依赖关系"""
        from pycoder.brain.task_planner import Task

        ptask = Task("1", "实现 API 接口", dependencies=["0"])
        agent_tasks = AgentSwarmOrchestrator.assign_roles([ptask])
        assert agent_tasks[0].dependencies == ["0"]

    # ── _execute_single() ──────────────────────────

    @pytest.mark.asyncio
    async def test_execute_single_success(self, orchestrator):
        """执行单个任务成功"""
        task = AgentTask("1", AgentRole.DEVELOPER, "编写代码")
        result = await orchestrator._execute_single(task)
        assert result.success is True
        assert result.task_id == "1"
        assert result.role == AgentRole.DEVELOPER
        assert result.tokens_used > 0
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_execute_single_tokens_calculation(self, orchestrator):
        """Token 用量计算"""
        task = AgentTask("1", AgentRole.DEVELOPER, "A" * 400)  # 400 字符 prompt
        result = await orchestrator._execute_single(task)
        assert result.tokens_used == 100  # 400 // 4

    # ── 集成测试 ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_full_workflow(self, orchestrator):
        """完整工作流：分配角色 → 执行 → 获取结果"""
        from pycoder.brain.task_planner import Task

        # 模拟 TaskPlanner 的任务
        ptasks = [
            Task("1", "设计 API 架构"),
            Task("2", "实现 API 接口", dependencies=["1"]),
            Task("3", "测试 API 接口", dependencies=["2"]),
            Task("4", "审查代码质量", dependencies=["2"]),
        ]
        agent_tasks = AgentSwarmOrchestrator.assign_roles(ptasks)

        # 执行
        results = await orchestrator.execute(agent_tasks, parallel=True)
        assert len(results) == 4
        assert all(r.success for r in results)

        # 验证角色分配
        roles = {r.task_id: r.role for r in results}
        assert roles["1"] == AgentRole.ARCHITECT
        assert roles["2"] == AgentRole.DEVELOPER
        assert roles["3"] == AgentRole.TESTER
        assert roles["4"] == AgentRole.REVIEWER