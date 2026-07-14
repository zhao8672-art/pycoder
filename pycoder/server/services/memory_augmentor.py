"""
MemoryAugmentor — 跨会话长期记忆增强组件

职责：
    1. 长期记忆存储 — SQLite 持久化关键事实、决策、解决方案
    2. 记忆检索 — 根据当前对话内容自动调用相关历史记忆
    3. 记忆衰减 — 基于时间+引用频率的淘汰策略

与 MemoryEngine 的关系：
    MemoryEngine 是 V2 大脑的四级记忆体，侧重运行时工作记忆。
    MemoryAugmentor 是服务层组件，提供持久化的跨会话知识检索，
    作为 MemoryEngine 的补充而非替代。

用法:
    aug = MemoryAugmentor()
    # 存储
    aug.store(project="pycoder", key="auth_implementation",
              content="使用 JWT + bcrypt", tags=["auth","security"])
    # 检索
    results = aug.retrieve("用户认证怎么实现")
    # 衰减
    aug.apply_decay()
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field


@dataclass
class LongTermMemory:
    """长期记忆条目"""

    id: int = 0
    project: str = ""  # 所属项目
    key: str = ""  # 记忆键
    content: str = ""  # 记忆内容
    tags: list[str] = field(default_factory=list)  # 标签
    importance: float = 0.5  # 重要性 0-1
    access_count: int = 0  # 引用次数
    created_at: float = 0.0  # 创建时间
    last_accessed: float = 0.0  # 最后访问时间
    ttl_days: int = 90  # 过期天数


class MemoryAugmentor:
    """长期记忆增强器 — 跨会话知识持久化与检索"""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from pycoder.server.unified_db import get_db_path

            db_path = str(get_db_path())
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL DEFAULT '',
                    key TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    importance REAL NOT NULL DEFAULT 0.5,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    ttl_days INTEGER NOT NULL DEFAULT 90
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ltm_project_key
                ON long_term_memory(project, key)
            """)
            conn.commit()
            conn.close()

    # ══════════════════════════════════════════════════════
    # 存储
    # ══════════════════════════════════════════════════════

    def store(
        self,
        project: str,
        key: str,
        content: str,
        tags: list[str] | None = None,
        importance: float = 0.5,
        ttl_days: int = 90,
    ) -> int:
        """存储一条长期记忆（存在则更新）

        Returns:
            memory_id
        """
        now = time.time()
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            # 先查是否存在
            existing = conn.execute(
                "SELECT id, access_count FROM long_term_memory " "WHERE project = ? AND key = ?",
                (project, key),
            ).fetchone()

            if existing:
                mem_id, access = existing
                conn.execute(
                    "UPDATE long_term_memory SET content = ?, tags = ?, "
                    "importance = ?, last_accessed = ?, ttl_days = ? "
                    "WHERE id = ?",
                    (content, tags_json, importance, now, ttl_days, mem_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO long_term_memory "
                    "(project, key, content, tags, importance, access_count, "
                    "created_at, last_accessed, ttl_days) "
                    "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
                    (project, key, content[:5000], tags_json, importance, now, now, ttl_days),
                )
                mem_id = cursor.lastrowid or 0

            conn.commit()
            conn.close()
            return int(mem_id)

    # ══════════════════════════════════════════════════════
    # 检索
    # ══════════════════════════════════════════════════════

    def retrieve(
        self,
        query: str,
        project: str = "",
        max_results: int = 5,
        min_importance: float = 0.1,
    ) -> list[dict]:
        """根据查询关键词检索相关长期记忆

        检索策略: 关键词交集 + 重要性加权
        """
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            params = []
            conditions = []

            # 项目过滤
            if project:
                conditions.append("project = ?")
                params.append(project)

            # 重要性过滤
            conditions.append("importance >= ?")
            params.append(min_importance)

            # 构建关键词搜索 SQL
            or_clauses = []
            for kw in keywords[:10]:
                or_clauses.append("(key LIKE ? OR content LIKE ? OR tags LIKE ?)")
                like_kw = f"%{kw}%"
                params.extend([like_kw, like_kw, like_kw])

            where = " AND ".join(conditions)
            where += f" AND ({' OR '.join(or_clauses)})"

            rows = conn.execute(
                "SELECT id, project, key, content, tags, importance, "
                "access_count, created_at, last_accessed, ttl_days "
                f"FROM long_term_memory WHERE {where} "
                "ORDER BY importance DESC, access_count DESC "
                f"LIMIT {min(max_results, 20)}",
                params,
            ).fetchall()

            # 更新访问计数
            ids = [r[0] for r in rows]
            if ids:
                conn.executemany(
                    "UPDATE long_term_memory SET access_count = access_count + 1, "
                    "last_accessed = ? WHERE id = ?",
                    [(time.time(), rid) for rid in ids],
                )
                conn.commit()

            conn.close()

            results = []
            for row in rows:
                try:
                    tags = json.loads(row[4])
                except (json.JSONDecodeError, TypeError):
                    tags = []
                results.append(
                    {
                        "id": row[0],
                        "project": row[1],
                        "key": row[2],
                        "content": row[3],
                        "tags": tags,
                        "importance": row[5],
                        "access_count": row[6],
                    }
                )

            return results

    # ══════════════════════════════════════════════════════
    # 衰减
    # ══════════════════════════════════════════════════════

    def apply_decay(self, min_importance_threshold: float = 0.05) -> int:
        """应用时间衰减 + 淘汰低重要性过期记忆

        - 超过 TTL 的记忆降低重要性
        - 重要性低于阈值的删除
        - 删除存在时间 > 180 天且 0 引用的记忆

        Returns:
            淘汰的记忆数量
        """
        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self._db_path)

            # 衰减: 每日降低 1%
            deleted = conn.execute(
                "DELETE FROM long_term_memory WHERE "
                "importance * POWER(0.99, (last_accessed - created_at) / 86400.0) < ?",
                (min_importance_threshold,),
            ).rowcount

            # 淘汰: TTL 过期
            expired = conn.execute(
                "DELETE FROM long_term_memory WHERE "
                "(? - created_at) / 86400.0 > ttl_days AND access_count = 0",
                (now,),
            ).rowcount

            # 淘汰: 180 天零引用
            stale = conn.execute(
                "DELETE FROM long_term_memory WHERE "
                "(? - last_accessed) / 86400.0 > 180 AND access_count = 0",
                (now,),
            ).rowcount

            conn.commit()
            conn.close()
            return deleted + expired + stale

    # ══════════════════════════════════════════════════════
    # 注入上下文
    # ══════════════════════════════════════════════════════

    def build_context_prompt(
        self,
        query: str,
        project: str = "",
        max_memories: int = 3,
    ) -> str:
        """检索相关记忆并生成注入 LLM 的上下文文本"""
        memories = self.retrieve(query, project, max_memories)
        if not memories:
            return ""

        lines = ["## 🧠 相关长期记忆"]
        for mem in memories:
            content_preview = mem["content"][:200]
            tags_str = ", ".join(mem.get("tags", [])[:5])
            lines.append(
                f"- **{mem['key']}**"
                + (f" `[{tags_str}]`" if tags_str else "")
                + f" (重要性: {mem['importance']:.0%})"
                + f"\n  {content_preview}"
            )
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════

    _STOP_WORDS = {
        "的",
        "了",
        "是",
        "在",
        "和",
        "也",
        "都",
        "就",
        "但",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "be",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
    }

    @classmethod
    def _extract_keywords(cls, text: str) -> list[str]:
        words = re.findall(r"[\u4e00-\u9fff\w]{2,}", text.lower())
        return [w for w in words if w not in cls._STOP_WORDS]

    def get_stats(self) -> dict:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            total = conn.execute("SELECT COUNT(*) FROM long_term_memory").fetchone()[0]
            avg_importance = (
                conn.execute("SELECT AVG(importance) FROM long_term_memory").fetchone()[0] or 0.0
            )
            conn.close()
        return {
            "total_memories": total,
            "avg_importance": round(avg_importance, 3),
        }
