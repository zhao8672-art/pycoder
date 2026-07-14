"""notify 模块测试 — 任务调度、通知中心、进度追踪"""
from __future__ import annotations

import asyncio
import pytest

from pycoder.notify.task_scheduler import (
    EnhancedScheduler,
    EnhancedTask,
    TaskStatus,
    TaskTrigger,
)
from pycoder.notify.notification_hub import NotificationHub, NotificationPriority
from pycoder.notify.progress_tracker import ProgressTracker


class TestEnhancedScheduler:
    @pytest.mark.asyncio
    async def test_submit_and_execute(self):
        results = []
        async def my_action(*, msg: str):
            results.append(msg)
            return {"ok": True}

        scheduler = EnhancedScheduler()
        await scheduler.start()
        task = EnhancedTask(
            id="test1", name="测试任务",
            action=my_action, action_args={"msg": "hello"},
        )
        await scheduler.submit(task)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert "hello" in results
        assert scheduler.get_task("test1").status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_task_priority(self):
        order = []
        async def make_action(name):
            async def action():
                order.append(name)
            return action

        scheduler = EnhancedScheduler()
        await scheduler.start()

        t1 = EnhancedTask(id="low", name="低优先级", priority=10,
                          action=await make_action("low"))
        t2 = EnhancedTask(id="high", name="高优先级", priority=0,
                          action=await make_action("high"))

        await scheduler.submit(t1)
        await scheduler.submit(t2)
        await asyncio.sleep(0.3)
        await scheduler.stop()

        assert "high" in order
        assert "low" in order

    @pytest.mark.asyncio
    async def test_task_retry(self):
        attempts = []
        async def flaky_action():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("失败")
            return {"ok": True}

        scheduler = EnhancedScheduler()
        await scheduler.start()
        task = EnhancedTask(
            id="retry_test", name="重试任务",
            action=flaky_action, max_retries=3, retry_delay=0.01,
        )
        await scheduler.submit(task)
        await asyncio.sleep(0.5)
        await scheduler.stop()

        assert len(attempts) == 3
        assert scheduler.get_task("retry_test").status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_task_retry_exhausted(self):
        async def always_fail():
            raise RuntimeError("永远失败")

        scheduler = EnhancedScheduler()
        await scheduler.start()
        task = EnhancedTask(
            id="fail_test", name="失败任务",
            action=always_fail, max_retries=0,
        )
        await scheduler.submit(task)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        assert scheduler.get_task("fail_test").status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_task_dependency_chain(self):
        order = []
        async def make_action(name):
            async def action():
                order.append(name)
            return action

        scheduler = EnhancedScheduler()
        await scheduler.start()

        t1 = EnhancedTask(id="t1", name="第一步", action=await make_action("step1"))
        t2 = EnhancedTask(id="t2", name="第二步", action=await make_action("step2"),
                          depends_on=["t1"])
        t3 = EnhancedTask(id="t3", name="第三步", action=await make_action("step3"),
                          depends_on=["t2"])

        await scheduler.submit(t1)
        await scheduler.submit(t2)
        await scheduler.submit(t3)
        await asyncio.sleep(0.5)
        await scheduler.stop()

        assert order == ["step1", "step2", "step3"]

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self):
        async def _sleep_action():
            await asyncio.sleep(0.05)

        scheduler = EnhancedScheduler()
        await scheduler.start()
        task = EnhancedTask(
            id="cancel_test", name="待取消",
            action=_sleep_action,
        )
        await scheduler.submit(task)
        await scheduler.cancel("cancel_test")
        await asyncio.sleep(0.1)
        await scheduler.stop()

        assert scheduler.get_task("cancel_test").status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        async def _quick_action():
            await asyncio.sleep(0.02)

        scheduler = EnhancedScheduler()
        await scheduler.start()
        t1 = EnhancedTask(id="l1", name="任务1", action=_quick_action)
        t2 = EnhancedTask(id="l2", name="任务2", action=_quick_action)
        await scheduler.submit(t1)
        await scheduler.submit(t2)
        await asyncio.sleep(0.2)
        await scheduler.stop()

        all_tasks = scheduler.list_tasks()
        assert len(all_tasks) == 2

    @pytest.mark.asyncio
    async def test_update_progress(self):
        async def _slow_action():
            await asyncio.sleep(0.2)

        scheduler = EnhancedScheduler()
        hub = NotificationHub()
        scheduler._hub = hub
        await scheduler.start()

        task = EnhancedTask(id="prog", name="进度任务", action=_slow_action)
        await scheduler.submit(task)
        await asyncio.sleep(0.05)  # 等待任务开始
        await scheduler.update_progress("prog", 0.5, "已完成一半")
        await asyncio.sleep(0.05)  # 等待进度更新传播

        t = scheduler.get_task("prog")
        assert t is not None
        assert t.progress_message == "已完成一半"
        # 进度可能被任务完成重置为 1.0，但消息应保留
        await scheduler.stop()


