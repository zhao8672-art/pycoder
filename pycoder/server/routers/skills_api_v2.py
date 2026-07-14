"""
🚀 Skills Market API v2 路由 — 高级搜索、推荐、评分接口

路由前缀: /api/skills/v2
支持: REST API + WebSocket 推送

示例:
  GET /api/skills/v2/search?query=test&sort_by=quality
  GET /api/skills/v2/recommendations?category=code&limit=10
  GET /api/skills/v2/trending?limit=20
  GET /api/skills/v2/{skill_id}
  POST /api/skills/v2/{skill_id}/rate {"rating": 5, "review": "..."}
  GET /api/skills/v2/stats
  POST /api/skills/v2/sync (异步)
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from pycoder.server.log import log

# ═══════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════


class SkillSearchRequest(BaseModel):
    """搜索请求"""

    query: str = Field(default="", description="搜索关键词")
    category: str = Field(default="", description="分类筛选")
    tags: list[str] = Field(default_factory=list, description="标签筛选")
    sort_by: str = Field(
        default="quality", description="排序方式: quality/stars/downloads/rating/name"
    )
    limit: int = Field(default=20, ge=1, le=100, description="返回数量")
    offset: int = Field(default=0, ge=0, description="分页偏移")


class SkillRateRequest(BaseModel):
    """评分请求"""

    rating: int = Field(ge=1, le=5, description="评分 1-5")
    review: str = Field(default="", description="评论文本")


class SkillSearchResponse(BaseModel):
    """搜索响应"""

    success: bool
    query: str
    total: int
    results: list
    sort_by: str
    offset: int
    limit: int


class SkillDetailResponse(BaseModel):
    """技能详情响应"""

    success: bool
    skill: dict | None = None
    error: str | None = None


class SkillRateResponse(BaseModel):
    """评分响应"""

    success: bool
    skill_id: str
    rating: int
    review: str
    message: str


class SkillStatsResponse(BaseModel):
    """统计响应"""

    success: bool
    stats: dict


# ═══════════════════════════════════════════════════════════
# 创建路由器
# ═══════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/skills/v2", tags=["Skills Market v2"])


# ─────────────────────────────────────────────────────────
# 搜索接口
# ─────────────────────────────────────────────────────────


@router.get(
    "/search",
    response_model=SkillSearchResponse,
    summary="🔍 高级搜索技能",
    description="支持关键词、分类、标签、排序、分页的高级搜索",
)
async def search_skills(
    query: str = Query(default="", description="搜索关键词"),
    category: str = Query(default="", description="分类筛选"),
    tags: str = Query(default="", description="标签列表，逗号分隔"),
    sort_by: str = Query(
        default="quality", pattern="^(quality|stars|downloads|rating|name)$", description="排序方式"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """
    高级搜索技能市场

    Args:
        query: 搜索关键词 (支持中英文)
        category: 按分类筛选
        tags: 标签列表 (逗号分隔)
        sort_by: 排序方式 (quality/stars/downloads/rating/name)
        limit: 返回数量 (1-100)
        offset: 分页偏移

    Returns:
        搜索结果和元数据
    """
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        results = market.search(
            query=query,
            category=category,
            tags=tag_list,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

        return {
            "success": True,
            "query": query,
            "total": results.get("total", 0),
            "results": results.get("skills", []),
            "sort_by": sort_by,
            "offset": offset,
            "limit": limit,
        }
    except Exception as e:
        log.error("skills_search_error", error=str(e))
        return {
            "success": False,
            "query": query,
            "total": 0,
            "results": [],
            "sort_by": sort_by,
            "offset": offset,
            "limit": limit,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────
# 推荐接口
# ─────────────────────────────────────────────────────────


@router.get(
    "/recommendations",
    summary="⭐ 获取推荐",
    description="基于质量评分的智能推荐",
)
async def get_recommendations(
    category: str = Query(default="", description="限定分类"),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    """获取推荐技能列表"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()
        recommendations = market.get_recommendations(category=category or None, limit=limit)
        return {
            "success": True,
            "recommendations": recommendations,
            "category": category or "(all)",
            "count": len(recommendations),
        }
    except Exception as e:
        log.error("skills_recommendations_error", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "recommendations": [],
            "count": 0,
        }


# ─────────────────────────────────────────────────────────
# 热门排行
# ─────────────────────────────────────────────────────────


