"""
V2 流水线引擎 API 端点 — 八阶段长项目开发全流程

提供:
  - POST /api/v2/pipeline/run           — 启动完整流水线
  - POST /api/v2/pipeline/run/async     — 异步启动流水线
  - GET  /api/v2/pipeline/status/{id}   — 流水线状态
  - GET  /api/v2/pipeline/list          — 列出流水线
  - GET  /api/v2/pipeline/stats         — 流水线统计
  - GET  /api/v2/pipeline/hermes/status — Hermes 调度中枢状态
  - POST /api/v2/pipeline/hermes/dispatch — Hermes 调度任务
  - GET  /api/v2/pipeline/agents/roles  — 列出所有 Agent 角色
  - GET  /api/v2/pipeline/agents/select — 自动选角
  - GET  /api/v2/pipeline/cost/status   — 成本控制状态
  - GET  /api/v2/pipeline/quality/gates — 质量门禁配置
  - GET  /api/v2/pipeline/model/route   — 模型路由测试
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.brain.pipeline_engine import (
    PipelineEngine,
    PipelinePhase,
    PipelinePhaseResult,
    get_pipeline_engine,
)
from pycoder.brain.hermes_agent import HermesAgent, get_hermes_agent
from pycoder.brain.specialized_agents import (
    AgentRole,
    SpecializedAgentTeam,
    get_agent_team,
)
from pycoder.brain.model_router import ModelRouter, get_model_router
from pycoder.brain.cost_controller import CostController, get_cost_controller
from pycoder.brain.quality_gate import QualityGate, get_quality_gate
from pycoder.brain.shared_state import SharedState, get_shared_state
from pycoder.brain.execution_report import ReportBuilder, get_report_builder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pipeline", tags=["v2-pipeline"])


# ══════════════════════════════════════════════════════════
# 请求模型
# ══════════════════════════════════════════════════════════


class PipelineRunRequest(BaseModel):
    task: str = Field(..., description="任务描述", min_length=1)
    context: dict | None = Field(default=None, description="额外上下文")
    enable_quality_gates: bool = Field(default=True, description="是否启用质量门禁")
    enable_audit: bool = Field(default=True, description="是否启用审计日志")


class HermesDispatchRequest(BaseModel):
    task: str = Field(..., description="任务描述", min_length=1)
    context: dict | None = Field(default=None, description="额外上下文")


class AgentSelectRequest(BaseModel):
    task_description: str = Field(..., description="任务描述", min_length=1)


class ModelRouteRequest(BaseModel):
    task: str = Field(..., description="任务描述", min_length=1)
    agent_role: str = Field(default="", description="Agent 角色")


# ══════════════════════════════════════════════════════════
# 流水线端点
# ══════════════════════════════════════════════════════════


@router.post("/run")
async def run_pipeline(body: PipelineRunRequest):
    """启动完整八阶段流水线"""
    engine = get_pipeline_engine()
    result = await engine.run(
        task=body.task,
        context=body.context or {},
    )
    return result.to_dict()


@router.post("/run/async")
async def run_pipeline_async(body: PipelineRunRequest):
    """异步启动流水线（立即返回，后台执行）"""
    engine = get_pipeline_engine()

    async def _background():
        await engine.run(
            task=body.task,
            context=body.context or {},
        )

    asyncio.create_task(_background())
    return {
        "status": "accepted",
        "message": "流水线已异步启动，请通过 /api/v2/pipeline/list 查询状态",
        "task": body.task[:200],
    }


@router.get("/status/{pipeline_id}")
async def pipeline_status(pipeline_id: str):
    """获取流水线执行状态"""
    engine = get_pipeline_engine()
    status = engine.get_pipeline_status(pipeline_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"流水线不存在: {pipeline_id}")
    return status


@router.get("/list")
async def list_pipelines(limit: int = Query(default=20, le=100)):
    """列出最近的流水线"""
    engine = get_pipeline_engine()
    return {
        "pipelines": engine.list_pipelines(limit),
        "total": len(engine.list_pipelines(limit)),
    }


@router.get("/stats")
async def pipeline_stats():
    """获取流水线统计"""
    engine = get_pipeline_engine()
    return engine.get_stats()


@router.get("/phases")
async def list_phases():
    """列出所有流水线阶段"""
    return {
        "phases": [
            {
                "phase": phase.value,
                "name": name,
                "required": required,
                "gate_level": gate_level,
            }
            for phase, name, required, gate_level in PipelineEngine.STAGES
        ],
        "total": len(PipelineEngine.STAGES),
    }


# ══════════════════════════════════════════════════════════
# Hermes 调度中枢端点
# ══════════════════════════════════════════════════════════


@router.post("/hermes/dispatch")
async def hermes_dispatch(body: HermesDispatchRequest):
    """Hermes 调度中枢 — 任务深度解析、规划和并发调度"""
    hermes = get_hermes_agent()
    result = await hermes.dispatch(
        task=body.task,
        context=body.context or {},
    )
    return {
        "dispatch_id": result.dispatch_id,
        "status": result.status,
        "complexity": result.task_analysis.complexity.value,
        "recommended_agents": result.task_analysis.recommended_agents,
        "estimated_tokens": result.task_analysis.estimated_tokens,
        "estimated_minutes": result.task_analysis.estimated_minutes,
        "sub_tasks": result.sub_tasks,
        "agent_results": result.agent_results,
        "errors": result.errors,
        "total_duration_ms": result.total_duration_ms,
    }


@router.get("/hermes/status")
async def hermes_status():
    """获取 Hermes 调度中枢状态"""
    hermes = get_hermes_agent()
    return hermes.get_stats()


# ══════════════════════════════════════════════════════════
# Agent 团队端点
# ══════════════════════════════════════════════════════════


@router.get("/agents/roles")
async def list_agent_roles():
    """列出所有 Agent 角色和配置"""
    team_mgr = get_agent_team()
    profiles = team_mgr.get_all_profiles()
    return {
        "roles": [p.to_dict() for p in profiles],
        "count": len(profiles),
    }


@router.post("/agents/select")
async def select_agents(body: AgentSelectRequest):
    """根据任务描述自动选择合适的 Agent 角色"""
    team_mgr = get_agent_team()
    agents = team_mgr.select_agents(body.task_description)
    return {
        "task": body.task_description,
        "selected": [p.to_dict() for p in agents],
        "count": len(agents),
    }


# ══════════════════════════════════════════════════════════
# 模型路由端点
# ══════════════════════════════════════════════════════════


@router.post("/model/route")
async def model_route(body: ModelRouteRequest):
    """测试模型路由 — 返回推荐模型"""
    router = get_model_router()
    route = router.resolve(
        task=body.task,
        agent_role=body.agent_role,
    )
    return route.to_dict()


@router.get("/model/stats")
async def model_stats():
    """获取模型路由统计"""
    router = get_model_router()
    return router.get_stats()


# ══════════════════════════════════════════════════════════
# 成本控制端点
# ══════════════════════════════════════════════════════════


@router.get("/cost/status")
async def cost_status():
    """获取成本控制状态"""
    controller = get_cost_controller()
    return controller.get_stats()


@router.get("/cost/budget/{budget_id}")
async def cost_budget_detail(budget_id: str):
    """获取预算详情"""
    controller = get_cost_controller()
    detail = controller.get_budget_details(budget_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"预算不存在: {budget_id}")
    return detail


# ══════════════════════════════════════════════════════════
# 质量门禁端点
# ══════════════════════════════════════════════════════════


@router.get("/quality/gates")
async def quality_gates_config():
    """获取质量门禁配置"""
    gate = get_quality_gate()
    return gate.get_stats()


# ══════════════════════════════════════════════════════════
# 共享状态端点
# ══════════════════════════════════════════════════════════


@router.get("/shared/stats")
async def shared_state_stats():
    """获取共享状态统计"""
    state = get_shared_state()
    return state.get_stats()


@router.get("/shared/tasks")
async def list_shared_tasks(
    status: str = Query(default="", description="按状态过滤"),
    workflow: str = Query(default="", description="按工作流过滤"),
):
    """列出共享状态中的任务"""
    state = get_shared_state()
    tasks = state.list_tasks(
        status=status or None,
        workflow=workflow or None,
    )
    return {
        "tasks": [t.to_dict() for t in tasks],
        "total": len(tasks),
    }