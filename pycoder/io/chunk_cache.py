"""分段缓存 — LRU 缓存最近读取的大文件分段

内存上限可控，防止大文件读取导致内存溢出。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class _CachedChunk:
    content: str
    size_bytes: int


class ChunkCache:
    """LRU 分段缓存

    按文件路径+分块索引作为 key，缓存最近读取的分段。
    超过最大内存限制时淘汰最久未使用的分段。
    """

    def __init__(self, max_bytes: int = 50 * 1024 * 1024):
        self._cache: OrderedDict[str, _CachedChunk] = OrderedDict()
        self._max_bytes = max_bytes
        self._current_bytes = 0

    def get(self, key: str) -> str | None:
        """获取缓存分段，命中时更新 LRU 位置"""
        chunk = self._cache.get(key)
        if chunk is not None:
            self._cache.move_to_end(key)
            return chunk.content
        return None

    def set(self, key: str, content: str):
        """缓存分段，触发 LRU 淘汰"""
        size = len(content.encode("utf-8"))
        # 淘汰旧条目直到有足够空间
        while self._current_bytes + size > self._max_bytes and self._cache:
            _, old = self._cache.popitem(last=False)
            self._current_bytes -= old.size_bytes
        self._cache[key] = _CachedChunk(content=content, size_bytes=size)
        self._current_bytes += size
        self._cache.move_to_end(key)

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._current_bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._current_bytes

    @property
    def entry_count(self) -> int:
        return len(self._cache)
