"""
✅ Task 3 Phase 2: 推荐引擎核心实现

算法:
1. 内容推荐 (Content-Based): 基于技能属性相似度
2. 协同过滤 (Collaborative Filtering): 基于用户相似性
3. 热度推荐 (Trending): 基于评分和浏览量
4. 个性化推荐 (Personalized): 组合多个来源
"""

import logging
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """推荐引擎 - 综合多种算法"""

    def __init__(self, db_session):
        self.db = db_session
        self._own_engine = None
        self._own_session = None
        if self.db is None:
            self._init_own_db()

    def _init_own_db(self):
        """当外部未传入 db session 时，自动创建 SQLite 连接"""
        try:
            import os as _os

            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            db_path = _os.path.expanduser("~/.pycoder/pycoder.db")
            self._own_engine = create_engine(f"sqlite:///{db_path}")
            SessionLocal = sessionmaker(bind=self._own_engine)
            self._own_session = SessionLocal()
            self.db = self._own_session
            from pycoder.server.models.behavior_models import Base

            Base.metadata.create_all(self._own_engine)
        except Exception as e:
            logger.warning("rec_engine_self_db_init_failed: %s", e)

    # ─────────────────────────────────────────────────────
    # 1. 内容推荐 (Content-Based)
    # ─────────────────────────────────────────────────────

    async def get_similar_skills(self, skill_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取相似的技能 (基于标签和类别)"""
        from pycoder.server.models.behavior_models import SkillSimilarity

        try:
            similarities = (
                self.db.query(SkillSimilarity)
                .filter(
                    (SkillSimilarity.skill_id_a == skill_id)
                    | (SkillSimilarity.skill_id_b == skill_id)
                )
                .order_by(SkillSimilarity.similarity_score.desc())
                .limit(limit)
                .all()
            )

            results = []
            for sim in similarities:
                other_skill_id = sim.skill_id_b if sim.skill_id_a == skill_id else sim.skill_id_a
                results.append(
                    {
                        "skill_id": other_skill_id,
                        "similarity": sim.similarity_score,
                        "reason": sim.reason,
                    }
                )

            logger.info(f"找到 {len(results)} 个相似技能: {skill_id}")
            return results
        except Exception as e:
            logger.error(f"获取相似技能失败: {e}")
            return []

    # ─────────────────────────────────────────────────────
    # 2. 协同过滤 (Collaborative Filtering)
    # ─────────────────────────────────────────────────────

    async def find_similar_users(self, user_id: str, limit: int = 5) -> list[tuple[str, float]]:
        """找出相似的用户 (基于评分历史)"""
        from pycoder.server.models.cloud_models import SkillRating

        try:
            # 获取当前用户的评分
            user_ratings = self.db.query(SkillRating).filter(SkillRating.user_id == user_id).all()

            if not user_ratings:
                return []

            user_skill_ratings = {r.skill_id: r.rating for r in user_ratings}

            # 计算其他用户的相似度
            similarity_scores = defaultdict(float)
            all_other_ratings = (
                self.db.query(SkillRating).filter(SkillRating.user_id != user_id).all()
            )

            # 按用户分组
            other_users = defaultdict(dict)
            for rating in all_other_ratings:
                other_users[rating.user_id][rating.skill_id] = rating.rating

            # 计算余弦相似度
            for other_user_id, other_ratings in other_users.items():
                common_skills = set(user_skill_ratings.keys()) & set(other_ratings.keys())

                if not common_skills:
                    continue

                # 余弦相似度
                dot_product = sum(
                    user_skill_ratings[skill] * other_ratings[skill] for skill in common_skills
                )
                norm_user = math.sqrt(sum(r**2 for r in user_skill_ratings.values()))
                norm_other = math.sqrt(sum(r**2 for r in other_ratings.values()))

                if norm_user > 0 and norm_other > 0:
                    similarity = dot_product / (norm_user * norm_other)
                    similarity_scores[other_user_id] = similarity

            # 返回最相似的用户
            similar_users = sorted(similarity_scores.items(), key=lambda x: x[1], reverse=True)[
                :limit
            ]

            logger.info(f"为用户 {user_id} 找到 {len(similar_users)} 个相似用户")
            return similar_users
        except Exception as e:
            logger.error(f"找相似用户失败: {e}")
            return []

    async def recommend_from_similar_users(
        self, user_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """从相似用户的评分推荐"""
        from pycoder.server.models.cloud_models import SkillRating

        try:
            similar_users = await self.find_similar_users(user_id, limit=5)
            if not similar_users:
                return []

            # 获取当前用户已评分的技能
            user_rated_skills = {
                r.skill_id
                for r in self.db.query(SkillRating).filter(SkillRating.user_id == user_id).all()
            }

            # 从相似用户收集推荐
            recommendations = defaultdict(float)
            for similar_user_id, similarity in similar_users:
                similar_user_ratings = (
                    self.db.query(SkillRating).filter(SkillRating.user_id == similar_user_id).all()
                )

                for rating in similar_user_ratings:
                    if rating.skill_id not in user_rated_skills:
                        # 权重: 相似度 × 评分
                        score = similarity * (rating.rating / 5.0)
                        recommendations[rating.skill_id] += score

            # 排序并返回
            results = [
                {"skill_id": skill_id, "score": score}
                for skill_id, score in sorted(
                    recommendations.items(), key=lambda x: x[1], reverse=True
                )[:limit]
            ]

            logger.info(f"从相似用户为 {user_id} 推荐 {len(results)} 个技能")
            return results
        except Exception as e:
            logger.error(f"协同过滤推荐失败: {e}")
            return []

    # ─────────────────────────────────────────────────────
    # 3. 热度推荐 (Trending)
    # ─────────────────────────────────────────────────────

    async def get_trending_skills(
        self, period_days: int = 7, category: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """获取热门技能"""
        from pycoder.server.models.behavior_models import BehaviorLog

        try:
            cutoff_time = datetime.now(UTC) - timedelta(days=period_days)

            # 统计最近评分和浏览
            logs = self.db.query(BehaviorLog).filter(BehaviorLog.timestamp >= cutoff_time).all()

            skill_scores = defaultdict(float)
            for log in logs:
                if log.action == "rate":
                    # 评分权重更高
                    rating = log.action_metadata.get("rating", 3)
                    skill_scores[log.skill_id] += rating * 2.0
                elif log.action == "view":
                    # 浏览权重较低
                    skill_scores[log.skill_id] += 1.0

            # 按分数排序
            trending = [
                {"skill_id": skill_id, "score": score}
                for skill_id, score in sorted(
                    skill_scores.items(), key=lambda x: x[1], reverse=True
                )[:limit]
            ]

            logger.info(f"获取过去 {period_days} 天的 {len(trending)} 个热门技能")
            return trending
        except Exception as e:
            logger.error(f"获取热门技能失败: {e}")
            # 降级: 从 skills_market_v2 获取热门
            try:
                from pycoder.server.skills_market_v2 import get_enhanced_market

                market = get_enhanced_market()
                fallback = market.get_trending(limit=limit)
                logger.info(f"trending_fallback_to_skills_market: count={len(fallback)}")
                return fallback
            except Exception as e2:
                logger.error(f"trending_fallback_failed: {e2}")
                return []

    # ─────────────────────────────────────────────────────
    # 4. 个性化推荐 (Personalized)
    # ─────────────────────────────────────────────────────

    async def get_personalized_recommendations(
        self, user_id: str, limit: int = 15
    ) -> list[dict[str, Any]]:
        """生成个性化推荐 (综合多个来源)"""
        from pycoder.server.models.behavior_models import UserBehavior

        try:
            # 获取用户偏好
            user_behavior = (
                self.db.query(UserBehavior).filter(UserBehavior.user_id == user_id).first()
            )

            if not user_behavior:
                logger.warning(f"用户 {user_id} 无行为记录")
                return []

            # 收集多个来源的推荐
            all_recommendations = {}

            # 1. 协同过滤 (50%)
            cf_recs = await self.recommend_from_similar_users(user_id, limit=20)
            for rec in cf_recs:
                all_recommendations[rec["skill_id"]] = (
                    all_recommendations.get(rec["skill_id"], 0) + rec["score"] * 0.5
                )

            # 2. 热度推荐 (30%)
            trending = await self.get_trending_skills(period_days=7, limit=20)
            for rec in trending:
                all_recommendations[rec["skill_id"]] = (
                    all_recommendations.get(rec["skill_id"], 0) + (rec["score"] / 100.0) * 0.3
                )

            # 3. 相似技能 (基于用户已评分的技能) (20%)
            from pycoder.server.models.cloud_models import SkillRating

            user_ratings = (
                self.db.query(SkillRating)
                .filter(SkillRating.user_id == user_id)
                .order_by(SkillRating.rating.desc())
                .limit(5)
                .all()
            )

            for user_rating in user_ratings:
                similar = await self.get_similar_skills(user_rating.skill_id, limit=5)
                for sim in similar:
                    all_recommendations[sim["skill_id"]] = (
                        all_recommendations.get(sim["skill_id"], 0) + sim["similarity"] * 0.2
                    )

            # 排序并返回
            results = [
                {"skill_id": skill_id, "score": score}
                for skill_id, score in sorted(
                    all_recommendations.items(), key=lambda x: x[1], reverse=True
                )[:limit]
            ]

            logger.info(f"为用户 {user_id} 生成 {len(results)} 个个性化推荐")
            return results
        except Exception as e:
            logger.error(f"生成个性化推荐失败: {e}")
            return []

    # ─────────────────────────────────────────────────────
    # 5. 行为追踪
    # ─────────────────────────────────────────────────────

    async def track_user_behavior(
        self, user_id: str, skill_id: str, action: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """追踪用户行为"""
        import uuid

        from pycoder.server.models.behavior_models import BehaviorLog, UserBehavior

        try:
            # 创建或更新用户行为记录
            user_behavior = (
                self.db.query(UserBehavior).filter(UserBehavior.user_id == user_id).first()
            )

            if not user_behavior:
                user_behavior = UserBehavior(id=str(uuid.uuid4()), user_id=user_id)
                self.db.add(user_behavior)
                self.db.flush()

            # 更新行为统计
            if action == "view":
                user_behavior.total_views += 1
            elif action == "click":
                user_behavior.total_clicks += 1
            elif action == "rate":
                user_behavior.total_ratings += 1
                if metadata and "rating" in metadata:
                    # 更新平均评分
                    avg = user_behavior.avg_rating_score
                    total = user_behavior.total_ratings
                    new_rating = metadata["rating"]
                    user_behavior.avg_rating_score = (avg * (total - 1) + new_rating) / total

            user_behavior.last_activity = datetime.now(UTC)

            # 记录行为日志
            behavior_log = BehaviorLog(
                id=str(uuid.uuid4()),
                user_behavior_id=user_behavior.id,
                skill_id=skill_id,
                action=action,
                action_metadata=metadata or {},
            )
            self.db.add(behavior_log)
            self.db.commit()

            logger.info(f"追踪行为: {user_id} 对 {skill_id} 的 {action}")
            return {"success": True, "action": action}
        except Exception as e:
            logger.error(f"追踪行为失败: {e}")
            self.db.rollback()
            return {"success": False, "error": str(e)}
