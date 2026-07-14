"""team_orchestrator — 兼容性重导出层（H2）

.. deprecated:: P1-1 / H2
    旧 ``TeamOrchestrator`` 上帝对象已在 P3-1 阶段删除。
    Agent 执行原语已迁移到 ``pycoder.server.services.team.agent_tool_loop``。
    团队编排请使用 ``pycoder.server.services.team.TeamCoordinator``。

本文件仅保留向后兼容的 re-export，避免破坏旧脚本（如 _verify_phase1.py）。
新代码不应再从本模块导入任何内容。
"""

from __future__ import annotations

# 向后兼容：旧脚本可能从本模块导入这些函数
from pycoder.server.services.team.agent_tool_loop import (  # noqa: F401
    AGENT_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    _agent_tool_loop,
    _execute_agent_with_files,
    _parse_files_from_response,
    _team_execute_tool,
    _team_parse_tool_calls,
    review_code,
)

__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "REVIEW_SYSTEM_PROMPT",
    "_parse_files_from_response",
    "_team_execute_tool",
    "_team_parse_tool_calls",
    "_agent_tool_loop",
    "_execute_agent_with_files",
    "review_code",
]
