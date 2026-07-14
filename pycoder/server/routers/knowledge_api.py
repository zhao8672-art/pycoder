"""知识更新 API — 知识源管理、手动触发更新、知识检索"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from pycoder.knowledge.knowledge_fetcher import KnowledgeFetcher, KnowledgeSource
from pycoder.knowledge.knowledge_index import KnowledgeIndex
from pycoder.knowledge.update_scheduler import KnowledgeUpdateScheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_fetcher = KnowledgeFetcher()
_index = KnowledgeIndex()
_scheduler = KnowledgeUpdateScheduler(_fetcher, _index)


@router.get("/sources")
async def list_sources():
    """列出所有知识源"""
    sources = _fetcher.list_sources()
    return {
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "category": s.category,
                "update_interval_hours": s.update_interval_hours,
                "last_fetched": s.last_fetched,
            }
            for s in sources
        ]
    }


@router.post("/sources")
async def add_source(req: dict):
    """添加自定义知识源"""
    source = KnowledgeSource(
        id=req.get("id", ""),
        name=req.get("name", ""),
        url=req.get("url", ""),
        category=req.get("category", "custom"),
        update_interval_hours=req.get("update_interval_hours", 24),
    )
    if not source.id or not source.name or not source.url:
        raise HTTPException(status_code=400, detail="缺少必填参数: id, name, url")
    _fetcher.register_source(source)
    return {"success": True, "source_id": source.id}


@router.delete("/sources/{source_id}")
async def remove_source(source_id: str):
    """移除知识源"""
    if not _fetcher.remove_source(source_id):
        raise HTTPException(status_code=404, detail="知识源不存在")
    return {"success": True}


@router.post("/sources/{source_id}/fetch")
async def trigger_fetch(source_id: str):
    """手动触发知识源更新"""
    source = _fetcher.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="知识源不存在")

    try:
        chunks = await _fetcher.fetch_source(source)
        new_count = _index.index_chunks(chunks)
        return {"success": True, "source_id": source_id, "new_chunks": new_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"抓取失败: {e}")


@router.get("/search")
async def search_knowledge(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(5, ge=1, le=20),
    category: str | None = Query(None, description="按类别筛选"),
):
    """语义搜索知识库"""
    results = _index.search(q, top_k=top_k, category=category)
    return {"query": q, "results": results}


@router.get("/stats")
async def get_stats():
    """获取知识库统计信息"""
    return _index.get_stats()