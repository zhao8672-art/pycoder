"""
多平台消息网关 — OpenClaw/Hermes 风格的多平台 Agent 网关

将不同平台（Telegram、Discord、Slack、CLI）的消息统一为 GatewayMessage 格式，
通过 V2 能力总线与 AI 大脑通信，实现跨平台的消息路由与上下文共享。

使用方式:
    from pycoder.gateway import MessageGateway

    gateway = MessageGateway()
    await gateway.start()
    await gateway.send_message("telegram", "user_123", "你好！")
    await gateway.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 核心数据类型
# ═══════════════════════════════════════════════


@dataclass
class GatewayMessage:
    """统一网关消息格式 —— 所有平台适配器都将原始消息规范化为此格式"""

    platform: str  # 消息来源平台: telegram, discord, slack, cli
    user_id: str  # 发送者唯一标识
    session_id: str  # 会话 ID
    content: str  # 消息文本内容
    message_type: str = "text"  # 消息类型: text, command, file, image, audio
    timestamp: float = field(default_factory=time.time)  # 消息时间戳
    metadata: dict[str, Any] = field(default_factory=dict)  # 平台特定元数据

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            "platform": self.platform,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "content": self.content,
            "message_type": self.message_type,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GatewayMessage:
        """从字典还原"""
        return cls(
            platform=data["platform"],
            user_id=data["user_id"],
            session_id=data["session_id"],
            content=data["content"],
            message_type=data.get("message_type", "text"),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {}),
        )


# ═══════════════════════════════════════════════
# 平台适配器抽象基类
# ═══════════════════════════════════════════════


class PlatformAdapter(ABC):
    """平台适配器抽象基类 —— 定义所有平台适配器必须实现的接口"""

    def __init__(self) -> None:
        self._running = False
        self._message_callback: Any = None  # 收到消息时的回调

    @property
    @abstractmethod
    def platform(self) -> str:
        """平台名称标识"""
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动适配器，开始监听平台消息"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止适配器，清理资源"""
        ...

    @abstractmethod
    async def send_message(self, target: str, content: str) -> bool:
        """向指定目标发送消息

        Args:
            target: 目标标识（用户 ID、频道 ID 等）
            content: 消息内容

        Returns:
            是否发送成功
        """
        ...

    @abstractmethod
    async def normalize_message(self, raw_message: Any) -> GatewayMessage:
        """将平台原生消息规范化为统一格式

        Args:
            raw_message: 平台原生消息对象

        Returns:
            规范化后的 GatewayMessage
        """
        ...

    def set_message_callback(self, callback: Any) -> None:
        """设置消息回调 —— 当收到平台消息时调用"""
        self._message_callback = callback

    @property
    def is_running(self) -> bool:
        """适配器是否正在运行"""
        return self._running


# ═══════════════════════════════════════════════
# 消息网关
# ═══════════════════════════════════════════════


