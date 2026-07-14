"""增强版任务调度器 — 优先级队列、依赖链、指数退避重试

在现有 Scheduler 基础上增加：
- 一次性任务（即时/延迟）
- 任务依赖链（DAG 执行）
- 优先级队列（0=最低, 10=最高）
- 指数退避重试策略
- 并发控制（最多 3 个任务同时执行）
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Callable, Awaitable


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskTrigger(Enum):
    IMMEDIATE = "immediate"
    DELAY = "delay"
    CRON = "cron"
    INTERVAL = "interval"
    DEPENDENCY = "dependency"


@dataclass(order=True)
class _QueueItem:
    priority: int
    task_id: str = field(compare=False)


@dataclass
class EnhancedTask:
    """增强任务定义"""
    id: str
    name: str
    trigger: TaskTrigger = TaskTrigger.IMMEDIATE
    trigger_config: dict = field(default_factory=dict)
    action: Callable[..., Awaitable] | None = None
    action_args: dict = field(default_factory=dict)
    priority: int = 0
    max_retries: int = 0
    retry_delay: float = 5.0
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    progress_message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str = ""
    result: dict | None = None


class EnhancedScheduler:
    """增强版任务调度器

    用法:
        scheduler = EnhancedScheduler(notification_hub)
        await scheduler.start()
        task = EnhancedTask(id="1", name="build", action=do_build)
        await scheduler.submit(task)
    """

    MAX_CONCURRENT = 3

    def __init__(self, notification_hub=None):
        self._tasks: dict[str, EnhancedTask] = {}
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._hub = notification_hub
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)

    async def submit(self, task: EnhancedTask) -> str:
        """提交任务到队列"""
        self._tasks[task.id] = task
        if task.depends_on:
            task.trigger = TaskTrigger.DEPENDENCY
            task.status = TaskStatus.PENDING
        else:
            await self._enqueue(task)
        await self._notify("task_submitted", task)
        return task.id

    async def _enqueue(self, task: EnhancedTask):
        await self._queue.put(_QueueItem(task.priority, task.id))

    async def start(self):
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    async def _worker_loop(self):
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                task = self._tasks.get(item.task_id)
                if task and task.status == TaskStatus.PENDING:
                    async with self._semaphore:
                        asyncio.create_task(self._execute(task))
            except asyncio.TimeoutError:
                continue

    async def _execute(self, task: EnhancedTask):
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        await self._notify("task_started", task)

        for attempt in range(task.max_retries + 1):
            try:
                if task.action:
                    result = await task.action(**task.action_args)
                    task.result = result
                task.status = TaskStatus.DONE
                task.progress = 1.0
                task.completed_at = time.time()
                await self._notify("task_completed", task)
                await self._trigger_dependents(task.id)
                return
            except Exception as e:
                task.error = str(e)
                if attempt < task.max_retries:
                    await self._notify("task_retrying", task, attempt=attempt + 1)
                    await asyncio.sleep(task.retry_delay * (2 ** attempt))
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = time.time()
                    await self._notify("task_failed", task)

    async def _trigger_dependents(self, completed_task_id: str):
        for task in self._tasks.values():
            if (task.trigger == TaskTrigger.DEPENDENCY
                    and completed_task_id in task.depends_on):
                all_done = all(
                    self._tasks[dep_id].status == TaskStatus.DONE
                    for dep_id in task.depends_on
                    if dep_id in self._tasks
                )
                if all_done:
                    await self._enqueue(task)

    async def update_progress(self, task_id: str, progress: float,
                              message: str = ""):
        task = self._tasks.get(task_id)
        if task:
            task.progress = min(1.0, max(0.0, progress))
            task.progress_message = message
            await self._notify("task_progress", task)

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            await self._notify("task_cancelled", task)
            return True
        return False

    def get_task(self, task_id: str) -> EnhancedTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[dict]:
        return [
            {"id": t.id, "name": t.name, "status": t.status.value,
             "progress": t.progress, "progress_message": t.progress_message,
             "error": t.error}
            for t in self._tasks.values()
            if status is None or t.status == status
        ]

    async def _notify(self, event: str, task: EnhancedTask, **extra):
        if self._hub:
            await self._hub.send(event, {
                "task_id": task.id,
                "task_name": task.name,
                "status": task.status.value,
                "progress": task.progress,
                "progress_message": task.progress_message,
                "error": task.error,
                **extra,
            })