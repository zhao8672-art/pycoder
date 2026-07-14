"""覆盖率测试: pycoder/server/scheduler.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - ScheduledTask dataclass
  - Scheduler: load / save / add_task / remove_task / list_tasks / toggle_task
    start / stop / _run_loop / _execute_action / _do_execute
  - get_scheduler 单例

测试策略:
  - 用 tmp_path 隔离存储文件
  - 用 monkeypatch 替换 Scheduler._storage 为 tmp_path 下文件
  - mock asyncio.sleep 让 _run_loop 单次迭代后退出
  - mock call_builtin_tool 测试 _do_execute 的 mcp: 分支
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pycoder.server import scheduler as sched_mod
from pycoder.server.scheduler import (
    ScheduledTask,
    Scheduler,
    get_scheduler,
)


# ── 工厂: 创建带 tmp_path 存储的 Scheduler ──────────────────

def _make_scheduler(tmp_path: Path) -> Scheduler:
    """创建 Scheduler，存储路径指向 tmp_path"""
    s = Scheduler()
    s._storage = tmp_path / "tasks.json"
    return s


def _make_task(
    tid="t1", name="task1", trigger="interval", config=None,
    action="mcp:noop", action_args=None, enabled=True, last_run=0.0,
):
    return ScheduledTask(
        id=tid, name=name, trigger=trigger,
        config=config or {"seconds": 60}, action=action,
        action_args=action_args or {}, enabled=enabled, last_run=last_run,
    )


# ══════════════════════════════════════════════════════════
# ScheduledTask dataclass
# ══════════════════════════════════════════════════════════

class TestScheduledTask:
    def test_defaults(self):
        t = ScheduledTask(id="t1", name="task1", trigger="interval")
        assert t.id == "t1"
        assert t.config == {}
        assert t.action == ""
        assert t.enabled is True
        assert t.last_run == 0.0
        assert t.run_count == 0
        assert t.created_at > 0


# ══════════════════════════════════════════════════════════
# load / save
# ══════════════════════════════════════════════════════════

class TestLoadSave:
    def test_load_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        # 不抛异常 — 文件不存在直接返回
        s.load()
        assert s._tasks == {}

    def test_load_valid(self, tmp_path):
        s = _make_scheduler(tmp_path)
        # 先保存一个任务
        task = _make_task()
        s._tasks[task.id] = task
        s.save()

        # 新实例加载
        s2 = _make_scheduler(tmp_path)
        s2.load()
        assert "t1" in s2._tasks
        assert s2._tasks["t1"].name == "task1"

    def test_load_corrupt_json(self, tmp_path):
        """损坏的 JSON → 静默捕获异常"""
        s = _make_scheduler(tmp_path)
        s._storage.parent.mkdir(parents=True, exist_ok=True)
        s._storage.write_text("not-json{", encoding="utf-8")
        # 不抛异常
        s.load()
        assert s._tasks == {}

    def test_load_invalid_data(self, tmp_path):
        """JSON 合法但字段缺失 → 静默捕获"""
        s = _make_scheduler(tmp_path)
        s._storage.parent.mkdir(parents=True, exist_ok=True)
        # 缺少必需字段 id/name/trigger
        s._storage.write_text(json.dumps({"tasks": [{"id": "x"}]}), encoding="utf-8")
        s.load()
        # 应静默失败
        assert s._tasks == {}

    def test_save_creates_parent_dir(self, tmp_path):
        """save 应自动创建父目录"""
        s = _make_scheduler(tmp_path)
        s._storage = tmp_path / "deep" / "nested" / "tasks.json"
        s._tasks[_make_task().id] = _make_task()
        s.save()
        assert s._storage.exists()

    def test_save_writes_json(self, tmp_path):
        s = _make_scheduler(tmp_path)
        task = _make_task(action="mcp:test", config={"seconds": 30})
        s._tasks[task.id] = task
        s.save()
        data = json.loads(s._storage.read_text(encoding="utf-8"))
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["action"] == "mcp:test"


# ══════════════════════════════════════════════════════════
# add_task / remove_task / list_tasks / toggle_task
# ══════════════════════════════════════════════════════════

class TestTaskCRUD:
    def test_add_task(self, tmp_path):
        s = _make_scheduler(tmp_path)
        task = _make_task()
        r = s.add_task(task)
        assert r["success"] is True
        assert r["task"]["id"] == "t1"
        assert "t1" in s._tasks
        # save 应被调用
        assert s._storage.exists()

    def test_remove_task_existing(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s._tasks["t1"] = _make_task()
        r = s.remove_task("t1")
        assert r["success"] is True
        assert "t1" not in s._tasks

    def test_remove_task_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        r = s.remove_task("nope")
        assert r["success"] is False
        assert "任务不存在" in r["error"]

    def test_list_tasks_empty(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert s.list_tasks() == []

    def test_list_tasks_with_data(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s._tasks["t1"] = _make_task(tid="t1")
        s._tasks["t2"] = _make_task(tid="t2", name="task2")
        result = s.list_tasks()
        assert len(result) == 2
        ids = {t["id"] for t in result}
        assert ids == {"t1", "t2"}

    def test_toggle_task_enable_to_disable(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s._tasks["t1"] = _make_task(enabled=True)
        r = s.toggle_task("t1")
        assert r["success"] is True
        assert r["enabled"] is False
        assert s._tasks["t1"].enabled is False

    def test_toggle_task_disable_to_enable(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s._tasks["t1"] = _make_task(enabled=False)
        r = s.toggle_task("t1")
        assert r["success"] is True
        assert r["enabled"] is True

    def test_toggle_task_nonexistent(self, tmp_path):
        s = _make_scheduler(tmp_path)
        r = s.toggle_task("nope")
        assert r["success"] is False
        assert "任务不存在" in r["error"]


# ══════════════════════════════════════════════════════════
# start / stop / is_running
# ══════════════════════════════════════════════════════════

class TestStartStop:
    async def test_start_creates_loop_task(self, tmp_path, monkeypatch):
        s = _make_scheduler(tmp_path)

        # mock _run_loop 让其立即返回
        async def fake_loop():
            pass
        monkeypatch.setattr(s, "_run_loop", fake_loop)

        # mock load 避免文件读取
        monkeypatch.setattr(s, "load", lambda: None)

        await s.start()
        assert s.is_running is True
        assert s._loop_task is not None
        # 清理
        await s.stop()

    async def test_stop_cancels_loop(self, tmp_path):
        s = _make_scheduler(tmp_path)
        s._running = True

        # 创建一个挂起的 loop task
        async def hang():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass
        s._loop_task = asyncio.create_task(hang())

        await s.stop()
        assert s.is_running is False
        assert s._loop_task is None

    async def test_stop_without_loop_task(self, tmp_path):
        """stop 时 _loop_task 为 None → 不抛异常"""
        s = _make_scheduler(tmp_path)
        s._running = True
        await s.stop()
        assert s.is_running is False

    def test_is_running_default_false(self, tmp_path):
        s = _make_scheduler(tmp_path)
        assert s.is_running is False


# ══════════════════════════════════════════════════════════
# _run_loop
# ══════════════════════════════════════════════════════════

class TestRunLoop:
    async def test_run_loop_executes_due_task(self, tmp_path, monkeypatch):
        """到期任务应被执行"""
        s = _make_scheduler(tmp_path)
        # 添加一个到期任务（last_run=0，间隔 60s）
        task = _make_task(last_run=0.0, config={"seconds": 60})
        s._tasks[task.id] = task
        # _run_loop 检查 _running 标志 — 手动置 True
        s._running = True

        # mock _execute_action 避免真实调度
        executed = []
        def fake_exec(t):
            executed.append(t.id)
        monkeypatch.setattr(s, "_execute_action", fake_exec)

        # mock save 避免文件写入
        monkeypatch.setattr(s, "save", lambda: None)

        # 让 sleep(10) 第二次调用时停止 loop
        call_count = [0]
        real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:  # 第二次（sleep 10）后停止
                s._running = False
            # 立即返回不等待
            return

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await s._run_loop()

        assert executed == ["t1"]
        assert s._tasks["t1"].run_count == 1
        # last_run 应被更新
        assert s._tasks["t1"].last_run > 0

    async def test_run_loop_skips_disabled_task(self, tmp_path, monkeypatch):
        """disabled 任务不执行"""
        s = _make_scheduler(tmp_path)
        task = _make_task(enabled=False, last_run=0.0)
        s._tasks[task.id] = task
        s._running = True

        executed = []
        monkeypatch.setattr(s, "_execute_action", lambda t: executed.append(t.id))
        monkeypatch.setattr(s, "save", lambda: None)

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                s._running = False
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await s._run_loop()

        assert executed == []
        assert s._tasks["t1"].run_count == 0

    async def test_run_loop_skips_not_due_task(self, tmp_path, monkeypatch):
        """未到期的任务不执行"""
        s = _make_scheduler(tmp_path)
        # last_run 设置为当前时间，60s 间隔 → 未到期
        now = time.time()
        task = _make_task(last_run=now, config={"seconds": 60})
        s._tasks[task.id] = task
        s._running = True

        executed = []
        monkeypatch.setattr(s, "_execute_action", lambda t: executed.append(t.id))
        monkeypatch.setattr(s, "save", lambda: None)

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                s._running = False
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await s._run_loop()

        assert executed == []

    async def test_run_loop_skips_non_interval_trigger(self, tmp_path, monkeypatch):
        """非 interval trigger 不执行"""
        s = _make_scheduler(tmp_path)
        task = _make_task(trigger="cron", last_run=0.0, config={})
        s._tasks[task.id] = task
        s._running = True

        executed = []
        monkeypatch.setattr(s, "_execute_action", lambda t: executed.append(t.id))
        monkeypatch.setattr(s, "save", lambda: None)

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                s._running = False
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await s._run_loop()

        assert executed == []

    async def test_run_loop_default_interval(self, tmp_path, monkeypatch):
        """interval 无 seconds 字段 → 默认 3600"""
        s = _make_scheduler(tmp_path)
        # last_run=0，间隔默认 3600s → 应该到期
        task = _make_task(last_run=0.0, config={})
        s._tasks[task.id] = task
        s._running = True

        executed = []
        monkeypatch.setattr(s, "_execute_action", lambda t: executed.append(t.id))
        monkeypatch.setattr(s, "save", lambda: None)

        call_count = [0]
        async def fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                s._running = False
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await s._run_loop()

        # 默认 3600s 间隔，last_run=0 → 应执行
        assert executed == ["t1"]


# ══════════════════════════════════════════════════════════
# _execute_action / _do_execute
# ══════════════════════════════════════════════════════════

class TestExecuteAction:
    async def test_execute_action_schedules_do_execute(self, tmp_path, monkeypatch):
        """_execute_action 应通过 create_task 调度 _do_execute"""
        s = _make_scheduler(tmp_path)
        task = _make_task()

        called = []
        async def fake_do_execute(t):
            called.append(t.id)
        monkeypatch.setattr(s, "_do_execute", fake_do_execute)

        s._execute_action(task)
        # 等待 create_task 完成
        await asyncio.sleep(0.01)
        assert called == ["t1"]

    async def test_do_execute_mcp_action(self, tmp_path, monkeypatch):
        """action 以 mcp: 开头 → 调用 call_builtin_tool"""
        s = _make_scheduler(tmp_path)
        task = _make_task(action="mcp:git_status", action_args={"path": "."})

        called = []
        async def fake_call_tool(name, args):
            called.append((name, args))
            return MagicMock(success=True)
        # mock import 时的函数
        import pycoder.server.mcp_tools as mt_mod
        monkeypatch.setattr(mt_mod, "call_builtin_tool", fake_call_tool)

        await s._do_execute(task)
        assert called == [("git_status", {"path": "."})]

    async def test_do_execute_non_mcp_action(self, tmp_path):
        """action 不以 mcp: 开头 → 不调用任何工具"""
        s = _make_scheduler(tmp_path)
        task = _make_task(action="shell:echo", action_args={})

        # 不抛异常即可
        await s._do_execute(task)

    async def test_do_execute_exception_handled(self, tmp_path, monkeypatch):
        """call_builtin_tool 抛异常 → 静默捕获并 log"""
        s = _make_scheduler(tmp_path)
        task = _make_task(action="mcp:bad_tool")

        import pycoder.server.mcp_tools as mt_mod
        async def boom(name, args):
            raise RuntimeError("tool not found")
        monkeypatch.setattr(mt_mod, "call_builtin_tool", boom)

        # 不抛异常
        await s._do_execute(task)


# ══════════════════════════════════════════════════════════
# get_scheduler 单例
# ══════════════════════════════════════════════════════════

class TestGetScheduler:
    def test_singleton(self, monkeypatch):
        monkeypatch.setattr(sched_mod, "_scheduler", None)
        s1 = get_scheduler()
        s2 = get_scheduler()
        assert s1 is s2

    def test_returns_scheduler(self, monkeypatch):
        monkeypatch.setattr(sched_mod, "_scheduler", None)
        assert isinstance(get_scheduler(), Scheduler)