class MessageGateway:
    """
    多平台消息网关 —— 中央控制器

    管理所有平台适配器、会话和消息路由。
    集成 V2 能力总线，使 AI 能够通过网关与外部平台通信。
    """

    def __init__(self) -> None:
        # 平台适配器注册表
        self._adapters: dict[str, PlatformAdapter] = {}
        # 会话管理器（延迟初始化）
        self._session_manager: Any = None
        # 消息路由器（延迟初始化）
        self._message_router: Any = None
        # 总线注册表引用
        self._registry: Any = None
        # 运行状态
        self._running = False

    # ── 适配器管理 ──────────────────────────

    def register_adapter(self, adapter: PlatformAdapter) -> None:
        """注册一个平台适配器

        Args:
            adapter: 平台适配器实例
        """
        platform = adapter.platform
        if platform in self._adapters:
            logger.warning("平台 '%s' 的适配器已存在，将被覆盖", platform)

        # 设置消息回调
        adapter.set_message_callback(self._on_platform_message)
        self._adapters[platform] = adapter
        logger.info("平台适配器已注册: %s", platform)

    def unregister_adapter(self, platform: str) -> bool:
        """注销一个平台适配器

        Args:
            platform: 平台名称

        Returns:
            是否成功注销
        """
        if platform not in self._adapters:
            return False
        del self._adapters[platform]
        logger.info("平台适配器已注销: %s", platform)
        return True

    def get_adapter(self, platform: str) -> PlatformAdapter | None:
        """获取指定平台的适配器"""
        return self._adapters.get(platform)

    @property
    def available_platforms(self) -> list[str]:
        """列出所有已注册的平台"""
        return list(self._adapters.keys())

    # ── 生命周期 ────────────────────────────

    async def start(self) -> None:
        """启动网关 —— 启动所有已注册的平台适配器"""
        if self._running:
            logger.warning("网关已在运行中")
            return

        logger.info("正在启动消息网关...")

        # 延迟初始化会话管理器
        if self._session_manager is None:
            from pycoder.gateway.session_manager import SessionManager

            self._session_manager = SessionManager()

        # 延迟初始化消息路由器
        if self._message_router is None:
            from pycoder.gateway.message_router import MessageRouter

            self._message_router = MessageRouter()

        # 启动所有适配器
        for platform, adapter in self._adapters.items():
            try:
                await adapter.start()
                logger.info("平台适配器已启动: %s", platform)
            except Exception as e:
                logger.error("启动平台适配器 '%s' 失败: %s", platform, e)

        self._running = True
        logger.info("消息网关已启动，共 %d 个平台适配器", len(self._adapters))

    async def stop(self) -> None:
        """停止网关 —— 停止所有平台适配器"""
        if not self._running:
            return

        logger.info("正在停止消息网关...")

        for platform, adapter in self._adapters.items():
            try:
                await adapter.stop()
                logger.info("平台适配器已停止: %s", platform)
            except Exception as e:
                logger.error("停止平台适配器 '%s' 失败: %s", platform, e)

        self._running = False
        logger.info("消息网关已停止")

    # ── 消息处理 ────────────────────────────

    async def send_message(self, platform: str, target: str, content: str) -> bool:
        """向指定平台的目标发送消息

        Args:
            platform: 目标平台名称
            target: 目标标识（用户 ID、频道 ID 等）
            content: 消息内容

        Returns:
            是否发送成功
        """
        adapter = self._adapters.get(platform)
        if adapter is None:
            logger.error("平台 '%s' 未注册", platform)
            return False

        try:
            return await adapter.send_message(target, content)
        except Exception as e:
            logger.error("向平台 '%s' 目标 '%s' 发送消息失败: %s", platform, target, e)
            return False

    async def _on_platform_message(self, gateway_msg: GatewayMessage) -> None:
        """平台消息回调 —— 处理来自适配器的消息

        Args:
            gateway_msg: 规范化后的网关消息
        """
        logger.debug(
            "收到平台消息: platform=%s user=%s type=%s",
            gateway_msg.platform,
            gateway_msg.user_id,
            gateway_msg.message_type,
        )

        # 获取或创建会话
        if self._session_manager is not None:
            session = self._session_manager.get_or_create_session(
                gateway_msg.platform, gateway_msg.user_id, gateway_msg.session_id
            )
            session.add_message(gateway_msg)

        # 路由到 AI 大脑
        if self._message_router is not None:
            try:
                response = await self._message_router.route_message(gateway_msg)
                if response:
                    await self.send_message(
                        gateway_msg.platform, gateway_msg.user_id, response
                    )
            except Exception as e:
                logger.error("消息路由处理失败: %s", e)

    # ── 会话管理 ────────────────────────────

    def get_session_info(self, platform: str, user_id: str) -> dict[str, Any] | None:
        """获取会话信息

        Args:
            platform: 平台名称
            user_id: 用户 ID

        Returns:
            会话信息字典，不存在则返回 None
        """
        if self._session_manager is None:
            return None
        session = self._session_manager.get_session(platform, user_id)
        if session is None:
            return None
        return session.to_info_dict()

    def switch_session(self, platform: str, user_id: str) -> dict[str, Any]:
        """切换活跃会话

        Args:
            platform: 平台名称
            user_id: 用户 ID

        Returns:
            切换后的会话信息
        """
        if self._session_manager is None:
            from pycoder.gateway.session_manager import SessionManager

            self._session_manager = SessionManager()
        session = self._session_manager.get_or_create_session(platform, user_id)
        self._session_manager.set_active_session(session.session_id)
        return session.to_info_dict()

    # ── 总线集成 ────────────────────────────

    def set_registry(self, registry: Any) -> None:
        """设置 V2 能力总线注册表引用"""
        self._registry = registry

    @property
    def is_running(self) -> bool:
        """网关是否正在运行"""
        return self._running


