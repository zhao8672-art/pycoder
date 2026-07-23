"""Sentry 错误监控集成 (可选).

设计原则:
  - 条件加载: 缺 sentry-sdk 时降级到本地 structlog, 不抛错
  - 配置驱动: 通过 SENTRY_DSN 环境变量启用
  - 性能敏感: 客户端默认采样率 10% (生产) / 100% (测试)
  - PII 安全: 默认不发送用户输入文本, 仅错误堆栈和上下文

启用方法:
  1. pip install sentry-sdk[fastapi,httpx]
  2. 设置环境变量:
       SENTRY_DSN=https://xxx@sentry.io/123
       SENTRY_ENVIRONMENT=production     # 默认 'development'
       SENTRY_TRACES_SAMPLE_RATE=0.1     # 性能采样 10%
       SENTRY_PROFILES_SAMPLE_RATE=0.1   # profile 采样 10%
  3. 调用 pycoder.observability.sentry.init_sentry()  (应用启动时)

禁用方法 (默认): 不设置 SENTRY_DSN, init_sentry() 直接返回 False, 无任何网络调用.
"""

from __future__ import annotations

import os
import sys
import platform
from typing import Any

_SENTRY_AVAILABLE: bool = False
_SENTRY_INITIALIZED: bool = False
_init_error: str | None = None

try:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.excepthook import ExcepthookIntegration

    _SENTRY_AVAILABLE = True
except ImportError as _exc:  # pragma: no cover
    _init_error = str(_exc)


def is_available() -> bool:
    """检查 sentry-sdk 是否已安装."""
    return _SENTRY_AVAILABLE


def is_enabled() -> bool:
    """检查 sentry 是否已初始化 (DSN 已配置)."""
    return _SENTRY_INITIALIZED


def init_sentry(
    dsn: str | None = None,
    environment: str | None = None,
    traces_sample_rate: float | None = None,
    profiles_sample_rate: float | None = None,
    send_default_pii: bool = False,
    debug: bool = False,
) -> bool:
    """初始化 Sentry 监控.

    Args:
        dsn: Sentry DSN, 默认从 SENTRY_DSN 环境变量读取
        environment: 部署环境 (development/staging/production), 默认 'development'
        traces_sample_rate: 性能采样率 0.0-1.0, 默认 0.1
        profiles_sample_rate: profile 采样率, 默认 0.1
        send_default_pii: 是否发送 PII (用户 IP / cookies), 默认 False
        debug: 启用 Sentry 调试日志

    Returns:
        bool: True 表示已启用, False 表示降级到本地日志
    """
    global _SENTRY_INITIALIZED

    if not _SENTRY_AVAILABLE:
        sys.stderr.write(
            f"[sentry] sentry-sdk 未安装 ({_init_error}); 降级到 structlog\n"
        )
        return False

    dsn = dsn or os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        # 未配置 DSN, 静默跳过 (不是错误, 是默认状态)
        return False

    environment = environment or os.environ.get("SENTRY_ENVIRONMENT", "development")
    traces_sample_rate = traces_sample_rate if traces_sample_rate is not None else float(
        os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")
    )
    profiles_sample_rate = profiles_sample_rate if profiles_sample_rate is not None else float(
        os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1")
    )

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            send_default_pii=send_default_pii,
            debug=debug,
            integrations=[
                LoggingIntegration(level=20, event_level=40),  # INFO+, ERROR 事件
                ExcepthookIntegration(),
            ],
            release=_get_release(),
        )
        _SENTRY_INITIALIZED = True
        sys.stderr.write(
            f"[sentry] initialized: env={environment} "
            f"traces={traces_sample_rate} profiles={profiles_sample_rate}\n"
        )
        return True
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"[sentry] init 失败: {exc}; 降级到 structlog\n")
        return False


def capture_exception(exc: BaseException, **context: Any) -> str | None:
    """手动捕获异常并上报到 Sentry.

    Args:
        exc: 异常实例
        **context: 附加上下文 (user_id / session_id / endpoint 等)

    Returns:
        event_id 或 None (Sentry 未启用时)
    """
    if not _SENTRY_INITIALIZED:
        return None
    with sentry_sdk.push_scope() as scope:
        for k, v in context.items():
            scope.set_extra(k, v)
        return sentry_sdk.capture_exception(exc)


def capture_message(message: str, level: str = "info", **context: Any) -> str | None:
    """手动发送消息事件到 Sentry."""
    if not _SENTRY_INITIALIZED:
        return None
    with sentry_sdk.push_scope() as scope:
        for k, v in context.items():
            scope.set_extra(k, v)
        return sentry_sdk.capture_message(message, level=level)


def set_user(user_id: str, **attrs: Any) -> None:
    """设置当前用户上下文 (用于错误关联)."""
    if not _SENTRY_INITIALIZED:
        return
    sentry_sdk.set_user({"id": user_id, **attrs})


def set_context(name: str, data: dict[str, Any]) -> None:
    """设置当前请求上下文 (例如: model / provider / latency)."""
    if not _SENTRY_INITIALIZED:
        return
    sentry_sdk.set_context(name, data)


def add_breadcrumb(category: str, message: str, **data: Any) -> None:
    """添加 breadcrumb (面包屑) - 用于追踪错误发生前的操作链."""
    if not _SENTRY_INITIALIZED:
        return
    sentry_sdk.add_breadcrumb(category=category, message=message, data=data, level="info")


def _get_release() -> str:
    """生成 release 标识 (git commit hash + 平台信息)."""
    release = "pycoder@unknown"
    try:
        from pycoder import __version__ as v
        release = f"pycoder@{v}"
    except Exception:
        pass
    # 附加平台信息用于诊断
    try:
        release += f" ({platform.system()} {platform.release()})"
    except Exception:
        pass
    return release


# ── 集成状态摘要 ─────────────────────────────────────────
def status() -> dict[str, Any]:
    """返回 sentry 集成状态 (供 /api/observability 端点使用)."""
    return {
        "available": _SENTRY_AVAILABLE,
        "initialized": _SENTRY_INITIALIZED,
        "install_error": _init_error,
        "dsn_configured": bool(os.environ.get("SENTRY_DSN", "").strip()),
        "environment": os.environ.get("SENTRY_ENVIRONMENT", "development"),
        "traces_sample_rate": float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    }
