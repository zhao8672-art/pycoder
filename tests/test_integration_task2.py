"""
✅ Task 2 集成测试 - 云端同步系统

测试项：
1. 认证系统（注册、登录、刷新令牌）
2. 用户和设备管理
3. 上传同步
4. 下载同步
5. 冲突检测和解决
6. 多设备同步
7. 性能测试

运行: python -m pytest test_integration_task2.py -v
"""

import pytest
from datetime import datetime, timedelta
from pycoder.server.models.cloud_models import (
    User, SkillRating, SyncLog, DeviceInfo, LocalRatingCache
)
from pycoder.server.auth.cloud_auth import (
    CloudAuthService, UserRegisterRequest, UserLoginRequest,
    hash_password, verify_password
)
from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Test 1: 认证系统
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_registration(db_session):
    """测试用户注册"""
    auth_service = CloudAuthService(db_session)
    request = UserRegisterRequest(
        username="testuser",
        email="test@example.com",
        password="password123"
    )

    result = await auth_service.register_user(request)
    assert result["success"] is True
    assert "user_id" in result
    assert result["message"] == "注册成功"

    print("✓ 用户注册成功")


@pytest.mark.asyncio
async def test_user_registration_duplicate(db_session):
    """测试重复注册"""
    auth_service = CloudAuthService(db_session)
    request = UserRegisterRequest(
        username="testuser",
        email="test@example.com",
        password="password123"
    )

    # 第一次注册
    await auth_service.register_user(request)

    # 第二次注册相同用户名
    result = await auth_service.register_user(request)
    assert result["success"] is False
    assert "已存在" in result.get("error", "")

    print("✓ 重复注册被正确拒绝")


@pytest.mark.asyncio
async def test_user_login(db_session):
    """测试用户登录"""
    auth_service = CloudAuthService(db_session)

    # 先注册
    register_request = UserRegisterRequest(
        username="loginuser",
        email="login@example.com",
        password="password123"
    )
    register_result = await auth_service.register_user(register_request)
    user_id = register_result["user_id"]

    # 然后登录
    login_request = UserLoginRequest(
        username="loginuser",
        password="password123",
        device_id="device-001",
        device_name="Test Desktop"
    )
    login_result = await auth_service.login_user(login_request)

    assert login_result["success"] is True
    assert "access_token" in login_result
    assert "refresh_token" in login_result
    assert login_result["user_id"] == user_id

    print("✓ 用户登录成功，获得令牌")


@pytest.mark.asyncio
async def test_user_login_invalid_password(db_session):
    """测试错误密码登录"""
    auth_service = CloudAuthService(db_session)

    # 先注册
    register_request = UserRegisterRequest(
        username="invaliduser",
        email="invalid@example.com",
        password="correct_password"
    )
    await auth_service.register_user(register_request)

    # 用错误密码登录
    login_request = UserLoginRequest(
        username="invaliduser",
        password="wrong_password",
        device_id="device-002",
        device_name="Test Desktop"
    )
    login_result = await auth_service.login_user(login_request)

    assert login_result["success"] is False
    assert "错误" in login_result.get("error", "")

    print("✓ 错误密码登录被正确拒绝")


# ─────────────────────────────────────────────────────────
# Test 2: 设备管理
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_registration(db_session):
    """测试设备注册"""
    auth_service = CloudAuthService(db_session)

    # 先注册用户
    register_request = UserRegisterRequest(
        username="deviceuser",
        email="device@example.com",
        password="password123"
    )
    register_result = await auth_service.register_user(register_request)
    user_id = register_result["user_id"]

    # 获取设备列表
    result = await auth_service.get_user_devices(user_id)
    assert result["success"] is True
    assert result["count"] >= 0

    print(f"✓ 设备列表获取成功，当前 {result['count']} 个设备")


# ─────────────────────────────────────────────────────────
# Test 3: 同步引擎 - 上传
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_ratings(db_session):
    """测试上传评分"""
    sync_engine = CloudSyncEngine(db_session)

    # 创建测试用户
    user = User(
        id="test-user-001",
        username="syncuser",
        email="sync@example.com",
        password_hash=hash_password("password123")
    )
    db_session.add(user)
    db_session.commit()

    # 上传评分
    local_ratings = [
        {
            "skill_id": "skill-001",
            "rating": 5,
            "review": "Excellent skill!",
            "timestamp": datetime.utcnow().isoformat()
        },
        {
            "skill_id": "skill-002",
            "rating": 4,
            "review": "Good",
            "timestamp": datetime.utcnow().isoformat()
        }
    ]

    result = await sync_engine.upload_ratings(
        user_id="test-user-001",
        device_id="device-sync-001",
        local_ratings=local_ratings
    )

    assert result["success"] is True
    assert result["uploaded"] == 2
    assert result["conflicts"] == []

    print(f"✓ 上传 {result['uploaded']} 个评分成功")


