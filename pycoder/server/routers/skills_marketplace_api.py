"""
技能市场 API 路由 — 技能发现、安装、评分和统计接口

路由前缀: /api/skills
支持: 技能列表、搜索、详情、安装/卸载、评分、市场统计

示例:
  GET  /api/skills/list?category=code&sort_by=rating&limit=20
  GET  /api/skills/search?q=test&category=code&tags=unit,testing
  GET  /api/skills/code-review
  POST /api/skills/install  {"skill_id": "code-review"}
  POST /api/skills/uninstall  {"skill_id": "code-review"}
  POST /api/skills/rate  {"skill_id": "code-review", "rating": 5}
  GET  /api/skills/stats
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.server.log import log
from pycoder.skills import SkillMarketplace

# ═══════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════


class SkillInstallRequest(BaseModel):
    """技能安装/卸载请求"""

    skill_id: str = Field(..., description="技能 ID")


class SkillRateRequest(BaseModel):
    """技能评分请求"""

    skill_id: str = Field(..., description="技能 ID")
    rating: int = Field(ge=1, le=5, description="评分 1-5")


class SkillListResponse(BaseModel):
    """技能列表响应"""

    success: bool
    skills: list[dict]
    total: int
    category: str = ""
    sort_by: str = ""


class SkillSearchResponse(BaseModel):
    """技能搜索响应"""

    success: bool
    query: str
    skills: list[dict]
    total: int
    category: str = ""
    tags: list[str] = []


class SkillDetailResponse(BaseModel):
    """技能详情响应"""

    success: bool
    skill: dict | None = None
    error: str | None = None


class SkillActionResponse(BaseModel):
    """技能操作响应（安装/卸载/评分）"""

    success: bool
    skill_id: str
    action: str = ""
    message: str = ""
    error: str | None = None


class SkillInstallResultResponse(BaseModel):
    """技能安装结果响应"""

    success: bool
    skill_id: str
    name: str = ""
    installed_at: str = ""
    action: str = ""
    error: str | None = None


class SkillStatsResponse(BaseModel):
    """市场统计响应"""

    success: bool
    stats: dict | None = None
    error: str | None = None


# ═══════════════════════════════════════════════════════════
# 创建路由器
# ═══════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/skills", tags=["skills"])

# ── 全局技能市场单例 ───────────────────────────────


def _get_marketplace() -> SkillMarketplace:
    """获取技能市场单例"""
    return SkillMarketplace()


# ─────────────────────────────────────────────────────────
# 列出技能
# ─────────────────────────────────────────────────────────


@router.get(
    "/list",
    response_model=SkillListResponse,
    summary="📋 列出技能",
    description="列出技能市场中的技能，支持分类过滤和排序",
)
async def list_skills(
    category: str = Query(default="", description="分类筛选"),
    sort_by: str = Query(
        default="rating",
        pattern="^(rating|install_count|name|updated_at)$",
        description="排序方式: rating/install_count/name/updated_at",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="最大返回数量"),
) -> dict:
    """
    列出技能市场中的技能

    Args:
        category: 按分类过滤
        sort_by: 排序字段
        limit: 最大返回数量（1-200）

    Returns:
        技能列表和元数据
    """
    marketplace = _get_marketplace()

    try:
        result = await marketplace.list_skills(
            category=category,
            sort_by=sort_by,
            limit=limit,
        )
        return {
            "success": True,
            "skills": result.get("skills", []),
            "total": result.get("total", 0),
            "category": category,
            "sort_by": sort_by,
        }
    except Exception as e:
        log.error("skills_list_error", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"获取技能列表失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 搜索技能
# ─────────────────────────────────────────────────────────


@router.get(
    "/search",
    response_model=SkillSearchResponse,
    summary="🔍 搜索技能",
    description="按关键词、分类和标签搜索技能",
)
async def search_skills(
    q: str = Query(default="", description="搜索关键词"),
    category: str = Query(default="", description="分类筛选"),
    tags: str = Query(default="", description="标签筛选，逗号分隔"),
) -> dict:
    """
    搜索技能市场

    Args:
        q: 搜索关键词（匹配名称和描述）
        category: 按分类过滤
        tags: 标签列表（逗号分隔）

    Returns:
        搜索结果
    """
    marketplace = _get_marketplace()

    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        result = await marketplace.search_skills(
            query=q,
            category=category,
            tags=tag_list if tag_list else None,
        )
        return {
            "success": True,
            "query": q,
            "skills": result.get("skills", []),
            "total": result.get("total", 0),
            "category": category,
            "tags": tag_list,
        }
    except Exception as e:
        log.error("skills_search_error", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"搜索技能失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 技能详情
# ─────────────────────────────────────────────────────────


@router.get(
    "/{skill_id}",
    response_model=SkillDetailResponse,
    summary="📖 技能详情",
    description="获取指定技能的完整信息，包括 Markdown 内容和评分",
)
async def get_skill_detail(
    skill_id: str,
) -> dict:
    """
    获取技能详情

    Args:
        skill_id: 技能 ID

    Returns:
        技能详情或错误信息
    """
    marketplace = _get_marketplace()

    try:
        result = await marketplace.get_skill(skill_id)

        if "error" in result:
            return {
                "success": False,
                "skill": None,
                "error": result["error"],
            }

        return {
            "success": True,
            "skill": result.get("skill"),
        }
    except Exception as e:
        log.error("skills_detail_error", skill_id=skill_id, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"获取技能详情失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 安装技能
# ─────────────────────────────────────────────────────────


@router.post(
    "/install",
    response_model=SkillInstallResultResponse,
    summary="📥 安装技能",
    description="安装指定的技能到本地",
)
async def install_skill(
    payload: SkillInstallRequest = Body(...),
) -> dict:
    """
    安装技能

    Args:
        payload: 包含 skill_id 的请求体

    Returns:
        安装结果
    """
    marketplace = _get_marketplace()

    try:
        result = await marketplace.install_skill(payload.skill_id)
        return result
    except Exception as e:
        log.error("skills_install_error", skill_id=payload.skill_id, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"安装技能失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 卸载技能
# ─────────────────────────────────────────────────────────


@router.post(
    "/uninstall",
    response_model=SkillActionResponse,
    summary="📤 卸载技能",
    description="卸载指定的已安装技能",
)
async def uninstall_skill(
    payload: SkillInstallRequest = Body(...),
) -> dict:
    """
    卸载技能（内置技能不可卸载）

    Args:
        payload: 包含 skill_id 的请求体

    Returns:
        卸载结果
    """
    marketplace = _get_marketplace()

    try:
        result = await marketplace.uninstall_skill(payload.skill_id)
        return result
    except Exception as e:
        log.error("skills_uninstall_error", skill_id=payload.skill_id, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"卸载技能失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 评分技能
# ─────────────────────────────────────────────────────────


@router.post(
    "/rate",
    response_model=SkillActionResponse,
    summary="⭐ 评分技能",
    description="为指定技能提交评分（1-5 分）",
)
async def rate_skill(
    payload: SkillRateRequest = Body(...),
) -> dict:
    """
    评分技能

    Args:
        payload: 包含 skill_id 和 rating 的请求体

    Returns:
        评分结果
    """
    marketplace = _get_marketplace()

    try:
        result = await marketplace.rate_skill(
            skill_id=payload.skill_id,
            rating=payload.rating,
        )
        return result
    except Exception as e:
        log.error("skills_rate_error", skill_id=payload.skill_id, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"评分技能失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 市场统计
# ─────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=SkillStatsResponse,
    summary="📊 市场统计",
    description="获取技能市场的统计信息，包括技能总数、安装数、评分等",
)
async def get_stats() -> dict:
    """
    获取市场统计信息

    Returns:
        统计数据：技能总数、已安装数、平均评分、分类分布等
    """
    marketplace = _get_marketplace()

    try:
        stats = marketplace.get_stats()
        return {
            "success": True,
            "stats": stats,
        }
    except Exception as e:
        log.error("skills_stats_error", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"获取市场统计失败: {e}"
        ) from e


__all__ = ["router"]