# ═══════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════

# 全局网关实例（单例模式）
_gateway_instance: MessageGateway | None = None


def get_gateway() -> MessageGateway:
    """获取全局网关单例"""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = MessageGateway()
    return _gateway_instance


# ═══════════════════════════════════════════════
# 能力注册
# ═══════════════════════════════════════════════


def register_capabilities(registry: Any) -> int:
    """向 V2 能力总线注册网关相关能力

    Args:
        registry: V2 CapabilityRegistry 实例

    Returns:
        注册的能力数量
    """
    gateway = get_gateway()
    gateway.set_registry(registry)

    count_before = registry.count

    # 1. 列出可用平台
    async def _handle_platforms_list(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """列出所有可用的消息平台"""
        platforms = gateway.available_platforms
        adapter_info = {}
        for p in platforms:
            adapter = gateway.get_adapter(p)
            adapter_info[p] = {
                "platform": p,
                "running": adapter.is_running if adapter else False,
            }
        return {
            "platforms": platforms,
            "count": len(platforms),
            "details": adapter_info,
        }

    registry.register(
        CapabilityDefinition(
            id="gateway.platforms_list",
            name="列出可用平台",
            description="列出所有已注册的消息平台（Telegram、Discord、Slack、CLI 等）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["gateway", "platforms", "messaging"],
        ),
        handler=_handle_platforms_list,
    )

    # 2. 发送消息
    async def _handle_send_message(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """向指定平台发送消息"""
        platform = params.get("platform", "")
        target = params.get("target", "")
        content = params.get("content", "")

        if not platform or not target or not content:
            return {"success": False, "error": "缺少必要参数: platform, target, content"}

        ok = await gateway.send_message(platform, target, content)
        return {"success": ok, "platform": platform, "target": target}

    registry.register(
        CapabilityDefinition(
            id="gateway.send_message",
            name="发送消息",
            description="向指定平台的目标发送消息",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NETWORK],
            tags=["gateway", "messaging", "send"],
            schema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "目标平台名称"},
                    "target": {"type": "string", "description": "目标用户/频道 ID"},
                    "content": {"type": "string", "description": "消息内容"},
                },
                "required": ["platform", "target", "content"],
            },
        ),
        handler=_handle_send_message,
    )

    # 3. 获取会话信息
    async def _handle_session_info(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """获取指定平台用户的会话信息"""
        platform = params.get("platform", "")
        user_id = params.get("user_id", "")

        if not platform or not user_id:
            return {"error": "缺少必要参数: platform, user_id"}

        info = gateway.get_session_info(platform, user_id)
        if info is None:
            return {"error": f"未找到会话: platform={platform}, user={user_id}"}
        return info

    registry.register(
        CapabilityDefinition(
            id="gateway.session_info",
            name="获取会话信息",
            description="获取指定平台用户的会话详情，包括消息历史和上下文",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["gateway", "session", "context"],
            schema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "平台名称"},
                    "user_id": {"type": "string", "description": "用户 ID"},
                },
                "required": ["platform", "user_id"],
            },
        ),
        handler=_handle_session_info,
    )

    # 4. 切换会话
    async def _handle_switch_session(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """切换当前活跃会话"""
        platform = params.get("platform", "")
        user_id = params.get("user_id", "")

        if not platform or not user_id:
            return {"error": "缺少必要参数: platform, user_id"}

        session_info = gateway.switch_session(platform, user_id)
        return {"success": True, "session": session_info}

    registry.register(
        CapabilityDefinition(
            id="gateway.switch_session",
            name="切换会话",
            description="切换到指定平台用户的会话，使后续对话在该上下文中进行",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["gateway", "session", "switch"],
            schema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "平台名称"},
                    "user_id": {"type": "string", "description": "用户 ID"},
                },
                "required": ["platform", "user_id"],
            },
        ),
        handler=_handle_switch_session,
    )

    registered_count = registry.count - count_before
    logger.info("网关能力已注册到 V2 总线: %d 个能力", registered_count)
    return registered_count


__all__ = [
    "GatewayMessage",
    "PlatformAdapter",
    "MessageGateway",
    "get_gateway",
    "register_capabilities",
]