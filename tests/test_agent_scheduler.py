"""
DAG 依赖调度器单元测试

测试 DAGScheduler 和 DAGTask 的核心功能：
- DAGTask 数据类创建与默认值
- 任务添加与获取
- 就绪任务检测（依赖满足）
- 阻塞任务检测
- 完成/失败状态检查
- 状态计数
- 异步执行（顺序、并行、混合）
- 失败任务处理
- 死锁场景处理
- 并发控制
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.agent_scheduler import DAGScheduler, DAGTask


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _make_task(
    task_id: str,
    title: str = "",
    dependencies: list[str] | None = None,
    role: str = "developer",
    priority: int = 0,
) -> DAGTask:
    """快速创建 DAGTask 的辅助函数"""
    return DAGTask(
        id=task_id,
        title=title or f"任务{task_id}",
        dependencies=dependencies or [],
        role=role,
        priority=priority,
    )


# ══════════════════════════════════════════════════════════
# 测试：DAGTask 数据类
# ══════════════════════════════════════════════════════════


class TestDAGTask:
    """DAGTask 数据类测试"""

    def test_create_task_defaults(self):
        """创建任务默认值"""
        task = DAGTask(id="t1", title="测试任务")
        assert task.id == "t1"
        assert task.title == "测试任务"
        assert task.dependencies == []
        assert task.role == "developer"
        assert task.priority == 0
        assert task.status == "pending"
        assert task.result is None
        assert task.error == ""
        assert task.executor is None
        assert task.executor_kwargs == {}

    def test_create_task_with_dependencies(self):
        """创建带依赖的任务"""
        task = DAGTask(id="t2", title="下游任务", dependencies=["t1", "t0"])
        assert task.dependencies == ["t1", "t0"]

    def test_create_task_with_executor(self):
        """创建带执行器的任务"""
        async def my_executor(t):
            return "done"

        task = DAGTask(
            id="t3",
            title="自定义执行器任务",
            executor=my_executor,
            executor_kwargs={"mode": "fast"},
        )
        assert task.executor is my_executor
        assert task.executor_kwargs == {"mode": "fast"}

    def test_task_status_transition(self):
        """任务状态可变更"""
        task = _make_task("t1")
        assert task.status == "pending"
        task.status = "running"
        assert task.status == "running"
        task.status = "completed"
        assert task.status == "completed"
        task.status = "failed"
        assert task.status == "failed"


# ══════════════════════════════════════════════════════════
# 测试：DAGScheduler 初始化
# ══════════════════════════════════════════════════════════


class TestDAGSchedulerInit:
    """DAGScheduler 初始化测试"""

    def test_create_empty_scheduler(self):
        """创建空调度器"""
        scheduler = DAGScheduler()
        assert scheduler._tasks == {}
        assert scheduler._results == {}

    def test_create_with_tasks(self):
        """创建带初始任务的调度器"""
        tasks = [
            _make_task("A", "任务A"),
            _make_task("B", "任务B", dependencies=["A"]),
        ]
        scheduler = DAGScheduler(tasks)
        assert len(scheduler._tasks) == 2
        assert scheduler.get_task("A") is not None
        assert scheduler.get_task("B") is not None

    def test_add_task(self):
        """添加任务"""
        scheduler = DAGScheduler()
        task = _make_task("A", "任务A")
        scheduler.add_task(task)
        assert scheduler.get_task("A") is task

    def test_get_task_nonexistent(self):
        """获取不存在的任务返回 None"""
        scheduler = DAGScheduler()
        assert scheduler.get_task("nonexistent") is None

    def test_get_task_existing(self):
        """获取存在的任务"""
        scheduler = DAGScheduler()
        task = _make_task("X", "任务X")
        scheduler.add_task(task)
        assert scheduler.get_task("X") is task


# ══════════════════════════════════════════════════════════
# 测试：任务状态检测
# ══════════════════════════════════════════════════════════


class TestTaskStatusDetection:
    """任务状态检测测试"""

    def test_get_ready_tasks_no_dependencies(self):
        """无依赖任务全部就绪"""
        scheduler = DAGScheduler()
        for tid in ["A", "B", "C"]:
            scheduler.add_task(_make_task(tid))
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 3
        assert {t.id for t in ready} == {"A", "B", "C"}

    def test_get_ready_tasks_with_dependencies_unmet(self):
        """依赖未满足时任务不就绪"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=["A"]))
        ready = scheduler.get_ready_tasks()
        # A 无依赖可执行，B 依赖 A 未完成
        assert len(ready) == 1
        assert ready[0].id == "A"

    def test_get_ready_tasks_with_dependencies_met(self):
        """依赖满足后任务就绪"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=["A"]))
        # 手动标记 A 完成
        scheduler._results["A"] = "done"
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 2  # A 已不是 pending，但 B 变为就绪
        # 注意：A 状态还是 pending，但 B 依赖满足
        # 实际上 A 状态仍为 pending 所以应该也在 ready 中
        # 让我们修正：A 状态需要改为 completed
        task_a = scheduler.get_task("A")
        assert task_a is not None
        task_a.status = "completed"
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "B"

    def test_get_ready_tasks_skips_completed(self):
        """已完成任务不在就绪列表"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "completed"
        scheduler.add_task(task_a)
        scheduler.add_task(_make_task("B"))
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "B"

    def test_get_ready_tasks_skips_failed(self):
        """失败任务不在就绪列表"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "failed"
        scheduler.add_task(task_a)
        scheduler.add_task(_make_task("B"))
        ready = scheduler.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "B"

    def test_get_blocked_tasks(self):
        """获取阻塞任务"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=["A"]))
        scheduler.add_task(_make_task("C", dependencies=["A", "B"]))
        blocked = scheduler.get_blocked_tasks()
        assert len(blocked) == 2
        assert {t.id for t in blocked} == {"B", "C"}

    def test_get_blocked_tasks_none(self):
        """无阻塞任务"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B"))
        blocked = scheduler.get_blocked_tasks()
        assert len(blocked) == 0

    def test_all_completed_empty(self):
        """空调度器已完成"""
        scheduler = DAGScheduler()
        assert scheduler.all_completed() is True

    def test_all_completed_true(self):
        """所有任务已完成"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "completed"
        task_b = _make_task("B")
        task_b.status = "completed"
        scheduler.add_task(task_a)
        scheduler.add_task(task_b)
        assert scheduler.all_completed() is True

    def test_all_completed_with_failed(self):
        """有失败任务也算完成"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "completed"
        task_b = _make_task("B")
        task_b.status = "failed"
        scheduler.add_task(task_a)
        scheduler.add_task(task_b)
        assert scheduler.all_completed() is True

    def test_all_completed_false(self):
        """有 pending 任务未完成"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "completed"
        scheduler.add_task(task_a)
        scheduler.add_task(_make_task("B"))
        assert scheduler.all_completed() is False

    def test_has_failed_true(self):
        """有失败任务"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "failed"
        scheduler.add_task(task_a)
        assert scheduler.has_failed() is True

    def test_has_failed_false(self):
        """无失败任务"""
        scheduler = DAGScheduler()
        task_a = _make_task("A")
        task_a.status = "completed"
        scheduler.add_task(task_a)
        assert scheduler.has_failed() is False

    def test_count_by_status(self):
        """按状态统计任务数"""
        scheduler = DAGScheduler()
        for i, status in enumerate(["pending", "pending", "completed", "completed", "failed"]):
            task = _make_task(str(i))
            task.status = status
            scheduler.add_task(task)
        assert scheduler.count_by_status("pending") == 2
        assert scheduler.count_by_status("completed") == 2
        assert scheduler.count_by_status("failed") == 1
        assert scheduler.count_by_status("running") == 0


# ══════════════════════════════════════════════════════════
# 测试：异步执行
# ══════════════════════════════════════════════════════════


class TestDAGSchedulerExecute:
    """DAGScheduler 异步执行测试"""

    @pytest.mark.asyncio
    async def test_execute_single_task(self):
        """执行单个任务"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A", "任务A"))

        async def executor(task: DAGTask) -> str:
            return f"{task.id}_result"

        result = await scheduler.execute(executor)
        assert result["total"] == 1
        assert result["success"] == 1
        assert result["failed"] == []
        assert result["results"]["A"] == "A_result"

    @pytest.mark.asyncio
    async def test_execute_sequential_tasks(self):
        """顺序执行依赖任务: A→B→C"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A", "任务A"))
        scheduler.add_task(_make_task("B", "任务B", dependencies=["A"]))
        scheduler.add_task(_make_task("C", "任务C", dependencies=["B"]))

        exec_order: list[str] = []

        async def executor(task: DAGTask) -> str:
            exec_order.append(task.id)
            await asyncio.sleep(0.01)
            return f"{task.id}_result"

        result = await scheduler.execute(executor)
        assert result["total"] == 3
        assert result["success"] == 3
        assert exec_order == ["A", "B", "C"]
        assert result["results"]["A"] == "A_result"
        assert result["results"]["B"] == "B_result"
        assert result["results"]["C"] == "C_result"

    @pytest.mark.asyncio
    async def test_execute_parallel_independent_tasks(self):
        """并行执行独立任务"""
        scheduler = DAGScheduler()
        for tid in ["A", "B", "C"]:
            scheduler.add_task(_make_task(tid))

        started: set[str] = set()
        completed: list[str] = []
        lock = asyncio.Lock()

        async def executor(task: DAGTask) -> str:
            async with lock:
                started.add(task.id)
            await asyncio.sleep(0.05)
            async with lock:
                completed.append(task.id)
            return f"{task.id}_result"

        result = await scheduler.execute(executor)
        assert result["total"] == 3
        assert result["success"] == 3
        assert len(started) == 3

    @pytest.mark.asyncio
    async def test_execute_mixed_dag(self):
        """混合 DAG 执行: A→(B, C)→D"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A"))
        scheduler.add_task(_make_task("B", dependencies=["A"]))
        scheduler.add_task(_make_task("C", dependencies=["A"]))
        scheduler.add_task(_make_task("D", dependencies=["B", "C"]))

        exec_order: list[str] = []

        async def executor(task: DAGTask) -> str:
            exec_order.append(task.id)
            await asyncio.sleep(0.01)
            return f"{task.id}_result"

        result = await scheduler.execute(executor)
        assert result["total"] == 4
        assert result["success"] == 4
        # A 必须先于 B 和 C
        assert exec_order.index("A") < exec_order.index("B")
        assert exec_order.index("A") < exec_order.index("C")
        # B 和 C 必须先于 D
        assert exec_order.index("B") < exec_order.index("D")
        assert exec_order.index("C") < exec_order.index("D")

    @pytest.mark.asyncio
    async def test_execute_empty(self):
        """执行空调度器"""
        scheduler = DAGScheduler()
        async def executor(task: DAGTask) -> str:
            return "never_called"

        result = await scheduler.execute(executor)
        assert result["total"] == 0
        assert result["success"] == 0
        assert result["results"] == {}

    @pytest.mark.asyncio
    async def test_execute_with_failure(self):
        """任务失败时的处理"""
        scheduler = DAGScheduler()
        scheduler.add_task(_make_task("A", "正常任务"))
        scheduler.add_task(_make_task("B", "失败任务", dependencies=["A"]))
        scheduler.add_task(_make_task("C", "依赖B的任务", dependencies=["B"]))

        async def executor(task: DAGTask) -> str:
            if task.id == "B":
                raise RuntimeError("B 执行失败")
            return f"{task.id}_result"

        result = await scheduler.execute(executor)
        # A 应成功，B 应失败，C 因调度停止而不会执行
        assert result["total"] == 3
        assert result["success"] == 1
        assert "B" in result["failed"]
        assert result["results"].get("A") == "A_result"

        # 验证任务状态
        assert scheduler.get_task("A").status == "completed"
        assert scheduler.get_task("B").status == "failed"
        assert scheduler.get_task("B").error == "B 执行失败"

    @pytest.mark.asyncio
    async def test_execute_max_concurrent_control(self):
        """最大并发数控制"""
        scheduler = DAGScheduler()
        for tid in ["A", "B", "C", "D", "E"]:
            scheduler.add_task(_make_task(tid))

        running_count = 0
        max_running = 0
        lock = asyncio.Lock()

        async def executor(task: DAGTask) -> str:
            nonlocal running_count, max_running
            async with lock:
                running_count += 1
                max_running = max(max_running, running_count)
            await asyncio.sleep(0.05)
            async with lock:
                running_count -= 1
            return f"{task.id}_result"

        result = await scheduler.execute(executor, max_concurrent=2)
        assert result["success"] == 5
        # 最大并发不超过 2
        assert max_running <= 2

    @pytest.mark.asyncio
    async def test_execute_stops_on_deadlock(self):
        """死锁时停止调度（无就绪任务但有阻塞任务）"""
        scheduler = DAGScheduler()
        # 创建循环依赖：A 依赖 B，B 依赖 A（不可能满足）
        scheduler.add_task(_make_task("A", dependencies=["B"]))
        scheduler.add_task(_make_task("B", dependencies=["A"]))

        async def executor(task: DAGTask) -> str:
            return f"{task.id}_result"

        result = await scheduler.execute(executor)
        # 死锁：无任务可执行，返回空结果
        assert result["total"] == 2
        assert result["success"] == 0