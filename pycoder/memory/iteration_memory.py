"""Level 2: IterationMemory — 特性级迭代追踪（SQLite + FTS5）"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from pycoder.memory.deep_memory_models import MemoryEntry

logger = logging.getLogger(__name__)


class IterationMemory:
    """迭代记忆 — 单特性级迭代追踪（Level 2）

    特性:
    - SQLite 持久化存储，支持 FTS5 全文搜索
    - 追踪: 修改文件、执行命令、错误日志、已解决问题
    - 生命周期: 单次特性迭代（可跨多次会话）
    """

    SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS iteration_entries (
            id TEXT PRIMARY KEY,
            iteration_id TEXT NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            timestamp REAL NOT NULL,
            ttl REAL
        );
        CREATE INDEX IF NOT EXISTS idx_iteration_entries_iter
            ON iteration_entries(iteration_id, category);
        CREATE VIRTUAL TABLE IF NOT EXISTS iteration_fts
            USING fts5(
                id, iteration_id, category, key, content,
                content='iteration_entries', content_rowid='rowid',
            );
    """

    TRIGGERS_SQL = """
        CREATE TRIGGER IF NOT EXISTS iteration_entries_ai AFTER INSERT ON iteration_entries BEGIN
            INSERT INTO iteration_fts(rowid, id, iteration_id, category, key, content)
            VALUES (new.rowid, new.id, new.iteration_id, new.category, new.key, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS iteration_entries_ad
            AFTER DELETE ON iteration_entries BEGIN
            INSERT INTO iteration_fts(
                iteration_fts, rowid, id, iteration_id,
                category, key, content,
            )
            VALUES (
                'delete', old.rowid, old.id, old.iteration_id,
                old.category, old.key, old.content,
            );
        END;
        CREATE TRIGGER IF NOT EXISTS iteration_entries_au
            AFTER UPDATE ON iteration_entries BEGIN
            INSERT INTO iteration_fts(
                iteration_fts, rowid, id, iteration_id,
                category, key, content,
            )
            VALUES (
                'delete', old.rowid, old.id, old.iteration_id,
                old.category, old.key, old.content,
            );
            INSERT INTO iteration_fts(rowid, id, iteration_id, category, key, content)
            VALUES (new.rowid, new.id, new.iteration_id, new.category, new.key, new.content);
        END;
    """

    CATEGORIES = ("file", "command", "error", "decision", "note")

    def __init__(self, storage_dir: Path, iteration_id: str | None = None):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._storage_dir / "iteration_memory.db"
        self._iteration_id = iteration_id
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(self.SCHEMA_SQL)
        try:
            conn.executescript(self.TRIGGERS_SQL)
        except sqlite3.OperationalError:
            pass
        conn.commit()

    async def start_iteration(self, iteration_id: str) -> None:
        self._iteration_id = iteration_id
        logger.info("iteration_started iteration_id=%s", iteration_id)

    async def end_iteration(self) -> None:
        logger.info("iteration_ended iteration_id=%s", self._iteration_id)
        self._iteration_id = None

    async def track_file(self, file_path: str, action: str = "modified") -> MemoryEntry:
        return await self._store("file", file_path, f"{action}: {file_path}", {"action": action})

    async def track_command(self, command: str, exit_code: int = 0, output: str = "") -> MemoryEntry:
        content = f"命令: {command} | 退出码: {exit_code}"
        if output:
            content += f" | 输出: {output[:800]}"
        return await self._store("command", command, content, {"exit_code": exit_code, "command": command})

    async def track_error(self, error_message: str, resolved: bool = False) -> MemoryEntry:
        return await self._store("error", error_message, error_message, {"resolved": resolved})

    async def track_decision(self, decision: str) -> MemoryEntry:
        return await self._store("decision", f"decision_{int(time.time())}", decision, {})

    async def track_note(self, note: str) -> MemoryEntry:
        return await self._store("note", f"note_{int(time.time())}", note, {})

    async def search(self, query: str, category: str | None = None, limit: int = 20) -> list[MemoryEntry]:
        conn = self._get_conn()
        fts_query = " OR ".join(f'"{word}"' for word in query.split() if word)
        if not fts_query:
            fts_query = query
        if category:
            sql = """
                SELECT e.* FROM iteration_entries e
                JOIN iteration_fts f ON e.rowid = f.rowid
                WHERE f.content MATCH ? AND e.category = ?
                ORDER BY rank LIMIT ?
            """
            rows = conn.execute(sql, (fts_query, category, limit)).fetchall()
        else:
            sql = """
                SELECT e.* FROM iteration_entries e
                JOIN iteration_fts f ON e.rowid = f.rowid
                WHERE f.content MATCH ?
                ORDER BY rank LIMIT ?
            """
            rows = conn.execute(sql, (fts_query, limit)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_by_category(self, category: str, limit: int = 50) -> list[MemoryEntry]:
        conn = self._get_conn()
        sql = """
            SELECT * FROM iteration_entries
            WHERE category = ? AND (iteration_id = ? OR ? IS NULL)
            ORDER BY timestamp DESC LIMIT ?
        """
        rows = conn.execute(sql, (category, self._iteration_id, self._iteration_id, limit)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_all(self, limit: int = 100) -> list[MemoryEntry]:
        conn = self._get_conn()
        if self._iteration_id:
            rows = conn.execute(
                "SELECT * FROM iteration_entries WHERE iteration_id = ? ORDER BY timestamp DESC LIMIT ?",
                (self._iteration_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM iteration_entries ORDER BY timestamp DESC LIMIT ?", (limit,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_errors(self, resolved_only: bool = False) -> list[MemoryEntry]:
        conn = self._get_conn()
        if resolved_only:
            rows = conn.execute(
                "SELECT * FROM iteration_entries WHERE category='error' "
                "AND json_extract(metadata, '$.resolved') = 1 ORDER BY timestamp DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM iteration_entries WHERE category='error' ORDER BY timestamp DESC"
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_files(self) -> list[MemoryEntry]:
        return await self.get_by_category("file")

    async def summarize(self, llm_provider=None) -> str:
        entries = await self.get_all(limit=200)
        if not entries:
            return "无迭代记录"
        files = [e for e in entries if e.metadata.get("category") == "file" or "file" in e.key]
        errors = [e for e in entries if e.metadata.get("category") == "error" or "error" in e.key]
        commands = [e for e in entries if e.metadata.get("category") == "command" or "command" in e.key]
        parts: list[str] = []
        if files:
            parts.append(f"修改文件 ({len(files)}): {', '.join(e.content[:80] for e in files[:10])}")
        if errors:
            unresolved = [e for e in errors if not e.metadata.get("resolved", False)]
            parts.append(f"错误 ({len(errors)}, 未解决 {len(unresolved)}): {', '.join(e.content[:80] for e in errors[:5])}")
        if commands:
            parts.append(f"执行命令 ({len(commands)}): {', '.join(e.content[:80] for e in commands[:5])}")
        if llm_provider:
            try:
                prompt = (
                    "请用 2-3 句话总结以下迭代记录:\n\n"
                    + "\n".join(f"[{e.key}] {e.content[:200]}" for e in entries[:50])
                    + "\n\n摘要:"
                )
                resp = await llm_provider.generate(prompt, max_tokens=200)
                return resp.content.strip()
            except (OSError, RuntimeError, ValueError, AttributeError) as e:
                logger.debug("iteration_summarize_failed: %s", e)
        return " | ".join(parts) if parts else "无迭代记录"

    async def cleanup(self, older_than_days: int = 30) -> int:
        cutoff = time.time() - older_than_days * 86400
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM iteration_entries WHERE timestamp < ?", (cutoff,))
        conn.commit()
        deleted = cursor.rowcount
        logger.info("iteration_cleanup deleted=%d older_than_days=%d", deleted, older_than_days)
        return deleted

    def get_stats(self) -> dict[str, int]:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM iteration_entries").fetchone()[0]
        cats = conn.execute(
            "SELECT category, COUNT(*) FROM iteration_entries GROUP BY category"
        ).fetchall()
        return {"total": total, "by_category": {r[0]: r[1] for r in cats}}

    async def _store(self, category: str, key: str, content: str, metadata: dict[str, Any]) -> MemoryEntry:
        entry = MemoryEntry(
            level=2, key=key, content=content,
            metadata={**metadata, "category": category, "iteration_id": self._iteration_id},
            ttl=86400 * 7,
        )
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO iteration_entries
               (id, iteration_id, category, key, content, metadata, timestamp, ttl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.id, self._iteration_id, category, entry.key, entry.content,
             json.dumps(entry.metadata, ensure_ascii=False), entry.timestamp, entry.ttl),
        )
        conn.commit()
        return entry

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"], level=2, key=row["key"], content=row["content"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            timestamp=row["timestamp"], ttl=row["ttl"],
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def iteration_id(self) -> str | None:
        return self._iteration_id
