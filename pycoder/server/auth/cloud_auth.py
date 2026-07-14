"""
🔐 云端同步 - 认证系统 (使用 PBKDF2 密码加密)

功能：
- 用户注册/登录
- JWT 令牌管理
- 多设备追踪
- PBKDF2 密码加密
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pydantic import BaseModel, EmailStr

logger = logging.getLogger(__name__)

# JWT 配置 — 密钥必须从环境变量获取，不提供默认值
_SECRET = os.environ.get("PYCODER_CLOUD_JWT_SECRET", "")
_SHOULD_LOG = True  # 模块级标志：只打印一次警告


if not _SECRET:
    if _SHOULD_LOG:
        _SHOULD_LOG = False
        # 检查是否在非开发模式下运行
        _is_dev = os.environ.get("PYCODER_ENV", "").lower() in ("dev", "development")
        if not _is_dev:
            logger.critical(
                "\n" + "=" * 70 + "\n"
                "  ⚠️  安全警告: PYCODER_CLOUD_JWT_SECRET 环境变量未设置！\n"
                "  当前使用随机临时密钥，服务器重启后所有用户 Token 将失效。\n"
                "  生产环境请执行:\n"
                '    export PYCODER_CLOUD_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")  # Linux/macOS\n'
                '    $env:PYCODER_CLOUD_JWT_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(32))")  # Windows\n'
                "=" * 70
            )
        else:
            logger.warning("JWT_SECRET 未设置！当前使用随机临时密钥（重启后所有 Token 失效）。")
    _SECRET = __import__("secrets").token_hex(32)
SECRET_KEY = _SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7


class TokenData(BaseModel):
    """JWT 令牌数据"""

    user_id: str
    username: str
    device_id: str
    token_type: str  # "access" or "refresh"
    exp: int


class UserRegisterRequest(BaseModel):
    """用户注册请求"""

    username: str
    email: EmailStr
    password: str


class UserLoginRequest(BaseModel):
    """用户登录请求"""

    username: str
    password: str
    device_id: str
    device_name: str


class AuthResponse(BaseModel):
    """认证响应"""

    success: bool
    user_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    error: str | None = None


class DeviceRegisterRequest(BaseModel):
    """设备注册请求"""

    device_id: str
    device_name: str
    device_type: str = "desktop"


# ─────────────────────────────────────────────────────────
# 密码加密工具（使用 PBKDF2 + SHA256）
# ─────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """使用 PBKDF2 + SHA256 加密密码"""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return base64.b64encode(salt + key).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    try:
        decoded = base64.b64decode(hashed.encode("utf-8"))
        salt = decoded[:16]
        original_key = decoded[16:]
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        # 使用 hmac.compare_digest 防止时序攻击
        return hmac.compare_digest(new_key, original_key)
    except (ValueError, base64.binascii.Error, TypeError) as e:
        logger.error(f"密码验证错误: {e}")
        return False


# ─────────────────────────────────────────────────────────
# JWT 令牌工具
# ─────────────────────────────────────────────────────────


def create_access_token(user_id: str, username: str, device_id: str) -> str:
    """创建访问令牌"""
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "user_id": user_id,
        "username": username,
        "device_id": device_id,
        "token_type": "access",
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str, username: str, device_id: str) -> str:
    """创建刷新令牌"""
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "user_id": user_id,
        "username": username,
        "device_id": device_id,
        "token_type": "refresh",
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """解码令牌"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("令牌已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"无效令牌: {e}")
        return None


def verify_access_token(token: str) -> TokenData | None:
    """验证访问令牌"""
    payload = decode_token(token)
    if not payload or payload.get("token_type") != "access":
        return None
    return TokenData(**payload)


def verify_refresh_token(token: str) -> TokenData | None:
    """验证刷新令牌"""
    payload = decode_token(token)
    if not payload or payload.get("token_type") != "refresh":
        return None
    return TokenData(**payload)


# ─────────────────────────────────────────────────────────
# 认证服务
# ─────────────────────────────────────────────────────────


class CloudAuthService:
    """云端认证服务"""

    def __init__(self, db_session):
        self.db = db_session

    async def register_user(self, request: UserRegisterRequest) -> dict[str, Any]:
        """用户注册"""
        from pycoder.server.models.cloud_models import User

        try:
            existing = (
                self.db.query(User)
                .filter((User.username == request.username) | (User.email == request.email))
                .first()
            )

            if existing:
                return {"success": False, "error": "用户名或邮箱已存在"}

            user = User(
                id=str(uuid.uuid4()),
                username=request.username,
                email=request.email,
                password_hash=hash_password(request.password),
            )
            self.db.add(user)
            self.db.commit()

            logger.info(f"用户注册成功: {request.username}")
            return {"success": True, "user_id": user.id, "message": "注册成功"}
        except Exception as e:
            logger.error(f"注册失败: {e}")
            self.db.rollback()
            return {"success": False, "error": str(e)}

    async def login_user(self, request: UserLoginRequest) -> dict[str, Any]:
        """用户登录"""
        from pycoder.server.models.cloud_models import DeviceInfo, User

        try:
            user = self.db.query(User).filter(User.username == request.username).first()

            if not user or not verify_password(request.password, user.password_hash):
                return {"success": False, "error": "用户名或密码错误"}

            device = DeviceInfo(
                user_id=user.id,
                device_id=request.device_id,
                device_name=request.device_name,
                device_type="desktop",
            )
            self.db.add(device)
            self.db.commit()

            access_token = create_access_token(user.id, user.username, request.device_id)
            refresh_token = create_refresh_token(user.id, user.username, request.device_id)

            logger.info(f"用户登录成功: {request.username}")
            return {
                "success": True,
                "user_id": user.id,
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
        except Exception as e:
            logger.error(f"登录失败: {e}")
            self.db.rollback()
            return {"success": False, "error": str(e)}

    async def get_user_devices(self, user_id: str) -> dict[str, Any]:
        """获取用户设备列表"""
        from pycoder.server.models.cloud_models import DeviceInfo

        try:
            devices = self.db.query(DeviceInfo).filter(DeviceInfo.user_id == user_id).all()
            return {
                "success": True,
                "count": len(devices),
                "devices": [
                    {
                        "device_id": d.device_id,
                        "device_name": d.device_name,
                        "device_type": d.device_type,
                        "last_sync": d.last_sync.isoformat() if d.last_sync else None,
                    }
                    for d in devices
                ],
            }
        except Exception as e:
            logger.error(f"获取设备列表失败: {e}")
            return {"success": False, "error": str(e)}
