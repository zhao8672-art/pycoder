"""P1-C: WebSocket 并发控制工具单元测试

验证:
- LLMConcurrencyLimiter: 信号量限流 + 统计
- WSResponseCache: TTL + LRU + 命中率
- WSBackpressureManager: 单连接槽位 + 空闲清理
"""

from __future__ import annotations

import asyncio
import time

import pytest

from pycoder.server.ws_concurrency import (
    LLMConcurrencyLimiter,
    WSBackpressureManager,
    WSResponseCache,
    get_backpressure_manager,
    get_llm_limiter,
    get_ws_response_cache,
    reset_concurrency_singletons,
)

# ──────────────────────────────────────────────────────────────
# LLMConcurrencyLimiter 测试
# ──────────────────────────────────────────────────────────────


class TestLLMConcurrencyLimiter:
    """LLM 并发限流器测试"""

    def test_invalid_max_concurrent(self) -> None:
        with pytest.raises(ValueError):
            LLMConcurrencyLimiter(max_concurrent=0)
        with pytest.raises(ValueError):
            LLMConcurrencyLimiter(max_concurrent=-1)

    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        limiter = LLMConcurrencyLimiter(max_concurrent=2)
        assert limiter.active_count == 0

        async with limiter.acquire():
            assert limiter.active_count == 1

        assert limiter.active_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_acquires_respect_limit(self) -> None:
        """并发 acquire 不超过 max_concurrent"""
        limiter = LLMConcurrencyLimiter(max_concurrent=3)
        max_observed = [0]
        current = [0]
        lock = asyncio.Lock()

        async def worker() -> None:
            async with limiter.acquire():
                async with lock:
                    current[0] += 1
                    max_observed[0] = max(max_observed[0], current[0])
                await asyncio.sleep(0.05)
                async with lock:
                    current[0] -= 1

        await asyncio.gather(*[worker() for _ in range(10)])

        assert max_observed[0] <= 3
        assert limiter.active_count == 0

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        limiter = LLMConcurrencyLimiter(max_concurrent=2)
        async with limiter.acquire():
            stats = limiter.stats()
            assert stats["max_concurrent"] == 2
            assert stats["active"] == 1
            assert stats["available"] == 1
            assert stats["total_acquired"] == 1

        stats = limiter.stats()
        assert stats["active"] == 0
        assert stats["total_released"] == 1

    @pytest.mark.asyncio
    async def test_waiting_acquires_after_release(self) -> None:
        """释放后等待者获得槽位"""
        limiter = LLMConcurrencyLimiter(max_concurrent=1)
        order: list[str] = []

        async def worker(name: str) -> None:
            async with limiter.acquire():
                order.append(f"{name}_start")
                await asyncio.sleep(0.05)
                order.append(f"{name}_end")

        await asyncio.gather(worker("a"), worker("b"))

        # a 先开始，b 必须等 a 结束
        assert order[0] == "a_start"
        assert order[1] == "a_end"
        assert order[2] == "b_start"
        assert order[3] == "b_end"


# ──────────────────────────────────────────────────────────────
# WSResponseCache 测试
# ──────────────────────────────────────────────────────────────


class TestWSResponseCache:
    """WebSocket 响应缓存测试"""

    def test_invalid_params(self) -> None:
        with pytest.raises(ValueError):
            WSResponseCache(max_size=0)
        with pytest.raises(ValueError):
            WSResponseCache(ttl=0)

    def test_make_key_deterministic(self) -> None:
        """相同输入产生相同 key"""
        k1 = WSResponseCache.make_key("hello", "deepseek-chat")
        k2 = WSResponseCache.make_key("hello", "deepseek-chat")
        assert k1 == k2

    def test_make_key_differs_on_different_input(self) -> None:
        k1 = WSResponseCache.make_key("hello", "deepseek-chat")
        k2 = WSResponseCache.make_key("world", "deepseek-chat")
        assert k1 != k2

    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        cache = WSResponseCache(max_size=10, ttl=60)
        key = "test_key"
        await cache.set(key, {"response": "ok"})
        result = await cache.get(key)
        assert result == {"response": "ok"}

    @pytest.mark.asyncio
    async def test_miss_returns_none(self) -> None:
        cache = WSResponseCache(max_size=10, ttl=60)
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self) -> None:
        cache = WSResponseCache(max_size=10, ttl=0.05)
        await cache.set("k", "v")
        time.sleep(0.1)
        result = await cache.get("k")
        assert result is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self) -> None:
        """max_size 满后淘汰最久未访问"""
        cache = WSResponseCache(max_size=3, ttl=60)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)
        # 访问 a，使其成为最近使用
        await cache.get("a")
        # 插入 d，应该淘汰 b（最久未用）
        await cache.set("d", 4)
        assert await cache.get("b") is None
        assert await cache.get("a") == 1
        assert await cache.get("c") == 3
        assert await cache.get("d") == 4

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        cache = WSResponseCache(max_size=10, ttl=60)
        await cache.set("k", "v")
        await cache.get("k")  # hit
        await cache.get("missing")  # miss

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["size"] == 1

    @pytest.mark.asyncio
    async def test_invalidate(self) -> None:
        cache = WSResponseCache(max_size=10, ttl=60)
        await cache.set("k", "v")
        assert await cache.invalidate("k") is True
        assert await cache.get("k") is None
        assert await cache.invalidate("missing") is False

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        cache = WSResponseCache(max_size=10, ttl=60)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None


