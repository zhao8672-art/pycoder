"""
Web 搜索 API 路由 — 为前端和 Agent 提供搜索接口

端点:
  GET  /api/web-search?q=xxx&num=5         — 搜索
  GET  /api/web-search/context?q=xxx       — 搜索并返回格式化上下文（RAG 增强）
  GET  /api/web-search/engines             — 列出可用搜索引擎
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from pycoder.plugins.web_search import WebSearchPlugin, get_web_search

router = APIRouter(prefix="/api/web-search", tags=["web-search"])


@router.get("")
async def search(
    q: str = Query(..., description="搜索关键词"),
    num: int = Query(5, ge=1, le=20, description="返回结果数量"),
    engine: str | None = Query(None, description="指定搜索引擎 (bing/serpapi/duckduckgo)"),
):
    """执行 Web 搜索"""
    plugin = get_web_search()
    result = await plugin.search(q, num=num, engine=engine)
    return result.to_dict()


@router.get("/context")
async def search_context(
    q: str = Query(..., description="搜索关键词"),
    num: int = Query(3, ge=1, le=10, description="返回结果数量"),
):
    """搜索并返回格式化上下文文本（用于 RAG 增强）"""
    plugin = get_web_search()
    context = await plugin.search_for_context(q, num=num)
    return {"query": q, "context": context, "has_results": bool(context)}


@router.get("/engines")
async def list_engines():
    """列出可用搜索引擎"""
    plugin = get_web_search()
    return {"engines": plugin._available_engines()}