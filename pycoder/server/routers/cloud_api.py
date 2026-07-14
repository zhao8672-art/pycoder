"""
🌐 云端同步 - REST API 路由

端点：
- /api/cloud/auth/* - 认证
- /api/cloud/sync/* - 同步
- /api/cloud/devices/* - 设备管理
"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from pycoder.server.auth.cloud_auth import (
    AuthResponse,
    CloudAuthService,
    DeviceRegisterRequest,
    UserLoginRequest,
    UserRegisterRequest,
    verify_access_token,
)
from pycoder.server.sync.cloud_sync_engine import (
    CloudSyncEngine,
    ConflictResolution,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cloud", tags=["cloud"])

# 数据库会话依赖（需在 app.py 配置）
from sqlalchemy.orm import Session  # noqa: E402


def get_db() -> Session:
    """获取数据库会话 — 优先使用 SQLite 本地数据库"""
    import logging as _logging
    from pathlib import Path as _Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _logger = _logging.getLogger(__name__)
    _db_path = _Path.home() / ".pycoder" / "cloud.db"
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{_db_path}"

    # 尝试连接 PostgreSQL（通过环境变量配置），失败时降级到 SQLite
    _pg_url = os.environ.get("PYCODER_CLOUD_DATABASE_URL", "")
    if _pg_url:
        try:
            engine = create_engine(_pg_url, connect_args={"connect_timeout": 3})
            engine.connect()
            _logger.info("cloud_db_connected provider=postgresql")
        except Exception as e:
            _logger.warning("cloud_db_pg_fallback_to_sqlite reason=%s", e)
            engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    """获取当前用户"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    token = authorization[7:]
    token_data = verify_access_token(token)

    if not token_data:
        raise HTTPException(status_code=401, detail="令牌已过期或无效")

    return {
        "user_id": token_data.user_id,
        "username": token_data.username,
        "device_id": token_data.device_id,
    }


# ─────────────────────────────────────────────────────────
# 认证路由
# ─────────────────────────────────────────────────────────


class RegisterResponse(BaseModel):
    """注册响应"""

    success: bool
    user_id: str | None = None
    error: str | None = None
    message: str | None = None


@router.post("/auth/register", response_model=RegisterResponse)
async def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """注册新用户"""
    auth_service = CloudAuthService(db)
    result = await auth_service.register_user(request)
    return RegisterResponse(**result)


@router.post("/auth/login", response_model=AuthResponse)
async def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    auth_service = CloudAuthService(db)
    result = await auth_service.login_user(request)

    if result["success"]:
        return AuthResponse(**result)
    else:
        raise HTTPException(status_code=401, detail=result.get("error"))


class RefreshTokenRequest(BaseModel):
    """刷新令牌请求"""

    refresh_token: str


class RefreshTokenResponse(BaseModel):
    """刷新令牌响应"""

    success: bool
    access_token: str | None = None
    expires_in: int | None = None
    error: str | None = None


