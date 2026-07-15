"""
任务评分与持久化 API 路由

端点:
    POST /api/task/grade              — 评估任务难度
    POST /api/task/save               — 保存任务状态
    GET  /api/task/{task_id}          — 加载任务
    GET  /api/task/list               — 列出任务
    POST /api/task/{task_id}/checkpoint — 创建断点
    POST /api/task/{task_id}/resume   — 从断点恢复
    GET  /api/task/stats              — 获取任务统计
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.server.services.task_grader import TaskGrader, TaskGrade, get_task_grader
from pycoder.server.services.task_persistence import (
    TaskPersistence,
    TaskState,
    VALID_GRADES,
    VALID_STATUSES,
    get_task_persistence,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/task", tags=["task"])

# ──────────────────────────────────────────────
# 模块级单例
# ──────────────────────────────────────────────

_grader: TaskGrader | None = None
_persistence: TaskPersistence | None = None


def _get_grader() -> TaskGrader:
    """获取 TaskGrader 单例"""
    global _grader
    if _grader is None:
        _grader = get_task_grader()
    return _grader


def _get_persistence() -> TaskPersistence:
    """获取 TaskPersistence 单例"""
    global _persistence
    if _persistence is None:
        _persistence = get_task_persistence()
    return _persistence


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────


class GradeRequest(BaseModel):
    """任务难度分级请求"""

    description: str = Field(..., description="任务描述文本", min_length=1)


class GradeResponse(BaseModel):
    """任务难度分级响应"""

    level: str = Field(..., description="难度级别: LIGHT/MEDIUM/HEAVY")
    max_steps: int = Field(..., description="最大执行步数")
    temperature: float = Field(..., description="推理温度")
    max_tokens: int = Field(..., description="最大输出 token 数")
    reasoning_depth: str = Field(..., description="推理深度: fast/standard/deep")
    description: str = Field(default="", description="级别描述")
    score: int = Field(default=0, description="复杂度评分 0-100")
    detected_types: list[str] = Field(default_factory=list, description="检测到的任务类型")


class SaveTaskRequest(BaseModel):
    """保存任务请求"""

    task_id: str | None = Field(default=None, description="任务 ID，不传则自动生成")
    description: str = Field(..., description="任务描述", min_length=1)
    status: str = Field(default="pending", description="任务状态")
    grade: str = Field(default="MEDIUM", description="难度级别")
    steps_completed: int = Field(default=0, description="已完成步骤数")
    current_step: str = Field(default="", description="当前步骤描述")
    checkpoint_data: dict[str, Any] = Field(default_factory=dict, description="断点数据")
    result: dict[str, Any] = Field(default_factory=dict, description="执行结果")
    error: str = Field(default="", description="错误信息")


class SaveTaskResponse(BaseModel):
    """保存任务响应"""

    task_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态")
    grade: str = Field(..., description="难度级别")
    updated_at: float = Field(..., description="更新时间戳")


class TaskDetailResponse(BaseModel):
    """任务详情响应"""

    task_id: str = Field(..., description="任务 ID")
    description: str = Field(default="", description="任务描述")
    status: str = Field(default="pending", description="任务状态")
    grade: str = Field(default="MEDIUM", description="难度级别")
    created_at: float = Field(default=0.0, description="创建时间戳")
    updated_at: float = Field(default=0.0, description="更新时间戳")
    completed_at: float | None = Field(default=None, description="完成时间戳")
    steps_completed: int = Field(default=0, description="已完成步骤数")
    current_step: str = Field(default="", description="当前步骤描述")
    checkpoint_data: dict[str, Any] = Field(default_factory=dict, description="断点数据")
    result: dict[str, Any] = Field(default_factory=dict, description="执行结果")
    error: str = Field(default="", description="错误信息")


class TaskListResponse(BaseModel):
    """任务列表响应"""

    tasks: list[TaskDetailResponse] = Field(default_factory=list, description="任务列表")
    total: int = Field(default=0, description="当前返回数量")
    limit: int = Field(default=50, description="分页大小")
    offset: int = Field(default=0, description="分页偏移")


class CheckpointRequest(BaseModel):
    """创建断点请求"""

    data: dict[str, Any] = Field(..., description="断点数据（上下文、中间结果等）")
    current_step: str = Field(default="", description="当前步骤描述")


class TaskStatsResponse(BaseModel):
    """任务统计响应"""

    total: int = Field(default=0, description="总任务数")
    by_status: dict[str, int] = Field(default_factory=dict, description="各状态任务数")
    by_grade: dict[str, int] = Field(default_factory=dict, description="各级别任务数")
    avg_steps_completed: float = Field(default=0.0, description="平均完成步骤数")
    db_path: str = Field(default="", description="数据库路径")


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────


def _task_to_detail(task: TaskState) -> TaskDetailResponse:
    """将 TaskState 转换为响应模型"""
    return TaskDetailResponse(
        task_id=task.task_id,
        description=task.description,
        status=task.status,
        grade=task.grade,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        steps_completed=task.steps_completed,
        current_step=task.current_step,
        checkpoint_data=task.checkpoint_data,
        result=task.result,
        error=task.error,
    )


def _validate_status(status: str) -> None:
    """验证任务状态是否有效"""
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"无效状态: {status}，有效值为 {', '.join(sorted(VALID_STATUSES))}",
        )


def _validate_grade(grade: str) -> None:
    """验证难度级别是否有效"""
    if grade not in VALID_GRADES:
        raise HTTPException(
            status_code=400,
            detail=f"无效级别: {grade}，有效值为 {', '.join(sorted(VALID_GRADES))}",
        )


# ──────────────────────────────────────────────
# 端点实现
# ──────────────────────────────────────────────


@router.post("/grade", response_model=GradeResponse)
async def grade_task(req: GradeRequest) -> GradeResponse:
    """
    评估任务难度

    根据任务描述文本自动分析复杂度，返回 LIGHT/MEDIUM/HEAVY 三级分级
    和推荐执行参数（温度、最大步数、token 数等）。
    """
    grader = _get_grader()
    grade: TaskGrade = grader.grade(req.description)

    logger.info(
        "任务分级: 描述长度=%d → 级别=%s 评分=%d 类型=%s",
        len(req.description),
        grade.level,
        grade.score,
        grade.detected_types,
    )

    return GradeResponse(
        level=grade.level,
        max_steps=grade.max_steps,
        temperature=grade.temperature,
        max_tokens=grade.max_tokens,
        reasoning_depth=grade.reasoning_depth,
        description=grade.description,
        score=grade.score,
        detected_types=grade.detected_types,
    )


@router.post("/save", response_model=SaveTaskResponse)
async def save_task(req: SaveTaskRequest) -> SaveTaskResponse:
    """
    保存任务状态

    创建或更新任务。如果 task_id 不存在则自动生成并新建，
    如果已存在则更新字段。支持持久化到 SQLite 数据库。
    """
    _validate_status(req.status)
    _validate_grade(req.grade)

    persistence = _get_persistence()

    task_id = req.task_id or str(uuid.uuid4())
    task = TaskState(
        task_id=task_id,
        description=req.description,
        status=req.status,
        grade=req.grade,
        steps_completed=req.steps_completed,
        current_step=req.current_step,
        checkpoint_data=req.checkpoint_data,
        result=req.result,
        error=req.error,
    )

    saved = await persistence.save_task(task)
    logger.info("任务已保存: task_id=%s status=%s grade=%s", task_id, saved.status, saved.grade)

    return SaveTaskResponse(
        task_id=saved.task_id,
        status=saved.status,
        grade=saved.grade,
        updated_at=saved.updated_at,
    )


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def load_task(task_id: str) -> TaskDetailResponse:
    """
    加载任务详情

    根据 task_id 从数据库加载完整的任务状态信息。
    """
    persistence = _get_persistence()
    task = await persistence.load_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return _task_to_detail(task)


@router.get("/list", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = Query(default=None, description="按状态过滤"),
    grade: str | None = Query(default=None, description="按难度级别过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="分页大小"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
) -> TaskListResponse:
    """
    列出任务

    支持按状态和难度级别过滤，按更新时间倒序排列，支持分页。
    """
    if status is not None:
        _validate_status(status)
    if grade is not None:
        _validate_grade(grade)

    persistence = _get_persistence()
    tasks = await persistence.list_tasks(
        status_filter=status,
        grade_filter=grade,
        limit=limit,
        offset=offset,
    )

    logger.info(
        "列出任务: %d 条 (status=%s grade=%s limit=%d offset=%d)",
        len(tasks),
        status or "全部",
        grade or "全部",
        limit,
        offset,
    )

    return TaskListResponse(
        tasks=[_task_to_detail(t) for t in tasks],
        total=len(tasks),
        limit=limit,
        offset=offset,
    )


@router.post("/{task_id}/checkpoint", response_model=TaskDetailResponse)
async def create_checkpoint(task_id: str, req: CheckpointRequest) -> TaskDetailResponse:
    """
    创建任务断点

    保存当前任务状态和中间数据，将任务状态设为 paused，
    支持后续从断点恢复继续执行。
    """
    persistence = _get_persistence()
    task = await persistence.create_checkpoint(
        task_id=task_id,
        data=req.data,
        current_step=req.current_step,
    )

    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    logger.info("断点已创建: task_id=%s step=%s", task_id, req.current_step)
    return _task_to_detail(task)


@router.post("/{task_id}/resume", response_model=TaskDetailResponse)
async def resume_task(task_id: str) -> TaskDetailResponse:
    """
    从断点恢复任务

    将任务状态从 paused 恢复为 running，返回断点数据供继续执行。
    """
    persistence = _get_persistence()
    task = await persistence.resume_from_checkpoint(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"无法恢复任务: {task_id}，任务不存在或无断点数据",
        )

    logger.info(
        "任务已恢复: task_id=%s step=%s completed=%d",
        task_id,
        task.current_step,
        task.steps_completed,
    )
    return _task_to_detail(task)


@router.get("/stats", response_model=TaskStatsResponse)
async def get_task_stats() -> TaskStatsResponse:
    """
    获取任务统计信息

    返回总任务数、各状态/级别分布、平均完成步骤数等统计。
    """
    persistence = _get_persistence()
    stats = await persistence.get_stats_async()

    logger.info("任务统计查询: total=%d", stats.get("total", 0))

    return TaskStatsResponse(
        total=stats.get("total", 0),
        by_status=stats.get("by_status", {}),
        by_grade=stats.get("by_grade", {}),
        avg_steps_completed=stats.get("avg_steps_completed", 0.0),
        db_path=stats.get("db_path", ""),
    )