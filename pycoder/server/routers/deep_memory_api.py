"""深度记忆 API — 四级记忆存储、检索、摘要、统计、语义搜索"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.memory.deep_memory import DeepMemorySystem, get_deep_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory/deep", tags=["deep_memory"])

# ── 请求模型 ──


class StoreRequest(BaseModel):
    """深度记忆存储请求"""

    level: int = Field(..., ge=1, le=4, description="记忆层级 (1=工作, 2=迭代, 3=项目, 4=全局)")
    key: str = Field(..., min_length=1, description="记忆键名")
    value: str = Field(..., min_length=1, description="记忆内容")
    metadata: dict[str, Any] | None = Field(default=None, description="附加元数据")


class RetrieveRequest(BaseModel):
    """深度记忆检索请求"""

    query: str = Field(..., min_length=1, description="搜索查询")
    level: str | int = Field(default="all", description="搜索层级 (all, 1, 2, 3, 4)")
    k: int = Field(default=5, ge=1, le=100, description="返回结果数")


class SummarizeRequest(BaseModel):
    """记忆摘要请求"""

    level: str | int = Field(default="all", description="要摘要的层级 (all, 1, 2, 3, 4)")


class SearchRequest(BaseModel):
    """语义搜索请求"""

    query: str = Field(..., min_length=1, description="搜索查询")
    k: int = Field(default=5, ge=1, le=100, description="返回结果数")


# ── 获取系统实例 ──


def _get_system() -> DeepMemorySystem:
    """获取深度记忆系统实例"""
    return get_deep_memory(project_root=Path.cwd())


# ── 路由 ──


@router.post("/store")
async def store_to_deep_memory(req: StoreRequest):
    """存储到深度记忆

    按指定层级存储记忆条目，支持 1-4 级渐进式记忆。
    """
    system = _get_system()
    try:
        entry = await system.store(
            level=req.level,
            key=req.key,
            value=req.value,
            metadata=req.metadata,
        )
        return {
            "id": entry.id,
            "level": entry.level,
            "key": entry.key,
            "timestamp": entry.timestamp,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/retrieve")
async def retrieve_from_deep_memory(req: RetrieveRequest):
    """从深度记忆检索

    支持多级联合检索，按级别筛选。
    """
    system = _get_system()
    context = await system.retrieve(
        query=req.query,
        level=req.level,
        k=req.k,
    )
    return {
        "entries": [
            {
                "id": e.id,
                "level": e.level,
                "key": e.key,
                "content": e.content[:500],
                "metadata": e.metadata,
            }
            for e in context.entries
        ],
        "source_levels": context.source_levels,
        "total_tokens": context.total_tokens,
        "retrieval_time_ms": context.retrieval_time_ms,
    }


@router.post("/summarize")
async def summarize_memory_level(req: SummarizeRequest):
    """摘要记忆层级

    生成指定层级的记忆摘要，返回各层级摘要文本。
    """
    system = _get_system()
    summaries = await system.summarize(level=req.level)
    return {"summaries": {str(k): v for k, v in summaries.items()}}


@router.get("/stats")
async def get_memory_stats():
    """获取记忆统计信息

    返回所有层级的记忆统计，包括条目数、Token 使用量、ChromaDB 状态等。
    """
    system = _get_system()
    stats = system.get_stats()
    return {
        "level_stats": {str(k): v for k, v in stats.level_stats.items()},
        "total_entries": stats.total_entries,
        "total_size_bytes": stats.total_size_bytes,
        "last_cleanup": stats.last_cleanup,
        "chroma_available": stats.chroma_available,
    }


@router.post("/search")
async def semantic_search(req: SearchRequest):
    """语义搜索记忆

    在 Project 和 Global 级别执行向量语义搜索，辅以迭代级 FTS5 全文搜索。
    """
    system = _get_system()
    context = await system.deep_search(
        query=req.query,
        k=req.k,
    )
    return {
        "entries": [
            {
                "id": e.id,
                "level": e.level,
                "key": e.key,
                "content": e.content[:500],
                "metadata": e.metadata,
            }
            for e in context.entries
        ],
        "source_levels": context.source_levels,
        "total_tokens": context.total_tokens,
        "retrieval_time_ms": context.retrieval_time_ms,
    }


@router.get("/cleanup")
async def cleanup_memory(level: str = Query("all", description="要清理的层级 (all, 1, 2, 3, 4)")):
    """清理过期记忆

    按层级清理过期记忆条目。
    """
    system = _get_system()
    cleaned = await system.cleanup(level=level)
    return {"cleaned": {str(k): v for k, v in cleaned.items()}}