"""
专业 Agent 团队 API — 10 角色自动选角与团队管理 REST 端点

端点列表:
  GET  /api/agents/roles              — 列出所有 Agent 角色
  POST /api/agents/select             — 根据任务描述自动选角
  POST /api/agents/team/create        — 创建专业 Agent 团队
  POST /api/agents/team/{team_id}/assign — 分配任务给 Agent
  GET  /api/agents/team/{team_id}/progress — 获取团队进度
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.brain.specialized_agents import (
    AgentRole,
    SpecializedAgentTeam,
    get_agent_team,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# ──────────────────────────────────────────────
# 全局实例
# ──────────────────────────────────────────────

_agent_team: SpecializedAgentTeam = get_agent_team()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class SelectRequest(BaseModel):
    """自动选角请求体"""
    task_description: str = Field(..., description="任务描述文本")


class AgentProfileResponse(BaseModel):
    """Agent 角色配置响应"""
    role: str
    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]
    temperature: float
    max_tokens: int
    priority: int


class SelectResponse(BaseModel):
    """自动选角响应"""
    task: str
    selected: list[AgentProfileResponse]
    count: int


class CreateTeamRequest(BaseModel):
    """创建团队请求体"""
    name: str = Field(..., description="团队名称")
    roles: list[str] = Field(..., description="角色列表，如: ['architect', 'developer', 'tester']")


class CreateTeamResponse(BaseModel):
    """创建团队响应"""
    success: bool
    team_name: str | None = None
    members: list[str] | None = None
    member_count: int | None = None
    error: str | None = None
    valid_roles: list[str] | None = None


class AssignTaskRequest(BaseModel):
    """分配任务请求体"""
    agent_role: str = Field(..., description="Agent 角色名称")
    task: str = Field(..., description="任务描述")


class AssignTaskResponse(BaseModel):
    """分配任务响应"""
    success: bool
    team_name: str | None = None
    task_id: str | None = None
    role: str | None = None
    description: str | None = None
    status: str | None = None
    error: str | None = None
    valid_roles: list[str] | None = None
    team_members: list[str] | None = None


class ProgressResponse(BaseModel):
    """团队进度响应"""
    team_name: str
    members: list[str]
    total_tasks: int
    done: int
    failed: int
    running: int
    pending: int
    progress_pct: float
    tasks: dict[str, Any]


# ──────────────────────────────────────────────
# 路由实现
# ──────────────────────────────────────────────


@router.get("/roles", response_model=dict[str, Any])
async def list_agent_roles() -> dict[str, Any]:
    """列出所有 10 个专业 Agent 角色及其配置"""
    profiles = _agent_team.get_all_profiles()
    return {
        "roles": [p.to_dict() for p in profiles],
        "count": len(profiles),
    }


@router.post("/select", response_model=SelectResponse)
async def select_agents(req: SelectRequest) -> SelectResponse:
    """根据任务描述自动选择合适的 Agent 角色

    基于关键词匹配，返回按相关度降序排列的角色列表。
    """
    if not req.task_description.strip():
        raise HTTPException(status_code=400, detail="task_description 不能为空")

    agents = _agent_team.select_agents(req.task_description)

    return SelectResponse(
        task=req.task_description,
        selected=[
            AgentProfileResponse(
                role=p.role.value,
                name=p.name,
                description=p.description,
                system_prompt=p.system_prompt,
                allowed_tools=p.allowed_tools,
                temperature=p.temperature,
                max_tokens=p.max_tokens,
                priority=p.priority,
            )
            for p in agents
        ],
        count=len(agents),
    )


@router.post("/team/create", response_model=CreateTeamResponse)
async def create_team(req: CreateTeamRequest) -> CreateTeamResponse:
    """创建包含指定角色的专业 Agent 团队"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="团队名称不能为空")

    if not req.roles:
        raise HTTPException(status_code=400, detail="至少需要一个角色")

    # 解析角色名
    roles: list[AgentRole] = []
    invalid_roles: list[str] = []
    for rn in req.roles:
        try:
            roles.append(AgentRole(rn))
        except ValueError:
            invalid_roles.append(rn)

    if invalid_roles:
        return CreateTeamResponse(
            success=False,
            error=f"无效角色: {invalid_roles}",
            valid_roles=[r.value for r in AgentRole],
        )

    team = _agent_team.create_team(req.name.strip(), roles)

    return CreateTeamResponse(
        success=True,
        team_name=team.name,
        members=[r.value for r in team.roles],
        member_count=len(team.roles),
    )


@router.post("/team/{team_id}/assign", response_model=AssignTaskResponse)
async def assign_task(team_id: str, req: AssignTaskRequest) -> AssignTaskResponse:
    """分配任务给指定团队中的 Agent

    将任务描述分配给团队中的某个 Agent 角色执行。
    """
    if not req.agent_role.strip():
        raise HTTPException(status_code=400, detail="agent_role 不能为空")

    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task 不能为空")

    team = _agent_team.get_team(team_id)
    if team is None:
        raise HTTPException(
            status_code=404,
            detail=f"团队不存在: {team_id}",
        )

    try:
        role = AgentRole(req.agent_role)
    except ValueError:
        return AssignTaskResponse(
            success=False,
            error=f"无效角色: {req.agent_role}",
            valid_roles=[r.value for r in AgentRole],
        )

    if role not in team.roles:
        return AssignTaskResponse(
            success=False,
            error=f"角色 '{req.agent_role}' 不在团队 '{team_id}' 中",
            team_members=[r.value for r in team.roles],
        )

    task = team.assign_task(role, req.task)

    return AssignTaskResponse(
        success=True,
        team_name=team.name,
        task_id=task.task_id,
        role=role.value,
        description=task.description,
        status=task.status,
    )


@router.get("/team/{team_id}/progress", response_model=ProgressResponse)
async def get_team_progress(team_id: str) -> ProgressResponse:
    """获取团队执行进度报告

    包含任务统计（完成/失败/运行中/待处理）和各任务状态详情。
    """
    team = _agent_team.get_team(team_id)
    if team is None:
        raise HTTPException(
            status_code=404,
            detail=f"团队不存在: {team_id}",
        )

    progress = team.get_progress()

    return ProgressResponse(
        team_name=progress["team_name"],
        members=progress["members"],
        total_tasks=progress["total_tasks"],
        done=progress["done"],
        failed=progress["failed"],
        running=progress["running"],
        pending=progress["pending"],
        progress_pct=progress["progress_pct"],
        tasks=progress["tasks"],
    )