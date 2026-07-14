"""
统一数据库配置 — 所有 SQLite 模块共享单文件

从 session_store / knowledge_base / metrics_tracker 三库分立
迁移到 ~/.pycoder/unified.db 统一数据库。

环境变量:
    PYCODER_DB_PATH  → 统一路径覆盖
    PYCODER_SESSIONS_DB → session_store 专用覆盖（legacy）
"""
import os
from pathlib import Path

UNIFIED_DB = Path(os.environ.get(
    "PYCODER_DB_PATH",
    str(Path.home() / ".pycoder" / "unified.db"),
))


def get_db_path(module: str = "") -> Path:
    """获取统一数据库路径"""
    if module == "sessions":
        return Path(os.environ.get(
            "PYCODER_SESSIONS_DB",
            str(UNIFIED_DB),
        ))
    return UNIFIED_DB
