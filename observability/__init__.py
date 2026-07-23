"""PyCoder 错误监控与日志 - 根级入口.

支持 Sentry 集成 (条件加载) + 结构化日志 (structlog).
完整实现位于 `pycoder.observability` 子包, 此处重导出以便根级 `import observability` 访问.
"""

from pycoder.observability import (
    init_sentry,
    capture_exception,
    capture_message,
    set_user,
    set_context,
    add_breadcrumb,
    is_available as is_sentry_available,
    is_enabled as is_sentry_enabled,
    status as sentry_status,
)

__version__ = "0.5.0"
__all__ = [
    "init_sentry",
    "capture_exception",
    "capture_message",
    "set_user",
    "set_context",
    "add_breadcrumb",
    "is_sentry_available",
    "is_sentry_enabled",
    "sentry_status",
    "__version__",
]
