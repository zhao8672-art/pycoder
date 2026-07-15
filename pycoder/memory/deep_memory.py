"""
深度记忆系统 — Codex 4级 & Hermes 4层风格记忆架构

实现四级渐进式记忆，覆盖从会话到跨项目的完整知识生命周期：
- Level 1: WorkingMemory   — 会话级滑动窗口（临时）
- Level 2: IterationMemory — 特性级迭代追踪（SQLite + FTS5）
- Level 3: ProjectMemory   — 项目级知识图谱（ChromaDB 向量存储）
- Level 4: GlobalMemory    — 用户级偏好模式（跨项目持久化）

ChromaDB 为可选依赖，未安装时自动回退到纯 SQLite 模式。
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── ChromaDB 可选导入 ──────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    _CHROMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]
    ChromaSettings = None  # type: ignore[assignment]
    _CHROMA_AVAILABLE = False
    logger.info("chromadb 未安装，向量搜索将回退到 SQLite 模式")


# ══════════════════════════════════════════════════════════════════════════════
# 数据类定义
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class MemoryEntry:
    """单条记忆条目"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    level: int = 0  # 1-4 记忆层级
    key: str = ""  # 记忆键名
    content: str = ""  # 记忆内容
    embedding: list[float] | None = None  # 向量嵌入（可选）
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl: float | None = None  # 过期时间（秒），None 表示永不过期

    def is_expired(self) -> bool:
        """检查记忆是否已过期"""
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl


@dataclass
class MemoryContext:
    """多级检索结果上下文"""

    entries: list[MemoryEntry] = field(default_factory=list)
    source_levels: list[int] = field(default_factory=list)  # 来源层级
    total_tokens: int = 0  # 估算总 Token 数
    query: str = ""
    retrieval_time_ms: float = 0.0


@dataclass
class MemoryStats:
    """记忆统计信息"""

    level_stats: dict[int, dict[str, int]] = field(default_factory=dict)
    total_entries: int = 0
    total_size_bytes: int = 0
    last_cleanup: str = ""
    chroma_available: bool = _CHROMA_AVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# 辅助工具
# ══════════════════════════════════════════════════════════════════════════════


