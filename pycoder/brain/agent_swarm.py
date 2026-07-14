"""
Agent 集群编排器 — 多角色并行协作引擎

支持:
- 角色工厂: 动态创建不同角色的 Agent
- 并行执行: 独立任务并行分发给多个 Agent
- 依赖感知: 上游任务完成后再启动下游
- 结果聚合: 合并多个 Agent 的输出
"""

from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class AgentRole(enum.StrEnum):
    """预定义的 Agent 角色"""
    ARCHITECT = "architect"        # 架构师：设计系统结构
    DEVELOPER = "developer"        # 开发：编写代码
    REVIEWER = "reviewer"          # 审查：代码审查
    TESTER = "tester"              # 测试：编写和运行测试
    DEVOPS = "devops"              # 运维：部署和配置
    ANALYST = "analyst"            # 分析：需求分析和文档


@dataclass
class AgentTask:
    """分配给 Agent 的任务"""
    task_id: str
    role: AgentRole
    prompt: str
    dependencies: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent 执行结果"""
    task_id: str
    role: AgentRole
    success: bool
    output: str = ""
    error: str | None = None
    files_modified: list[str] = field(default_factory=list)
    tokens_used: int = 0
    duration_seconds: float = 0.0


class AgentSwarmOrchestrator:
    """
    Agent 集群编排器

    功能:
    - 将任务列表分配给不同角色的 Agent
    - 管理并行执行与依赖关系
    - 聚合结果并处理冲突
    """

    def __init__(self):
        self._active_agents: dict[str, AgentTask] = {}
        self._results: dict[str, AgentResult] = {}

    async def execute(
        self,
        tasks: list[AgentTask],
        *,
        parallel: bool = True,
        on_progress: Any = None,
    ) -> list[AgentResult]:
        """
        执行一组 Agent 任务

        Args:
            tasks: 任务列表
            parallel: 是否并行执行
            on_progress: 进度回调

        Returns:
            执行结果列表
        """
        if not tasks:
            return []

        # 构建依赖图
        {t.task_id: t for t in tasks}
        completed: set[str] = set()
        results: list[AgentResult] = []

        while len(completed) < len(tasks):
            # 找到所有可执行的任务（依赖已满足）
            ready = [
                t for t in tasks
                if t.task_id not in completed
                and all(d in completed for d in t.dependencies)
            ]

            if not ready:
                # 死锁检测
                logger.error("死锁检测: 等待的依赖无法满足")
                break

            if parallel and len(ready) > 1:
                # 并行执行
                batch_results = await asyncio.gather(*[
                    self._execute_single(t) for t in ready
                ])
                for r in batch_results:
                    results.append(r)
                    completed.add(r.task_id)
                    self._results[r.task_id] = r
            else:
                # 顺序执行
                for t in ready:
                    r = await self._execute_single(t)
                    results.append(r)
                    completed.add(r.task_id)
                    self._results[r.task_id] = r

                    if callable(on_progress):
                        on_progress(t.task_id, r)

        return results

    async def _execute_single(self, task: AgentTask) -> AgentResult:
        """
        执行单个 Agent 任务

        实际执行会通过总线调用 AI LLM。
        这里是框架实现，具体逻辑在 services/ 中。
        """
        import time
        start = time.monotonic()

        try:
            # 模拟 Agent 执行 —— 实际会调用 AI LLM
            output = f"[{task.role.value}] 完成任务: {task.prompt[:100]}"
            duration = time.monotonic() - start

            return AgentResult(
                task_id=task.task_id,
                role=task.role,
                success=True,
                output=output,
                tokens_used=len(task.prompt) // 4,
                duration_seconds=duration,
            )
        except Exception as e:
            return AgentResult(
                task_id=task.task_id,
                role=task.role,
                success=False,
                error=str(e),
            )

    def get_result(self, task_id: str) -> AgentResult | None:
        """获取任务结果"""
        return self._results.get(task_id)

    def get_all_results(self) -> dict[str, AgentResult]:
        """获取所有结果"""
        return dict(self._results)

    def cancel_task(self, task_id: str) -> None:
        """取消任务"""
        task = self._active_agents.pop(task_id, None)
        if task:
            logger.info("任务已取消: %s", task_id)

    @staticmethod
    def assign_roles(tasks: list[Any]) -> list[AgentTask]:
        """
        根据任务描述自动分配 Agent 角色

        Args:
            tasks: TaskPlanner.Task 列表

        Returns:
            AgentTask 列表
        """
        agent_tasks: list[AgentTask] = []

        for task in tasks:
            desc = task.description.lower()

            if any(w in desc for w in ["设计", "架构", "design", "architect"]):
                role = AgentRole.ARCHITECT
            elif any(w in desc for w in ["测试", "test", "验证", "verify"]):
                role = AgentRole.TESTER
            elif any(w in desc for w in ["审查", "review", "检查", "check"]):
                role = AgentRole.REVIEWER
            elif any(w in desc for w in ["部署", "deploy", "发布", "release"]):
                role = AgentRole.DEVOPS
            elif any(w in desc for w in ["分析", "analyze", "需求", "requirement"]):
                role = AgentRole.ANALYST
            else:
                role = AgentRole.DEVELOPER

            agent_tasks.append(AgentTask(
                task_id=task.task_id,
                role=role,
                prompt=task.description,
                dependencies=task.dependencies,
            ))

        return agent_tasks
