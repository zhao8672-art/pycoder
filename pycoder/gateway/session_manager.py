"""
会话管理器 — 平台隔离 + 跨平台上下文共享

为每个平台+用户组合维护独立会话，同时支持跨平台共享上下文。
当同一用户从不同平台接入时，AI 可以引用其他平台的历史对话上下文。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """单个会话 —— 对应一个平台+用户组合"""

    platform: str  # 平台名称
    user_id: str  # 用户 ID
    session_id: str  # 会话唯一 ID
    created_at: float  # 创建时间戳
    last_activity: float  # 最后活跃时间
    messages: list[dict[str, Any]] = field(default_factory=list)  # 消息历史
    context: dict[str, Any] = field(default_factory=dict)  # 会话上下文
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据

    # 最大消息历史条数
    _max_messages: int = 100

    def add_message(self, gateway_msg: Any) -> None:
        """添加一条消息到会话历史

        Args:
            gateway_msg: GatewayMessage 实例
        """
        self.messages.append(
            gateway_msg.to_dict() if hasattr(gateway_msg, "to_dict") else gateway_msg
        )
        self.last_activity = time.time()

        # 限制消息历史大小
        if len(self.messages) > self._max_messages:
            self.messages = self.messages[-self._max_messages:]

    def add_response(self, content: str) -> None:
        """添加 AI 响应到会话历史"""
        self.messages.append({
            "role": "assistant",
            "content": content,
            "timestamp": time.time(),
        })
        self.last_activity = time.time()

    def get_recent_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取最近的消息历史

        Args:
            limit: 返回的消息数量上限

        Returns:
            最近的消息列表
        """
        return self.messages[-limit:]

    def update_context(self, key: str, value: Any) -> None:
        """更新会话上下文

        Args:
            key: 上下文键
            value: 上下文值
        """
        self.context[key] = value
        self.last_activity = time.time()

    def get_context(self, key: str, default: Any = None) -> Any:
        """获取会话上下文值

        Args:
            key: 上下文键
            default: 默认值

        Returns:
            上下文值
        """
        return self.context.get(key, default)

    def to_info_dict(self) -> dict[str, Any]:
        """转换为信息字典（不含完整消息历史）"""
        return {
            "platform": self.platform,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "message_count": len(self.messages),
            "context_keys": list(self.context.keys()),
            "metadata": self.metadata,
        }

    def to_dict(self) -> dict[str, Any]:
        """完整序列化（含消息历史）"""
        return {
            "platform": self.platform,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "messages": self.messages,
            "context": self.context,
            "metadata": self.metadata,
        }