def _estimate_tokens(text: str) -> int:
    """粗略估算文本的 Token 数量（按字符数 / 4 估算）"""
    return max(1, math.ceil(len(text) / 4))


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串"""
    return datetime.now(UTC).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# Level 1: WorkingMemory — 会话级滑动窗口
# ══════════════════════════════════════════════════════════════════════════════


class WorkingMemory:
    """工作记忆 — 会话级临时记忆（Level 1）

    特性:
    - 滑动窗口上下文管理，限制最大 Token 数
    - 超限自动摘要压缩
    - LRU 缓存高频访问项
    - 生命周期: 单次会话

    用法:
        wm = WorkingMemory(max_tokens=4096)
        wm.store("current_file", "src/main.py")
        wm.store("pending_task", "修复登录页 Bug")
        ctx = wm.get_context()
    """

    DEFAULT_MAX_TOKENS = 4096
    LRU_CACHE_SIZE = 64

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        self._max_tokens = max_tokens
        self._store: dict[str, MemoryEntry] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()  # LRU 访问顺序
        self._total_tokens = 0
        self._created_at = _now_iso()

    # ── 存储与检索 ──

    def store(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """存储一条工作记忆

        Args:
            key: 记忆键名
            content: 记忆内容
            metadata: 附加元数据

        Returns:
            创建的 MemoryEntry
        """
        entry = MemoryEntry(
            level=1,
            key=key,
            content=content,
            metadata=metadata or {},
            ttl=3600,  # 工作记忆默认 1 小时过期
        )

        # 替换已有条目
        if key in self._store:
            old = self._store[key]
            self._total_tokens -= _estimate_tokens(old.content)

        self._store[key] = entry
        self._total_tokens += _estimate_tokens(content)
        self._touch_lru(key)

        # 超限自动压缩
        if self._total_tokens > self._max_tokens:
            self._evict_lru()

        logger.debug(
            "working_memory_store key=%s tokens=%d/%d",
            key, self._total_tokens, self._max_tokens,
        )
        return entry

    def retrieve(self, key: str) -> MemoryEntry | None:
        """检索一条工作记忆"""
        if key in self._store:
            entry = self._store[key]
            if entry.is_expired():
                self.delete(key)
                return None
            self._touch_lru(key)
            return entry
        return None

    def get_context(self) -> str:
        """获取当前工作上下文（拼接所有活跃记忆）"""
        parts: list[str] = []
        for key in self._store:
            entry = self._store[key]
            if not entry.is_expired():
                parts.append(f"[{key}] {entry.content}")
        return "\n".join(parts)

    def get_all_entries(self) -> list[MemoryEntry]:
        """获取所有活跃记忆条目"""
        return [e for e in self._store.values() if not e.is_expired()]

    def delete(self, key: str) -> bool:
        """删除一条工作记忆"""
        if key in self._store:
            self._total_tokens -= _estimate_tokens(self._store[key].content)
            del self._store[key]
            self._lru.pop(key, None)
            return True
        return False

    def clear(self) -> None:
        """清空所有工作记忆"""
        self._store.clear()
        self._lru.clear()
        self._total_tokens = 0

    # ── 摘要压缩 ──

    async def summarize(self, llm_provider=None) -> str:
        """压缩当前工作记忆为摘要

        Args:
            llm_provider: 可选的 LLM 提供者，用于生成智能摘要

        Returns:
            摘要文本
        """
        entries = self.get_all_entries()
        if not entries:
            return ""

        # 收集关键信息
        pending_tasks = [e for e in entries if "task" in e.key.lower() or "todo" in e.key.lower()]
        open_files = [e for e in entries if "file" in e.key.lower()]
        current = [
            e for e in entries
            if "current" in e.key.lower() or "conversation" in e.key.lower()
        ]

        parts: list[str] = []
        if current:
            parts.append(f"当前对话: {'; '.join(e.content[:100] for e in current)}")
        if pending_tasks:
            parts.append(f"待办任务: {'; '.join(e.content[:100] for e in pending_tasks)}")
        if open_files:
            parts.append(f"打开文件: {'; '.join(e.content[:100] for e in open_files)}")

        if llm_provider:
            try:
                prompt = (
                    "请用 1-2 句话总结以下工作上下文:\n\n"
                    + "\n".join(f"[{e.key}] {e.content[:200]}" for e in entries)
                    + "\n\n摘要:"
                )
                resp = await llm_provider.generate(prompt, max_tokens=150)
                return resp.content.strip()
            except (OSError, RuntimeError, ValueError, AttributeError) as e:
                logger.debug("working_memory_summarize_failed: %s", e)

        return " | ".join(parts) if parts else "无活跃上下文"

    # ── 内部方法 ──

    def _touch_lru(self, key: str) -> None:
        """更新 LRU 访问记录"""
        self._lru.pop(key, None)
        self._lru[key] = None

    def _evict_lru(self) -> None:
        """LRU 淘汰，释放 Token 空间"""
        while self._total_tokens > self._max_tokens and self._lru:
            oldest_key, _ = self._lru.popitem(last=False)
            if oldest_key in self._store:
                self._total_tokens -= _estimate_tokens(self._store[oldest_key].content)
                del self._store[oldest_key]
                logger.debug(
                "working_memory_evict key=%s remaining_tokens=%d",
                oldest_key, self._total_tokens,
            )

    @property
    def token_count(self) -> int:
        return self._total_tokens

    @property
    def entry_count(self) -> int:
        return len(self._store)


# ══════════════════════════════════════════════════════════════════════════════
# Level 2: IterationMemory — 特性级迭代追踪
# ══════════════════════════════════════════════════════════════════════════════


class IterationMemory:
    """迭代记忆 — 单特性级迭代追踪（Level 2）

    特性:
    - SQLite 持久化存储，支持 FTS5 全文搜索
    - 追踪: 修改文件、执行命令、错误日志、已解决问题
    - 生命周期: 单次特性迭代（可跨多次会话）

    用法:
        im = IterationMemory(Path("./.pycoder/memory"))
        await im.start_iteration("feat-login")
        await im.track_file("src/auth/login.py", "modified")
        await im.track_command("pytest tests/auth/", exit_code=0)
        await im.track_error("ConnectionError: timeout", resolved=True)
        results = await im.search("login timeout")
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
        """获取数据库连接（懒初始化）"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        """初始化数据库 schema"""
        conn = self._get_conn()
        conn.executescript(self.SCHEMA_SQL)
        # 尝试创建触发器（可能已存在）
        try:
            conn.executescript(self.TRIGGERS_SQL)
        except sqlite3.OperationalError:
            pass  # 触发器已存在时忽略
        conn.commit()

    # ── 迭代生命周期 ──

    async def start_iteration(self, iteration_id: str) -> None:
        """开始新的特性迭代

        Args:
            iteration_id: 迭代标识（如 "feat-login"）
        """
        self._iteration_id = iteration_id
        logger.info("iteration_started iteration_id=%s", iteration_id)

    async def end_iteration(self) -> None:
        """结束当前迭代"""
        logger.info("iteration_ended iteration_id=%s", self._iteration_id)
        self._iteration_id = None

    # ── 追踪操作 ──

    async def track_file(self, file_path: str, action: str = "modified") -> MemoryEntry:
        """追踪文件变更

        Args:
            file_path: 文件路径
            action: 操作类型（modified/created/deleted）
        """
        return await self._store("file", file_path, f"{action}: {file_path}", {"action": action})

    async def track_command(
        self, command: str, exit_code: int = 0, output: str = "",
    ) -> MemoryEntry:
        """追踪执行的命令

        Args:
            command: 执行的命令
            exit_code: 退出码
            output: 命令输出（截断）
        """
        # 将命令本身也纳入 content，确保 FTS5 可搜索到
        content = f"命令: {command} | 退出码: {exit_code}"
        if output:
            content += f" | 输出: {output[:800]}"
        return await self._store(
            "command",
            command,
            content,
            {"exit_code": exit_code, "command": command},
        )

    async def track_error(self, error_message: str, resolved: bool = False) -> MemoryEntry:
        """追踪错误日志

        Args:
            error_message: 错误信息
            resolved: 是否已解决
        """
        return await self._store(
            "error",
            error_message,
            error_message,
            {"resolved": resolved},
        )

    async def track_decision(self, decision: str) -> MemoryEntry:
        """追踪关键决策"""
        return await self._store("decision", f"decision_{int(time.time())}", decision, {})

    async def track_note(self, note: str) -> MemoryEntry:
        """追踪一般笔记"""
        return await self._store("note", f"note_{int(time.time())}", note, {})

    # ── 检索操作 ──

    async def search(
        self, query: str, category: str | None = None, limit: int = 20,
    ) -> list[MemoryEntry]:
        """FTS5 全文搜索记忆

        Args:
            query: 搜索关键词
            category: 按类别过滤（可选）
            limit: 最大返回数

        Returns:
            匹配的 MemoryEntry 列表
        """
        conn = self._get_conn()

        fts_query = " OR ".join(f'"{word}"' for word in query.split() if word)
        if not fts_query:
            fts_query = query

        if category:
            sql = """
                SELECT e.* FROM iteration_entries e
                JOIN iteration_fts f ON e.rowid = f.rowid
                WHERE f.content MATCH ? AND e.category = ?
                ORDER BY rank
                LIMIT ?
            """
            rows = conn.execute(sql, (fts_query, category, limit)).fetchall()
        else:
            sql = """
                SELECT e.* FROM iteration_entries e
                JOIN iteration_fts f ON e.rowid = f.rowid
                WHERE f.content MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            rows = conn.execute(sql, (fts_query, limit)).fetchall()

        return [self._row_to_entry(r) for r in rows]

    async def get_by_category(self, category: str, limit: int = 50) -> list[MemoryEntry]:
        """按类别获取记忆条目"""
        conn = self._get_conn()
        sql = """
            SELECT * FROM iteration_entries
            WHERE category = ? AND (iteration_id = ? OR ? IS NULL)
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows = conn.execute(
            sql, (category, self._iteration_id, self._iteration_id, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_all(self, limit: int = 100) -> list[MemoryEntry]:
        """获取所有迭代记忆"""
        conn = self._get_conn()
        if self._iteration_id:
            rows = conn.execute(
                "SELECT * FROM iteration_entries "
                "WHERE iteration_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (self._iteration_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM iteration_entries ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_errors(self, resolved_only: bool = False) -> list[MemoryEntry]:
        """获取错误列表"""
        conn = self._get_conn()
        if resolved_only:
            rows = conn.execute(
                "SELECT * FROM iteration_entries "
                "WHERE category='error' "
                "AND json_extract(metadata, '$.resolved') = 1"
                " ORDER BY timestamp DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM iteration_entries WHERE category='error' ORDER BY timestamp DESC"
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def get_files(self) -> list[MemoryEntry]:
        """获取所有追踪的文件"""
        return await self.get_by_category("file")

    # ── 维护操作 ──

    async def summarize(self, llm_provider=None) -> str:
        """生成当前迭代的摘要

        Args:
            llm_provider: 可选的 LLM 提供者

        Returns:
            摘要文本
        """
        entries = await self.get_all(limit=200)
        if not entries:
            return "无迭代记录"

        files = [e for e in entries if e.metadata.get("category") == "file" or "file" in e.key]
        errors = [e for e in entries if e.metadata.get("category") == "error" or "error" in e.key]
        commands = [
            e for e in entries
            if e.metadata.get("category") == "command" or "command" in e.key
        ]

        parts: list[str] = []
        if files:
            parts.append(
                f"修改文件 ({len(files)}): "
                f"{', '.join(e.content[:80] for e in files[:10])}"
            )
        if errors:
            unresolved = [e for e in errors if not e.metadata.get("resolved", False)]
            parts.append(
                f"错误 ({len(errors)}, 未解决 {len(unresolved)}): "
                f"{', '.join(e.content[:80] for e in errors[:5])}"
            )
        if commands:
            parts.append(
                f"执行命令 ({len(commands)}): "
                f"{', '.join(e.content[:80] for e in commands[:5])}"
            )

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
        """清理过期记忆

        Args:
            older_than_days: 清理多少天前的记录

        Returns:
            清理的条目数
        """
        cutoff = time.time() - older_than_days * 86400
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM iteration_entries WHERE timestamp < ?", (cutoff,))
        conn.commit()
        deleted = cursor.rowcount
        logger.info("iteration_cleanup deleted=%d older_than_days=%d", deleted, older_than_days)
        return deleted

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM iteration_entries").fetchone()[0]
        cats = conn.execute(
            "SELECT category, COUNT(*) FROM iteration_entries GROUP BY category"
        ).fetchall()
        return {"total": total, "by_category": {r[0]: r[1] for r in cats}}

    # ── 内部方法 ──

    async def _store(
        self, category: str, key: str, content: str, metadata: dict[str, Any]
    ) -> MemoryEntry:
        """内部存储方法"""
        entry = MemoryEntry(
            level=2,
            key=key,
            content=content,
            metadata={**metadata, "category": category, "iteration_id": self._iteration_id},
            ttl=86400 * 7,  # 迭代记忆默认 7 天过期
        )
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO iteration_entries
               (id, iteration_id, category, key, content, metadata, timestamp, ttl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                self._iteration_id,
                category,
                entry.key,
                entry.content,
                json.dumps(entry.metadata, ensure_ascii=False),
                entry.timestamp,
                entry.ttl,
            ),
        )
        conn.commit()
        return entry

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        """将数据库行转换为 MemoryEntry"""
        return MemoryEntry(
            id=row["id"],
            level=2,
            key=row["key"],
            content=row["content"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            timestamp=row["timestamp"],
            ttl=row["ttl"],
        )

    def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def iteration_id(self) -> str | None:
        return self._iteration_id


# ══════════════════════════════════════════════════════════════════════════════
# Level 3: ProjectMemory — 项目级知识图谱（向量存储）
# ══════════════════════════════════════════════════════════════════════════════


class ProjectMemory:
    """项目记忆 — 项目级知识图谱（Level 3）

    特性:
    - ChromaDB 向量存储（可选，回退 SQLite 模式）
    - 存储: 项目架构、技术栈、代码约定、历史 Bug 模式、依赖图
    - 语义搜索（ChromaDB 模式下）
    - 生命周期: 项目持久化

    用法:
        pm = ProjectMemory(project_root=Path("./myproject"))
        await pm.store("architecture", "项目使用 FastAPI + SQLAlchemy 架构")
        results = await pm.search("数据库架构", k=5)
    """

    COLLECTION_NAME = "pycoder_project_memory"

    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._memory_dir = project_root / ".pycoder" / "project_memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)

        # ChromaDB 客户端
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
                "project_memory_chroma_initialized path=%s",
                self._memory_dir / "chroma",
            )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_init_failed: %s，回退到 SQLite 模式", e)
                self._chroma_client = None
                self._chroma_collection = None

        # SQLite 回退存储
        self._sqlite_path = self._memory_dir / "project_memory.db"

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        """获取 SQLite 连接"""
        conn = sqlite3.connect(str(self._sqlite_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS project_entries (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                timestamp REAL NOT NULL,
                ttl REAL
            )"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_project_entries_key
               ON project_entries(key)"""
        )
        conn.commit()
        return conn

    # ── 存储与检索 ──

    async def store(
        self,
        key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryEntry:
        """存储项目记忆

        Args:
            key: 记忆键名
            content: 记忆内容
            metadata: 附加元数据
            embedding: 预计算的向量嵌入（可选）

        Returns:
            创建的 MemoryEntry
        """
        entry = MemoryEntry(
            level=3,
            key=key,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            ttl=None,  # 项目记忆永不过期
        )

        # 优先使用 ChromaDB
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

        # SQLite 兜底
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
        self,
        query: str,
        k: int = 5,
        embedding: list[float] | None = None,
    ) -> list[MemoryEntry]:
        """语义搜索项目记忆

        Args:
            query: 搜索查询（自然语言）
            k: 返回结果数
            embedding: 预计算的查询向量（可选）

        Returns:
            匹配的 MemoryEntry 列表
        """
        results: list[MemoryEntry] = []

        # ChromaDB 语义搜索
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
                            if chroma_results.get("documents") else ""
                        )
                        meta = (
                            chroma_results["metadatas"][0][i]
                            if chroma_results.get("metadatas") else {}
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

        # SQLite 关键词搜索回退
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
        """按键名获取项目记忆"""
        # ChromaDB 获取
        if self._chroma_collection is not None:
            try:
                chroma_results = self._chroma_collection.get(
                    where={"key": key},
                    limit=1,
                )
                if chroma_results and chroma_results.get("ids"):
                    i = 0
                    return MemoryEntry(
                        id=chroma_results["ids"][i],
                        level=3,
                        key=key,
                        content=(
                            chroma_results["documents"][i]
                            if chroma_results.get("documents") else ""
                        ),
                        metadata=(
                            chroma_results["metadatas"][i]
                            if chroma_results.get("metadatas") else {}
                        ),
                    )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("project_memory_chroma_get_failed: %s", e)

        # SQLite 回退
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
        """删除项目记忆"""
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

    # ── 维护操作 ──

    async def summarize(self, llm_provider=None) -> str:
        """生成项目记忆总览摘要"""

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
        """清理过期项目记忆"""
        cutoff = time.time() - older_than_days * 86400
        conn = self._get_sqlite_conn()
        cursor = conn.execute("DELETE FROM project_entries WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
        deleted = cursor.rowcount
        logger.info("project_memory_cleanup deleted=%d", deleted)
        return deleted

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
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


# ══════════════════════════════════════════════════════════════════════════════
# Level 4: GlobalMemory — 用户级偏好模式（跨项目）
# ══════════════════════════════════════════════════════════════════════════════


class GlobalMemory:
    """全局记忆 — 用户级偏好与模式（Level 4）

    特性:
    - ChromaDB 向量存储（可选，回退 SQLite 模式）
    - 存储: 用户编码风格、偏好模式、禁止模式、常用技术栈
    - 语义搜索跨项目知识
    - 生命周期: 跨项目持久化

    用法:
        gm = GlobalMemory(storage_dir=Path.home() / ".pycoder" / "global_memory")
        await gm.store("coding_style", "偏好使用 dataclass 而非 namedtuple")
        results = await gm.search("代码风格", k=5)
    """

    COLLECTION_NAME = "pycoder_global_memory"

    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # ChromaDB 客户端
        self._chroma_client: Any = None
        self._chroma_collection: Any = None
        if _CHROMA_AVAILABLE:
            try:
                self._chroma_client = chromadb.PersistentClient(
                    path=str(self._storage_dir / "chroma"),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                self._chroma_collection = self._chroma_client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(
                "global_memory_chroma_initialized path=%s",
                self._storage_dir / "chroma",
            )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("global_memory_chroma_init_failed: %s，回退到 SQLite 模式", e)
                self._chroma_client = None
                self._chroma_collection = None

        self._sqlite_path = self._storage_dir / "global_memory.db"

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        """获取 SQLite 连接"""
        conn = sqlite3.connect(str(self._sqlite_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS global_entries (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                timestamp REAL NOT NULL,
                ttl REAL
            )"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_global_entries_key
               ON global_entries(key)"""
        )
        conn.commit()
        return conn

    # ── 存储与检索 ──

    async def store(
        self,
        key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryEntry:
        """存储全局记忆

        Args:
            key: 记忆键名
            content: 记忆内容
            metadata: 附加元数据
            embedding: 预计算的向量嵌入（可选）

        Returns:
            创建的 MemoryEntry
        """
        entry = MemoryEntry(
            level=4,
            key=key,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            ttl=None,  # 全局记忆永不过期
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
                logger.warning("global_memory_chroma_store_failed: %s", e)

        conn = self._get_sqlite_conn()
        conn.execute(
            """INSERT OR REPLACE INTO global_entries (id, key, content, metadata, timestamp, ttl)
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

        logger.debug("global_memory_store key=%s", key)
        return entry

    async def search(
        self,
        query: str,
        k: int = 5,
        embedding: list[float] | None = None,
    ) -> list[MemoryEntry]:
        """语义搜索全局记忆

        Args:
            query: 搜索查询
            k: 返回结果数
            embedding: 预计算的查询向量

        Returns:
            匹配的 MemoryEntry 列表
        """
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
                            if chroma_results.get("documents") else ""
                        )
                        meta = (
                            chroma_results["metadatas"][0][i]
                            if chroma_results.get("metadatas") else {}
                        )
                        key = meta.get("key", "") if isinstance(meta, dict) else ""
                        results.append(
                            MemoryEntry(
                                id=doc_id,
                                level=4,
                                key=key,
                                content=doc if doc else "",
                                metadata=meta if isinstance(meta, dict) else {},
                            )
                        )
                    return results
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("global_memory_chroma_search_failed: %s", e)

        conn = self._get_sqlite_conn()
        search_terms = query.split()
        conditions = " OR ".join(["content LIKE ?" for _ in search_terms])
        params = [f"%{t}%" for t in search_terms]
        rows = conn.execute(
            f"SELECT * FROM global_entries WHERE {conditions} ORDER BY timestamp DESC LIMIT ?",
            (*params, k),
        ).fetchall()
        conn.close()

        for row in rows:
            results.append(
                MemoryEntry(
                    id=row["id"],
                    level=4,
                    key=row["key"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    timestamp=row["timestamp"],
                    ttl=row["ttl"],
                )
            )
        return results

    async def get(self, key: str) -> MemoryEntry | None:
        """按键名获取全局记忆"""
        if self._chroma_collection is not None:
            try:
                chroma_results = self._chroma_collection.get(
                    where={"key": key},
                    limit=1,
                )
                if chroma_results and chroma_results.get("ids"):
                    i = 0
                    return MemoryEntry(
                        id=chroma_results["ids"][i],
                        level=4,
                        key=key,
                        content=(
                            chroma_results["documents"][i]
                            if chroma_results.get("documents") else ""
                        ),
                        metadata=(
                            chroma_results["metadatas"][i]
                            if chroma_results.get("metadatas") else {}
                        ),
                    )
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("global_memory_chroma_get_failed: %s", e)

        conn = self._get_sqlite_conn()
        row = conn.execute(
            "SELECT * FROM global_entries WHERE key = ? ORDER BY timestamp DESC LIMIT 1",
            (key,),
        ).fetchone()
        conn.close()

        if row:
            return MemoryEntry(
                id=row["id"],
                level=4,
                key=row["key"],
                content=row["content"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                timestamp=row["timestamp"],
                ttl=row["ttl"],
            )
        return None

    async def delete(self, key: str) -> bool:
        """删除全局记忆"""
        deleted = False
        if self._chroma_collection is not None:
            try:
                existing = self._chroma_collection.get(where={"key": key}, limit=100)
                if existing and existing.get("ids"):
                    self._chroma_collection.delete(ids=existing["ids"])
                    deleted = True
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("global_memory_chroma_delete_failed: %s", e)

        conn = self._get_sqlite_conn()
        cursor = conn.execute("DELETE FROM global_entries WHERE key = ?", (key,))
        conn.commit()
        conn.close()
        if cursor.rowcount > 0:
            deleted = True
        return deleted

    # ── 维护操作 ──

    async def summarize(self, llm_provider=None) -> str:
        """生成全局记忆摘要"""
        conn = self._get_sqlite_conn()
        rows = conn.execute(
            "SELECT key, content FROM global_entries ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
        conn.close()

        if not rows:
            return "无全局记忆"

        keys = list({r["key"] for r in rows})
        parts = [f"全局记忆 ({len(rows)} 条): {', '.join(keys[:20])}"]

        if llm_provider:
            try:
                prompt = (
                    "请用 2-3 句话总结以下用户偏好:\n\n"
                    + "\n".join(f"[{r['key']}] {r['content'][:200]}" for r in rows[:20])
                    + "\n\n摘要:"
                )
                resp = await llm_provider.generate(prompt, max_tokens=200)
                return resp.content.strip()
            except (OSError, RuntimeError, ValueError, AttributeError) as e:
                logger.debug("global_summarize_failed: %s", e)

        return " | ".join(parts)

    async def cleanup(self, older_than_days: int = 365) -> int:
        """清理过期全局记忆"""
        cutoff = time.time() - older_than_days * 86400
        conn = self._get_sqlite_conn()
        cursor = conn.execute("DELETE FROM global_entries WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
        deleted = cursor.rowcount
        logger.info("global_memory_cleanup deleted=%d", deleted)
        return deleted

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        conn = self._get_sqlite_conn()
        total = conn.execute("SELECT COUNT(*) FROM global_entries").fetchone()[0]
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


# ══════════════════════════════════════════════════════════════════════════════
# DeepMemorySystem — 四级记忆编排器
# ══════════════════════════════════════════════════════════════════════════════


class DeepMemorySystem:
    """深度记忆系统 — 编排四级记忆

    统一管理 Working / Iteration / Project / Global 四级记忆，
    提供统一的存储、检索、摘要、清理接口。

    用法:
        system = DeepMemorySystem(
            project_root=Path("./myproject"),
            global_dir=Path.home() / ".pycoder" / "global_memory",
        )
        await system.store(1, "current_task", "修复登录 Bug")
        ctx = await system.retrieve("登录", level="all")
        stats = system.get_stats()
    """

    def __init__(self, project_root: Path, global_dir: Path | None = None):
        self._project_root = project_root
        self._global_dir = global_dir or Path.home() / ".pycoder" / "global_memory"

        # 初始化四级记忆
        self._working = WorkingMemory()
        self._iteration = IterationMemory(project_root / ".pycoder" / "iteration_memory")
        self._project = ProjectMemory(project_root)
        self._global = GlobalMemory(self._global_dir)

        self._last_cleanup = _now_iso()

    # ── 统一存储 ──

    async def store(
        self,
        level: int,
        key: str,
        value: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """统一存储接口，按级别路由

        Args:
            level: 记忆层级 (1-4)
            key: 记忆键名
            value: 记忆内容
            metadata: 附加元数据

        Returns:
            创建的 MemoryEntry
        """
        match level:
            case 1:
                return self._working.store(key, value, metadata)
            case 2:
                return await self._iteration._store(
                    "note", key, value, metadata or {}
                )
            case 3:
                return await self._project.store(key, value, metadata)
            case 4:
                return await self._global.store(key, value, metadata)
            case _:
                raise ValueError(f"无效的记忆层级: {level}，有效值为 1-4")

    # ── 统一检索 ──

    async def retrieve(
        self,
        query: str,
        level: str | int = "all",
        k: int = 5,
    ) -> MemoryContext:
        """多级记忆检索

        Args:
            query: 搜索查询
            level: 搜索层级 ("all" / 1 / 2 / 3 / 4)
            k: 每级返回结果数

        Returns:
            MemoryContext 包含所有匹配结果
        """
        start = time.time()
        entries: list[MemoryEntry] = []
        source_levels: list[int] = []

        if level == "all" or level == 1:
            # WorkingMemory 按 key 精确匹配
            wm_entry = self._working.retrieve(query)
            if wm_entry:
                entries.append(wm_entry)
                source_levels.append(1)
            # 也做内容匹配
            for e in self._working.get_all_entries():
                if query.lower() in e.content.lower() and e not in entries:
                    entries.append(e)
                    source_levels.append(1)

        if level == "all" or level == 2:
            im_entries = await self._iteration.search(query, limit=k)
            for e in im_entries:
                if e not in entries:
                    entries.append(e)
                    source_levels.append(2)

        if level == "all" or level == 3:
            pm_entries = await self._project.search(query, k=k)
            for e in pm_entries:
                if e not in entries:
                    entries.append(e)
                    source_levels.append(3)

        if level == "all" or level == 4:
            gm_entries = await self._global.search(query, k=k)
            for e in gm_entries:
                if e not in entries:
                    entries.append(e)
                    source_levels.append(4)

        total_tokens = sum(_estimate_tokens(e.content) for e in entries)
        elapsed = (time.time() - start) * 1000

        return MemoryContext(
            entries=entries,
            source_levels=list(set(source_levels)),
            total_tokens=total_tokens,
            query=query,
            retrieval_time_ms=elapsed,
        )

    # ── 摘要 ──

    async def summarize(self, level: str | int = "all", llm_provider=None) -> dict[int, str]:
        """生成记忆摘要

        Args:
            level: 要摘要的层级 ("all" / 1 / 2 / 3 / 4)
            llm_provider: 可选的 LLM 提供者

        Returns:
            {level: summary_text} 字典
        """
        summaries: dict[int, str] = {}

        if level == "all" or level == 1:
            summaries[1] = await self._working.summarize(llm_provider)
        if level == "all" or level == 2:
            summaries[2] = await self._iteration.summarize(llm_provider)
        if level == "all" or level == 3:
            summaries[3] = await self._project.summarize(llm_provider)
        if level == "all" or level == 4:
            summaries[4] = await self._global.summarize(llm_provider)

        return summaries

    # ── 清理 ──

    async def cleanup(self, level: str | int = "all") -> dict[int, int]:
        """清理过期记忆

        Args:
            level: 要清理的层级 ("all" / 1 / 2 / 3 / 4)

        Returns:
            {level: deleted_count} 字典
        """
        cleaned: dict[int, int] = {}

        if level == "all" or level == 1:
            self._working.clear()
            cleaned[1] = 0  # WorkingMemory 是瞬时清理

        if level == "all" or level == 2:
            cleaned[2] = await self._iteration.cleanup(older_than_days=14)

        if level == "all" or level == 3:
            cleaned[3] = await self._project.cleanup(older_than_days=90)

        if level == "all" or level == 4:
            cleaned[4] = await self._global.cleanup(older_than_days=365)

        self._last_cleanup = _now_iso()
        logger.info("deep_memory_cleanup cleaned=%s", cleaned)
        return cleaned

    # ── 语义搜索（跨级） ──

    async def deep_search(
        self,
        query: str,
        k: int = 5,
        embedding: list[float] | None = None,
    ) -> MemoryContext:
        """深度语义搜索 — 优先在 Project 和 Global 级做向量搜索

        Args:
            query: 搜索查询
            k: 返回结果数
            embedding: 预计算的查询向量

        Returns:
            MemoryContext
        """
        start = time.time()
        entries: list[MemoryEntry] = []
        source_levels: list[int] = []

        # Level 3: 项目向量搜索
        pm_entries = await self._project.search(query, k=k, embedding=embedding)
        for e in pm_entries:
            entries.append(e)
            source_levels.append(3)

        # Level 4: 全局向量搜索
        gm_entries = await self._global.search(query, k=k, embedding=embedding)
        for e in gm_entries:
            entries.append(e)
            source_levels.append(4)

        # Level 2: FTS5 全文搜索补充
        im_entries = await self._iteration.search(query, limit=k)
        for e in im_entries:
            if e not in entries:
                entries.append(e)
                source_levels.append(2)

        total_tokens = sum(_estimate_tokens(e.content) for e in entries)
        elapsed = (time.time() - start) * 1000

        return MemoryContext(
            entries=entries,
            source_levels=list(set(source_levels)),
            total_tokens=total_tokens,
            query=query,
            retrieval_time_ms=elapsed,
        )

    # ── 统计 ──

    def get_stats(self) -> MemoryStats:
        """获取所有级别的记忆统计"""
        level_stats: dict[int, dict[str, int]] = {
            1: {"entries": self._working.entry_count, "tokens": self._working.token_count},
            2: self._iteration.get_stats(),
            3: self._project.get_stats(),
            4: self._global.get_stats(),
        }

        total_entries = self._working.entry_count
        for level in (2, 3, 4):
            stats = level_stats[level]
            total_entries += stats.get("total", stats.get("total_sqlite", 0))

        return MemoryStats(
            level_stats=level_stats,
            total_entries=total_entries,
            total_size_bytes=0,
            last_cleanup=self._last_cleanup,
            chroma_available=_CHROMA_AVAILABLE,
        )

    # ── 迭代管理 ──

    async def start_iteration(self, iteration_id: str) -> None:
        """开始新迭代"""
        await self._iteration.start_iteration(iteration_id)

    async def end_iteration(self) -> None:
        """结束当前迭代"""
        await self._iteration.end_iteration()

    # ── 便捷方法 ──

    async def track_file(self, file_path: str, action: str = "modified") -> MemoryEntry:
        """便捷：追踪文件变更"""
        return await self._iteration.track_file(file_path, action)

    async def track_command(
        self, command: str, exit_code: int = 0, output: str = "",
    ) -> MemoryEntry:
        """便捷：追踪命令执行"""
        return await self._iteration.track_command(command, exit_code, output)

    async def track_error(self, error_message: str, resolved: bool = False) -> MemoryEntry:
        """便捷：追踪错误"""
        return await self._iteration.track_error(error_message, resolved)

    def close(self) -> None:
        """关闭所有资源"""
        self._iteration.close()

    @property
    def working(self) -> WorkingMemory:
        return self._working

    @property
    def iteration(self) -> IterationMemory:
        return self._iteration

    @property
    def project(self) -> ProjectMemory:
        return self._project

    @property
    def global_(self) -> GlobalMemory:
        return self._global


# ══════════════════════════════════════════════════════════════════════════════
# 能力注册
# ══════════════════════════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> None:
    """向能力总线注册深度记忆能力

    注册以下能力:
    - memory.deep_store: 存储到深度记忆
    - memory.deep_retrieve: 从深度记忆检索
    - memory.deep_summarize: 摘要记忆层级
    - memory.deep_stats: 获取记忆统计
    - memory.deep_search: 语义搜索记忆
    """

    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    # 使用全局单例（实际部署时通过依赖注入）
    _system: DeepMemorySystem | None = None

    def _get_system() -> DeepMemorySystem:
        nonlocal _system
        if _system is None:
            _system = DeepMemorySystem(project_root=Path.cwd())
        return _system

    # ── memory.deep_store ──

    async def _deep_store(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """存储深度记忆"""
        system = _get_system()
        entry = await system.store(
            level=params["level"],
            key=params["key"],
            value=params["value"],
            metadata=params.get("metadata"),
        )
        return {
            "id": entry.id,
            "level": entry.level,
            "key": entry.key,
            "timestamp": entry.timestamp,
        }

    # ── memory.deep_retrieve ──

    async def _deep_retrieve(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """检索深度记忆"""
        system = _get_system()
        context = await system.retrieve(
            query=params["query"],
            level=params.get("level", "all"),
            k=params.get("k", 5),
        )
        return {
            "entries": [
                {
                    "id": e.id,
                    "level": e.level,
                    "key": e.key,
                    "content": e.content[:500],
                    "metadata": e.metadata,
                }
                for e in context.entries
            ],
            "source_levels": context.source_levels,
            "total_tokens": context.total_tokens,
            "retrieval_time_ms": context.retrieval_time_ms,
        }

    # ── memory.deep_summarize ──

    async def _deep_summarize(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """摘要记忆层级"""
        system = _get_system()
        summaries = await system.summarize(level=params.get("level", "all"))
        return {"summaries": {str(k): v for k, v in summaries.items()}}

    # ── memory.deep_stats ──

    async def _deep_stats(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """获取记忆统计"""
        system = _get_system()
        stats = system.get_stats()
        return {
            "level_stats": {
                str(k): v for k, v in stats.level_stats.items()
            },
            "total_entries": stats.total_entries,
            "last_cleanup": stats.last_cleanup,
            "chroma_available": stats.chroma_available,
        }

    # ── memory.deep_search ──

    async def _deep_search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """语义搜索记忆"""
        system = _get_system()
        context = await system.deep_search(
            query=params["query"],
            k=params.get("k", 5),
            embedding=params.get("embedding"),
        )
        return {
            "entries": [
                {
                    "id": e.id,
                    "level": e.level,
                    "key": e.key,
                    "content": e.content[:500],
                    "metadata": e.metadata,
                }
                for e in context.entries
            ],
            "source_levels": context.source_levels,
            "total_tokens": context.total_tokens,
            "retrieval_time_ms": context.retrieval_time_ms,
        }

    # ── 注册到总线 ──

    registry.register(
        CapabilityDefinition(
            id="memory.deep_store",
            name="深度记忆存储",
            description=(
                "将数据存储到指定层级的深度记忆系统（Level 1-4），"
                "支持工作记忆、迭代记忆、项目记忆和全局记忆"
            ),
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.SELF_MODIFY],
            schema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "记忆层级 (1=工作, 2=迭代, 3=项目, 4=全局)",
                        "minimum": 1,
                        "maximum": 4,
                    },
                    "key": {"type": "string", "description": "记忆键名"},
                    "value": {"type": "string", "description": "记忆内容"},
                    "metadata": {"type": "object", "description": "附加元数据"},
                },
                "required": ["level", "key", "value"],
            },
            tags=["memory", "deep", "store", "记忆", "深度"],
        ),
        handler=_deep_store,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_retrieve",
            name="深度记忆检索",
            description="从深度记忆系统的指定层级检索记忆，支持跨级联合检索",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "level": {
                        "type": "string",
                        "description": "搜索层级 (all, 1, 2, 3, 4)",
                        "default": "all",
                    },
                    "k": {
                        "type": "integer",
                        "description": "每级返回结果数",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
            },
            tags=["memory", "deep", "retrieve", "search", "记忆", "检索"],
        ),
        handler=_deep_retrieve,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_summarize",
            name="深度记忆摘要",
            description="压缩和总结指定层级的记忆内容，可选使用 LLM 生成智能摘要",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": "要摘要的层级 (all, 1, 2, 3, 4)",
                        "default": "all",
                    },
                },
            },
            tags=["memory", "deep", "summarize", "摘要", "记忆"],
        ),
        handler=_deep_summarize,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_stats",
            name="深度记忆统计",
            description="获取所有层级的记忆统计信息，包括条目数、Token 使用量、ChromaDB 状态等",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["memory", "deep", "stats", "统计", "记忆"],
        ),
        handler=_deep_stats,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_search",
            name="深度语义搜索",
            description="在 Project 和 Global 级别执行向量语义搜索，辅以迭代级 FTS5 全文搜索",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "k": {
                        "type": "integer",
                        "description": "返回结果数",
                        "default": 5,
                    },
                    "embedding": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "预计算的查询向量",
                    },
                },
                "required": ["query"],
            },
            tags=["memory", "deep", "search", "semantic", "语义", "搜索"],
        ),
        handler=_deep_search,
    )

    logger.info(
        "deep_memory_capabilities_registered chroma_available=%s",
        _CHROMA_AVAILABLE,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════════════════════════

_deep_memory_instance: DeepMemorySystem | None = None


def get_deep_memory(
    project_root: Path | None = None,
    global_dir: Path | None = None,
) -> DeepMemorySystem:
    """获取 DeepMemorySystem 单例

    Args:
        project_root: 项目根路径，首次调用时设置
        global_dir: 全局记忆存储目录

    Returns:
        DeepMemorySystem 实例
    """
    global _deep_memory_instance
    if _deep_memory_instance is None:
        _deep_memory_instance = DeepMemorySystem(
            project_root=project_root or Path.cwd(),
            global_dir=global_dir,
        )
    return _deep_memory_instance


def reset_deep_memory() -> None:
    """重置深度记忆实例（用于测试）"""
    global _deep_memory_instance
    _deep_memory_instance = None
