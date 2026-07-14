"""会话记忆模块 — 跨会话上下文自动保存与恢复"""

from __future__ import annotations

from typing import Any

from pycoder.memory.session_memory import SessionMemory, SessionMemoryEngine

__all__ = [
    "SessionMemoryEngine",
    "SessionMemory",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册会话记忆能力"""
    from pathlib import Path

    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    engine = SessionMemoryEngine(Path.cwd())

    def _get_session_info(params: dict, ctx: dict) -> dict:
        session = engine.current_session
        if not session:
            return {"session": None}
        return {
            "session": {
                "session_id": session.session_id,
                "workspace": session.workspace,
                "created_at": session.created_at,
                "summary": session.summary,
                "key_decisions": session.key_decisions,
                "active_files": session.active_files,
                "task_progress": session.task_progress,
                "message_count": session.message_count,
            }
        }

    def _record_decision(params: dict, ctx: dict) -> dict:
        engine.record_decision(params["decision"])
        return {"success": True}

    def _record_file_activity(params: dict, ctx: dict) -> dict:
        engine.record_file_activity(params["file_path"])
        return {"success": True}

    def _get_summary(params: dict, ctx: dict) -> dict:
        session = engine.current_session
        return {"summary": session.summary if session else ""}

    def _search_sessions(params: dict, ctx: dict) -> dict:
        results = engine.search_sessions(params.get("query", ""))
        return {"sessions": results}

    registry.register(
        CapabilityDefinition(
            id="memory.session_info",
            name="获取会话信息",
            description="获取当前会话的记忆信息（决策、活跃文件、进度）",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["memory", "session", "会话", "记忆"],
        ),
        handler=_get_session_info,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.record_decision",
            name="记录决策",
            description="记录会话中的关键决策，用于跨会话记忆",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.SELF_MODIFY],
            schema={
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "description": "决策内容"},
                },
                "required": ["decision"],
            },
            tags=["memory", "decision", "record", "决策"],
        ),
        handler=_record_decision,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.record_file_activity",
            name="记录文件活动",
            description="记录活跃文件，用于跨会话上下文恢复",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.SELF_MODIFY],
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                },
                "required": ["file_path"],
            },
            tags=["memory", "file", "activity", "文件"],
        ),
        handler=_record_file_activity,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.get_summary",
            name="获取记忆摘要",
            description="获取当前会话的 LLM 生成摘要",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["memory", "summary", "摘要"],
        ),
        handler=_get_summary,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.search_sessions",
            name="搜索历史会话",
            description="搜索历史会话记录",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
            },
            tags=["memory", "search", "history", "搜索"],
        ),
        handler=_search_sessions,
    )
