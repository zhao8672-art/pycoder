"""P1-C: WebSocket 并发优化 — LLM 调用限流 + 响应缓存 + 背压

设计动机:
    ws_handler_v2 在高并发下:
    - 每个连接的 chat 请求都立即调用 LLM → LLM API 限流/超时
    - 相同 prompt 短期内重复请求 → 浪费 token
    - 连接积压无上限 → 内存暴涨

    本模块提供三个独立工具:
    - LLMConcurrencyLimiter: asyncio.Semaphore 包装，限制并发 LLM 调用数
    - WSResponseCache: TTL 缓存，相同 prompt+model 在 TTL 内复用响应
    - WSBackpressureManager: 队列深度限制，超限拒绝新请求

使用方式:
    # 1. 限流
    limiter = get_llm_limiter(max_concurrent=8)
    async with limiter.acquire():
        result = await call_llm(...)

    # 2. 缓存
    cache = get_ws_response_cache(ttl=60)
    cached = cache.get(prompt, model)
    if cached:
        return cached
    result = await call_llm(...)
    cache.set(prompt, model, result)

    # 3. 背压
    bp = get_backpressure_manager(max_per_connection=10)
    if not bp.try_acquire(connection_id):
        return error("too_many_inflight")
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# 1. LLM 并发限流器
# ════════════════════════════════════════════════════════════════════════════


class LLMConcurrencyLimiter:
    """LLM 并发限流器 — 基于 asyncio.Semaphore

    限制同时进行的 LLM 调用数量，避免:
    - LLM API 限流（429）
    - 内存暴涨
    - 单用户占满全部资源

    用法:
        limiter = LLMConcurrencyLimiter(max_concurrent=8)
        async with limiter.acquire():
            result = await call_llm(...)
    """

    def __init__(self, max_concurrent: int = 8) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent 必须 > 0")
        self._max = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._active = 0
        self._total_acquired = 0
        self._total_released = 0
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def active_count(self) -> int:
        """当前活跃请求数"""
        return self._active

    def acquire(self):
        """获取一个并发槽位（async context manager）"""

        async def _acquire() -> None:
            await self._sem.acquire()
            async with self._lock:
                self._active += 1
                self._total_acquired += 1
            logger.debug(
                "llm_limiter_acquired active=%d/%d total=%d",
                self._active, self._max, self._total_acquired,
            )

        class _Ctx:
            async def __aenter__(self) -> None:
                await _acquire()

            async def __aexit__(self, *exc: Any) -> None:
                async with limiter_lock:
                    limiter._active -= 1
                    limiter._total_released += 1
                limiter._sem.release()

        limiter = self
        limiter_lock = self._lock
        return _Ctx()

    def stats(self) -> dict[str, int]:
        """获取统计信息"""
        return {
            "max_concurrent": self._max,
            "active": self._active,
            "available": self._max - self._active,
            "total_acquired": self._total_acquired,
            "total_released": self._total_released,
        }


# ════════════════════════════════════════════════════════════════════════════
# 2. WebSocket 响应缓存
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class CacheEntry:
    """缓存条目"""

    value: Any
    timestamp: float
    ttl: float


class WSResponseCache:
    """WebSocket 响应缓存 — TTL + LRU

    缓存键: (prompt_hash, model)
    缓存值: LLM 响应

    用法:
        cache = WSResponseCache(max_size=128, ttl=60)
        key = cache.make_key(prompt, model)
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = await call_llm(...)
        cache.set(key, result)
    """

    def __init__(self, max_size: int = 128, ttl: float = 60.0) -> None:
        if max_size <= 0:
            raise ValueError("max_size 必须 > 0")
        if ttl <= 0:
            raise ValueError("ttl 必须 > 0")
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def make_key(prompt: str, model: str, **extra: Any) -> str:
        """生成缓存键

        基于 prompt 内容 + model + 可选额外参数的 hash，
        避免长 prompt 占用内存。
        """
        # 取 prompt 的前 500 字符 + hash，避免大 prompt 拖慢 hash
        prompt_part = prompt[:500]
        full = json.dumps(
            {"prompt": prompt_part, "model": model, "extra": extra},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.md5(full.encode("utf-8")).hexdigest()  # nosec

    async def get(self, key: str) -> Any | None:
        """获取缓存值（未命中或已过期返回 None）"""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.time() - entry.timestamp > entry.ttl:
                # 过期
                self._cache.pop(key, None)
                self._misses += 1
                return None
            # 命中，更新 LRU 顺序
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """设置缓存值"""
        async with self._lock:
            effective_ttl = ttl if ttl is not None else self._ttl
            entry = CacheEntry(
                value=value,
                timestamp=time.time(),
                ttl=effective_ttl,
            )
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = entry
            # LRU 淘汰
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
                self._evictions += 1

    async def invalidate(self, key: str) -> bool:
        """手动失效某个键"""
        async with self._lock:
            return self._cache.pop(key, None) is not None

    async def clear(self) -> None:
        """清空所有缓存"""
        async with self._lock:
            self._cache.clear()

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total > 0 else 0.0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(hit_rate, 4),
        }


# ════════════════════════════════════════════════════════════════════════════
# 3. 背压管理器
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class ConnectionBackpressure:
    """单连接的背压状态"""

    connection_id: str
    inflight: int = 0
    max_inflight: int = 10
    last_activity: float = field(default_factory=time.time)
    total_acquired: int = 0
    total_rejected: int = 0

    def try_acquire(self) -> bool:
        """尝试获取一个槽位"""
        if self.inflight >= self.max_inflight:
            self.total_rejected += 1
            return False
        self.inflight += 1
        self.total_acquired += 1
        self.last_activity = time.time()
        return True

    def release(self) -> None:
        """释放一个槽位"""
        if self.inflight > 0:
            self.inflight -= 1
        self.last_activity = time.time()


class WSBackpressureManager:
    """WebSocket 背压管理器 — 限制单连接并发请求数

    用法:
        bp = WSBackpressureManager(max_per_connection=10)
        if not bp.try_acquire(connection_id):
            return error("too_many_inflight")
        try:
            result = await handle_request(...)
        finally:
            bp.release(connection_id)
    """

    def __init__(
        self,
        max_per_connection: int = 10,
        idle_cleanup_seconds: float = 300.0,
    ) -> None:
        if max_per_connection <= 0:
            raise ValueError("max_per_connection 必须 > 0")
        self._max_per_conn = max_per_connection
        self._idle_seconds = idle_cleanup_seconds
        self._connections: dict[str, ConnectionBackpressure] = {}
        self._lock = asyncio.Lock()

    def try_acquire(self, connection_id: str) -> bool:
        """尝试获取槽位（同步，无需 await）"""
        import threading

        with threading.Lock():
            conn = self._connections.get(connection_id)
            if conn is None:
                conn = ConnectionBackpressure(
                    connection_id=connection_id,
                    max_inflight=self._max_per_conn,
                )
                self._connections[connection_id] = conn
            return conn.try_acquire()

    def release(self, connection_id: str) -> None:
        """释放槽位"""
        import threading

        with threading.Lock():
            conn = self._connections.get(connection_id)
            if conn:
                conn.release()

    def get_connection_state(self, connection_id: str) -> ConnectionBackpressure | None:
        """获取连接状态"""
        return self._connections.get(connection_id)

    def cleanup_idle(self) -> int:
        """清理空闲连接，返回清理数量"""
        now = time.time()
        idle_keys = [
            cid
            for cid, conn in self._connections.items()
            if now - conn.last_activity > self._idle_seconds and conn.inflight == 0
        ]
        for cid in idle_keys:
            del self._connections[cid]
        return len(idle_keys)

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total_inflight = sum(c.inflight for c in self._connections.values())
        total_acquired = sum(c.total_acquired for c in self._connections.values())
        total_rejected = sum(c.total_rejected for c in self._connections.values())
        return {
            "connection_count": len(self._connections),
            "max_per_connection": self._max_per_conn,
            "total_inflight": total_inflight,
            "total_acquired": total_acquired,
            "total_rejected": total_rejected,
            "idle_cleanup_seconds": self._idle_seconds,
        }


# ════════════════════════════════════════════════════════════════════════════
# 全局单例
# ════════════════════════════════════════════════════════════════════════════


_llm_limiter: LLMConcurrencyLimiter | None = None
_ws_cache: WSResponseCache | None = None
_backpressure: WSBackpressureManager | None = None


def get_llm_limiter(max_concurrent: int = 8) -> LLMConcurrencyLimiter:
    """获取全局 LLM 并发限流器"""
    global _llm_limiter
    if _llm_limiter is None:
        _llm_limiter = LLMConcurrencyLimiter(max_concurrent=max_concurrent)
    return _llm_limiter


def get_ws_response_cache(max_size: int = 128, ttl: float = 60.0) -> WSResponseCache:
    """获取全局 WebSocket 响应缓存"""
    global _ws_cache
    if _ws_cache is None:
        _ws_cache = WSResponseCache(max_size=max_size, ttl=ttl)
    return _ws_cache


def get_backpressure_manager(
    max_per_connection: int = 10,
) -> WSBackpressureManager:
    """获取全局背压管理器"""
    global _backpressure
    if _backpressure is None:
        _backpressure = WSBackpressureManager(max_per_connection=max_per_connection)
    return _backpressure


def reset_concurrency_singletons() -> None:
    """重置所有单例（用于测试）"""
    global _llm_limiter, _ws_cache, _backpressure
    _llm_limiter = None
    _ws_cache = None
    _backpressure = None


__all__ = [
    "LLMConcurrencyLimiter",
    "WSResponseCache",
    "WSBackpressureManager",
    "ConnectionBackpressure",
    "CacheEntry",
    "get_llm_limiter",
    "get_ws_response_cache",
    "get_backpressure_manager",
    "reset_concurrency_singletons",
]
