"""
KV Cache 持久化实现

使用 SQLite 存储 prompt 前缀的摘要和缓存元数据。
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""

    prefix_hash: str
    model: str
    temperature: float
    cached_output: str  # 前缀对应的 LLM 输出（kv cache 元数据）
    token_count: int
    hit_count: int
    created_at: float
    expires_at: float


# 默认缓存时长 (秒)
DEFAULT_TTL = 3600  # 1 小时

# 最大缓存条目数
MAX_ENTRIES = 10000

# 缓存 DB 路径
CACHE_DB = os.path.expanduser("~/.pycoder/prompt_cache.db")


class PromptCache:
    """LLM Prompt 前缀缓存 — 减少重复计算

    缓存粒度: 按 (prefix_hash, model, temperature) 组合缓存。
    prefix_hash 取自 prompt 前 30% 的内容 hash，
    通常是 system_prompt + 工具定义 + 上下文锚点。
    """

    def __init__(self, db_path: str = CACHE_DB) -> None:
        self._db_path = db_path
        self._local: dict[str, CacheEntry] = {}  # 内存缓存 (更快)
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 表"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_cache (
                    prefix_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    cached_output TEXT,
                    token_count INTEGER DEFAULT 0,
                    hit_count INTEGER DEFAULT 0,
                    created_at REAL,
                    expires_at REAL,
                    PRIMARY KEY (prefix_hash, model, temperature)
                )
            """)
            # 索引过期时间，加速淘汰
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON prompt_cache(expires_at)")
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("KV Cache DB 初始化失败: %s", exc)

    def get(self, prompt: str, model: str = "", temperature: float = 0.7) -> str | None:
        """获取缓存的 prefix output

        Args:
            prompt: 完整 prompt
            model: 模型名
            temperature: 温度参数
        Returns:
            缓存的 prefix_output，未命中返回 None
        """
        prefix, prefix_hash = self._extract_prefix(prompt)

        # 1. 检查内存缓存
        key = f"{prefix_hash}:{model}:{temperature}"
        entry = self._local.get(key)
        if entry:
            if entry.expires_at > time.time():
                entry.hit_count += 1
                logger.debug("KV Cache 内存命中: key=%.16s", prefix_hash)
                return entry.cached_output
            else:
                self._local.pop(key, None)

        # 2. 检查 SQLite
        try:
            conn = sqlite3.connect(self._db_path, timeout=3)
            row = conn.execute(
                "SELECT cached_output, hit_count FROM prompt_cache "
                "WHERE prefix_hash=? AND model=? AND temperature=? AND expires_at>?",
                (prefix_hash, model, temperature, time.time()),
            ).fetchone()
            if row:
                output, hit_count = row
                sql = (
                    "UPDATE prompt_cache SET hit_count=? "
                    "WHERE prefix_hash=? AND model=? AND temperature=?"
                )
                conn.execute(sql, (hit_count + 1, prefix_hash, model, temperature))
                conn.commit()
                conn.close()

                # 回填内存缓存
                self._local[key] = CacheEntry(
                    prefix_hash=prefix_hash, model=model, temperature=temperature,
                    cached_output=output, token_count=0,
                    hit_count=int(hit_count) + 1,
                    created_at=time.time(), expires_at=time.time() + DEFAULT_TTL,
                )

                logger.debug("KV Cache SQLite 命中: key=%.16s, hits=%d", prefix_hash, hit_count + 1)
                return output
            conn.close()
        except Exception as exc:
            logger.debug("KV Cache 查询失败: %s", exc)

        return None

    def set(
        self, prompt: str, cached_output: str,
        model: str = "", temperature: float = 0.7,
        token_count: int = 0, ttl: int = DEFAULT_TTL,
    ) -> None:
        """缓存结果

        Args:
            prompt: 完整 prompt (用于提取前缀)
            cached_output: 缓存的输出
            model: 模型名
            temperature: 温度参数
            token_count: 缓存的 token 数
            ttl: 缓存有效期 (秒)
        """
        prefix, prefix_hash = self._extract_prefix(prompt)

        if not prefix.strip():
            return  # 不缓存空前缀

        now = time.time()
        key = f"{prefix_hash}:{model}:{temperature}"

        # 内存缓存
        self._local[key] = CacheEntry(
            prefix_hash=prefix_hash, model=model, temperature=temperature,
            cached_output=cached_output, token_count=token_count,
            hit_count=0, created_at=now, expires_at=now + ttl,
        )

        # 限制内存缓存大小
        if len(self._local) > MAX_ENTRIES:
            self._evict_memory()

        # SQLite 持久化
        try:
            conn = sqlite3.connect(self._db_path, timeout=3)
            sql = (
                "INSERT OR REPLACE INTO prompt_cache "
                "(prefix_hash, model, temperature, cached_output, "
                " token_count, hit_count, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            )
            conn.execute(
                sql,
                (prefix_hash, model, temperature, cached_output,
                 token_count, 0, now, now + ttl),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("KV Cache 写入失败: %s", exc)

    def _extract_prefix(self, prompt: str) -> tuple[str, str]:
        """提取 prompt 前缀 (前 30%) 并计算 hash"""
        if not prompt:
            return "", ""

        # 取前 30% 字符作为前缀
        prefix_len = max(100, len(prompt) // 3)
        prefix = prompt[:prefix_len]

        # 计算 hash
        prefix_hash = hashlib.sha256(prefix.encode()).hexdigest()

        return prefix, prefix_hash

    def hit_rate(self) -> float:
        """计算缓存命中率"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=3)
            total = conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0]
            hits_sql = "SELECT COALESCE(SUM(hit_count), 0) FROM prompt_cache"
            hits = conn.execute(hits_sql).fetchone()[0]
            conn.close()
            if total == 0:
                return 0.0
            return hits / (total * 10)  # 估算
        except Exception:
            return 0.0

    def clear_expired(self) -> int:
        """清理过期缓存，返回清理条目数"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=3)
            count = conn.execute(
                "DELETE FROM prompt_cache WHERE expires_at < ?",
                (time.time(),),
            ).rowcount
            conn.commit()
            conn.close()
            return count
        except Exception:
            return 0

    def clear_all(self) -> None:
        """清空所有缓存"""
        self._local.clear()
        try:
            conn = sqlite3.connect(self._db_path, timeout=3)
            conn.execute("DELETE FROM prompt_cache")
            conn.commit()
            conn.close()
        except Exception:
            pass

    def stats(self) -> dict:
        """缓存统计"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=3)
            total = conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0]
            cache_size = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0
            conn.close()
        except Exception:
            total = 0
            cache_size = 0

        return {
            "memory_entries": len(self._local),
            "sqlite_entries": total,
            "db_size_kb": round(cache_size / 1024, 1),
            "hit_rate": round(self.hit_rate(), 3),
        }

    def _evict_memory(self) -> None:
        """淘汰内存中最早的缓存"""
        if not self._local:
            return
        # 按过期时间排序，淘汰最早的一半
        sorted_entries = sorted(
            self._local.items(),
            key=lambda x: x[1].expires_at,
        )
        evict_count = len(sorted_entries) // 2
        for key, _ in sorted_entries[:evict_count]:
            self._local.pop(key, None)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_cache: PromptCache | None = None


def get_cache() -> PromptCache:
    """获取缓存单例"""
    global _cache
    if _cache is None:
        _cache = PromptCache()
    return _cache