@router.get(
    "/trending",
    summary="🔥 热门排行",
    description="实时热门技能榜单",
)
async def get_trending(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """获取热门技能排行"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()
        trending = market.get_trending(limit=limit)
        return {
            "success": True,
            "trending": trending,
            "count": len(trending),
        }
    except Exception as e:
        log.error("skills_trending_error", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "trending": [],
            "count": 0,
        }


# ─────────────────────────────────────────────────────────
# 技能详情
# ─────────────────────────────────────────────────────────


@router.get(
    "/{skill_id}",
    summary="📖 技能详情",
    description="获取技能的完整信息和评分",
)
async def get_skill_detail(
    skill_id: str = PathParam(description="技能 ID"),
) -> dict:
    """获取单个技能的详细信息"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()
        detail = market.get_skill_detail(skill_id)

        if detail:
            return {
                "success": True,
                "skill": detail,
            }
        else:
            return {
                "success": False,
                "error": f"技能不存在: {skill_id}",
            }
    except Exception as e:
        log.error("skills_detail_error", skill_id=skill_id, error=str(e))
        return {
            "success": False,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────
# 评分
# ─────────────────────────────────────────────────────────


@router.post(
    "/{skill_id}/rate",
    summary="⭐ 评分技能",
    description="提交对技能的评分和评论",
)
async def rate_skill(
    skill_id: str = PathParam(description="技能 ID"),
    payload: SkillRateRequest = Body(...),
) -> dict:
    """评分一个技能"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    if not 1 <= payload.rating <= 5:
        return {
            "success": False,
            "error": "评分必须在 1-5 之间",
        }

    try:
        market = get_enhanced_market()
        market.rate_skill(skill_id, payload.rating, payload.review)

        return {
            "success": True,
            "skill_id": skill_id,
            "rating": payload.rating,
            "review": payload.review,
            "message": f"✓ 评分成功: {skill_id} = {payload.rating}⭐",
        }
    except Exception as e:
        log.error("skills_rate_error", skill_id=skill_id, error=str(e))
        return {
            "success": False,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────
# 统计
# ─────────────────────────────────────────────────────────


@router.get(
    "/stats/overview",
    summary="📊 统计仪表板",
    description="获取 Skills Market 的统计数据",
)
async def get_stats() -> dict:
    """获取市场统计信息"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()
        stats = market.get_stats()
        return {
            "success": True,
            "stats": stats,
        }
    except Exception as e:
        log.error("skills_stats_error", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "stats": {},
        }


# ─────────────────────────────────────────────────────────
# 分类列表
# ─────────────────────────────────────────────────────────


@router.get(
    "/categories/list",
    summary="🏷️ 分类列表",
    description="获取所有可用的技能分类",
)
async def get_categories() -> dict:
    """获取分类列表"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()
        categories = market.get_categories()
        return {
            "success": True,
            "categories": categories,
            "count": len(categories),
        }
    except Exception as e:
        log.error("skills_categories_error", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "categories": [],
            "count": 0,
        }


# ─────────────────────────────────────────────────────────
# 数据同步（异步）
# ─────────────────────────────────────────────────────────


@router.post(
    "/sync",
    summary="🔄 同步数据",
    description="从所有源同步最新技能数据（异步操作）",
)
async def sync_skills() -> dict:
    """
    触发异步数据同步

    Returns:
        {success, total_skills, sources, ...}

    Note:
        这是一个异步操作，可能需要 10-30 秒完成。
        返回 success=true 表示同步已启动，不是已完成。
    """
    from pycoder.server.skills_market_v2 import get_enhanced_market

    try:
        market = get_enhanced_market()

        # 异步执行，不阻塞
        async def sync_background():
            try:
                return await market.sync_from_all_sources()
            except Exception as e:
                log.error("skills_sync_background_error", error=str(e))
                return {"success": False, "error": str(e)}

        # 不等待完成
        asyncio.create_task(sync_background())

        return {
            "success": True,
            "message": "✓ 数据同步已启动 (异步操作，通常需要 10-30 秒)",
            "status": "syncing",
        }
    except Exception as e:
        log.error("skills_sync_error", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "status": "failed",
        }


# ═══════════════════════════════════════════════════════════
# 导出路由
# ═══════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────
# 同步状态
# ─────────────────────────────────────────────────────────


@router.get(
    "/sync/status",
    summary="📡 同步状态",
    description="获取 Skills 数据同步的实时状态",
)
async def get_sync_status() -> dict:
    """获取自动同步状态"""
    from pycoder.server.skills_updater_v2 import get_enhanced_fetcher

    try:
        fetcher = get_enhanced_fetcher()
        status = fetcher.sync_status()
        return {"success": True, "status": status}
    except (OSError, ValueError, KeyError, RuntimeError, TypeError) as e:
        return {"success": False, "error": str(e)}


@router.post(
    "/sync/auto",
    summary="🔄 自动同步控制",
    description="启动或停止 Skills 数据定期自动同步",
)
async def control_auto_sync(payload: dict = Body(...)) -> dict:
    """
    控制自动同步

    Body:
        action: "start" | "stop"
        interval: 同步间隔（小时），默认 24
    """
    from pycoder.server.skills_updater_v2 import get_enhanced_fetcher

    action = payload.get("action", "status")
    fetcher = get_enhanced_fetcher()

    if action == "start":
        interval_hours = float(payload.get("interval", 24))
        interval_seconds = interval_hours * 3600
        await fetcher.start_auto_sync(interval=interval_seconds)
        return {
            "success": True,
            "message": f"自动同步已启动，间隔 {interval_hours} 小时",
            "status": fetcher.sync_status(),
        }
    elif action == "stop":
        fetcher.stop_auto_sync()
        return {
            "success": True,
            "message": "自动同步已停止",
            "status": fetcher.sync_status(),
        }
    else:
        return {
            "success": True,
            "action": "status",
            "status": fetcher.sync_status(),
        }


__all__ = ["router"]