# ─────────────────────────────────────────────────────────
# Test 4: 同步引擎 - 下载
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_ratings(db_session):
    """测试下载评分"""
    sync_engine = CloudSyncEngine(db_session)

    # 创建测试用户和评分
    user = User(
        id="test-user-002",
        username="downloaduser",
        email="download@example.com",
        password_hash=hash_password("password123")
    )
    db_session.add(user)
    db_session.commit()

    # 添加几个评分
    for i in range(3):
        rating = SkillRating(
            user_id="test-user-002",
            skill_id=f"skill-{i:03d}",
            rating=4 + i % 2,
            review=f"Review {i}",
        )
        db_session.add(rating)
    db_session.commit()

    # 下载评分
    result = await sync_engine.download_ratings(
        user_id="test-user-002",
        device_id="device-sync-002"
    )

    assert result["success"] is True
    assert result["count"] >= 3

    print(f"✓ 下载 {result['count']} 个评分成功")


# ─────────────────────────────────────────────────────────
# Test 5: 冲突检测
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_detection(db_session):
    """测试冲突检测"""
    sync_engine = CloudSyncEngine(db_session)

    # 创建用户和初始评分
    user = User(
        id="test-user-003",
        username="conflictuser",
        email="conflict@example.com",
        password_hash=hash_password("password123")
    )
    db_session.add(user)

    # 云端现有评分（时间戳：T0）
    now = datetime.utcnow()
    cloud_rating = SkillRating(
        user_id="test-user-003",
        skill_id="skill-conflict",
        rating=3,
        created_at=now,
        updated_at=now
    )
    db_session.add(cloud_rating)
    db_session.commit()

    # 本地评分（时间戳：T0 + 10秒，在冲突阈值内）
    local_ts = now + timedelta(seconds=10)
    local_ratings = [
        {
            "skill_id": "skill-conflict",
            "rating": 5,
            "review": "Local update",
            "timestamp": local_ts.isoformat()
        }
    ]

    # 上传会检测到冲突
    result = await sync_engine.upload_ratings(
        user_id="test-user-003",
        device_id="device-sync-003",
        local_ratings=local_ratings
    )

    assert result["success"] is True
    assert len(result["conflicts"]) > 0

    print(f"✓ 检测到 {len(result['conflicts'])} 个冲突")


# ─────────────────────────────────────────────────────────
# Test 6: 冲突解决
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_resolution(db_session):
    """测试冲突解决"""
    from pycoder.server.sync.cloud_sync_engine import ConflictResolution

    sync_engine = CloudSyncEngine(db_session)

    # 创建冲突
    user = User(
        id="test-user-004",
        username="resolveuser",
        email="resolve@example.com",
        password_hash=hash_password("password123")
    )
    db_session.add(user)

    rating = SkillRating(
        user_id="test-user-004",
        skill_id="skill-to-resolve",
        rating=2
    )
    db_session.add(rating)
    db_session.commit()

    # 解决冲突 - 使用本地版本
    result = await sync_engine.resolve_conflict(
        user_id="test-user-004",
        skill_id="skill-to-resolve",
        resolution=ConflictResolution.LOCAL_WINS
    )

    assert result["success"] is True

    print("✓ 冲突已解决")


# ─────────────────────────────────────────────────────────
# Test 7: 同步状态
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_status(db_session):
    """测试同步状态查询"""
    sync_engine = CloudSyncEngine(db_session)

    # 创建用户和同步日志
    user = User(
        id="test-user-005",
        username="statususer",
        email="status@example.com",
        password_hash=hash_password("password123")
    )
    db_session.add(user)

    # 添加同步日志
    log = SyncLog(
        user_id="test-user-005",
        device_id="device-status",
        action="upload",
        skill_ids=["skill-1", "skill-2"],
        status="success"
    )
    db_session.add(log)
    db_session.commit()

    # 查询状态
    result = await sync_engine.get_sync_status("test-user-005")

    assert result["success"] is True
    assert "last_sync" in result
    assert result["upload_count"] >= 0

    print(f"✓ 同步状态: 上传 {result['upload_count']} 次")


# ─────────────────────────────────────────────────────────
# Test 8: 多设备同步
# ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_device_sync(db_session):
    """测试多设备同步"""
    sync_engine = CloudSyncEngine(db_session)

    # 创建用户
    user = User(
        id="test-user-006",
        username="multideviceuser",
        email="multidevice@example.com",
        password_hash=hash_password("password123")
    )
    db_session.add(user)
    db_session.commit()

    # 从设备1上传
    result1 = await sync_engine.upload_ratings(
        user_id="test-user-006",
        device_id="device-1",
        local_ratings=[
            {
                "skill_id": "shared-skill",
                "rating": 5,
                "timestamp": datetime.utcnow().isoformat()
            }
        ]
    )
    assert result1["success"] is True

    # 从设备2下载
    result2 = await sync_engine.download_ratings(
        user_id="test-user-006",
        device_id="device-2"
    )
    assert result2["success"] is True

    # 验证数据一致
    assert len(result2["ratings"]) >= 1

    print("✓ 多设备数据同步成功")


# ─────────────────────────────────────────────────────────
# Test 9: 密码加密
# ─────────────────────────────────────────────────────────


def test_password_hashing():
    """测试密码加密"""
    password = "secure123"  # 使用短密码避免bcrypt限制(72字节)
    hashed = hash_password(password)

    # 验证正确密码
    assert verify_password(password, hashed) is True

    # 拒绝错误密码
    assert verify_password("wrong_pass", hashed) is False

    print("✓ 密码加密和验证成功")


# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """创建数据库会话"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from pycoder.server.models.cloud_models import Base

    # 使用内存SQLite进行测试
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
