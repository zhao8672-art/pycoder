"""knowledge 模块测试"""
from __future__ import annotations

import pytest
from pycoder.knowledge.knowledge_fetcher import KnowledgeFetcher, KnowledgeSource, KnowledgeChunk
from pycoder.knowledge.knowledge_index import KnowledgeIndex
from pycoder.knowledge.update_scheduler import KnowledgeUpdateScheduler


class TestKnowledgeFetcher:
    def test_register_default_sources(self):
        fetcher = KnowledgeFetcher()
        fetcher.register_default_sources()
        sources = fetcher.list_sources()
        assert len(sources) == 3
        assert any(s.id == "python-docs" for s in sources)

    def test_register_custom_source(self):
        fetcher = KnowledgeFetcher()
        fetcher.register_source(KnowledgeSource(
            id="custom", name="自定义", url="https://example.com", category="custom",
        ))
        assert fetcher.get_source("custom") is not None

    def test_get_source_not_found(self):
        fetcher = KnowledgeFetcher()
        assert fetcher.get_source("nonexistent") is None

    def test_html_to_text(self):
        html = "<html><body><p>Hello</p><script>evil()</script><p>World</p></body></html>"
        text = KnowledgeFetcher._html_to_text(html)
        assert "Hello" in text
        assert "World" in text
        assert "evil()" not in text

    def test_chunk_text(self):
        source = KnowledgeSource(id="test", name="测试", url="https://test.com", category="test")
        text = "A" * 1000
        chunks = KnowledgeFetcher()._chunk_text(text, source, chunk_size=200)
        assert len(chunks) == 5
        assert all(isinstance(c, KnowledgeChunk) for c in chunks)
        assert all(c.source_id == "test" for c in chunks)

    def test_chunk_text_empty(self):
        source = KnowledgeSource(id="test", name="测试", url="https://test.com", category="test")
        chunks = KnowledgeFetcher()._chunk_text("", source)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_fetch_source_without_fetch_fn(self):
        fetcher = KnowledgeFetcher()
        source = KnowledgeSource(id="test", name="测试", url="https://test.com", category="test")
        chunks = await fetcher.fetch_source(source)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_fetch_source_with_fetch_fn(self):
        async def mock_fetch(url):
            return "<html><body><p>Test content</p></body></html>"

        fetcher = KnowledgeFetcher()
        source = KnowledgeSource(id="test", name="测试", url="https://test.com", category="test")
        chunks = await fetcher.fetch_source(source, fetch_fn=mock_fetch)
        assert len(chunks) > 0
        assert "Test content" in chunks[0].content


class TestKnowledgeIndex:
    def test_index_without_chromadb(self, tmp_path):
        index = KnowledgeIndex(persist_dir=tmp_path)
        stats = index.get_stats()
        assert "total_chunks" in stats

    def test_search_without_chromadb(self, tmp_path):
        index = KnowledgeIndex(persist_dir=tmp_path)
        results = index.search("test query")
        assert results == []

    def test_index_chunks_no_chromadb(self, tmp_path):
        index = KnowledgeIndex(persist_dir=tmp_path)
        count = index.index_chunks([])
        assert count == 0


class TestKnowledgeUpdateScheduler:
    def test_search_and_format_empty(self, tmp_path):
        index = KnowledgeIndex(persist_dir=tmp_path)
        fetcher = KnowledgeFetcher()
        kus = KnowledgeUpdateScheduler(fetcher, index)
        result = kus.search_and_format("test")
        assert result == ""

    def test_setup_default_tasks_no_scheduler(self, tmp_path):
        index = KnowledgeIndex(persist_dir=tmp_path)
        fetcher = KnowledgeFetcher()
        kus = KnowledgeUpdateScheduler(fetcher, index)
        kus.setup_default_tasks()  # 无 scheduler 时不报错

    @pytest.mark.asyncio
    async def test_run_update_no_source(self, tmp_path):
        index = KnowledgeIndex(persist_dir=tmp_path)
        fetcher = KnowledgeFetcher()
        kus = KnowledgeUpdateScheduler(fetcher, index)
        count = await kus.run_update("nonexistent")
        assert count == 0