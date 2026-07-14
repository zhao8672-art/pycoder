"""
✅ Task 3 Phase 1: 用户行为追踪模型 (SQLAlchemy ORM)

数据模型:
- UserBehavior: 用户行为汇总统计
- BehaviorLog: 单次行为记录 (视图、点击、评分、搜索)
- UserPreference: 用户偏好配置
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class UserBehavior(Base):
    """用户行为汇总统计"""

    __tablename__ = "user_behaviors"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), nullable=False, index=True)  # 关联到 User.id
    total_views = Column(Integer, default=0)  # 总浏览次数
    total_clicks = Column(Integer, default=0)  # 总点击次数
    total_ratings = Column(Integer, default=0)  # 总评分次数
    avg_rating_score = Column(Float, default=0.0)  # 平均评分分数

    # 偏好信息
    preferred_categories = Column(JSON, default=[])  # 偏好的类别列表 ["编辑", "调试", ...]
    preferred_difficulty = Column(String(20), default="medium")  # beginner/medium/advanced

    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    behavior_logs = relationship("BehaviorLog", back_populates="user_behavior")
    user_preference = relationship("UserPreference", uselist=False, back_populates="user_behavior")

    __table_args__ = (
        Index("idx_user_activity", "user_id", "last_activity"),
        UniqueConstraint("user_id", name="uq_user_behavior"),
    )


class BehaviorLog(Base):
    """单次行为记录"""

    __tablename__ = "behavior_logs"

    id = Column(String(36), primary_key=True)  # UUID
    user_behavior_id = Column(
        String(36), ForeignKey("user_behaviors.id"), nullable=False, index=True
    )
    skill_id = Column(String(100), nullable=False, index=True)

    # 行为类型: view (浏览) | click (点击) | search (搜索) | rate (评分) | share (分享)
    action = Column(String(20), nullable=False, index=True)

    # 行为元数据
    action_metadata = Column(JSON, default={})  # 如 rating=5, review="很好用"
    duration_seconds = Column(Integer, default=0)  # 页面停留时长

    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # 关系
    user_behavior = relationship("UserBehavior", back_populates="behavior_logs")

    __table_args__ = (
        Index("idx_skill_action_time", "skill_id", "action", "timestamp"),
        Index("idx_user_action_time", "user_behavior_id", "action", "timestamp"),
    )


class UserPreference(Base):
    """用户偏好配置"""

    __tablename__ = "user_preferences"

    id = Column(String(36), primary_key=True)  # UUID
    user_behavior_id = Column(
        String(36), ForeignKey("user_behaviors.id"), nullable=False, unique=True, index=True
    )

    # 难度偏好: beginner | intermediate | advanced | expert
    difficulty_level = Column(String(20), default="intermediate")

    # 类别权重 {"编辑": 0.8, "调试": 0.6, ...}
    category_weights = Column(JSON, default={})

    # 推荐倾向
    prefer_trending = Column(Integer, default=50)  # 0-100: 对热门技能的关注度
    prefer_new = Column(Integer, default=30)  # 0-100: 对新技能的关注度
    prefer_similar = Column(Integer, default=70)  # 0-100: 对相似技能的关注度

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user_behavior = relationship("UserBehavior", back_populates="user_preference")


class SkillSimilarity(Base):
    """技能相似度缓存 (用于协同过滤)"""

    __tablename__ = "skill_similarities"

    id = Column(String(36), primary_key=True)  # UUID
    skill_id_a = Column(String(100), nullable=False, index=True)
    skill_id_b = Column(String(100), nullable=False, index=True)

    # 相似度分数: 0-1
    similarity_score = Column(Float, nullable=False)

    # 相似度原因: content (内容相同) | category (类别相同) | tags (标签相同)
    reason = Column(String(50), default="content")

    computed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_skill_similarity", "skill_id_a", "skill_id_b"),
        UniqueConstraint("skill_id_a", "skill_id_b", name="uq_skill_pair"),
    )


class RecommendationCache(Base):
    """推荐结果缓存 (减少重复计算)"""

    __tablename__ = "recommendation_caches"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), nullable=False, index=True)  # 关联到 User.id

    # 推荐类型: personalized | trending | similar | collaborative
    recommendation_type = Column(String(30), nullable=False, index=True)

    # 推荐的技能ID列表
    skill_ids = Column(JSON, default=[])

    # 每个技能的推荐分数
    scores = Column(JSON, default={})

    # 缓存过期时间 (TTL: Time To Live)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_cache_expiry", "user_id", "expires_at"),)
