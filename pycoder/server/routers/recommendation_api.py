"""
Task 3 Phase 3: 推荐系统 REST API

端点:
- GET /api/recommendations/for-me (个性化推荐)
- GET /api/recommendations/trending (热门技能)
- POST /api/recommendations/track-behavior (追踪行为)
- GET /api/recommendations/similar/{skill_id} (相似技能)
"""

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


def _get_user_id(x_user_id: str | None = Header(None)) -> str:
    """从请求头或会话获取用户ID

    优先级: X-User-Id Header > session_id 派生 > 回退到 demo
    """
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    # 回退: 环境变量或 demo
    return os.environ.get("PYCODER_USER_ID", "demo-user-001")


# ─────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────


class TrackBehaviorRequest(BaseModel):
    """追踪行为请求"""

    skill_id: str
    action: str  # view | click | search | rate | share
    action_metadata: dict[str, Any] | None = None


class RecommendationResponse(BaseModel):
    """推荐响应"""

    success: bool
    recommendations: list[dict[str, Any]] = []
    error: str | None = None


class TrendingResponse(BaseModel):
    """热门技能响应"""

    success: bool
    skills: list[dict[str, Any]] = []
    period_days: int = 7


# ─────────────────────────────────────────────────────────
# 端点实现
# ─────────────────────────────────────────────────────────


@router.get("/for-me", response_model=RecommendationResponse)
async def get_personalized_recommendations(
    limit: int = Query(15, ge=1, le=50),
    category: str | None = None,
    user_id: str = Depends(_get_user_id),
):
    """为当前用户获取个性化推荐"""
    try:
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(None)
        recommendations = await engine.get_personalized_recommendations(user_id, limit=limit)

        return RecommendationResponse(success=True, recommendations=recommendations)
    except Exception as e:
        logger.error(f"获取个性化推荐失败: {e}")
        return RecommendationResponse(success=False, error=str(e))


@router.get("/trending", response_model=TrendingResponse)
async def get_trending_skills(
    period_days: int = Query(7, ge=1, le=30),
    limit: int = Query(10, ge=1, le=50),
    category: str | None = None,
):
    """获取热门技能"""
    try:
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(None)
        trending = await engine.get_trending_skills(
            period_days=period_days, category=category, limit=limit
        )

        return TrendingResponse(success=True, skills=trending, period_days=period_days)
    except Exception as e:
        logger.error(f"获取热门技能失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/track-behavior")
async def track_user_behavior(
    request: TrackBehaviorRequest,
    user_id: str = Depends(_get_user_id),
):
    """追踪用户行为"""
    try:
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(None)
        result = await engine.track_user_behavior(
            user_id=user_id,
            skill_id=request.skill_id,
            action=request.action,
            metadata=request.action_metadata,
        )

        return result
    except Exception as e:
        logger.error(f"追踪行为失败: {e}")
        return {"success": False, "error": str(e)}


@router.get("/similar/{skill_id}")
async def get_similar_skills(
    skill_id: str,
    limit: int = Query(10, ge=1, le=50),
):
    """获取相似技能"""
    try:
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(None)
        similar = await engine.get_similar_skills(skill_id=skill_id, limit=limit)

        return {"success": True, "skill_id": skill_id, "similar_skills": similar}
    except Exception as e:
        logger.error(f"获取相似技能失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats")
async def get_recommendation_stats():
    """获取推荐统计"""
    try:
        import os

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from pycoder.server.models.behavior_models import BehaviorLog, UserBehavior

        db_path = os.path.expanduser("~/.pycoder/pycoder.db")
        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        total_users = db.query(UserBehavior).count()
        total_behaviors = db.query(BehaviorLog).count()
        db.close()

        return {
            "success": True,
            "stats": {
                "total_users": total_users,
                "total_behaviors": total_behaviors,
                "database": str(db_path),
            },
        }
    except Exception as e:
        logger.error(f"获取推荐统计失败: {e}")
        return {"success": False, "error": str(e)}
