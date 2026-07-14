"""
✅ Task 3 集成测试 - 个性化推荐系统

测试项:
1. 行为追踪 (浏览、点击、评分、搜索)
2. 推荐算法 (内容、协同、热度、个性化)
3. API端点功能
4. 性能和准确率

运行: python -m pytest test_integration_task3.py -v
"""

import pytest
from datetime import datetime, timedelta
from pycoder.server.models.behavior_models import (
    UserBehavior, BehaviorLog, UserPreference, SkillSimilarity
)
from pycoder.server.recommendation.engine import RecommendationEngine
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Test 1: 行为追踪
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_track_user_view(db_session):
    """测试追踪用户浏览"""
    engine = RecommendationEngine(db_session)

    result = await engine.track_user_behavior(
        user_id="user-001",
        skill_id="skill-001",
        action="view"
    )

    assert result["success"] is True

    # 验证数据库
    user_behavior = (
        db_session.query(UserBehavior)
        .filter(UserBehavior.user_id == "user-001")
        .first()
    )
    assert user_behavior is not None
    assert user_behavior.total_views == 1

    print("✓ 用户浏览追踪成功")


@pytest.mark.asyncio
async def test_track_user_rating(db_session):
    """测试追踪用户评分"""
    engine = RecommendationEngine(db_session)

    result = await engine.track_user_behavior(
        user_id="user-002",
        skill_id="skill-002",
        action="rate",
        metadata={"rating": 5, "review": "很棒!"}
    )

    assert result["success"] is True

    user_behavior = (
        db_session.query(UserBehavior)
        .filter(UserBehavior.user_id == "user-002")
        .first()
    )
    assert user_behavior.total_ratings == 1
    assert user_behavior.avg_rating_score > 0

    print("✓ 用户评分追踪成功")


@pytest.mark.asyncio
async def test_track_multiple_behaviors(db_session):
    """测试追踪多个行为"""
    engine = RecommendationEngine(db_session)

    # 追踪多个行为
    for i in range(10):
        await engine.track_user_behavior(
            user_id="user-003",
            skill_id=f"skill-{i:03d}",
            action="view" if i % 2 == 0 else "click"
        )

    user_behavior = (
        db_session.query(UserBehavior)
        .filter(UserBehavior.user_id == "user-003")
        .first()
    )

    assert user_behavior.total_views + user_behavior.total_clicks == 10

    print("✓ 多个行为追踪成功")


# ─────────────────────────────────────────────────────────
# Test 2: 热度推荐
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trending_skills(db_session):
    """测试热门技能推荐"""
    engine = RecommendationEngine(db_session)

    # 先添加一些评分
    from pycoder.server.models.cloud_models import User
    import uuid

    user = User(
        id=str(uuid.uuid4()),
        username="trending-user",
        email="trending@test.com",
        password_hash="hash"
    )
    db_session.add(user)
    db_session.flush()

    # 添加行为日志
    for i in range(5):
        log = BehaviorLog(
            id=str(uuid.uuid4()),
            user_behavior_id=user.id,
            skill_id="popular-skill",
            action="rate",
            metadata={"rating": 5}
        )
        db_session.add(log)

    db_session.commit()

    # 获取热门技能
    trending = await engine.get_trending_skills(
        period_days=7,
        limit=10
    )

    assert isinstance(trending, list)
    print(f"✓ 获取热门技能成功, 共 {len(trending)} 个")


# ─────────────────────────────────────────────────────────
# Test 3: 相似技能推荐
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_similar_skills(db_session):
    """测试相似技能推荐"""
    import uuid

    # 添加技能相似度数据
    for i in range(5):
        sim = SkillSimilarity(
            id=str(uuid.uuid4()),
            skill_id_a="skill-base",
            skill_id_b=f"skill-{i}",
            similarity_score=0.8 - (i * 0.1),
            reason="tags"
        )
        db_session.add(sim)

    db_session.commit()

    engine = RecommendationEngine(db_session)
    similar = await engine.get_similar_skills("skill-base", limit=10)

    assert len(similar) > 0
    assert similar[0]["similarity"] >= similar[-1]["similarity"]

    print(f"✓ 相似技能推荐成功, 共 {len(similar)} 个")


