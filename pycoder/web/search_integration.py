"""
搜索引擎集成 — 支持 DuckDuckGo / SearXNG / Tavily 多引擎

为 AI 提供联网搜索能力，默认使用 DuckDuckGo（无需 API Key）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    title: str
    url: str
    snippet: str
    source: str = ""


class SearchIntegration:
    """搜索引擎集成

    搜索顺序: DuckDuckGo → SearXNG → Tavily
    """

    def __init__(self):
        self._duck = DuckDuckGoSearch()
        self._searxng = SearXNGSearch()
        self._tavily = TavilySearch()

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        """执行搜索，返回结果列表"""
        # Layer 1: DuckDuckGo (免费，无需 Key)
        try:
            results = await self._duck.search(query, num_results)
            if results:
                return results
        except Exception as exc:
            logger.debug("DuckDuckGo 搜索失败: %s", exc)

        # Layer 2: SearXNG (自建，需要配置 URL)
        try:
            results = await self._searxng.search(query, num_results)
            if results:
                return results
        except Exception as exc:
            logger.debug("SearXNG 搜索失败: %s", exc)

        # Layer 3: Tavily (API Key 付费)
        try:
            results = await self._tavily.search(query, num_results)
            if results:
                return results
        except Exception as exc:
            logger.debug("Tavily 搜索失败: %s", exc)

        return []


# ── DuckDuckGo ──


class DuckDuckGoSearch:
    """DuckDuckGo 免费搜索（无需 API Key）"""

    SEARCH_URL = "https://html.duckduckgo.com/html/"

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        """使用 DuckDuckGo 的 HTML 版进行搜索"""
        import httpx

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            resp = await c.post(
                self.SEARCH_URL,
                data={"q": query},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                    ),
                },
            )
            resp.raise_for_status()
            return self._parse_results(resp.text, num_results)

    def _parse_results(self, html: str, num_results: int) -> list[SearchResult]:
        """解析 DuckDuckGo HTML 搜索结果"""
        import re

        results = []
        # 匹配搜索结果块
        blocks = re.findall(
            r'<a[^>]*class=["\']result__a["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )
        snippets = re.findall(
            r'<a[^>]*class=["\']result__snippet["\'][^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for i, (url, title_html) in enumerate(blocks[:num_results]):
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                source="duckduckgo",
            ))

        return results


# ── SearXNG ──


class SearXNGSearch:
    """SearXNG 自建搜索引擎（需要配置地址）"""

    def __init__(self):
        import os
        self._base_url = os.environ.get("SEARXNG_BASE_URL", "")

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        if not self._base_url:
            return []

        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "language": "zh-CN"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    source="searxng",
                ))
            return results


# ── Tavily ──


class TavilySearch:
    """Tavily AI 搜索 API（付费，需要 API Key）"""

    def __init__(self):
        import os
        self._api_key = os.environ.get("TAVILY_API_KEY", "")

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            return []

        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": num_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    source="tavily",
                ))
            return results


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_instance: SearchIntegration | None = None


def get_search() -> SearchIntegration:
    """获取搜索引擎单例"""
    global _instance
    if _instance is None:
        _instance = SearchIntegration()
    return _instance
