"""知识获取引擎 — 定时抓取文档和更新

支持 HTML→Markdown 转换、文本切片、增量更新检测。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field


@dataclass
class KnowledgeSource:
    """知识源定义"""
    id: str
    name: str
    url: str
    category: str  # "python_docs" | "security" | "packages" | "custom"
    update_interval_hours: int = 24
    last_fetched: str = ""


@dataclass
class KnowledgeChunk:
    """知识片段"""
    id: str
    source_id: str
    content: str
    url: str
    title: str
    category: str
    fetched_at: str
    content_hash: str


class KnowledgeFetcher:
    """知识获取引擎

    用法:
        fetcher = KnowledgeFetcher()
        chunks = await fetcher.fetch_source(source, fetch_fn)
        # 或使用默认源
        fetcher.register_default_sources()
    """

    DEFAULT_SOURCES = [
        KnowledgeSource(
            id="python-docs",
            name="Python 官方文档",
            url="https://docs.python.org/3/",
            category="python_docs",
        ),
        KnowledgeSource(
            id="python-security",
            name="Python 安全公告",
            url="https://github.com/python/security/advisories",
            category="security",
        ),
        KnowledgeSource(
            id="pypi-updates",
            name="PyPI 热门包更新",
            url="https://pypi.org/rss/updates.xml",
            category="packages",
        ),
    ]

    def __init__(self):
        self._sources: dict[str, KnowledgeSource] = {}

    def register_default_sources(self):
        """注册默认知识源"""
        for s in self.DEFAULT_SOURCES:
            self._sources[s.id] = s

    def register_source(self, source: KnowledgeSource):
        """注册自定义知识源"""
        self._sources[source.id] = source

    def get_source(self, source_id: str) -> KnowledgeSource | None:
        return self._sources.get(source_id)

    def list_sources(self) -> list[KnowledgeSource]:
        return list(self._sources.values())

    async def fetch_source(self, source: KnowledgeSource,
                           fetch_fn=None) -> list[KnowledgeChunk]:
        """抓取单个知识源

        Args:
            source: 知识源定义
            fetch_fn: 异步函数 async (url) -> str，返回 HTML 内容

        Returns:
            知识片段列表
        """
        if not fetch_fn:
            return []

        html = await fetch_fn(source.url)
        if not html:
            return []

        text = self._html_to_text(html)
        chunks = self._chunk_text(text, source, chunk_size=512)
        source.last_fetched = datetime.now(timezone.utc).isoformat()
        return chunks

    @staticmethod
    def _html_to_text(html: str) -> str:
        """HTML 转纯文本（简单标签剥离）"""
        import re
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _chunk_text(self, text: str, source: KnowledgeSource,
                    chunk_size: int = 512) -> list[KnowledgeChunk]:
        """文本切片（按字符数分块）"""
        if not text:
            return []
        chunks = []
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i:i + chunk_size]
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            chunks.append(KnowledgeChunk(
                id=f"{source.id}_{i // chunk_size}",
                source_id=source.id,
                content=chunk_text,
                url=source.url,
                title=f"{source.name} #{i // chunk_size + 1}",
                category=source.category,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                content_hash=content_hash,
            ))
        return chunks