"""会话记忆管理 API — 历史会话列表、搜索、导出、删除"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from pycoder.memory.session_memory import SessionMemoryEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])

_engine = SessionMemoryEngine(Path.cwd())


@router.get("/sessions")
async def list_sessions(limit: int = Query(20, ge=1, le=100)):
    """列出历史会话（按时间倒序）"""
    return {"sessions": _engine.list_sessions(limit)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取指定会话详情"""
    data = _engine.get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="会话不存在")
    return data


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话记忆"""
    if not _engine.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True}


@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """导出会话为 Markdown"""
    md = _engine.export_session(session_id)
    if md is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"markdown": md}


@router.get("/current")
async def get_current_session():
    """获取当前会话状态"""
    session = _engine.current_session
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


@router.get("/search")
async def search_memories(q: str = Query("", description="搜索关键词"), limit: int = Query(10, ge=1, le=50)):
    """搜索会话记忆"""
    return {"sessions": _engine.search_sessions(q, limit)}