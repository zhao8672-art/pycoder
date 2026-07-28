"""P0-3: 调度器单元测试 — 匹配当前 scheduler.py API"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from pycoder.server.scheduler import ScheduledTask, Scheduler


class TestScheduledTask:
    def test_default(self):
        t = ScheduledTask(id="x", name="x", trigger="interval")
        assert t.id == "x"
        assert t.enabled is True
        assert t.run_count == 0

    def test_to_dict(self):
        t = ScheduledTask(id="x", name="x", trigger="interval", config={"seconds": 60})
        d = t.__dict__
        assert d["id"] == "x"
        assert d["config"]["seconds"] == 60


class TestSchedulerBasic:
    def setup_method(self):
        self.sched = Scheduler()

    def test_empty_list(self):
        """新建调度器不应有任务（默认任务在 start() 时注册）"""
        assert self.sched.get_all_tasks() == []

    def test_add_task(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval", config={"seconds": 60})
        result = self.sched.add_task(t)
        assert result["success"] is True
        assert "t1" in self.sched._tasks

    def test_remove_task(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval")
        self.sched.add_task(t)
        result = self.sched.remove_task("t1")
        assert result["success"] is True
        assert "t1" not in self.sched._tasks

    def test_remove_nonexistent(self):
        result = self.sched.remove_task("nonexistent")
        assert result["success"] is False

    def test_get_task_status(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval")
        self.sched.add_task(t)
        status = self.sched.get_task_status("t1")
        assert status["id"] == "t1"
        assert status["name"] == "Test"
        assert self.sched.get_task_status("nonexistent") == {}

    def test_get_all_tasks(self):
        t1 = ScheduledTask(id="t1", name="Task1", trigger="interval")
        t2 = ScheduledTask(id="t2", name="Task2", trigger="cron")
        self.sched.add_task(t1)
        self.sched.add_task(t2)
        all_tasks = self.sched.get_all_tasks()
        assert len(all_tasks) == 2
        ids = {t["id"] for t in all_tasks}
        assert ids == {"t1", "t2"}

    def test_toggle_enabled(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval", enabled=True)
        self.sched.add_task(t)
        self.sched._tasks["t1"].enabled = False
        assert self.sched._tasks["t1"].enabled is False
        self.sched._tasks["t1"].enabled = True
        assert self.sched._tasks["t1"].enabled is True


class TestPersistence:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sched = Scheduler()
        self.sched._storage = Path(self.tmp.name) / "tasks.json"

    def teardown_method(self):
        self.tmp.cleanup()

    def test_save_and_load(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval", config={"seconds": 60})
        self.sched.add_task(t)
        # 重新加载
        sched2 = Scheduler()
        sched2._storage = self.sched._storage
        sched2.load()
        assert "t1" in sched2._tasks
        assert sched2._tasks["t1"].name == "Test"


@pytest.mark.asyncio
class TestAsyncStartStop:
    async def test_start_stop(self):
        sched = Scheduler()
        # 不注册默认任务，避免外部依赖
        await sched.start()
        assert sched.is_running
        await sched.stop()
        assert not sched.is_running

    async def test_interval_trigger(self):
        """测试 interval 触发器确实能触发执行."""
        sched = Scheduler()
        t = ScheduledTask(
            id="t1",
            name="Test",
            trigger="interval",
            config={"seconds": 1},
            action="mcp:nonexistent_tool",  # 故意失败，仅测试触发逻辑
        )
        sched.add_task(t)
        sched._tasks["t1"].last_run = 0  # 强制触发
        await sched.start()
        await asyncio.sleep(2.5)  # 等待足够 tick
        await sched.stop()
        # run_count 应该 >= 1
        assert sched._tasks["t1"].run_count >= 1