@router.post("/auth/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """刷新访问令牌"""
    auth_service = CloudAuthService(db)
    result = await auth_service.refresh_access_token(request.refresh_token)

    if result["success"]:
        return RefreshTokenResponse(**result)
    else:
        raise HTTPException(status_code=401, detail=result.get("error"))


class LogoutResponse(BaseModel):
    """登出响应"""

    success: bool
    message: str


@router.post("/auth/logout", response_model=LogoutResponse)
async def logout(current_user: dict = Depends(get_current_user)):
    """用户登出"""
    logger.info(f"用户登出: {current_user['username']}")
    return LogoutResponse(success=True, message="登出成功")


# ─────────────────────────────────────────────────────────
# 同步路由
# ─────────────────────────────────────────────────────────


class RatingData(BaseModel):
    """评分数据"""

    skill_id: str
    rating: int  # 1-5
    review: str | None = None
    timestamp: str


class UploadSyncRequest(BaseModel):
    """上传同步请求"""

    ratings: list[RatingData]


class UploadSyncResponse(BaseModel):
    """上传同步响应"""

    success: bool
    uploaded: int
    conflicts: list
    timestamp: str
    error: str | None = None


@router.post("/sync/upload", response_model=UploadSyncResponse)
async def upload_ratings(
    request: UploadSyncRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传本地评分"""
    sync_engine = CloudSyncEngine(db)
    result = await sync_engine.upload_ratings(
        user_id=current_user["user_id"],
        device_id=current_user["device_id"],
        local_ratings=[r.model_dump() for r in request.ratings],
    )

    if result["success"]:
        return UploadSyncResponse(**result)
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


class DownloadSyncResponse(BaseModel):
    """下载同步响应"""

    success: bool
    ratings: list
    count: int
    timestamp: str
    error: str | None = None


@router.get("/sync/download", response_model=DownloadSyncResponse)
async def download_ratings(
    since: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载云端评分"""
    sync_engine = CloudSyncEngine(db)
    since_dt = None

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的时间格式") from None

    result = await sync_engine.download_ratings(
        user_id=current_user["user_id"],
        device_id=current_user["device_id"],
        since=since_dt,
    )

    if result["success"]:
        return DownloadSyncResponse(**result)
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


class SyncStatusResponse(BaseModel):
    """同步状态响应"""

    success: bool
    last_sync: str | None = None
    upload_count: int = 0
    download_count: int = 0
    conflict_count: int = 0
    is_syncing: bool = False
    error: str | None = None


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取同步状态"""
    sync_engine = CloudSyncEngine(db)
    result = await sync_engine.get_sync_status(current_user["user_id"])

    if result["success"]:
        return SyncStatusResponse(**result)
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


class ResolveConflictRequest(BaseModel):
    """冲突解决请求"""

    skill_id: str
    resolution: str  # "local_wins", "remote_wins", "manual"


class ResolveConflictResponse(BaseModel):
    """冲突解决响应"""

    success: bool
    message: str | None = None
    error: str | None = None


@router.post("/sync/resolve", response_model=ResolveConflictResponse)
async def resolve_conflict(
    request: ResolveConflictRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解决冲突"""
    try:
        resolution = ConflictResolution(request.resolution)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的解决策略") from None

    sync_engine = CloudSyncEngine(db)
    result = await sync_engine.resolve_conflict(
        user_id=current_user["user_id"],
        skill_id=request.skill_id,
        resolution=resolution,
    )

    if result["success"]:
        return ResolveConflictResponse(**result)
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


# ─────────────────────────────────────────────────────────
# 设备管理路由
# ─────────────────────────────────────────────────────────


class DeviceListResponse(BaseModel):
    """设备列表响应"""

    success: bool
    devices: list
    count: int
    error: str | None = None


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户设备列表"""
    auth_service = CloudAuthService(db)
    result = await auth_service.get_user_devices(current_user["user_id"])

    if result["success"]:
        return DeviceListResponse(**result)
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


class DeviceRegisterResponse(BaseModel):
    """设备注册响应"""

    success: bool
    device_id: str | None = None
    message: str | None = None
    error: str | None = None


@router.post("/devices/register", response_model=DeviceRegisterResponse)
async def register_device(
    request: DeviceRegisterRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """注册新设备"""
    import uuid

    from pycoder.server.models.cloud_models import DeviceInfo

    try:
        device = (
            db.query(DeviceInfo)
            .filter(
                (DeviceInfo.user_id == current_user["user_id"])
                & (DeviceInfo.device_id == request.device_id)
            )
            .first()
        )

        if device:
            return DeviceRegisterResponse(success=False, error="设备已存在")

        new_device = DeviceInfo(
            id=str(uuid.uuid4()),
            user_id=current_user["user_id"],
            device_id=request.device_id,
            device_name=request.device_name,
            device_type=request.device_type,
        )
        db.add(new_device)
        db.commit()

        logger.info(f"设备已注册: {request.device_name} ({request.device_id})")
        return DeviceRegisterResponse(
            success=True, device_id=request.device_id, message="设备注册成功"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"设备注册失败: {e}")
        raise HTTPException(status_code=400, detail="设备注册失败") from e


class DeviceDeleteResponse(BaseModel):
    """设备删除响应"""

    success: bool
    message: str | None = None
    error: str | None = None


@router.delete("/devices/{device_id}", response_model=DeviceDeleteResponse)
async def delete_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除设备"""
    from pycoder.server.models.cloud_models import DeviceInfo

    try:
        device = (
            db.query(DeviceInfo)
            .filter(
                (DeviceInfo.user_id == current_user["user_id"])
                & (DeviceInfo.device_id == device_id)
            )
            .first()
        )

        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")

        db.delete(device)
        db.commit()

        logger.info(f"设备已删除: {device_id}")
        return DeviceDeleteResponse(success=True, message="设备删除成功")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"设备删除失败: {e}")
        raise HTTPException(status_code=400, detail="设备删除失败") from e
