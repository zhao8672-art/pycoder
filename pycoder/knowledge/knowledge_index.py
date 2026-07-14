"""知识索引与检索 — 基于 ChromaDB 的向量存储

支持语义搜索和元数据过滤。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class KnowledgeIndex:
    """知识向量索引

    用法:
        index = KnowledgeIndex()
        index.index_chunks(chunks)
        results = index.search("Python async await", top_k=5)
    """

    def __init__(self, persist_dir: Path | None = None):
        dir_path = str(persist_dir or Path.home() / ".pycoder" / "knowledge_db")
        self._client = None
        self._collection = None
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=dir_path)
            self._collection = self._client.get_or_create_collection(
                name="pycoder_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            self._documents: list[dict] = []  # fallback: 简单列表

    def index_chunks(self, chunks: list) -> int:
        """索引知识片段（去重）

        Returns:
            新增数量
        """
        if not chunks or not self._collection:
            return 0
        try:
            existing_ids = set()
            result = self._collection.get(ids=[c.id for c in chunks])
            existing_ids = set(result["ids"])
        except Exception:
            existing_ids = set()

        new_chunks = [c for c in chunks if c.id not in existing_ids]
        if not new_chunks:
            return 0

        self._collection.add(
            ids=[c.id for c in new_chunks],
            documents=[c.content for c in new_chunks],
            metadatas=[{
                "source_id": c.source_id,
                "url": c.url,
                "title": c.title,
                "category": c.category,
                "fetched_at": c.fetched_at,
            } for c in new_chunks],
        )
        return len(new_chunks)

    def search(self, query: str, top_k: int = 5,
               category: str | None = None) -> list[dict]:
        """语义搜索知识

        Returns:
            [{"content": str, "metadata": dict, "score": float}, ...]
        """
        if not self._collection:
            return []

        where = {"category": category} if category else None
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where,
            )
            return [
                {
                    "content": doc,
                    "metadata": meta,
                    "score": 1 - dist,
                }
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                )
            ]
        except (ValueError, KeyError, IndexError, RuntimeError) as e:
            logger.debug("knowledge_index_search_failed: %s", e)
            return []

    def get_stats(self) -> dict:
        """获取索引统计"""
        if self._collection:
            try:
                return {"total_chunks": self._collection.count()}
            except (ValueError, RuntimeError) as e:
                logger.debug("knowledge_index_stats_failed: %s", e)
        return {"total_chunks": 0}
