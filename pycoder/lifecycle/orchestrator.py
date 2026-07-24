"""项目管理闭环 — 编排核心

ProjectLifecycleOrchestrator 是整个闭环系统的"指挥家"：
- 调度 7 阶段按序执行
- 维护状态机流转
- 发布进度事件
- 提供查询/取消接口

设计纪律：
- 只做编排，不实现业务逻辑（业务在 adapters 委托的现有模块中）
- 不持有 LLM 调用/沙箱执行/数据库操作
- 单文件 ≤ 300 行
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from pycoder.lifecycle.context import ProjectContext, ProjectStatus
from pycoder.lifecycle.phases import (
    LifecyclePhase,
    PhaseStrategy,
    get_progress,
    should_advance,
)
from pycoder.lifecycle.adapters import create_default_phases

logger = logging.getLogger(__name__)


class ProjectLifecycleOrchestrator:
    """项目生命周期编排器 — 7 阶段闭环的统一入口

    使用方式:
        orchestrator = ProjectLifecycleOrchestrator()
        ctx = orchestrator.create_project("实现一个用户注册API")
        async for event in orchestrator.run(ctx.project_id):
            print(event)

    可替换阶段策略:
        custom_phases = create_default_phases()
        custom_phases[LifecyclePhase.TEST] = MyTestAdapter()
        orchestrator = ProjectLifecycleOrchestrator(phases=custom_phases)
    """

    def __init__(
        self,
        phases: dict[LifecyclePhase, PhaseStrategy] | None = None,
    ) -> None:
        self._phases: dict[LifecyclePhase, PhaseStrategy] = (
            phases if phases is not None else create_default_phases()
        )
        self._projects: dict[str, ProjectContext] = {}

    # ── 项目管理 ────────────────────────────────────

    def create_project(
        self,
        request: str,
        workspace: str = "",
        model: str = "deepseek-chat",
        auto_apply: bool = False,
        quality_gate_level: int = 2,
    ) -> ProjectContext:
        """创建新项目并初始化上下文"""
        ctx = ProjectContext(
            request=request,
            workspace=workspace,
            model=model,
            auto_apply=auto_apply,
            quality_gate_level=quality_gate_level,
        )
        self._projects[ctx.project_id] = ctx
        logger.info("lifecycle_project_created id=%s", ctx.project_id)
        return ctx

    def get_project(self, project_id: str) -> ProjectContext | None:
        """获取项目上下文"""
        return self._projects.get(project_id)

    def list_projects(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出最近的项目"""
        sorted_items = sorted(
            self._projects.items(),
            key=lambda x: x[1].updated_at,
            reverse=True,
        )
        return [ctx.to_dict() for _, ctx in sorted_items[:limit]]

    def cancel_project(self, project_id: str) -> bool:
        """取消项目"""
        ctx = self._projects.get(project_id)
        if ctx is None:
            return False
        if ctx.status in (ProjectStatus.COMPLETED, ProjectStatus.FAILED, ProjectStatus.CANCELLED):
            return False
        ctx.status = ProjectStatus.CANCELLED
        ctx.touch()
        logger.info("lifecycle_project_cancelled id=%s", project_id)
        return True

    # ── 核心执行 ────────────────────────────────────

    async def run(
        self,
        project_id: str,
        resume: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行项目闭环（流式事件）

        Yields:
            {"type": "phase_start", "phase": str, "label": str, "progress": float}
            {"type": "phase_done", "phase": str, "status": str, "duration_ms": float}
            {"type": "gate", "phase": str, "passed": bool, "score": float}
            {"type": "error", "phase": str, "message": str}
            {"type": "done", "project_id": str, "status": str, "report": dict}
        """
        ctx = self._projects.get(project_id)
        if ctx is None:
            yield {"type": "error", "message": f"项目不存在: {project_id}"}
            return

        ctx.status = ProjectStatus.RUNNING
        ctx.touch()

        yield {
            "type": "pipeline_start",
            "project_id": project_id,
            "request": ctx.request[:200],
            "phases": [p.name for p in LifecyclePhase.ordered()],
        }

        # 确定起始阶段
        start_phase = LifecyclePhase.INTAKE
        if resume:
            # 恢复模式：从第一个未完成的阶段开始
            for phase in LifecyclePhase.ordered():
                rec = ctx.phases.get(phase.name)
                if rec is None or not rec.is_terminal:
                    start_phase = phase
                    break
            else:
                # 所有阶段已完成
                yield {
                    "type": "done",
                    "project_id": project_id,
                    "status": ctx.status.value,
                    "report": ctx.to_dict(),
                }
                return

        # 按序执行 7 阶段
        current = start_phase
        while current is not None:
            strategy = self._phases.get(current)
            if strategy is None:
                logger.warning("阶段 %s 无策略，跳过", current.name)
                current = current.next()
                continue

            # 发布阶段开始事件
            yield {
                "type": "phase_start",
                "phase": current.name,
                "label": current.label,
                "description": current.description,
                "progress": get_progress(ctx),
            }

            # 执行阶段
            try:
                record = await strategy.execute(ctx)
            except Exception as e:
                record = ctx.get_phase(current.name)
                record.status = "failed"
                record.error = f"{type(e).__name__}: {e}"

            # 发布阶段完成事件
            yield {
                "type": "phase_done",
                "phase": current.name,
                "status": record.status,
                "duration_ms": round(record.duration_ms, 1),
                "progress": get_progress(ctx),
            }

            # 质量门禁事件
            if record.gate_score > 0:
                yield {
                    "type": "gate",
                    "phase": current.name,
                    "passed": record.gate_passed,
                    "score": round(record.gate_score, 1),
                }

            # 检查是否可进入下一阶段
            if record.status == "failed":
                if not should_advance(ctx, current):
                    ctx.status = ProjectStatus.FAILED
                    ctx.touch()
                    yield {
                        "type": "error",
                        "phase": current.name,
                        "message": record.error,
                    }
                    yield {
                        "type": "done",
                        "project_id": project_id,
                        "status": ctx.status.value,
                        "report": ctx.to_dict(),
                    }
                    return

            current = current.next()

        # 全部阶段完成
        ctx.status = ProjectStatus.COMPLETED
        ctx.completed_at = time.time()
        ctx.touch()

        yield {
            "type": "done",
            "project_id": project_id,
            "status": ctx.status.value,
            "progress": get_progress(ctx),
            "report": ctx.to_dict(),
        }

        logger.info(
            "lifecycle_project_completed id=%s duration=%.1fs",
            project_id, ctx.completed_at - ctx.created_at,
        )

    # ── 阶段管理 ────────────────────────────────────

    def replace_phase(
        self,
        phase: LifecyclePhase,
        strategy: PhaseStrategy,
    ) -> None:
        """替换某个阶段的策略（支持运行时扩展）"""
        self._phases[phase] = strategy
        logger.info("lifecycle_phase_replaced phase=%s", phase.name)

    def get_phase_progress(self, project_id: str) -> dict[str, Any]:
        """获取项目进度详情"""
        ctx = self._projects.get(project_id)
        if ctx is None:
            return {"error": "项目不存在"}

        return {
            "project_id": project_id,
            "status": ctx.status.value,
            "current_phase": ctx.current_phase,
            "progress": get_progress(ctx),
            "phases": {
                p.name: ctx.phases.get(p.name, {}).to_dict()
                if ctx.phases.get(p.name)
                else {"phase": p.name, "status": "pending"}
                for p in LifecyclePhase.ordered()
            },
        }


# ══════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════

_orchestrator: ProjectLifecycleOrchestrator | None = None


def get_orchestrator() -> ProjectLifecycleOrchestrator:
    """获取全局编排器单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ProjectLifecycleOrchestrator()
    return _orchestrator