class TestNotificationHub:
    def test_register_ws(self):
        hub = NotificationHub()
        mock_ws = type("MockWS", (), {"send_text": lambda self, msg: None})()
        hub.register_ws("session_1", mock_ws)
        assert hub.ws_client_count == 1

    def test_unregister_ws(self):
        hub = NotificationHub()
        mock_ws = type("MockWS", (), {"send_text": lambda self, msg: None})()
        hub.register_ws("session_1", mock_ws)
        hub.unregister_ws("session_1", mock_ws)
        assert hub.ws_client_count == 0

    def test_add_remove_webhook(self):
        hub = NotificationHub()
        hub.add_webhook("https://example.com/hook")
        assert "https://example.com/hook" in hub._webhook_urls
        hub.remove_webhook("https://example.com/hook")
        assert "https://example.com/hook" not in hub._webhook_urls

    def test_configure_channels(self):
        hub = NotificationHub()
        hub.configure_channels({"websocket", "desktop"})
        assert "desktop" in hub.enabled_channels

    def test_default_channels(self):
        hub = NotificationHub()
        assert "websocket" in hub.enabled_channels

    @pytest.mark.asyncio
    async def test_send_to_ws(self):
        messages = []
        class MockWS:
            async def send_text(self, msg):
                messages.append(msg)

        hub = NotificationHub()
        mock_ws = MockWS()
        hub.register_ws("test", mock_ws)
        await hub.send("test_event", {"key": "value"})
        assert len(messages) == 1
        assert "test_event" in messages[0]


class TestProgressTracker:
    def test_record_and_get_current(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.0, "开始")
        tracker.record("t1", 0.5, "完成一半")
        current = tracker.get_current("t1")
        assert current is not None
        assert current["progress"] == 0.5
        assert current["message"] == "完成一半"

    def test_estimate_remaining(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.0, "开始")
        tracker.record("t1", 0.5, "完成一半")
        eta = tracker.estimate_remaining("t1")
        assert eta is not None
        assert eta > 0

    def test_estimate_none_for_single_snapshot(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.5, "一个快照")
        assert tracker.estimate_remaining("t1") is None

    def test_estimate_none_for_zero_progress(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.0, "开始")
        tracker.record("t1", 0.0, "没进展")
        assert tracker.estimate_remaining("t1") is None

    def test_estimate_zero_when_done(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.9, "快完成了")
        tracker.record("t1", 1.0, "完成")
        assert tracker.estimate_remaining("t1") == 0.0

    def test_get_history(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.0, "开始")
        tracker.record("t1", 0.5, "一半")
        history = tracker.get_history("t1")
        assert len(history) == 2

    def test_get_current_none(self):
        tracker = ProgressTracker()
        assert tracker.get_current("nonexistent") is None

    def test_clear(self):
        tracker = ProgressTracker()
        tracker.record("t1", 0.5, "测试")
        tracker.clear("t1")
        assert tracker.get_current("t1") is None