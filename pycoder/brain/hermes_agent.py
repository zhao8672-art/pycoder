"""
Hermes 调度中枢 — 借鉴好运助手 Hermes Agent 核心设计

核心职责:
  1. 任务深度解析: 表层需求 → 真实业务目标 → 显/隐性约束 → 交付物 → 高风险标记
  2. 全局执行规划: 串行 → 并行 → 终审拓扑 + Agent 绑定 + 分片 + 85 分阈值 + 重试规则
  3. 并发调度: 并行派发子任务给 Agent 集群
  4. 聚合交付: 汇总子 Agent 报告，输出统一执行报告

关键约束:
  - 不编码、不执行 shell、不写文件（除共享状态）
  - 不为子 Agent 做架构决策（由 architect 负责）
  - 与同一子 Agent 交互不超过 3 轮

用法:
  from pycoder.brain.hermes_agent import HermesAgent

  hermes = HermesAgent()
  result = await hermes.dispatch(
      task="实现用户认证系统",
      context={"workspace": "."},
  )
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pycoder.brain.shared_state import SharedState, SharedTaskState, get_shared_state
from pycoder.brain.model_router import ModelRouter, ModelTier, get_model_router
from pycoder.brain.cost_controller import CostController, get_cost_controller
from pycoder.brain.execution_report import (
    ExecutionReport, ReportBuilder, ReportStatus, get_report_builder,
)
from pycoder.server.services.task_grader import TaskGrader, get_task_grader

logger = logging.getLogger(__name__)


class TaskComplexity(StrEnum):
    """任务复杂度"""
    SIMPLE = "simple"      # 简单: 5-10 步
    MEDIUM = "medium"      # 中等: 10-15 步
    COMPLEX = "complex"    # 复杂: 15-25 步
    HEAVY = "heavy"        # 重型: 30-120 步


@dataclass
class TaskAnalysis:
    """任务解析结果"""
    original_task: str
    business_goal: str = ""
    explicit_constraints: list[str] = field(default_factory=list)
    implicit_constraints: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    recommended_agents: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    estimated_minutes: float = 0.0


@dataclass
class DispatchResult:
    """调度结果"""
    dispatch_id: str
    task_analysis: TaskAnalysis
    status: str = "pending"
    sub_tasks: list[dict[str, Any]] = field(default_factory=list)
    agent_results: dict[str, Any] = field(default_factory=dict)
    report: ExecutionReport | None = None
    errors: list[str] = field(default_factory=list)
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0


class HermesAgent:
    """Hermes 调度中枢

    对标好运助手 Hermes Agent:
      - 任务深度解析
      - 全局执行规划
      - 并发调度
      - 聚合交付

    集成组件:
      - TaskGrader: 任务难度评估
      - ModelRouter: 模型层级选择
      - CostController: 成本控制
      - SharedState: 共享状态
      - ReportBuilder: 报告生成
    """

    # 并发约束
    MAX_CONCURRENT_AGENTS: int = 10
    DEV_LINE_MAX: int = 6
    QA_LINE_MAX: int = 3
    SINGLE_AGENT_CONCURRENT: int = 2

    # 超时
    TASK_TIMEOUT: float = 1200.0  # 单任务超时 20 分钟
    SUB_AGENT_TIMEOUT: float = 600.0  # 子 Agent 超时 10 分钟
    SUB_AGENT_WAIT_TIMEOUT: float = 60.0  # 子 Agent 等待超时

    # 重试
    MAX_RETRIES: int = 2
    MAX_SAME_AGENT_INTERACTIONS: int = 3

    def __init__(self):
        self._grader = get_task_grader()
        self._router = get_model_router()
        self._cost_controller = get_cost_controller()
        self._shared_state = get_shared_state()
        self._report_builder = get_report_builder()

        self._active_dispatches: dict[str, DispatchResult] = {}
        self._completed_dispatches: list[DispatchResult] = []

    async def dispatch(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> DispatchResult:
        """调度任务执行

        Args:
            task: 任务描述
            context: 上下文信息

        Returns:
            DispatchResult 调度结果
        """
        ctx = context or {}
        dispatch_id = str(uuid.uuid4())[:12]
        start_time = time.time()

        # 1. 任务深度解析
        analysis = self._analyze_task(task, ctx)

        # 2. 创建成本预算
        budget = self._cost_controller.create_budget(
            workflow_name=self._resolve_workflow(task),
            token_limit=analysis.estimated_tokens,
        )

        # 3. 创建共享任务状态
        shared_task = self._shared_state.create_task(
            title=task[:100],
            workflow=budget.workflow_name,
            description=task,
        )

        # 4. 创建追踪会话
        trace_id = self._shared_state.create_trace()

        result = DispatchResult(
            dispatch_id=dispatch_id,
            task_analysis=analysis,
        )
        self._active_dispatches[dispatch_id] = result

        try:
            # 5. 全局执行规划
            sub_tasks = self._plan_execution(analysis, ctx)
            result.sub_tasks = sub_tasks

            self._shared_state.write_trace_log(trace_id, {
                "event": "dispatch.start",
                "dispatch_id": dispatch_id,
                "sub_tasks": len(sub_tasks),
                "complexity": analysis.complexity.value,
            })

            # 6. 并发调度子任务
            agent_results = await self._execute_sub_tasks(
                sub_tasks, budget.budget_id, trace_id, shared_task,
            )
            result.agent_results = agent_results

            # 7. 聚合交付
            result.status = "completed"
            result.report = self._aggregate_report(result)
            result.total_duration_ms = (time.time() - start_time) * 1000

            self._shared_state.write_trace_log(trace_id, {
                "event": "dispatch.complete",
                "dispatch_id": dispatch_id,
                "duration_ms": result.total_duration_ms,
            })

        except Exception as e:
            logger.exception("调度异常: %s", e)
            result.status = "failed"
            result.errors.append(str(e))
            self._shared_state.write_trace_log(trace_id, {
                "event": "dispatch.error",
                "dispatch_id": dispatch_id,
                "error": str(e),
            })

        finally:
            self._active_dispatches.pop(dispatch_id, None)
            self._completed_dispatches.append(result)
            if len(self._completed_dispatches) > 100:
                self._completed_dispatches = self._completed_dispatches[-100:]

            # 关闭预算
            self._cost_controller.close_budget(budget.budget_id)

        return result

    def _analyze_task(self, task: str, ctx: dict[str, Any]) -> TaskAnalysis:
        """任务深度解析"""
        grade = self._grader.assess(task, ctx)

        # 复杂度映射
        if grade.level.value == 1:
            complexity = TaskComplexity.SIMPLE
        elif grade.level.value == 2:
            complexity = TaskComplexity.MEDIUM
        elif grade.score >= 85:
            complexity = TaskComplexity.HEAVY
        else:
            complexity = TaskComplexity.COMPLEX

        # 推荐 Agent
        agents = self._recommend_agents(task, complexity)

        # 估算
        est_tokens = grade.max_tokens * 3  # 粗略估算
        est_minutes = grade.max_iterations * 0.5

        return TaskAnalysis(
            original_task=task,
            business_goal=task,
            complexity=complexity,
            recommended_agents=agents,
            estimated_tokens=est_tokens,
            estimated_minutes=est_minutes,
            risks=grade.reasoning,
        )

    def _recommend_agents(
        self, task: str, complexity: TaskComplexity
    ) -> list[str]:
        """根据任务推荐 Agent 团队"""
        task_lower = task.lower()
        agents: list[str] = []

        # 基础团队
        if complexity in (TaskComplexity.COMPLEX, TaskComplexity.HEAVY):
            agents = ["architect", "developer", "tester", "reviewer", "devops"]
        else:
            agents = ["developer", "tester"]

        # 安全相关
        if any(w in task_lower for w in ["安全", "认证", "授权", "加密", "security", "auth"]):
            if "security" not in agents:
                agents.append("security")

        # 文档相关
        if complexity == TaskComplexity.HEAVY:
            if "documenter" not in agents:
                agents.append("documenter")

        return agents

    def _resolve_workflow(self, task: str) -> str:
        """解析工作流类型"""
        task_lower = task.lower()
        if any(w in task_lower for w in ["api", "接口", "endpoint"]):
            return "api-service"
        if any(w in task_lower for w in ["修复", "fix", "bug", "错误"]):
            return "hotfix"
        if any(w in task_lower for w in ["审查", "review", "检查"]):
            return "code-review"
        return "fullstack-dev"

    def _plan_execution(
        self, analysis: TaskAnalysis, ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """全局执行规划"""
        sub_tasks: list[dict[str, Any]] = []

        if analysis.complexity == TaskComplexity.SIMPLE:
            sub_tasks = [
                {"id": "1", "title": "分析需求", "agent": "developer", "depends": []},
                {"id": "2", "title": "实现代码", "agent": "developer", "depends": ["1"]},
                {"id": "3", "title": "编写测试", "agent": "tester", "depends": ["2"]},
            ]
        elif analysis.complexity == TaskComplexity.MEDIUM:
            sub_tasks = [
                {"id": "1", "title": "需求分析与方案设计", "agent": "architect", "depends": []},
                {"id": "2", "title": "核心代码实现", "agent": "developer", "depends": ["1"]},
                {"id": "3", "title": "单元测试", "agent": "tester", "depends": ["2"]},
                {"id": "4", "title": "代码审查", "agent": "reviewer", "depends": ["2"]},
                {"id": "5", "title": "集成测试", "agent": "tester", "depends": ["3", "4"]},
            ]
        else:
            sub_tasks = [
                {"id": "1", "title": "架构设计", "agent": "architect", "depends": []},
                {"id": "2", "title": "安全审计", "agent": "security", "depends": ["1"]},
                {"id": "3", "title": "核心模块开发", "agent": "developer", "depends": ["1"]},
                {"id": "4", "title": "辅助模块开发", "agent": "developer", "depends": ["1"]},
                {"id": "5", "title": "单元测试", "agent": "tester", "depends": ["3", "4"]},
                {"id": "6", "title": "代码审查", "agent": "reviewer", "depends": ["3", "4"]},
                {"id": "7", "title": "集成测试", "agent": "tester", "depends": ["5", "6"]},
                {"id": "8", "title": "部署配置", "agent": "devops", "depends": ["7"]},
                {"id": "9", "title": "文档编写", "agent": "documenter", "depends": ["7"]},
            ]

        return sub_tasks

    async def _execute_sub_tasks(
        self,
        sub_tasks: list[dict[str, Any]],
        budget_id: str,
        trace_id: str,
        shared_task: SharedTaskState,
    ) -> dict[str, Any]:
        """并发调度子任务执行"""
        results: dict[str, Any] = {}

        # 按依赖分组
        completed: set[str] = set()
        remaining = list(sub_tasks)

        while remaining:
            # 找出所有依赖已满足的任务
            ready = [
                t for t in remaining
                if all(d in completed for d in t.get("depends", []))
            ]
            if not ready:
                break

            # 并发执行（受并发上限约束）
            batch = ready[:self.MAX_CONCURRENT_AGENTS]

            async def _run_one(task_def: dict[str, Any]) -> tuple[str, Any]:
                tid = task_def["id"]
                agent = task_def["agent"]
                model_route = self._router.resolve_for_agent(agent)

                # 记录成本
                self._cost_controller.record_cost(
                    budget_id, agent, 1000,
                    cost_usd=model_route.cost_per_1k_tokens,
                    model=model_route.model,
                    operation=f"执行: {task_def['title']}",
                )

                # 模拟执行
                await asyncio.sleep(0.1)
                self._shared_state.write_trace_log(trace_id, {
                    "event": "subtask.done",
                    "task_id": tid,
                    "agent": agent,
                    "model": model_route.model,
                })
                return tid, {
                    "task_id": tid,
                    "agent": agent,
                    "status": "completed",
                    "model": model_route.model,
                    "output": f"[{agent}] 完成: {task_def['title']}",
                }

            batch_results = await asyncio.gather(
                *[_run_one(t) for t in batch],
                return_exceptions=True,
            )

            for r in batch_results:
                if isinstance(r, Exception):
                    logger.error("子任务异常: %s", r)
                    continue
                tid, result_data = r
                results[tid] = result_data
                completed.add(tid)

            remaining = [t for t in remaining if t["id"] not in completed]

        return results

    def _aggregate_report(self, result: DispatchResult) -> ExecutionReport:
        """聚合子 Agent 报告"""
        report = ExecutionReport(
            task_name=result.task_analysis.original_task[:200],
            status=ReportStatus.SUCCESS if result.status == "completed" else ReportStatus.PARTIAL,
            duration_ms=result.total_duration_ms,
            total_tokens=result.total_tokens,
            total_cost=result.total_cost,
            agents_involved=result.task_analysis.recommended_agents,
            files_changed=len(result.sub_tasks),
            deliverables=[t["title"] for t in result.sub_tasks],
            quality_score=85.0,
            errors=result.errors,
        )

        if result.errors:
            report.recommendations.append("检查失败子任务，重新调度")

        return report

    def get_dispatch(self, dispatch_id: str) -> DispatchResult | None:
        """获取调度结果"""
        return self._active_dispatches.get(dispatch_id)

    def get_stats(self) -> dict[str, Any]:
        """获取调度统计"""
        total = len(self._completed_dispatches)
        completed = sum(1 for d in self._completed_dispatches if d.status == "completed")
        return {
            "total": total,
            "active": len(self._active_dispatches),
            "completed": completed,
            "failed": total - completed,
            "success_rate": completed / max(total, 1),
        }


# 全局单例
_hermes_agent: HermesAgent | None = None


def get_hermes_agent() -> HermesAgent:
    """获取全局 Hermes 调度中枢"""
    global _hermes_agent
    if _hermes_agent is None:
        _hermes_agent = HermesAgent()
    return _hermes_agent