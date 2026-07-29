"""网关能力域 — 将 gateway/ 消息路由包装为 V2 能力

能力清单：
    gateway.platforms.list  — 列出支持的平台
    gateway.message.send    — 发送消息到指定平台
    gateway.session.info    — 查询会话信息
    gateway.session.switch   — 切换会话
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_gateway_capabilities() -> None:
    """注册网关域能力到 V2 能力总线"""
    try:
        from pycoder.bus.protocol import (
            CapabilityCategory,
            CapabilityDefinition,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )
        from pycoder.bus.registry import CapabilityRegistry

        registry = CapabilityRegistry.get_instance()

        registry.register(
            CapabilityDefinition(
                id="gateway.platforms.list",
                category=CapabilityCategory.SYSTEM,
                description="列出所有支持的消息平台",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_platforms_list,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="gateway.message.send",
                category=CapabilityCategory.SYSTEM,
                description="发送消息到指定平台",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NETWORK},
                trust_level=TrustLevel.SYSTEM_ACCESS,
                handler=_handle_message_send,
            )
        )

        logger.info("gateway_capabilities_registered: count=2")
    except Exception as e:
        logger.warning("gateway_capabilities_register_failed: %s", e)


async def _handle_platforms_list(args: dict[str, Any]) -> dict[str, Any]:
    """处理 gateway.platforms.list"""
    from pycoder.gateway import get_gateway

    gw = get_gateway()
    platforms = gw.list_platforms() if gw else []
    return {"success": True, "platforms": platforms}


async def _handle_message_send(args: dict[str, Any]) -> dict[str, Any]:
    """处理 gateway.message.send"""
    from pycoder.gateway import get_gateway

    gw = get_gateway()
    if not gw:
        return {"success": False, "error": "网关未初始化"}
    result = await gw.send_message(
        platform=args.get("platform", ""),
        message=args.get("message", ""),
        channel=args.get("channel"),
    )
    return {"success": True, "result": result}
