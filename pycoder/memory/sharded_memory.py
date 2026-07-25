"""P1-B: 分片记忆存储 — LRU + 按需加载 + 磁盘持久化

设计动机:
    deep_memory.py 中的 WorkingMemory 已有 LRU + token 限制（轻量），
    但未来需要存储大量条目时（如长期会话历史、向量索引缓存），
    一次性加载全部到内存会消耗过高。

    ShardedMemory 提供:
    - 按 hash(key) 分片到 N 个磁盘文件
    - 内存中只保留活跃分片 + LRU 淘汰
    - 单条目按需加载（mmap 或 json）
    - 线程安全

适用场景:
    - 长期会话历史（>10000 条）
    - 向量嵌入缓存
    - 用户偏好模式
    - 跨项目知识图谱节点缓存

不适用:
    - WorkingMemory（已有 LRU，无需分片）
    - SQLite/ChromaDB 后端（它们自己管理内存）

用法:
    store = ShardedMemory(Path("./memories"), shard_count=16, max_inmemory=100)
    store.put("user_pref_1", {"theme": "dark"})
    val = store.get("user_pref_1")  # 首次从磁盘加载，后续走 LRU
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ShardedEntry:
    """分片存储的单条条目"""

    key: str
    value: Any
    timestamp: float = field(default_factory=time.time)
    ttl: float | None = None  # 秒，None 表示永不过期

    def is_expired(self) -> bool:
        """是否已过期"""
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl


class ShardedMemory:
    """分片记忆存储 — 内存 LRU + 磁盘分片持久化

    线程安全。所有操作都通过锁保护。
    """

    def __init__(
        self,
        base_dir: Path,
        shard_count: int = 16,
        max_inmemory: int = 100,
        file_prefix: str = "shard",
    ) -> None:
        """
        Args:
            base_dir: 存储根目录
            shard_count: 分片数量（决定并发度与单文件大小）
            max_inmemory: 内存 LRU 容量
            file_prefix: 分片文件名前缀
        """
        if shard_count <= 0:
            raise ValueError("shard_count 必须 > 0")
        if max_inmemory <= 0:
            raise ValueError("max_inmemory 必须 > 0")

        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._shard_count = shard_count
        self._max_inmemory = max_inmemory
        self._file_prefix = file_prefix

        # 内存 LRU 缓存: key -> ShardedEntry
        self._cache: OrderedDict[str, ShardedEntry] = OrderedDict()
        # 索引: key -> 所在分片号（避免每次都重新 hash）
        self._key_to_shard: dict[str, int] = {}
        # 分片级写锁（避免并发写同一分片）
        self._shard_locks: list[threading.Lock] = [
            threading.Lock() for _ in range(shard_count)
        ]
        # 全局读锁（保护 cache 和 index）
        self._global_lock = threading.RLock()

    # ── 公开 API ──────────────────────────────────────────

    def put(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """存储一个键值对（同时写入内存缓存和磁盘分片）

        Args:
            key: 键名
            value: 值（必须可 JSON 序列化）
            ttl: 过期时间（秒），None 表示永不过期
        """
        if not key:
            raise ValueError("key 不能为空")

        entry = ShardedEntry(key=key, value=value, ttl=ttl)
        shard_id = self._shard_of(key)

        # 写磁盘（分片锁）
        with self._shard_locks[shard_id]:
            self._write_to_shard(shard_id, entry)

        # 写内存（全局锁）
        with self._global_lock:
            self._key_to_shard[key] = shard_id
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = entry
            else:
                self._cache[key] = entry
                self._evict_if_needed()

        logger.debug(
            "sharded_put key=%s shard=%d cache_size=%d",
            key, shard_id, len(self._cache),
        )

    def get(self, key: str) -> Any | None:
        """获取一个键的值（先查 LRU，未命中则从磁盘加载）

        Returns:
            值；键不存在或已过期返回 None
        """
        with self._global_lock:
            # LRU 命中
            if key in self._cache:
                entry = self._cache[key]
                if entry.is_expired():
                    self._remove_key(key)
                    return None
                self._cache.move_to_end(key)
                return entry.value

            # LRU 未命中，查索引
            shard_id = self._key_to_shard.get(key)
            if shard_id is None:
                # 索引中也没有，可能在磁盘上（其他进程写入）
                shard_id = self._shard_of(key)

        # 从磁盘加载（分片锁）
        with self._shard_locks[shard_id]:
            entry = self._read_from_shard(shard_id, key)

        if entry is None:
            return None
        if entry.is_expired():
            # 异步删除过期项
            with self._shard_locks[shard_id]:
                self._delete_from_shard(shard_id, key)
            return None

        # 装入 LRU
        with self._global_lock:
            self._key_to_shard[key] = shard_id
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = entry
            self._evict_if_needed()

        return entry.value

    def delete(self, key: str) -> bool:
        """删除一个键"""
        with self._global_lock:
            shard_id = self._key_to_shard.get(key)
            in_cache = key in self._cache
            in_index = shard_id is not None

            if not in_cache and not in_index:
                # 仍然尝试磁盘（可能在磁盘但未加载到索引）
                shard_id = self._shard_of(key)

        if shard_id is None:
            return False

        with self._shard_locks[shard_id]:
            existed_on_disk = self._delete_from_shard(shard_id, key)

        with self._global_lock:
            self._remove_key(key)

        return existed_on_disk or in_cache

    def exists(self, key: str) -> bool:
        """键是否存在（不更新 LRU）"""
        with self._global_lock:
            if key in self._cache:
                return not self._cache[key].is_expired()
            shard_id = self._key_to_shard.get(key)
            if shard_id is None:
                shard_id = self._shard_of(key)

        with self._shard_locks[shard_id]:
            entry = self._read_from_shard(shard_id, key)
            return entry is not None and not entry.is_expired()

    def clear(self) -> None:
        """清空所有数据（内存 + 磁盘分片）"""
        with self._global_lock:
            self._cache.clear()
            self._key_to_shard.clear()

        # 清空磁盘
        for shard_id in range(self._shard_count):
            with self._shard_locks[shard_id]:
                path = self._shard_path(shard_id)
                if path.exists():
                    path.unlink()

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        with self._global_lock:
            cache_size = len(self._cache)
            index_size = len(self._key_to_shard)

        # 磁盘使用量
        total_bytes = 0
        for shard_id in range(self._shard_count):
            path = self._shard_path(shard_id)
            if path.exists():
                total_bytes += path.stat().st_size

        return {
            "shard_count": self._shard_count,
            "cache_size": cache_size,
            "index_size": index_size,
            "max_inmemory": self._max_inmemory,
            "disk_bytes": total_bytes,
            "base_dir": str(self._base_dir),
        }

    def keys(self) -> list[str]:
        """列出所有键（扫描磁盘分片，较慢）"""
        all_keys: list[str] = []
        for shard_id in range(self._shard_count):
            with self._shard_locks[shard_id]:
                shard_data = self._load_shard(shard_id)
                all_keys.extend(shard_data.keys())
        return all_keys

    # ── 内部方法 ──────────────────────────────────────────

    def _shard_of(self, key: str) -> int:
        """计算 key 所属分片（一致性 hash 简化版）"""
        digest = hashlib.md5(key.encode("utf-8")).digest()  # nosec - 非安全用途
        # 取前 4 字节作为整数
        shard_id = int.from_bytes(digest[:4], "big") % self._shard_count
        return shard_id

    def _shard_path(self, shard_id: int) -> Path:
        """获取分片文件路径"""
        return self._base_dir / f"{self._file_prefix}_{shard_id:04d}.jsonl"

    def _write_to_shard(self, shard_id: int, entry: ShardedEntry) -> None:
        """写入分片（先读出全部，更新键，再写回）"""
        shard_data = self._load_shard(shard_id)
        shard_data[entry.key] = self._serialize_entry(entry)
        self._save_shard(shard_id, shard_data)

    def _read_from_shard(self, shard_id: int, key: str) -> ShardedEntry | None:
        """从分片读取单条"""
        shard_data = self._load_shard(shard_id)
        if key not in shard_data:
            return None
        return self._deserialize_entry(shard_data[key])

    def _delete_from_shard(self, shard_id: int, key: str) -> bool:
        """从分片删除单条"""
        shard_data = self._load_shard(shard_id)
        if key not in shard_data:
            return False
        del shard_data[key]
        self._save_shard(shard_id, shard_data)
        return True

    def _load_shard(self, shard_id: int) -> dict[str, dict[str, Any]]:
        """加载整个分片为 dict"""
        path = self._shard_path(shard_id)
        if not path.exists():
            return {}
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return {}
            # JSONL: 每行一个 entry
            data: dict[str, dict[str, Any]] = {}
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry_dict = json.loads(line)
                    data[entry_dict["key"]] = entry_dict
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(
                        "sharded_load_corrupt_line shard=%d error=%s",
                        shard_id, e,
                    )
            return data
        except OSError as e:
            logger.warning("sharded_load_failed shard=%d error=%s", shard_id, e)
            return {}

    def _save_shard(self, shard_id: int, data: dict[str, dict[str, Any]]) -> None:
        """保存整个分片"""
        path = self._shard_path(shard_id)
        lines = [json.dumps(data[key], ensure_ascii=False) for key in data]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _serialize_entry(self, entry: ShardedEntry) -> dict[str, Any]:
        """序列化为 dict"""
        return {
            "key": entry.key,
            "value": entry.value,
            "timestamp": entry.timestamp,
            "ttl": entry.ttl,
        }

    def _deserialize_entry(self, data: dict[str, Any]) -> ShardedEntry | None:
        """从 dict 反序列化"""
        try:
            return ShardedEntry(
                key=data["key"],
                value=data["value"],
                timestamp=float(data.get("timestamp", time.time())),
                ttl=data.get("ttl"),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("sharded_deserialize_failed error=%s", e)
            return None

    def _evict_if_needed(self) -> None:
        """LRU 淘汰（调用方持有 _global_lock）"""
        while len(self._cache) > self._max_inmemory:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug("sharded_evicted key=%s", evicted_key)

    def _remove_key(self, key: str) -> None:
        """从内存中移除键（调用方持有 _global_lock）"""
        self._cache.pop(key, None)
        self._key_to_shard.pop(key, None)


__all__ = ["ShardedMemory", "ShardedEntry"]