# ──────────────────────────────────────────────────────────────
# WSBackpressureManager 测试
# ──────────────────────────────────────────────────────────────


class TestWSBackpressureManager:
    """背压管理器测试"""

    def test_invalid_max_per_connection(self) -> None:
        with pytest.raises(ValueError):
            WSBackpressureManager(max_per_connection=0)

    def test_try_acquire_and_release(self) -> None:
        bp = WSBackpressureManager(max_per_connection=5)
        assert bp.try_acquire("conn1") is True
        assert bp.try_acquire("conn1") is True
        bp.release("conn1")
        bp.release("conn1")

    def test_max_per_connection(self) -> None:
        bp = WSBackpressureManager(max_per_connection=2)
        assert bp.try_acquire("conn1") is True
        assert bp.try_acquire("conn1") is True
        # 第三个应该被拒绝
        assert bp.try_acquire("conn1") is False
        bp.release("conn1")
        # 释放后可以再次获取
        assert bp.try_acquire("conn1") is True

    def test_independent_connections(self) -> None:
        """不同连接互不影响"""
        bp = WSBackpressureManager(max_per_connection=1)
        assert bp.try_acquire("conn1") is True
        assert bp.try_acquire("conn2") is True  # 不同连接，不互相影响
        assert bp.try_acquire("conn1") is False  # conn1 已满
        assert bp.try_acquire("conn2") is False  # conn2 已满

    def test_get_connection_state(self) -> None:
        bp = WSBackpressureManager(max_per_connection=3)
        bp.try_acquire("conn1")
        bp.try_acquire("conn1")
        state = bp.get_connection_state("conn1")
        assert state is not None
        assert state.inflight == 2
        assert state.total_acquired == 2

    def test_cleanup_idle(self) -> None:
        """清理空闲连接"""
        bp = WSBackpressureManager(
            max_per_connection=5,
            idle_cleanup_seconds=0.05,
        )
        bp.try_acquire("conn1")
        bp.release("conn1")
        time.sleep(0.1)
        cleaned = bp.cleanup_idle()
        assert cleaned == 1
        assert bp.get_connection_state("conn1") is None

    def test_cleanup_keeps_active(self) -> None:
        """活跃连接不被清理"""
        bp = WSBackpressureManager(
            max_per_connection=5,
            idle_cleanup_seconds=0.05,
        )
        bp.try_acquire("conn1")  # 仍在进行中
        time.sleep(0.1)
        cleaned = bp.cleanup_idle()
        assert cleaned == 0
        assert bp.get_connection_state("conn1") is not None

    def test_stats(self) -> None:
        bp = WSBackpressureManager(max_per_connection=5)
        bp.try_acquire("c1")
        bp.try_acquire("c2")
        stats = bp.stats()
        assert stats["connection_count"] == 2
        assert stats["total_inflight"] == 2
        assert stats["total_acquired"] == 2
        assert stats["max_per_connection"] == 5


# ──────────────────────────────────────────────────────────────
# 全局单例测试
# ──────────────────────────────────────────────────────────────


class TestGlobalSingletons:
    """全局单例测试"""

    def setup_method(self) -> None:
        reset_concurrency_singletons()

    def test_get_llm_limiter_singleton(self) -> None:
        l1 = get_llm_limiter()
        l2 = get_llm_limiter()
        assert l1 is l2

    def test_get_ws_response_cache_singleton(self) -> None:
        c1 = get_ws_response_cache()
        c2 = get_ws_response_cache()
        assert c1 is c2

    def test_get_backpressure_manager_singleton(self) -> None:
        b1 = get_backpressure_manager()
        b2 = get_backpressure_manager()
        assert b1 is b2

    def test_reset_clears_all(self) -> None:
        l1 = get_llm_limiter()
        reset_concurrency_singletons()
        l2 = get_llm_limiter()
        assert l1 is not l2


# ──────────────────────────────────────────────────────────────
# 集成场景: 限流器与缓存组合
# ──────────────────────────────────────────────────────────────


class TestIntegrationScenario:
    """集成场景测试"""

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_limiter(self) -> None:
        """缓存命中时不消耗限流槽位"""
        limiter = LLMConcurrencyLimiter(max_concurrent=2)
        cache = WSResponseCache(max_size=10, ttl=60)

        # 第一次: miss → acquire limiter → set cache
        key = WSResponseCache.make_key("prompt1", "model1")
        cached = await cache.get(key)
        assert cached is None

        async with limiter.acquire():
            await asyncio.sleep(0.01)
            await cache.set(key, "response1")

        # 第二次: hit → 不 acquire limiter
        cached = await cache.get(key)
        assert cached == "response1"
        # limiter 不应该被消耗
        assert limiter.active_count == 0
        assert limiter.stats()["total_acquired"] == 1  # 只有第一次 acquire
