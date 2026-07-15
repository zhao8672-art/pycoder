"""
封闭学习循环 API — 观察→反思→生成→应用的完整闭环 REST 端点

端点列表:
  POST /api/learning/observe        — 观察执行，记录跟踪数据
  POST /api/learning/reflect        — 反思模式，分析成功/失败规律
  POST /api/learning/generate-skill — 生成技能，将模式编码为可复用技能
  POST /api/learning/apply          — 应用反馈，注入经验到新任务
  POST /api/learning/cycle          — 一键运行完整闭环
  GET  /api/learning/stats          — 获取学习统计
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.capabilities.self_evo.learning.closed_loop import (
    ClosedLearningLoop,
    get_closed_loop,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/learning", tags=["learning"])

# ──────────────────────────────────────────────
# 全局实例
# ──────────────────────────────────────────────

_loop: ClosedLearningLoop = get_closed_loop()


# ──────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────


class ObserveRequest(BaseModel):
    """观察执行请求体"""
    task_id: str = Field(..., description="任务唯一标识")
    execution_result: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "执行结果，可包含: description, success, steps, "
            "errors, patterns_used, patterns_failed, metadata"
        ),
    )


class ObserveResponse(BaseModel):
    """观察执行响应"""
    success: bool
    task_id: str | None = None
    recorded: bool = False
    steps: int = 0
    errors_count: int = 0
    error: str | None = None


class ReflectRequest(BaseModel):
    """反思模式请求体"""
    observation: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "学习观察对象，可包含: task_id, task_description, success, "
            "steps_taken, errors_encountered, patterns_used, patterns_failed"
        ),
    )


class ReflectResponse(BaseModel):
    """反思模式响应"""
    success: bool
    reflection: dict[str, Any] | None = None
    error: str | None = None


class GenerateSkillRequest(BaseModel):
    """生成技能请求体"""
    reflection: dict[str, Any] = Field(
        default_factory=dict,
        description="反思结果，包含 patterns_found 和 patterns_avoid",
    )


class GenerateSkillResponse(BaseModel):
    """生成技能响应"""
    success: bool
    skills_generated: int = 0
    skill_ids: list[str] = []
    skill_names: list[str] = []
    error: str | None = None


class ApplyFeedbackRequest(BaseModel):
    """应用反馈请求体"""
    task_description: str = Field(..., description="新任务描述")


class ApplyFeedbackResponse(BaseModel):
    """应用反馈响应"""
    success: bool
    feedback: dict[str, Any] | None = None
    error: str | None = None


class CycleRequest(BaseModel):
    """完整闭环请求体"""
    task_id: str = Field(..., description="任务唯一标识")
    execution_result: dict[str, Any] = Field(
        default_factory=dict,
        description="执行结果，同 observe 的 execution_result",
    )


class CycleResponse(BaseModel):
    """完整闭环响应"""
    task_id: str
    cycle_duration_ms: float
    observation: dict[str, Any]
    reflection: dict[str, Any]
    skills_generated: int
    new_skill_ids: list[str]
    feedback: dict[str, Any]
    refine: dict[str, Any]
    timestamp: float


class StatsResponse(BaseModel):
    """学习统计响应"""
    success: bool
    stats: dict[str, Any] | None = None
    error: str | None = None


# ──────────────────────────────────────────────
# 路由实现
# ──────────────────────────────────────────────


@router.post("/observe", response_model=ObserveResponse)
async def observe_execution(req: ObserveRequest) -> ObserveResponse:
    """观察执行 — 将任务执行结果记录为结构化观察数据

    记录每次任务执行的步骤、错误、使用的模式等，供后续反思分析使用。
    """
    if not req.task_id.strip():
        raise HTTPException(status_code=400, detail="task_id 不能为空")

    try:
        observation = await _loop.observe(req.task_id, req.execution_result)
        return ObserveResponse(
            success=True,
            task_id=observation.task_id,
            recorded=True,
            steps=observation.steps_taken,
            errors_count=len(observation.errors_encountered),
        )
    except Exception as e:
        logger.exception("观察记录失败: task_id=%s error=%s", req.task_id, e)
        raise HTTPException(status_code=500, detail=f"观察记录失败: {e}")


@router.post("/reflect", response_model=ReflectResponse)
async def reflect_patterns(req: ReflectRequest) -> ReflectResponse:
    """反思模式 — 分析观察数据中的成功/失败模式

    从观察中提取可学习的规律，识别应避免的失败模式。
    """
    if not req.observation:
        raise HTTPException(status_code=400, detail="observation 不能为空")

    task_id = req.observation.get("task_id", "unknown")
    try:
        from pycoder.capabilities.self_evo.learning.closed_loop import (
            LearningObservation,
        )

        observation = LearningObservation(
            task_id=str(task_id),
            task_description=str(req.observation.get("task_description", "")),
            success=bool(req.observation.get("success", False)),
            steps_taken=int(req.observation.get("steps_taken", 0)),
            errors_encountered=ClosedLearningLoop._ensure_list(
                req.observation.get("errors_encountered", [])
            ),
            patterns_used=ClosedLearningLoop._ensure_list(
                req.observation.get("patterns_used", [])
            ),
            patterns_failed=ClosedLearningLoop._ensure_list(
                req.observation.get("patterns_failed", [])
            ),
            metadata=req.observation.get("metadata", {}),
        )

        reflection = await _loop.reflect(observation)
        return ReflectResponse(success=True, reflection=reflection)
    except Exception as e:
        logger.exception("反思分析失败: task_id=%s error=%s", task_id, e)
        raise HTTPException(status_code=500, detail=f"反思分析失败: {e}")


@router.post("/generate-skill", response_model=GenerateSkillResponse)
async def generate_skill(req: GenerateSkillRequest) -> GenerateSkillResponse:
    """生成技能 — 将成功模式编码为可复用的技能

    从反思结果中提取高置信度模式，创建或更新技能条目。
    """
    if not req.reflection:
        raise HTTPException(status_code=400, detail="reflection 不能为空")

    try:
        skills = await _loop.generate_skill(req.reflection)
        return GenerateSkillResponse(
            success=True,
            skills_generated=len(skills),
            skill_ids=[s.id for s in skills],
            skill_names=[s.name for s in skills],
        )
    except Exception as e:
        logger.exception("技能生成失败: error=%s", e)
        raise HTTPException(status_code=500, detail=f"技能生成失败: {e}")


@router.post("/apply", response_model=ApplyFeedbackResponse)
async def apply_feedback(req: ApplyFeedbackRequest) -> ApplyFeedbackResponse:
    """应用反馈 — 将相关经验注入新任务上下文

    根据任务描述搜索匹配技能，生成增强上下文提示。
    """
    if not req.task_description.strip():
        raise HTTPException(status_code=400, detail="task_description 不能为空")

    try:
        feedback = await _loop.apply_feedback(req.task_description)
        return ApplyFeedbackResponse(success=True, feedback=feedback)
    except Exception as e:
        logger.exception("反馈应用失败: error=%s", e)
        raise HTTPException(status_code=500, detail=f"反馈应用失败: {e}")


@router.post("/cycle", response_model=CycleResponse)
async def run_learning_cycle(req: CycleRequest) -> CycleResponse:
    """运行完整闭环 — observe → reflect → generate → apply

    一键运行 Hermes 风格封闭学习循环的四个阶段。
    """
    if not req.task_id.strip():
        raise HTTPException(status_code=400, detail="task_id 不能为空")

    try:
        result = await _loop.run_cycle(req.task_id, req.execution_result)
        return CycleResponse(
            task_id=result["task_id"],
            cycle_duration_ms=result["cycle_duration_ms"],
            observation=result["observation"],
            reflection=result["reflection"],
            skills_generated=result["skills_generated"],
            new_skill_ids=result["new_skill_ids"],
            feedback=result["feedback"],
            refine=result["refine"],
            timestamp=result["timestamp"],
        )
    except Exception as e:
        logger.exception("闭环执行失败: task_id=%s error=%s", req.task_id, e)
        raise HTTPException(status_code=500, detail=f"闭环执行失败: {e}")


@router.get("/stats", response_model=StatsResponse)
async def get_learning_stats() -> StatsResponse:
    """获取学习统计 — 观察数、技能数、成功率等

    返回封闭学习循环的完整统计信息，包括历史趋势和热门错误。
    """
    try:
        stats = _loop.get_stats()
        return StatsResponse(success=True, stats=stats)
    except Exception as e:
        logger.exception("统计获取失败: error=%s", e)
        raise HTTPException(status_code=500, detail=f"统计获取失败: {e}")