# ─────────────────────────────────────────────────────────
# Test 4: 协同过滤推荐
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collaborative_filtering(db_session):
    """测试协同过滤"""
    from pycoder.server.models.cloud_models import User, SkillRating
    import uuid

    # 创建两个用户
    user1 = User(
        id=str(uuid.uuid4()),
        username="cf-user-1",
        email="cf1@test.com",
        password_hash="hash"
    )
    user2 = User(
        id=str(uuid.uuid4()),
        username="cf-user-2",
        email="cf2@test.com",
        password_hash="hash"
    )
    db_session.add_all([user1, user2])
    db_session.flush()

    # user1 和 user2 对相同技能评分相似
    for skill_id in ["s1", "s2", "s3"]:
        rating1 = SkillRating(
            user_id=user1.id,
            skill_id=skill_id,
            rating=4
        )
        rating2 = SkillRating(
            user_id=user2.id,
            skill_id=skill_id,
            rating=5
        )
        db_session.add_all([rating1, rating2])

    # user2 还评分了 s4
    rating_new = SkillRating(
        user_id=user2.id,
        skill_id="s4",
        rating=5
    )
    db_session.add(rating_new)
    db_session.commit()

    engine = RecommendationEngine(db_session)

    # 找相似用户
    similar_users = await engine.find_similar_users(user1.id)
    assert len(similar_users) > 0

    # 从相似用户推荐
    recs = await engine.recommend_from_similar_users(user1.id)
    assert isinstance(recs, list)

    print(f"✓ 协同过滤推荐成功, 找到 {len(similar_users)} 个相似用户")


# ─────────────────────────────────────────────────────────
# Test 5: 个性化推荐
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_personalized_recommendations(db_session):
    """测试个性化推荐"""
    from pycoder.server.models.cloud_models import User
    import uuid

    user = User(
        id=str(uuid.uuid4()),
        username="personal-user",
        email="personal@test.com",
        password_hash="hash"
    )
    db_session.add(user)
    db_session.flush()

    # 为用户创建行为记录
    behavior = UserBehavior(
        id=str(uuid.uuid4()),
        user_id=user.id,
        total_views=100,
        total_ratings=20,
        avg_rating_score=4.2
    )
    db_session.add(behavior)
    db_session.commit()

    engine = RecommendationEngine(db_session)

    # 获取个性化推荐
    recs = await engine.get_personalized_recommendations(
        user_id=user.id,
        limit=15
    )

    assert isinstance(recs, list)
    print(f"✓ 个性化推荐成功, 生成 {len(recs)} 个推荐")


# ─────────────────────────────────────────────────────────
# Test 6: API端点
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendation_api_endpoints(db_session):
    """测试推荐API端点"""
    from pycoder.server.routers.recommendation_api import router

    # 验证路由存在
    routes = [route.path for route in router.routes]

    assert "/for-me" in str(routes)
    assert "/trending" in str(routes)
    assert "/track-behavior" in str(routes)
    assert "/similar/{skill_id}" in str(routes)

    print("✓ 推荐API端点已注册")


# ─────────────────────────────────────────────────────────
# Test 7: 性能测试
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendation_performance(db_session):
    """测试推荐系统性能"""
    import time
    from pycoder.server.models.cloud_models import User
    import uuid

    user = User(
        id=str(uuid.uuid4()),
        username="perf-user",
        email="perf@test.com",
        password_hash="hash"
    )
    db_session.add(user)

    behavior = UserBehavior(
        id=str(uuid.uuid4()),
        user_id=user.id,
        total_views=1000,
        total_ratings=100
    )
    db_session.add(behavior)
    db_session.commit()

    engine = RecommendationEngine(db_session)

    # 测试个性化推荐性能
    start = time.time()
    await engine.get_personalized_recommendations(user.id, limit=20)
    elapsed = (time.time() - start) * 1000  # ms

    assert elapsed < 1000  # 应该在1秒内完成
    print(f"✓ 个性化推荐性能良好: {elapsed:.2f}ms")


# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """创建测试数据库会话"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from pycoder.server.models.cloud_models import Base as CloudBase
    from pycoder.server.models.behavior_models import Base as BehaviorBase

    # 使用内存SQLite
    engine = create_engine("sqlite:///:memory:")

    # 创建所有表
    CloudBase.metadata.create_all(engine)
    BehaviorBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
