"""通知系统 — 管理应用内通知和外部通知推送"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_capabilities(registry=None) -> None:
    """注册所有通知能力到 V2 能力总线

    Args:
        registry: 可选的能力注册表（兼容 V2 引擎传入；内部使用单例）
    """
    _register_in_app_notifications()
    _register_email_notifications()
    _register_webhook_notifications()
    _register_desktop_notifications()
    _register_notification_preferences()


def _register_in_app_notifications() -> None:
    """注册应用内通知能力"""
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
                id="notify.in_app.send",
                category=CapabilityCategory.SYSTEM,
                description="发送应用内通知",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_in_app_send,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="notify.in_app.list",
                category=CapabilityCategory.SYSTEM,
                description="列出应用内通知",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_in_app_list,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="notify.in_app.mark_read",
                category=CapabilityCategory.SYSTEM,
                description="标记通知为已读",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_in_app_mark_read,
            )
        )

        logger.debug("in_app_notification_capabilities_registered")
    except Exception as e:
        logger.warning("in_app_notification_register_failed: %s", e)


def _register_email_notifications() -> None:
    """注册邮件通知能力"""
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
                id="notify.email.send",
                category=CapabilityCategory.SYSTEM,
                description="发送邮件通知",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NETWORK},
                trust_level=TrustLevel.SYSTEM_ACCESS,
                handler=_handle_email_send,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="notify.email.config",
                category=CapabilityCategory.SYSTEM,
                description="配置邮件通知设置",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.SYSTEM_ACCESS,
                handler=_handle_email_config,
            )
        )

        logger.debug("email_notification_capabilities_registered")
    except Exception as e:
        logger.warning("email_notification_register_failed: %s", e)


def _register_webhook_notifications() -> None:
    """注册 Webhook 通知能力"""
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
                id="notify.webhook.send",
                category=CapabilityCategory.SYSTEM,
                description="发送 Webhook 通知",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NETWORK},
                trust_level=TrustLevel.SYSTEM_ACCESS,
                handler=_handle_webhook_send,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="notify.webhook.register",
                category=CapabilityCategory.SYSTEM,
                description="注册 Webhook URL",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.SYSTEM_ACCESS,
                handler=_handle_webhook_register,
            )
        )

        logger.debug("webhook_notification_capabilities_registered")
    except Exception as e:
        logger.warning("webhook_notification_register_failed: %s", e)


def _register_desktop_notifications() -> None:
    """注册桌面通知能力"""
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
                id="notify.desktop.send",
                category=CapabilityCategory.SYSTEM,
                description="发送桌面系统通知",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_desktop_send,
            )
        )

        logger.debug("desktop_notification_capabilities_registered")
    except Exception as e:
        logger.warning("desktop_notification_register_failed: %s", e)


def _register_notification_preferences() -> None:
    """注册通知偏好设置能力"""
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
                id="notify.preferences.get",
                category=CapabilityCategory.SYSTEM,
                description="获取通知偏好设置",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_preferences_get,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="notify.preferences.update",
                category=CapabilityCategory.SYSTEM,
                description="更新通知偏好设置",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_preferences_update,
            )
        )

        logger.debug("notification_preferences_capabilities_registered")
    except Exception as e:
        logger.warning("notification_preferences_register_failed: %s", e)


# ── 处理器实现 ──


async def _handle_in_app_send(args: dict[str, Any]) -> dict[str, Any]:
    """处理 in_app send"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    await mgr.send_in_app(
        title=args.get("title", ""),
        message=args.get("message", ""),
        level=args.get("level", "info"),
    )
    return {"success": True}


async def _handle_in_app_list(args: dict[str, Any]) -> dict[str, Any]:
    """处理 in_app list"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    notifications = await mgr.list_in_app(
        limit=args.get("limit", 50),
        unread_only=args.get("unread_only", False),
    )
    return {"success": True, "notifications": notifications}


async def _handle_in_app_mark_read(args: dict[str, Any]) -> dict[str, Any]:
    """处理 in_app mark_read"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    await mgr.mark_read(notification_id=args.get("notification_id", ""))
    return {"success": True}


async def _handle_email_send(args: dict[str, Any]) -> dict[str, Any]:
    """处理 email send"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    result = await mgr.send_email(
        to=args.get("to", ""),
        subject=args.get("subject", ""),
        body=args.get("body", ""),
    )
    return {"success": result}


async def _handle_email_config(args: dict[str, Any]) -> dict[str, Any]:
    """处理 email config"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    await mgr.configure_email(
        smtp_server=args.get("smtp_server", ""),
        smtp_port=args.get("smtp_port", 587),
        username=args.get("username", ""),
        password=args.get("password", ""),
    )
    return {"success": True}


async def _handle_webhook_send(args: dict[str, Any]) -> dict[str, Any]:
    """处理 webhook send"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    result = await mgr.send_webhook(
        url=args.get("url", ""),
        payload=args.get("payload", {}),
    )
    return {"success": result}


async def _handle_webhook_register(args: dict[str, Any]) -> dict[str, Any]:
    """处理 webhook register"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    await mgr.register_webhook(
        url=args.get("url", ""),
        events=args.get("events", []),
    )
    return {"success": True}


async def _handle_desktop_send(args: dict[str, Any]) -> dict[str, Any]:
    """处理 desktop send"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    await mgr.send_desktop(
        title=args.get("title", ""),
        message=args.get("message", ""),
    )
    return {"success": True}


async def _handle_preferences_get(args: dict[str, Any]) -> dict[str, Any]:
    """处理 preferences get"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    prefs = await mgr.get_preferences()
    return {"success": True, "preferences": prefs}


async def _handle_preferences_update(args: dict[str, Any]) -> dict[str, Any]:
    """处理 preferences update"""
    from pycoder.notify import NotificationManager

    mgr = NotificationManager()
    await mgr.update_preferences(
        email_enabled=args.get("email_enabled"),
        desktop_enabled=args.get("desktop_enabled"),
        webhook_enabled=args.get("webhook_enabled"),
    )
    return {"success": True}
