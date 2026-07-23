"""
Web 搜索插件 — 为 AI Agent 提供联网搜索能力

支持多种搜索引擎:
  - Bing Web Search API
  - SerpAPI (Google Search)
  - DuckDuckGo (免费，无需 API Key)

用法:
  from pycoder.plugins.web_search import WebSearchPlugin

  plugin = WebSearchPlugin()
  results = await plugin.search("Python async best practices", num=5)
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    title: str
    url: str
    snippet: str
    source: str = "web"
    relevance_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "relevance_score": self.relevance_score,
        }


@dataclass
class SearchResponse:
    """搜索响应"""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    engine: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "engine": self.engine,
            "duration_ms": self.duration_ms,
        }


class WebSearchPlugin:
    """Web 搜索插件 — 多引擎聚合搜索

    自动选择可用引擎:
      1. Bing API (BING_API_KEY 环境变量)
      2. SerpAPI (SERPAPI_KEY 环境变量)
      3. DuckDuckGo (免费回退，无需 API Key)
    """

    def __init__(self) -> None:
        self._bing_key = os.environ.get("BING_API_KEY", "")
        self._serpapi_key = os.environ.get("SERPAPI_KEY", "")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def search(
        self,
        query: str,
        num: int = 5,
        engine: str | None = None,
        lang: str = "zh-CN",
    ) -> SearchResponse:
        """执行搜索

        Args:
            query: 搜索关键词
            num: 返回结果数量
            engine: 指定搜索引擎 (bing/serpapi/duckduckgo)，为空则自动选择
            lang: 搜索语言

        Returns:
            SearchResponse 搜索结果
        """
        import time
        start = time.time()

        if engine:
            engines = [engine]
        else:
            engines = self._available_engines()

        for eng in engines:
            try:
                if eng == "bing":
                    results = await self._search_bing(query, num, lang)
                elif eng == "serpapi":
                    results = await self._search_serpapi(query, num, lang)
                elif eng == "duckduckgo":
                    results = await self._search_duckduckgo(query, num)
                else:
                    continue

                duration = (time.time() - start) * 1000
                return SearchResponse(
                    query=query,
                    results=results[:num],
                    total_results=len(results),
                    engine=eng,
                    duration_ms=duration,
                )
            except Exception as e:
                logger.debug("搜索引擎 %s 失败: %s", eng, e)
                continue

        # 所有引擎都失败
        duration = (time.time() - start) * 1000
        return SearchResponse(
            query=query,
            results=[],
            total_results=0,
            engine="none",
            duration_ms=duration,
        )

    def _available_engines(self) -> list[str]:
        """返回可用的搜索引擎列表"""
        engines = []
        if self._bing_key:
            engines.append("bing")
        if self._serpapi_key:
            engines.append("serpapi")
        engines.append("duckduckgo")  # 免费回退
        return engines

    async def _search_bing(
        self, query: str, num: int, lang: str
    ) -> list[SearchResult]:
        """Bing Web Search API"""
        resp = await self._client.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": self._bing_key},
            params={"q": query, "count": num, "mkt": lang, "textFormat": "Raw"},
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append(SearchResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                source="bing",
            ))
        return results

    async def _search_serpapi(
        self, query: str, num: int, lang: str
    ) -> list[SearchResult]:
        """SerpAPI (Google Search)"""
        resp = await self._client.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "api_key": self._serpapi_key,
                "num": num,
                "hl": lang,
                "engine": "google",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("organic_results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source="serpapi",
            ))
        return results

    async def _search_duckduckgo(
        self, query: str, num: int
    ) -> list[SearchResult]:
        """DuckDuckGo Instant Answer API（免费，无需 API Key）"""
        resp = await self._client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        results = []

        # Abstract / Answer
        if data.get("AbstractText"):
            results.append(SearchResult(
                title=data.get("Heading", query),
                url=data.get("AbstractURL", ""),
                snippet=data.get("AbstractText", ""),
                source="duckduckgo",
            ))

        # Related Topics
        for topic in data.get("RelatedTopics", [])[:num]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(SearchResult(
                    title=topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                    url=topic.get("FirstURL", ""),
                    snippet=topic.get("Text", ""),
                    source="duckduckgo",
                ))

        return results

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        await self._client.aclose()

    # ── RAG 上下文增强 ──

    async def search_for_context(
        self, query: str, num: int = 3
    ) -> str:
        """搜索并返回格式化上下文（用于 RAG 增强）

        Args:
            query: 搜索关键词
            num: 返回结果数量

        Returns:
            格式化的上下文文本
        """
        resp = await self.search(query, num=num)
        if not resp.results:
            return ""

        lines = [f"## Web 搜索结果: {query}\n"]
        for i, r in enumerate(resp.results, 1):
            lines.append(f"### {i}. {r.title}")
            lines.append(f"URL: {r.url}")
            lines.append(f"{r.snippet}\n")
        return "\n".join(lines)


# ── 全局单例 ──

_web_search_instance: WebSearchPlugin | None = None


def get_web_search() -> WebSearchPlugin:
    """获取 WebSearchPlugin 全局单例"""
    global _web_search_instance
    if _web_search_instance is None:
        _web_search_instance = WebSearchPlugin()
    return _web_search_instance