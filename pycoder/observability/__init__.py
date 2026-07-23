"""可观测性集成 (Sentry / OpenTelemetry 等).

提供可选的错误监控和链路追踪能力, 所有集成均为条件加载:
- sentry-sdk 未安装时降级到 structlog, 不抛错
- 不设置 SENTRY_DSN 时 init_sentry() 直接返回 False, 不发送任何数据
"""

from __future__ import annotations

from typing import Any

from .sentry import (
    add_breadcrumb,
    capture_exception,
    capture_message,
    init_sentry,
    is_available,
    is_enabled,
    set_context,
    set_user,
    status,
)

__all__ = [
    "init_sentry",
    "capture_exception",
    "capture_message",
    "set_user",
    "set_context",
    "add_breadcrumb",
    "is_available",
    "is_enabled",
    "status",
]
