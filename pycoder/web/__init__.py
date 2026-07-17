"""PyCoder 联网搜索模块

提供 AI 可直接调用的网页抓取、搜索引擎、内容提取能力。

架构:
  FetchEngine ── Layer 1: httpx 直连
              └── Layer 2: Playwright 浏览器降级 (JS 渲染)

  SearchIntegration ── DuckDuckGo / SearXNG / Tavily

  ContentExtractor ── HTML → Markdown → 结构化文本
"""

from __future__ import annotations

from pycoder.web.fetch_engine import FetchEngine, FetchResult, NeedJSError
from pycoder.web.content_extractor import ContentExtractor, ExtractedContent
from pycoder.web.search_integration import (
    SearchIntegration,
    SearchResult,
    get_search,
)
from pycoder.web.tool_definitions import WEB_TOOLS
from pycoder.web.browser_agent import BrowserAgent

__all__ = [
    "FetchEngine",
    "FetchResult",
    "NeedJSError",
    "ContentExtractor",
    "ExtractedContent",
    "SearchIntegration",
    "SearchResult",
    "get_search",
    "WEB_TOOLS",
    "BrowserAgent",
]