class SessionManager:
    """
    会话管理器 —— 维护所有平台会话

    特性:
    - 每个 (platform, user_id) 组合有独立会话
    - 会话可以跨平台共享上下文（通过 shared_context）
    - 支持会话过期清理
    - 支持活跃会话切换
    """

    def __init__(self, session_ttl_seconds: float = 3600.0) -> None:
        # 会话存储: key = (platform, user_id)
        self._sessions: dict[tuple[str, str], Session] = {}
        # 跨平台共享上下文: key = user_id
        self._shared_context: dict[str, dict[str, Any]] = {}
        # 当前活跃会话 ID
        self._active_session_id: str | None = None
        # 会话过期时间（秒）
        self._session_ttl = session_ttl_seconds
        # 运行中的清理任务
        self._cleanup_task: Any = None

    def get_or_create_session(
        self,
        platform: str,
        user_id: str,
        session_id: str | None = None,
    ) -> Session:
        """获取或创建会话

        Args:
            platform: 平台名称
            user_id: 用户 ID
            session_id: 指定的会话 ID（为 None 则自动生成）

        Returns:
            Session 实例
        """
        key = (platform, user_id)
        if key in self._sessions:
            session = self._sessions[key]
            session.last_activity = time.time()
            return session

        # 创建新会话
        sid = session_id or str(uuid.uuid4())
        session = Session(
            platform=platform,
            user_id=user_id,
            session_id=sid,
            created_at=time.time(),
            last_activity=time.time(),
        )
        self._sessions[key] = session
        logger.info("新会话已创建: platform=%s user=%s session=%s", platform, user_id, sid)
        return session

    def get_session(self, platform: str, user_id: str) -> Session | None:
        """获取指定平台+用户的会话

        Args:
            platform: 平台名称
            user_id: 用户 ID

        Returns:
            Session 实例，不存在则返回 None
        """
        return self._sessions.get((platform, user_id))

    def get_user_sessions(self, user_id: str) -> list[Session]:
        """获取同一用户在所有平台的会话列表

        Args:
            user_id: 用户 ID

        Returns:
            该用户的所有会话列表
        """
        return [
            session
            for (_, uid), session in self._sessions.items()
            if uid == user_id
        ]

    def set_active_session(self, session_id: str) -> None:
        """设置当前活跃会话

        Args:
            session_id: 会话 ID
        """
        self._active_session_id = session_id
        logger.info("活跃会话已切换: %s", session_id)

    @property
    def active_session(self) -> Session | None:
        """获取当前活跃会话"""
        if self._active_session_id is None:
            return None
        for session in self._sessions.values():
            if session.session_id == self._active_session_id:
                return session
        return None

    # ── 跨平台上下文共享 ────────────────────

    def share_context(self, user_id: str, key: str, value: Any) -> None:
        """设置跨平台共享上下文

        同一用户在不同平台接入时，可以共享此上下文。

        Args:
            user_id: 用户 ID
            key: 上下文键
            value: 上下文值
        """
        if user_id not in self._shared_context:
            self._shared_context[user_id] = {}
        self._shared_context[user_id][key] = value
        logger.debug("跨平台上下文已设置: user=%s key=%s", user_id, key)

    def get_shared_context(self, user_id: str, key: str, default: Any = None) -> Any:
        """获取跨平台共享上下文

        Args:
            user_id: 用户 ID
            key: 上下文键
            default: 默认值

        Returns:
            上下文值
        """
        return self._shared_context.get(user_id, {}).get(key, default)

    def get_all_shared_context(self, user_id: str) -> dict[str, Any]:
        """获取用户的所有跨平台共享上下文

        Args:
            user_id: 用户 ID

        Returns:
            共享上下文字典
        """
        return self._shared_context.get(user_id, {})

    def merge_shared_context(self, user_id: str, context: dict[str, Any]) -> None:
        """合并跨平台共享上下文

        Args:
            user_id: 用户 ID
            context: 要合并的上下文字典
        """
        if user_id not in self._shared_context:
            self._shared_context[user_id] = {}
        self._shared_context[user_id].update(context)

    # ── 会话管理 ────────────────────────────

    def close_session(self, platform: str, user_id: str) -> bool:
        """关闭指定会话

        Args:
            platform: 平台名称
            user_id: 用户 ID

        Returns:
            是否成功关闭
        """
        key = (platform, user_id)
        if key in self._sessions:
            del self._sessions[key]
            logger.info("会话已关闭: platform=%s user=%s", platform, user_id)
            return True
        return False

    def cleanup_expired_sessions(self) -> int:
        """清理过期会话

        Returns:
            清理的会话数量
        """
        now = time.time()
        expired_keys = [
            key
            for key, session in self._sessions.items()
            if now - session.last_activity > self._session_ttl
        ]
        for key in expired_keys:
            del self._sessions[key]
        if expired_keys:
            logger.info("已清理 %d 个过期会话", len(expired_keys))
        return len(expired_keys)

    @property
    def session_count(self) -> int:
        """当前会话总数"""
        return len(self._sessions)

    def get_stats(self) -> dict[str, Any]:
        """获取会话管理器统计信息"""
        return {
            "total_sessions": self.session_count,
            "active_session_id": self._active_session_id,
            "shared_context_users": len(self._shared_context),
            "platforms": self._get_platform_stats(),
        }

    def _get_platform_stats(self) -> dict[str, int]:
        """按平台统计会话数"""
        stats: dict[str, int] = {}
        for (platform, _), _ in self._sessions.items():
            stats[platform] = stats.get(platform, 0) + 1
        return stats


__all__ = ["Session", "SessionManager"]