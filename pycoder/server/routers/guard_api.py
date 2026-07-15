"""幻觉守卫 API — LLM 响应验证、溯源、事实核查、统计"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.server.services.hallucination_guard import HallucinationGuard, get_hallucination_guard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/guard", tags=["guard"])

# ── 请求模型 ──


class ValidateRequest(BaseModel):
    """LLM 响应验证请求"""

    response: str = Field(..., min_length=1, description="LLM 的原始响应文本")
    context: dict[str, Any] | None = Field(default=None, description="额外上下文信息")


class TraceRequest(BaseModel):
    """溯源请求"""

    response: str = Field(..., min_length=1, description="LLM 的原始响应文本")


class FactCheckRequest(BaseModel):
    """事实核查请求"""

    claims: list[dict[str, Any]] = Field(..., min_length=1, description="待验证的声明列表")


class ClaimItem(BaseModel):
    """单条声明"""

    text: str = Field(..., description="声明文本")
    claim_type: str = Field(default="fact", description="声明类型")
    source: str = Field(default="", description="来源描述")
    confidence: str = Field(default="low", description="置信度")


# ── 获取守卫实例 ──


def _get_guard() -> HallucinationGuard:
    """获取幻觉守卫实例"""
    return get_hallucination_guard()


# ── 路由 ──


@router.post("/validate")
async def validate_llm_response(req: ValidateRequest):
    """验证 LLM 响应

    执行三步验证管线（溯源 → 事实校验 → 一致性检查），返回综合评分与建议。
    """
    guard = _get_guard()
    try:
        result = await guard.validate(
            response=req.response,
            context=req.context,
        )
        return result.to_dict()
    except Exception as e:
        logger.exception("验证 LLM 响应异常")
        raise HTTPException(status_code=500, detail=f"验证异常: {e}") from e


@router.post("/trace")
async def trace_sources(req: TraceRequest):
    """溯源 LLM 响应中的声明

    从响应中提取文件、API、依赖、代码、统计、配置六类可追溯声明。
    """
    guard = _get_guard()
    try:
        result = await guard.trace_sources(
            response=req.response,
            context=None,
        )
        return result
    except Exception as e:
        logger.exception("溯源异常")
        raise HTTPException(status_code=500, detail=f"溯源异常: {e}") from e


@router.post("/fact-check")
async def fact_check_claims(req: FactCheckRequest):
    """事实核查声明列表

    对声明进行运行时验证（文件存在、模块导入、路由注册、依赖声明等）。
    """
    guard = _get_guard()
    try:
        result = await guard.fact_check(
            claims=req.claims,
            context=None,
        )
        return result
    except Exception as e:
        logger.exception("事实核查异常")
        raise HTTPException(status_code=500, detail=f"事实核查异常: {e}") from e


@router.get("/stats")
async def get_guard_stats():
    """获取幻觉守卫统计信息

    返回验证次数、幻觉检测数、平均评分等运行统计。
    """
    guard = _get_guard()
    try:
        result = await guard.get_stats()
        return result
    except Exception as e:
        logger.exception("获取统计异常")
        raise HTTPException(status_code=500, detail=f"获取统计异常: {e}") from e