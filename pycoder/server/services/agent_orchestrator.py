"""
Agent Orchestrator — 兼容层（已迁移到 unified_agent.py）

保留此文件用于向后兼容，实际执行逻辑在 UnifiedAgentEngine 中。
"""

from __future__ import annotations

import os
from pathlib import Path

# ══════════════════════════════════════════════════════════
# 向后兼容导出 — 从 unified_agent 转发
# ══════════════════════════════════════════════════════════
from pycoder.server.services.unified_agent import UnifiedAgentEngine, agent_chat_stream

MAX_ITERATIONS = 15
TOOL_TIMEOUT = 30
MAX_RETRIES = 2

ALLOWED_COMMANDS: list[str] = [
    "python",
    "python3",
    "node",
    "npm",
    "npx",
    "pip",
    "pip3",
    "uv",
    "uvx",
    "git",
    "pytest",
    "coverage",
    "ruff",
    "black",
    "isort",
    "mypy",
    "uvicorn",
    "fastapi",
    "flask",
    "streamlit",
    "docker",
    "ls",
    "dir",
    "echo",
    "cat",
    "type",
    "pwd",
    "cd",
    "mkdir",
    "cp",
    "copy",
]

WORKSPACE = Path(os.environ.get("PYCODER_WORKSPACE", str(Path(__file__).resolve().parents[3])))

AGENT_SYSTEM_PROMPT = """（已迁移到 UnifiedAgentEngine）"""

__all__ = [
    "UnifiedAgentEngine",
    "agent_chat_stream",
    "MAX_ITERATIONS",
    "TOOL_TIMEOUT",
    "MAX_RETRIES",
    "ALLOWED_COMMANDS",
    "WORKSPACE",
    "AGENT_SYSTEM_PROMPT",
]
