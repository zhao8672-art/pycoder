"""
DAG 依赖调度器 — 多 Agent 任务的优先级调度与并行执行

根据任务依赖图（DAG），按拓扑顺序调度任务：
  - 无依赖任务并行执行
  - 所有依赖完成后触发下游任务
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DAGTask:
    """DAG 中的一个任务节点"""

    id: str
    title: str
    dependencies: list[str] = field(default_factory=list)  # 依赖的任务 ID 列表
    role: str = "developer"
    priority: int = 0
    status: str = "pending"  # pending | running | completed | failed
    result: Any = None
    error: str = ""
    executor: Callable | None = None
    executor_kwargs: dict = field(default_factory=dict)


class DAGScheduler:
    """DAG 依赖调度器 — 按依赖顺序并行执行任务"""

    def __init__(self, tasks: list[DAGTask] | None = None):
        self._tasks: dict[str, DAGTask] = {}
        self._results: dict[str, Any] = {}
        self._lock = asyncio.Lock()

        if tasks:
            for t in tasks:
                self.add_task(t)

    def add_task(self, task: DAGTask) -> None:
        self._tasks[task.id] = task

    def get_task(self, task_id: str) -> DAGTask | None:
        return self._tasks.get(task_id)

    def get_ready_tasks(self) -> list[DAGTask]:
        """获取所有可以执行的任务（依赖已全部完成）"""
        ready = []
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            deps_met = all(dep_id in self._results for dep_id in task.dependencies)
            if deps_met:
                ready.append(task)
        return ready

    def get_blocked_tasks(self) -> list[DAGTask]:
        """获取被阻塞的任务"""
        blocked = []
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            deps_met = all(dep_id in self._results for dep_id in task.dependencies)
            if not deps_met:
                blocked.append(task)
        return blocked

    def all_completed(self) -> bool:
        return all(t.status in ("completed", "failed") for t in self._tasks.values())

    def has_failed(self) -> bool:
        return any(t.status == "failed" for t in self._tasks.values())

    def count_by_status(self, status: str) -> int:
        return sum(1 for t in self._tasks.values() if t.status == status)

    async def execute(
        self,
        task_executor: Callable[[DAGTask], Coroutine[Any, Any, Any]],
        max_concurrent: int = 5,
    ) -> dict[str, Any]:
        """
        按 DAG 拓扑顺序执行所有任务。

        Args:
            task_executor: 异步函数，接收 DAGTask 返回结果
            max_concurrent: 最大并行数

        Returns:
            {"results": {id: result}, "failed": [id], "total": N, "success": N}
        """
        pending = set(self._tasks)
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _run_task(task: DAGTask) -> None:
            async with semaphore:
                task.status = "running"
                try:
                    result = await task_executor(task)
                    task.status = "completed"
                    task.result = result
                    async with self._lock:
                        self._results[task.id] = result
                    logger.info("dag_task_completed id=%s", task.id)
                except Exception as e:
                    task.status = "failed"
                    task.error = str(e)
                    logger.warning("dag_task_failed id=%s error=%s", task.id, e)

        while pending:
            ready = self.get_ready_tasks()
            if not ready:
                if self.has_failed():
                    logger.warning("dag_stopped_due_to_failure")
                    break
                blocked_ids = [t.id for t in self.get_blocked_tasks()]
                logger.warning(
                    "dag_no_ready_tasks blocked=%s pending=%d",
                    blocked_ids,
                    len(pending),
                )
                break

            batch = ready[:max_concurrent]
            pending -= {t.id for t in batch}

            await asyncio.gather(*[_run_task(t) for t in batch], return_exceptions=True)

        failed_tasks = [t.id for t in self._tasks.values() if t.status == "failed"]
        success_count = self.count_by_status("completed")

        return {
            "results": self._results,
            "failed": failed_tasks,
            "total": len(self._tasks),
            "success": success_count,
        }
