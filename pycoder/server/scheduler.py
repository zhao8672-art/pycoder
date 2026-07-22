"""
调度任务引擎 — 定时任务与自动化触发器

支持: cron 表达式 / 间隔定时 / 文件变化触发 / HTTP webhook

P0-3 升级：
- 集成 watchdog 实现文件监听（Windows ReadDirectoryChangesW）
- 内置 HTTP Webhook 端点
- 完整的 REST API + WebSocket 通知
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
    last_result: str = ""  # 最近一次执行结果
    last_error: str = ""  # 最近一次错误
    created_at: float = field(default_factory=time.time)


class Scheduler:
    """任务调度器"""

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._storage = Path.home() / ".pycoder" / "scheduled_tasks.json"
        # P0-3: 文件监听器字典 { task_id: observer }
        self._file_observers: dict[str, object] = {}
        # P0-3: WebSocket 通知回调
        self._notifier: object | None = None

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
        # P0-3: 若为文件监听任务，立即启动
        if task.trigger == "file_watch" and self._running and task.enabled:
            self._start_file_watch(task)
        # P0-3: 若为 webhook 任务，注册端点
        if task.trigger == "webhook" and self._running:
            self._register_webhook(task)
        return {"success": True, "task": task.__dict__}

    def remove_task(self, task_id: str) -> dict:
        if task_id in self._tasks:
            # P0-3: 清理监听器 / 注销 webhook
            self._stop_file_watch(task_id)
            self._unregister_webhook(task_id)
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
        # P0-3: 启动所有文件监听 / webhook 端点
        for task in self._tasks.values():
            if not task.enabled:
                continue
            if task.trigger == "file_watch":
                self._start_file_watch(task)
            elif task.trigger == "webhook":
                self._register_webhook(task)
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        # P0-3: 停止所有文件监听
        for tid in list(self._file_observers.keys()):
            self._stop_file_watch(tid)
        # P0-3: 注销所有 webhook
        for tid in list(self._tasks.keys()):
            self._unregister_webhook(tid)

    def set_notifier(self, notifier: object) -> None:
        """设置通知回调（用于向前端 WebSocket 推送任务执行结果）."""
        self._notifier = notifier

    # ── P0-3: 文件监听 ──

    def _start_file_watch(self, task: ScheduledTask) -> bool:
        """启动文件监听任务."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            log.warning("watchdog_not_installed, file_watch_disabled")
            return False

        watch_path = task.config.get("path", "")
        if not watch_path or not Path(watch_path).exists():
            log.warning("file_watch_path_invalid", path=watch_path)
            return False

        patterns = task.config.get("patterns", [])  # e.g., ["*.py"]
        events_filter = task.config.get("events", ["modified"])  # modified/created/deleted

        class _Handler(FileSystemEventHandler):
            def __init__(self, scheduler, t):
                self._sched = scheduler
                self._t = t

            def on_any_event(self, event):
                if event.is_directory:
                    return
                # 事件类型过滤
                event_type = event.event_type  # modified/created/deleted/moved
                if events_filter and event_type not in events_filter:
                    return
                # 文件名模式过滤
                if patterns:
                    from fnmatch import fnmatch
                    if not any(fnmatch(event.src_path.split("\\")[-1].split("/")[-1], p) for p in patterns):
                        return
                # 触发任务
                self._sched._execute_action(self._t, trigger_meta={"event": event_type, "path": event.src_path})

        observer = Observer()
        observer.schedule(_Handler(self, task), watch_path, recursive=task.config.get("recursive", False))
        observer.daemon = True
        observer.start()
        self._file_observers[task.id] = observer
        log.info("file_watch_started", task_id=task.id, path=watch_path)
        return True

    def _stop_file_watch(self, task_id: str) -> None:
        observer = self._file_observers.pop(task_id, None)
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception as e:
                log.warning("file_watch_stop_failed", task_id=task_id, error=str(e))

    # ── P0-3: Webhook ──

    def _register_webhook(self, task: ScheduledTask) -> bool:
        """注册 webhook 端点（仅记录，路由层动态添加）."""
        # 实际路由由 api/tasks.py 在启动时遍历所有 webhook 任务动态添加
        return True

    def _unregister_webhook(self, task_id: str) -> None:
        """注销 webhook 端点."""
        # 由路由层处理
        pass

    def trigger_webhook(self, task_id: str, payload: dict) -> dict:
        """外部 webhook 命中时触发对应任务."""
        task = self._tasks.get(task_id)
        if not task or task.trigger != "webhook":
            return {"success": False, "error": "任务不存在或非 webhook 类型"}
        if not task.enabled:
            return {"success": False, "error": "任务已禁用"}
        self._execute_action(task, trigger_meta={"source": "webhook", "payload": payload})
        return {"success": True, "task_id": task_id}

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

    def _execute_action(self, task: ScheduledTask, trigger_meta: dict | None = None):
        """执行任务动作（非阻塞）"""
        asyncio.create_task(self._do_execute(task, trigger_meta))

    async def _do_execute(self, task: ScheduledTask, trigger_meta: dict | None = None):
        try:
            result_text = ""
            if task.action.startswith("mcp:"):
                tool_name = task.action[4:]
                from pycoder.server.mcp_tools import call_builtin_tool

                result = await call_builtin_tool(tool_name, task.action_args)
                result_text = str(result)[:500]
            elif task.action.startswith("python:"):
                # 直接调用 Python 函数: "python:module.func"
                func_path = task.action[7:]
                module_path, func_name = func_path.rsplit(".", 1)
                import importlib

                mod = importlib.import_module(module_path)
                func = getattr(mod, func_name)
                # 注入 trigger_meta 作为第一参数
                if trigger_meta:
                    result = await func(trigger_meta, **task.action_args) if asyncio.iscoroutinefunction(func) else func(trigger_meta, **task.action_args)
                else:
                    result = await func(**task.action_args) if asyncio.iscoroutinefunction(func) else func(**task.action_args)
                result_text = str(result)[:500]
            task.last_result = result_text
            task.last_error = ""
            # 通知回调
            if self._notifier is not None:
                try:
                    notif = {
                        "type": "task_executed",
                        "task_id": task.id,
                        "name": task.name,
                        "trigger": task.trigger,
                        "result": result_text,
                        "trigger_meta": trigger_meta or {},
                        "timestamp": time.time(),
                    }
                    if hasattr(self._notifier, "broadcast"):
                        await self._notifier.broadcast(notif)
                    elif callable(self._notifier):
                        self._notifier(notif)
                except Exception:
                    pass
        except Exception as e:
            task.last_error = str(e)[:500]
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
