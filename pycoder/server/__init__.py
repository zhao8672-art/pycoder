"""
PyCoder App Server 模块

提供:
- FastAPI + WebSocket 服务
- SQLite 会话持久化
- TUI/VS Code 共享会话

启动方式:
    python -m pycoder --server
    python -m pycoder --server --port 8423
"""

from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────────────────
# 阶段 0 架构升级：app 改为 lazy 暴露
#
# 原实现：
#     from pycoder.server.app import app
#
# 问题：
#     1. 任何 `import pycoder.server` 都会触发 server.app 完整加载
#        （进而触发 60+ 路由模块 import、生命周期钩子注册、API 密钥同步等）
#     2. server.app 内部 import 的部分服务/工具模块反过来又 `from .app import ...`，
#        形成循环依赖触发器
#     3. 单元测试、CLI、子工具脚本只需要 session_store/router/auth 能力，
#        不应被迫加载 FastAPI 实例
#
# 新实现：
#     使用 PEP 562 的模块 __getattr__ 协议，仅在 `pycoder.server.app` 被显式访问
#     时才加载 `app` 对象。
# ──────────────────────────────────────────────────────────


def __getattr__(name: str) -> Any:
    """PEP 562 模块级懒加载：仅在被访问时才加载"""
    if name == "app":
        from pycoder.server.app import app as _app

        return _app
    if name in ("run_server", "_server_start", "get_health_info", "get_uptime"):
        from pycoder.server import app_lifecycle

        return getattr(app_lifecycle, name)
    if name in ("Message", "Session", "SessionStore", "get_session_store"):
        from pycoder.server import session_store

        return getattr(session_store, name)
    raise AttributeError(f"module 'pycoder.server' has no attribute {name!r}")


__all__ = [
    "app",
    "run_server",
    "SessionStore",
    "Session",
    "Message",
    "get_session_store",
]
