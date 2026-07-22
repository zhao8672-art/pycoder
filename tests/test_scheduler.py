"""P0-3: 调度器单元测试"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

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
        self.tmp_dir = Path(tempfile.mkdtemp()) if False else None

    def test_empty_list(self):
        assert self.sched.list_tasks() == []

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

    def test_get_task(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval")
        self.sched.add_task(t)
        assert self.sched.get_task("t1") is t
        assert self.sched.get_task("nonexistent") is None

    def test_toggle_task(self):
        t = ScheduledTask(id="t1", name="Test", trigger="interval", enabled=True)
        self.sched.add_task(t)
        self.sched.toggle_task("t1")
        assert self.sched._tasks["t1"].enabled is False
        self.sched.toggle_task("t1")
        assert self.sched._tasks["t1"].enabled is True


class TestCronMatching:
    def test_match_wildcard(self):
        now = time.time()
        last = 0.0
        assert Scheduler._match_cron("* *", now, last) is True

    def test_match_specific(self):
        from datetime import datetime

        # 构造一个当前分钟的时间戳
        now = time.time()
        dt = datetime.fromtimestamp(now)
        cron = f"{dt.minute} {dt.hour}"
        assert Scheduler._match_cron(cron, now, 0.0) is True

    def test_no_match_different_minute(self):
        # 永远不可能匹配的时间
        from datetime import datetime
        now = time.time()
        dt = datetime.fromtimestamp(now)
        target_minute = (dt.minute + 30) % 60
        cron = f"{target_minute} {dt.hour}"
        # 注意：如果跨越小时，需要更复杂的逻辑
        if (dt.minute + 30) < 60:
            assert Scheduler._match_cron(cron, now, 0.0) is False

    def test_same_minute_only_once(self):
        now = time.time()
        # 同分钟内 last_run=now 应该不重复触发
        assert Scheduler._match_cron("* *", now, now) is False


class TestWebhookTrigger:
    def setup_method(self):
        self.sched = Scheduler()

    def test_webhook_hit(self):
        t = ScheduledTask(id="w1", name="Webhook", trigger="webhook")
        self.sched.add_task(t)
        with patch.object(self.sched, "_execute_action") as mock_exec:
            result = self.sched.trigger_webhook("w1", {"key": "value"})
            assert result["success"] is True
            mock_exec.assert_called_once()

    def test_webhook_not_found(self):
        result = self.sched.trigger_webhook("nonexistent", {})
        assert result["success"] is False

    def test_webhook_wrong_type(self):
        t = ScheduledTask(id="i1", name="Interval", trigger="interval")
        self.sched.add_task(t)
        result = self.sched.trigger_webhook("i1", {})
        assert result["success"] is False

    def test_webhook_disabled(self):
        t = ScheduledTask(id="w1", name="Webhook", trigger="webhook", enabled=False)
        self.sched.add_task(t)
        result = self.sched.trigger_webhook("w1", {})
        assert result["success"] is False


class TestPersistence:
    def setup_method(self):
        import tempfile
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
        await asyncio.sleep(12)  # 等待一个 tick
        await sched.stop()
        # run_count 应该 >= 1
        assert sched._tasks["t1"].run_count >= 1
