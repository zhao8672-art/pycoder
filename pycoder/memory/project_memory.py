"""Level 3: ProjectMemory — 项目级知识图谱（ChromaDB 向量存储 + SQLite 回退）"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from pycoder.memory.deep_memory_models import (
    _CHROMA_AVAILABLE,
    ChromaSettings,
    MemoryEntry,
    chromadb,
)

logger = logging.getLogger(__name__)


class ProjectMemory:
    """项目记忆 — 项目级知识图谱（Level 3）

    特性:
    - ChromaDB 向量存储（可选，回退 SQLite 模式）
    - 存储: 项目架构、技术栈、代码约定、历史 Bug 模式、依赖图
    - 语义搜索（ChromaDB 模式下）
    - 生命周期: 项目持久化
    """

    COLLECTION_NAME = "pycoder_project_memory"

    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._memory_dir = project_root / ".pycoder" / "project_memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)

        self._chroma_client: Any = None
        self._chroma_collection: Any = None
        if _CHROMA_AVAILABLE:
            try:
                self._chroma_client = chromadb.PersistentClient(
                    path=str(self._memory_dir / "chroma"),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                self._chroma_collection = self._chroma_client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(
                    "project_memory_chroma_initialized path=%s", self._memory_dir / "chroma"
                )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_init_failed: %s，回退到 SQLite 模式", e)
                self._chroma_client = None
                self._chroma_collection = None

        self._sqlite_path = self._memory_dir / "project_memory.db"

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._sqlite_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS project_entries (
                id TEXT PRIMARY KEY, key TEXT NOT NULL, content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}', timestamp REAL NOT NULL, ttl REAL
            )""")
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_project_entries_key ON project_entries(key)"""
        )
        conn.commit()
        return conn

    async def store(
        self,
        key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            level=3,
            key=key,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            ttl=None,
        )
        if self._chroma_collection is not None:
            try:
                self._chroma_collection.upsert(
                    ids=[entry.id],
                    documents=[content],
                    metadatas=[{**entry.metadata, "key": key}],
                    embeddings=[embedding] if embedding else None,
                )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_store_failed: %s", e)
        conn = self._get_sqlite_conn()
        conn.execute(
            """INSERT OR REPLACE INTO project_entries (id, key, content, metadata, timestamp, ttl)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.key,
                entry.content,
                json.dumps(entry.metadata, ensure_ascii=False),
                entry.timestamp,
                entry.ttl,
            ),
        )
        conn.commit()
        conn.close()
        logger.debug("project_memory_store key=%s", key)
        return entry

    async def search(
        self, query: str, k: int = 5, embedding: list[float] | None = None
    ) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        if self._chroma_collection is not None:
            try:
                chroma_results = self._chroma_collection.query(
                    query_texts=[query],
                    n_results=k,
                    query_embeddings=[embedding] if embedding else None,
                )
                if chroma_results and chroma_results.get("ids"):
                    for i, doc_id in enumerate(chroma_results["ids"][0]):
                        doc = (
                            chroma_results["documents"][0][i]
                            if chroma_results.get("documents")
                            else ""
                        )
                        meta = (
                            chroma_results["metadatas"][0][i]
                            if chroma_results.get("metadatas")
                            else {}
                        )
                        key = meta.get("key", "") if isinstance(meta, dict) else ""
                        results.append(
                            MemoryEntry(
                                id=doc_id,
                                level=3,
                                key=key,
                                content=doc if doc else "",
                                metadata=meta if isinstance(meta, dict) else {},
                            )
                        )
                    return results
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_search_failed: %s", e)
        conn = self._get_sqlite_conn()
        search_terms = query.split()
        conditions = " OR ".join(["content LIKE ?" for _ in search_terms])
        params = [f"%{t}%" for t in search_terms]
        rows = conn.execute(
            f"SELECT * FROM project_entries WHERE {conditions} ORDER BY timestamp DESC LIMIT ?",
            (*params, k),
        ).fetchall()
        conn.close()
        for row in rows:
            results.append(
                MemoryEntry(
                    id=row["id"],
                    level=3,
                    key=row["key"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    timestamp=row["timestamp"],
                    ttl=row["ttl"],
                )
            )
        return results

    async def get(self, key: str) -> MemoryEntry | None:
        if self._chroma_collection is not None:
            try:
                chroma_results = self._chroma_collection.get(where={"key": key}, limit=1)
                if chroma_results and chroma_results.get("ids"):
                    i = 0
                    return MemoryEntry(
                        id=chroma_results["ids"][i],
                        level=3,
                        key=key,
                        content=(
                            chroma_results["documents"][i]
                            if chroma_results.get("documents")
                            else ""
                        ),
                        metadata=(
                            chroma_results["metadatas"][i]
                            if chroma_results.get("metadatas")
                            else {}
                        ),
                    )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_get_failed: %s", e)
        conn = self._get_sqlite_conn()
        row = conn.execute(
            "SELECT * FROM project_entries WHERE key = ? ORDER BY timestamp DESC LIMIT 1",
            (key,),
        ).fetchone()
        conn.close()
        if row:
            return MemoryEntry(
                id=row["id"],
                level=3,
                key=row["key"],
                content=row["content"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                timestamp=row["timestamp"],
                ttl=row["ttl"],
            )
        return None

    async def delete(self, key: str) -> bool:
        deleted = False
        if self._chroma_collection is not None:
            try:
                existing = self._chroma_collection.get(where={"key": key}, limit=100)
                if existing and existing.get("ids"):
                    self._chroma_collection.delete(ids=existing["ids"])
                    deleted = True
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_delete_failed: %s", e)
        conn = self._get_sqlite_conn()
        cursor = conn.execute("DELETE FROM project_entries WHERE key = ?", (key,))
        conn.commit()
        conn.close()
        if cursor.rowcount > 0:
            deleted = True
        return deleted

    async def summarize(self, llm_provider=None) -> str:
        conn = self._get_sqlite_conn()
        rows = conn.execute(
            "SELECT key, content FROM project_entries ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
        conn.close()
        if not rows:
            return "无项目记忆"
        keys = list({r["key"] for r in rows})
        parts = [f"项目记忆 ({len(rows)} 条): {', '.join(keys[:20])}"]
        if llm_provider:
            try:
                prompt = (
                    "请用 2-3 句话总结以下项目知识:\n\n"
                    + "\n".join(f"[{r['key']}] {r['content'][:200]}" for r in rows[:20])
                    + "\n\n摘要:"
                )
                resp = await llm_provider.generate(prompt, max_tokens=200)
                return resp.content.strip()
            except (OSError, RuntimeError, ValueError, AttributeError) as e:
                logger.debug("project_summarize_failed: %s", e)
        return " | ".join(parts)

    async def cleanup(self, older_than_days: int = 90) -> int:
        cutoff = time.time() - older_than_days * 86400
        conn = self._get_sqlite_conn()
        cursor = conn.execute("DELETE FROM project_entries WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
        deleted = cursor.rowcount
        logger.info("project_memory_cleanup deleted=%d", deleted)
        return deleted

    def get_stats(self) -> dict[str, int]:
        conn = self._get_sqlite_conn()
        total = conn.execute("SELECT COUNT(*) FROM project_entries").fetchone()[0]
        conn.close()
        chroma_count = 0
        if self._chroma_collection is not None:
            try:
                chroma_count = self._chroma_collection.count()
            except (OSError, RuntimeError, ValueError):
                pass
        return {
            "total_sqlite": total,
            "total_chroma": chroma_count,
            "chroma_available": _CHROMA_AVAILABLE,
        }

    @property
    def chroma_available(self) -> bool:
        return self._chroma_collection is not None
