"""项目管理闭环 — FastAPI 路由

提供 HTTP 接口触发 7 阶段闭环，支持 SSE 流式事件。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pycoder.lifecycle import (
    LifecyclePhase,
    get_orchestrator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


# ══════════════════════════════════════════════════════
# 请求/响应模型
# ══════════════════════════════════════════════════════


class CreateProjectRequest(BaseModel):
    """创建项目请求"""

    request: str = Field(..., description="项目需求描述")
    workspace: str = Field("", description="工作目录")
    model: str = Field("deepseek-chat", description="LLM 模型")
    auto_apply: bool = Field(False, description="是否自动应用修改")
    quality_gate_level: int = Field(2, ge=1, le=4, description="质量门禁级别")


class RunProjectRequest(BaseModel):
    """运行项目请求"""

    project_id: str = Field(..., description="项目 ID")
    resume: bool = Field(False, description="是否从断点恢复")


# ══════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════


@router.post("/projects")
async def create_project(req: CreateProjectRequest) -> dict[str, Any]:
    """创建新的项目管理闭环项目"""
    orch = get_orchestrator()
    ctx = orch.create_project(
        request=req.request,
        workspace=req.workspace,
        model=req.model,
        auto_apply=req.auto_apply,
        quality_gate_level=req.quality_gate_level,
    )
    return {
        "project_id": ctx.project_id,
        "status": ctx.status.value,
        "phases": [p.name for p in LifecyclePhase.ordered()],
    }


@router.get("/projects")
async def list_projects(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
) -> dict[str, Any]:
    """列出项目"""
    orch = get_orchestrator()
    return {"projects": orch.list_projects(limit=limit), "count": limit}


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    """获取项目详情"""
    orch = get_orchestrator()
    ctx = orch.get_project(project_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")
    return ctx.to_dict()


@router.get("/projects/{project_id}/progress")
async def get_progress(project_id: str) -> dict[str, Any]:
    """获取项目进度"""
    orch = get_orchestrator()
    result = orch.get_phase_progress(project_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/run")
async def run_project(req: RunProjectRequest) -> dict[str, Any]:
    """运行项目闭环（同步模式，返回最终报告）"""
    orch = get_orchestrator()
    ctx = orch.get_project(req.project_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {req.project_id}")

    final_report: dict[str, Any] = {}
    events_count = 0

    async for event in orch.run(req.project_id, resume=req.resume):
        events_count += 1
        if event.get("type") == "done":
            final_report = event
            break
        if event.get("type") == "error":
            raise HTTPException(
                status_code=500,
                detail=f"阶段 {event.get('phase')} 失败: {event.get('message')}",
            )

    return {
        "project_id": req.project_id,
        "events_count": events_count,
        "status": final_report.get("status"),
        "report": final_report.get("report"),
    }


@router.post("/run/stream")
async def run_project_stream(req: RunProjectRequest) -> StreamingResponse:
    """运行项目闭环（SSE 流式模式，实时返回阶段事件）"""
    orch = get_orchestrator()
    ctx = orch.get_project(req.project_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {req.project_id}")

    async def event_generator():
        """SSE 事件生成器"""
        async for event in orch.run(req.project_id, resume=req.resume):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/projects/{project_id}/cancel")
async def cancel_project(project_id: str) -> dict[str, Any]:
    """取消项目"""
    orch = get_orchestrator()
    ok = orch.cancel_project(project_id)
    if not ok:
        raise HTTPException(status_code=400, detail="项目不存在或已终态")
    return {"project_id": project_id, "cancelled": True}


@router.get("/phases")
async def list_phases() -> dict[str, Any]:
    """列出所有阶段定义"""
    return {
        "phases": [
            {
                "id": p.name,
                "order": p.value,
                "label": p.label,
                "description": p.description,
            }
            for p in LifecyclePhase.ordered()
        ],
        "total": len(LifecyclePhase.ordered()),
    }
