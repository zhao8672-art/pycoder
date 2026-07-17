"""
联网搜索 REST API 路由

提供 HTTP 端点供前端直接调用搜索/抓取功能。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/web/fetch")
async def web_fetch(req: dict):
    """获取网页内容"""
    from pycoder.web.tool_definitions import execute_web_fetch

    url = req.get("url", "")
    if not url:
        return {"success": False, "error": "URL 不能为空"}
    extract = req.get("extract_text", True)
    return await execute_web_fetch(url, extract)


@router.post("/api/web/search")
async def web_search(req: dict):
    """联网搜索"""
    from pycoder.web.tool_definitions import execute_web_search

    query = req.get("query", "")
    if not query:
        return {"success": False, "error": "搜索关键词不能为空"}
    num = min(max(int(req.get("num_results", 5)), 1), 10)
    return await execute_web_search(query, num)


@router.post("/api/web/screenshot")
async def web_screenshot(req: dict):
    """网页截图"""
    from pycoder.web.tool_definitions import execute_web_screenshot

    url = req.get("url", "")
    if not url:
        return {"success": False, "error": "URL 不能为空"}
    return await execute_web_screenshot(url)
