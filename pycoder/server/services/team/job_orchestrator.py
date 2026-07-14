"""P1-1: 任务调度 — 并行执行、聚合、依赖管理

从 team_orchestrator.py 抽取的职责：
- 阶段 2 的并行调度逻辑（asyncio.gather）
- 依赖关系解析（仅执行依赖已完成的任务）
- 单任务执行结果聚合
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pycoder.server.log import log


@dataclass
class Job:
    """单个可执行任务"""

    task_id: str
    title: str
    description: str
    assigned_role: str = ""
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed | skipped
    result: Any = None
    error: str = ""
    deliverables: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)


# 任务执行器类型：接受 Job，返回结果字符串
JobExecutor = Callable[[Job], Awaitable[str]]


class JobOrchestrator:
    """任务调度器 — 不含 Agent 业务逻辑，只负责调度"""

    async def execute_with_dependencies(
        self,
        jobs: list[Job],
        executor: JobExecutor,
        max_rounds: int = 20,
    ) -> tuple[set[str], dict[str, str]]:
        """按依赖关系并行执行任务

        Args:
            jobs: 全部任务列表
            executor: 任务执行函数（接受 Job，返回结果字符串）
            max_rounds: 最大调度轮次（防止死循环）

        Returns:
            (executed_ids, results_map) — 已执行任务 ID 集合与结果映射
        """
        executed_ids: set[str] = set()
        results: dict[str, str] = {}
        round_num = 0

        while len(executed_ids) < len(jobs) and round_num < max_rounds:
            round_num += 1

            # 找可执行的任务（依赖都已完成的）
            available = [
                j
                for j in jobs
                if j.task_id not in executed_ids
                and all(dep in executed_ids for dep in j.depends_on)
            ]
            if not available:
                log.warning(
                    "job_scheduler_no_available",
                    round=round_num,
                    remaining=len(jobs) - len(executed_ids),
                )
                break

            # 并行调度
            coros = [self._run_one(j, executor, results) for j in available]
            await asyncio.gather(*coros, return_exceptions=True)

            for j in available:
                executed_ids.add(j.task_id)

        return executed_ids, results

    async def _run_one(
        self,
        job: Job,
        executor: JobExecutor,
        results: dict[str, str],
    ) -> str:
        """执行单个任务并记录结果

        失败时记录错误但不抛出，让 gather 继续运行其他任务。
        """
        job.status = "running"
        try:
            result = await executor(job)
            job.status = "done"
            job.result = result
            results[job.task_id] = result
            return result
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            log.error("job_failed", task_id=job.task_id, error=str(e))
            return ""

    def filter_available(
        self,
        jobs: list[Job],
        executed_ids: set[str],
    ) -> list[Job]:
        """筛选可执行的任务（依赖已全部完成）"""
        return [
            j
            for j in jobs
            if j.task_id not in executed_ids and all(dep in executed_ids for dep in j.depends_on)
        ]
