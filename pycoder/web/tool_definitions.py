"""
AI 可调用的联网搜索工具注册表

向 ChatBridge/AIAgent 注册以下工具:
  - web_fetch      获取网页内容
  - web_search     联网搜索
  - web_screenshot 网页截图
"""

from __future__ import annotations

# ── AI 工具定义 ──

WEB_TOOLS: list[dict] = [
    {
        "name": "web_fetch",
        "description": (
            "获取网页内容。自动处理 JavaScript 渲染，返回 Markdown 格式文本。"
            "适用于：读取文档、查看文章、抓取 API 文档"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "目标网页 URL，必须以 http:// 或 https:// 开头",
                },
                "extract_text": {
                    "type": "boolean",
                    "description": "是否提取纯文本（去除 HTML 标签）",
                    "default": True,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "联网搜索获取最新信息。可以实时查询互联网上最新内容。"
            "适用于：查询最新新闻、搜索技术文档、查找 API 变更"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，越精确越好",
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量 (1-10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_screenshot",
        "description": (
            "对网页进行截图，返回图片路径。可用于分析页面布局、UI 设计、图表等视觉内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "目标网页 URL",
                },
            },
            "required": ["url"],
        },
    },
]


# ── 工具执行函数 ──

_engine: object = None
_search: object = None
_extractor: object = None


async def execute_web_fetch(url: str, extract_text: bool = True) -> dict:
    """执行 web_fetch 工具"""
    from pycoder.web.fetch_engine import FetchEngine
    from pycoder.web.content_extractor import ContentExtractor

    global _engine, _extractor
    if _engine is None:
        _engine = FetchEngine()
    if _extractor is None:
        _extractor = ContentExtractor()

    result = await _engine.fetch(url)
    if result.error:
        return {"success": False, "error": result.error}

    if extract_text and result.html:
        content = await _extractor.extract(result.html, url)
        return {
            "success": True,
            "url": url,
            "title": content.title,
            "content": content.text[:10000],
            "word_count": content.word_count,
            "links": content.links[:20],
        }

    return {
        "success": True,
        "url": url,
        "content": result.html[:10000] if result.html else "",
    }


async def execute_web_search(query: str, num_results: int = 5) -> dict:
    """执行 web_search 工具"""
    from pycoder.web.search_integration import get_search

    search = get_search()
    results = await search.search(query, num_results)

    if not results:
        return {
            "success": False,
            "error": "搜索无结果，请尝试更换关键词",
            "results": [],
        }

    return {
        "success": True,
        "query": query,
        "total": len(results),
        "results": [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
            }
            for r in results
        ],
    }


async def execute_web_screenshot(url: str) -> dict:
    """执行 web_screenshot 工具"""
    from pycoder.web.fetch_engine import FetchEngine

    global _engine
    if _engine is None:
        _engine = FetchEngine()

    screenshot_bytes = await _engine.screenshot(url)
    if screenshot_bytes is None:
        return {"success": False, "error": "截图失败"}

    # 保存到临时文件
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(screenshot_bytes)
    tmp.close()

    return {
        "success": True,
        "url": url,
        "screenshot_path": tmp.name,
        "file_size_kb": round(len(screenshot_bytes) / 1024, 1),
    }
