"""
☁️ 云端同步 - 数据库 ORM 模型

使用 SQLAlchemy 定义所有云端数据结构
- User: 用户账户
- SkillRating: 技能评分
- SyncLog: 同步日志
- DeviceInfo: 设备信息
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """用户账户模型"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  # bcrypt 加密
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    ratings = relationship("SkillRating", back_populates="user", cascade="all, delete-orphan")
    devices = relationship("DeviceInfo", back_populates="user", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_user_created_at", "created_at"),)

    def __repr__(self):
        return f"<User {self.username}>"


class SkillRating(Base):
    """技能评分模型"""

    __tablename__ = "skill_ratings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    skill_id = Column(String(100), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    review = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    user = relationship("User", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_user_skill"),
        Index("idx_skill_rating_user_id", "user_id"),
        Index("idx_skill_rating_skill_id", "skill_id"),
        Index("idx_skill_rating_updated_at", "updated_at"),
    )

    def __repr__(self):
        return f"<SkillRating user={self.user_id}, skill={self.skill_id}, rating={self.rating}>"


class SyncLog(Base):
    """同步日志模型"""

    __tablename__ = "sync_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    device_id = Column(String(100), nullable=False)
    action = Column(String(20), nullable=False)  # "upload", "download", "conflict"
    skill_ids = Column(JSON, nullable=False)  # List[str]
    status = Column(String(20), nullable=False)  # "success", "pending", "failed"
    error_message = Column(String(500), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    user = relationship("User", back_populates="sync_logs")

    __table_args__ = (
        Index("idx_sync_log_user_id", "user_id"),
        Index("idx_sync_log_device_id", "device_id"),
        Index("idx_sync_log_timestamp", "timestamp"),
        Index("idx_sync_log_status", "status"),
    )

    def __repr__(self):
        return f"<SyncLog user={self.user_id}, action={self.action}, status={self.status}>"


class DeviceInfo(Base):
    """设备信息模型"""

    __tablename__ = "device_info"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    device_id = Column(String(100), nullable=False)  # UUID from client
    device_name = Column(String(100), nullable=False)
    device_type = Column(String(20), nullable=True)  # "desktop", "mobile", "web"
    last_sync = Column(DateTime, nullable=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    user = relationship("User", back_populates="devices")

    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_user_device"),
        Index("idx_device_user_id", "user_id"),
        Index("idx_device_last_sync", "last_sync"),
    )

    def __repr__(self):
        return f"<DeviceInfo user={self.user_id}, device={self.device_name}>"


# 本地离线存储模型（SQLite）
class LocalRatingCache(Base):
    """本地离线评分缓存（使用 SQLite 存储在客户端）"""

    __tablename__ = "local_rating_cache"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String(100), unique=True, nullable=False)
    rating = Column(Integer, nullable=False)
    review = Column(String(500), nullable=True)
    local_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    cloud_timestamp = Column(DateTime, nullable=True)
    sync_status = Column(String(20), default="pending")  # "pending", "synced", "conflict"
    is_deleted = Column(Boolean, default=False)

    __table_args__ = (
        Index("idx_local_cache_sync_status", "sync_status"),
        Index("idx_local_cache_local_timestamp", "local_timestamp"),
    )

    def __repr__(self):
        return f"<LocalRatingCache skill={self.skill_id}, status={self.sync_status}>"
