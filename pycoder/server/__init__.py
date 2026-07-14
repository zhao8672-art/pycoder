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

from pycoder.server.app import app
from pycoder.server.app_lifecycle import _server_start, get_health_info, get_uptime, run_server
from pycoder.server.session_store import (
    Message,
    Session,
    SessionStore,
    get_session_store,
)

__all__ = [
    "app",
    "run_server",
    "SessionStore",
    "Session",
    "Message",
    "get_session_store",
]
