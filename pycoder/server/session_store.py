"""会话持久化存储 — to be migrated to DAL"""
from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log

# ── 会话数据模型 ──────────────────────────────────────────


@dataclass
class Message:
    """单条聊天消息"""

    role: str  # user | assistant | system | tool
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(
            role=d["role"],
            content=d["content"],
            timestamp=d.get("timestamp", time.time()),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Session:
    """聊天会话"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    model: str = "auto"
    project_path: str = ""
    title: str = ""  # 从第一条消息自动生成
    message_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "project_path": self.project_path,
            "title": self.title,
            "message_count": self.message_count,
            "metadata": self.metadata,
        }


# ── SQLite 会话存储 ──────────────────────────────────────


class SessionStore:
    """
    SQLite 会话持久化存储，带连接池和线程安全锁。

    表结构:
        sessions: session_id, created_at, updated_at, model, project_path, title, metadata(json)
        messages: message_id, session_id, role, content, timestamp, metadata(json)

    用法:
        store = SessionStore()
        sid = store.create_session(model="deepseek-chat")
        store.add_message(sid, "user", "你好")
        history = store.get_messages(sid)
    """

    _init_lock = threading.Lock()
    _db_initialized: bool = False

    def __init__(self, db_path: str | Path = None, pool_size: int = 5):
        if db_path is None:
            from pycoder.server.unified_db import get_db_path

            db_path = get_db_path("sessions")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # 线程本地连接缓存（避免高频创建连接）
        self._local = threading.local()
        # 备选连接池（跨线程共享）
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=pool_size)
        self._pool_max = pool_size
        self._init_db()

    def _init_db(self):
        """初始化数据库表（带 double-check 线程安全锁）"""
        if SessionStore._db_initialized:
            return
        with SessionStore._init_lock:
            if SessionStore._db_initialized:
                return
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        model TEXT DEFAULT 'auto',
                        project_path TEXT DEFAULT '',
                        title TEXT DEFAULT '',
                        message_count INTEGER DEFAULT 0,
                        metadata TEXT DEFAULT '{}'
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        metadata TEXT DEFAULT '{}',
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_updated
                    ON sessions(updated_at DESC)
                """)
            SessionStore._db_initialized = True

    def _connect(self) -> sqlite3.Connection:
        """获取连接：优先从线程本地缓存获取，否则从池获取或新建。"""
        # 尝试线程本地缓存（FastAPI 每个请求在同一线程）
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.execute("SELECT 1")
                return self._local.conn
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                pass

        # 从池获取
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            conn = self._new_conn()

        self._local.conn = conn
        return conn

    def _new_conn(self) -> sqlite3.Connection:
        """创建新连接并配置 WAL 模式"""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def close_pool(self):
        """关闭连接池中的所有连接"""
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break

    # ── 会话操作 ──────────────────────────────────────────

    def create_session(
        self,
        session_id: str = None,
        model: str = "auto",
        project_path: str = "",
        title: str = "",
    ) -> Session:
        """创建新会话"""
        session = Session(
            id=session_id or str(uuid.uuid4()),
            created_at=time.time(),
            updated_at=time.time(),
            model=model,
            project_path=project_path,
            title=title,
        )

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (id, created_at, updated_at, model, project_path, title,
                    message_count, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.created_at,
                    session.updated_at,
                    session.model,
                    session.project_path,
                    session.title,
                    session.message_count,
                    json.dumps(session.metadata),
                ),
            )

        return session

    def get_session(self, session_id: str) -> Session | None:
        """获取会话"""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()

        if row is None:
            return None

        return Session(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            model=row["model"],
            project_path=row["project_path"],
            title=row["title"],
            message_count=row["message_count"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def update_session(self, session_id: str, **kwargs):
        """更新会话字段"""
        allowed = {"model", "project_path", "title", "message_count", "metadata"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}

        if not updates:
            return

        updates["updated_at"] = time.time()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [session_id]

        with self._connect() as conn:
            conn.execute(
                f"UPDATE sessions SET {set_clause} WHERE id = ?",
                values,
            )

    def delete_session(self, session_id: str):
        """删除会话及其所有消息"""
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def batch_delete_sessions(self, session_ids: list[str]) -> int:
        """批量删除会话（含外键级联删除消息）"""
        if not session_ids:
            return 0
        with self._connect() as conn:
            placeholders = ",".join("?" * len(session_ids))
            cursor = conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})",
                session_ids,
            )
            return cursor.rowcount

    def delete_all_sessions(self) -> int:
        """清空所有会话"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions")
            return cursor.rowcount

    def delete_sessions_before(self, timestamp: float) -> int:
        """删除指定时间之前的所有会话"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE updated_at < ?",
                (timestamp,),
            )
            return cursor.rowcount

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """列出会话（按更新时间倒序）"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        return [
            Session(
                id=row["id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                model=row["model"],
                project_path=row["project_path"],
                title=row["title"],
                message_count=row["message_count"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )
            for row in rows
        ]

    def get_last_session(self) -> Session | None:
        """获取最近一次会话"""
        sessions = self.list_sessions(limit=1)
        return sessions[0] if sessions else None

    # ── 消息操作 ──────────────────────────────────────────

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: float = None,
        metadata: dict = None,
    ) -> int:
        """添加消息到会话"""
        ts = timestamp or time.time()
        meta_json = json.dumps(metadata or {})

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO messages (session_id, role, content, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, role, content, ts, meta_json),
            )
            message_id = cursor.lastrowid

            # 更新 message_count 和 updated_at
            conn.execute(
                """UPDATE sessions
                   SET message_count = message_count + 1, updated_at = ?
                   WHERE id = ?""",
                (ts, session_id),
            )

            # 如果是第一条用户消息，自动生成标题
            if role == "user":
                current = conn.execute(
                    "SELECT title, message_count FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if current and not current["title"] and current["message_count"] <= 2:
                    title = content[:50] + ("..." if len(content) > 50 else "")
                    conn.execute(
                        "UPDATE sessions SET title = ? WHERE id = ?",
                        (title, session_id),
                    )

        return message_id

    def get_messages(
        self,
        session_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Message]:
        """获取会话消息列表"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE session_id = ?
                   ORDER BY id ASC LIMIT ? OFFSET ?""",
                (session_id, limit, offset),
            ).fetchall()

        return [
            Message(
                role=row["role"],
                content=row["content"],
                timestamp=row["timestamp"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )
            for row in rows
        ]

    def clear_messages(self, session_id: str):
        """清空会话消息"""
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE sessions SET message_count = 0, updated_at = ? WHERE id = ?",
                (time.time(), session_id),
            )

    # ── 导入/导出 ─────────────────────────────────────────

    def export_session(self, session_id: str) -> dict | None:
        """导出会话为 JSON"""
        session = self.get_session(session_id)
        if session is None:
            return None

        messages = self.get_messages(session_id)
        return {
            "session": session.to_dict(),
            "messages": [m.to_dict() for m in messages],
        }

    def import_session(self, data: dict) -> str:
        """从 JSON 导入会话"""
        s = data.get("session", {})
        session = self.create_session(
            model=s.get("model", "auto"),
            project_path=s.get("project_path", ""),
            title=s.get("title", ""),
        )

        for m in data.get("messages", []):
            self.add_message(
                session_id=session.id,
                role=m["role"],
                content=m["content"],
                timestamp=m.get("timestamp"),
                metadata=m.get("metadata"),
            )

        return session.id

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取存储统计"""
        with self._connect() as conn:
            session_count = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
            message_count = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
            total_tokens = (
                conn.execute("""SELECT SUM(json_extract(metadata, '$.usage.total_tokens'))
                   FROM messages WHERE json_extract(metadata, '$.usage') IS NOT NULL""").fetchone()[
                    0
                ]
                or 0
            )

        return {
            "session_count": session_count,
            "message_count": message_count,
            "total_tokens_approx": total_tokens,
            "db_path": str(self._db_path),
            "db_size_kb": (
                round(self._db_path.stat().st_size / 1024, 1) if self._db_path.exists() else 0
            ),
        }

    def close(self):
        """关闭连接（WAL checkpoint）"""
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError as e:
            log.debug("session_store_close_checkpoint_failed", error=str(e))


# ── 全局单例 ─────────────────────────────────────────────

_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """获取全局会话存储实例（线程安全）"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SessionStore()
    return _store


def reset_session_store():
    """重置全局会话存储"""
    global _store
    if _store:
        _store.close()
    _store = None
