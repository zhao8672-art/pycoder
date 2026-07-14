"""
调度任务引擎 — 定时任务与自动化触发器

支持: cron 表达式 / 间隔定时 / 文件变化触发 / HTTP webhook
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log


@dataclass
class ScheduledTask:
    """定时任务定义"""

    id: str
    name: str
    trigger: str  # "interval" | "cron" | "file_watch" | "webhook"
    config: dict = field(default_factory=dict)  # 触发配置
    action: str = ""  # MCP 工具名或命令
    action_args: dict = field(default_factory=dict)
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    created_at: float = field(default_factory=time.time)


class Scheduler:
    """任务调度器"""

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._storage = Path.home() / ".pycoder" / "scheduled_tasks.json"

    def load(self):
        """从磁盘加载任务"""
        if self._storage.exists():
            try:
                data = json.loads(self._storage.read_text(encoding="utf-8"))
                for t in data.get("tasks", []):
                    task = ScheduledTask(**t)
                    self._tasks[task.id] = task
            except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError) as e:
                log.warning("scheduler_load_failed", path=str(self._storage), error=str(e))

    def save(self):
        """持久化到磁盘"""
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        self._storage.write_text(
            json.dumps(
                {"tasks": [t.__dict__ for t in self._tasks.values()]},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def add_task(self, task: ScheduledTask) -> dict:
        self._tasks[task.id] = task
        self.save()
        return {"success": True, "task": task.__dict__}

    def remove_task(self, task_id: str) -> dict:
        if task_id in self._tasks:
            del self._tasks[task_id]
            self.save()
            return {"success": True}
        return {"success": False, "error": "任务不存在"}

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """按 ID 获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[dict]:
        return [t.__dict__ for t in self._tasks.values()]

    def toggle_task(self, task_id: str) -> dict:
        if task_id in self._tasks:
            self._tasks[task_id].enabled = not self._tasks[task_id].enabled
            self.save()
            return {"success": True, "enabled": self._tasks[task_id].enabled}
        return {"success": False, "error": "任务不存在"}

    async def start(self):
        """启动调度循环"""
        self.load()
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def _run_loop(self):
        while self._running:
            now = time.time()
            for task in list(self._tasks.values()):
                if not task.enabled:
                    continue
                should_run = False
                if task.trigger == "interval":
                    interval = task.config.get("seconds", 3600)
                    if now - task.last_run >= interval:
                        should_run = True
                elif task.trigger == "cron":
                    # 简化 cron 格式: "minute hour * * *"（支持逗号分隔）
                    cron_expr = task.config.get("cron", "")
                    should_run = self._match_cron(cron_expr, now, task.last_run)
                if should_run:
                    task.last_run = now
                    task.run_count += 1
                    # 通过事件通知
                    self._execute_action(task)
                await asyncio.sleep(0)
            self.save()
            await asyncio.sleep(10)

    def _execute_action(self, task: ScheduledTask):
        """执行任务动作（非阻塞）"""
        asyncio.create_task(self._do_execute(task))

    async def _do_execute(self, task: ScheduledTask):
        try:
            if task.action.startswith("mcp:"):
                tool_name = task.action[4:]
                from pycoder.server.mcp_tools import call_builtin_tool

                await call_builtin_tool(tool_name, task.action_args)
            elif task.action.startswith("python:"):
                # 直接调用 Python 函数: "python:module.func"
                func_path = task.action[7:]
                module_path, func_name = func_path.rsplit(".", 1)
                import importlib

                mod = importlib.import_module(module_path)
                func = getattr(mod, func_name)
                await func(**task.action_args)
        except Exception as e:
            # 调度任务执行失败不应阻断调度器主循环
            log.warning(
                "scheduler_execute_failed", task_id=task.id, action=task.action, error=str(e)
            )

    @staticmethod
    def _match_cron(cron_expr: str, now: float, last_run: float) -> bool:
        """简约 cron 匹配: "minute hour * * *" （支持 comma list）"""
        from datetime import datetime

        dt = datetime.fromtimestamp(now)
        last_dt = datetime.fromtimestamp(last_run)
        parts = cron_expr.strip().split()
        if len(parts) < 2:
            return False
        # 分钟匹配
        minute_ok = False
        if "," in parts[0]:
            minute_ok = dt.minute in [int(m.strip()) for m in parts[0].split(",")]
        elif parts[0] == "*":
            minute_ok = True
        else:
            try:
                minute_ok = dt.minute == int(parts[0])
            except ValueError:
                minute_ok = False
        # 小时匹配
        hour_ok = False
        if "," in parts[1]:
            hour_ok = dt.hour in [int(h.strip()) for h in parts[1].split(",")]
        elif parts[1] == "*":
            hour_ok = True
        else:
            try:
                hour_ok = dt.hour == int(parts[1])
            except ValueError:
                hour_ok = False
        # 同一分钟内只执行一次
        same_minute = (
            dt.minute == last_dt.minute and dt.hour == last_dt.hour and dt.date() == last_dt.date()
        )
        return minute_ok and hour_ok and not same_minute


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
