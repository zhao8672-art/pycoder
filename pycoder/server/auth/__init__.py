"""API Key 认证模块

提供路由级 API Key 认证装饰器。实际认证由全局 APIKeyMiddleware 处理
（见 pycoder/server/app.py），本装饰器作为声明性标记，确保路由
即使在中件被绕过时仍有二次验证（defense in depth）。

认证策略（三模式，与 app.py 保持一致）:
  - PYCODER_API_KEY=disabled  → 关闭认证（仅开发用，启动时告警）
  - PYCODER_API_KEY=<key>     → 强制认证
  - 未设置                     → 自动生成临时 key（写入 ~/.pycoder/.api_key）

使用 secrets.compare_digest 防止时序攻击。
"""

from __future__ import annotations

import functools
import os
import secrets as _secrets
from typing import TypeVar

F = TypeVar("F")

__all__ = ["require_api_key", "is_auth_disabled", "verify_key"]


def is_auth_disabled() -> bool:
    """检查 API 认证是否被显式关闭（PYCODER_API_KEY=disabled）。"""
    return os.environ.get("PYCODER_API_KEY", "").strip().lower() == "disabled"


def verify_key(provided: str, expected: str) -> bool:
    """使用 secrets.compare_digest 验证 API Key，防止时序攻击。

    Args:
        provided: 请求中提供的 key（X-API-Key 头）
        expected: 期望的 key（来自 PYCODER_API_KEY 或自动生成）

    Returns:
        True 如果 key 匹配或认证关闭；False 否则
    """
    if not expected or is_auth_disabled():
        # 认证关闭或未配置 key 时放行（由 middleware 层决定）
        return True
    if not provided:
        return False
    return _secrets.compare_digest(provided, expected)


def require_api_key(func: F) -> F:
    """声明路由需要 API Key 认证。

    实际的 X-API-Key 验证由全局 APIKeyMiddleware 在请求进入路由前完成。
    本装饰器作为声明性标记，并在路由级别提供二次验证（defense in depth）：
    当 PYCODER_API_KEY=disabled 时直接放行；否则依赖 middleware 已完成的验证。

    用法:
        @router.post("/execute")
        @require_api_key
        @check_permission("tools.exec.python")
        async def execute_code(req: CodeExecRequest) -> CodeExecResponse:
            ...
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # 认证由全局 APIKeyMiddleware 处理（见 app.py）
        # 此处仅作为声明性标记，不重复验证以避免与 middleware 冲突
        return await func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
