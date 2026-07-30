"""AI KV 缓存命中统计测试"""
from __future__ import annotations

from pathlib import Path

import pytest

from pycoder.ai.cache.kv_cache import (
    CacheStatsCollector,
    PromptCache,
    get_cache_stats,
)


@pytest.fixture(autouse=True)
def reset_stats_singleton():
    """每个测试前重置统计单例, 避免相互污染"""
    get_cache_stats().reset()
    yield
    get_cache_stats().reset()


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """临时 SQLite DB 路径"""
    return str(tmp_path / "test_prompt_cache.db")


# ════════════════════════════════════════════════════════
# CacheStatsCollector 基础测试
# ════════════════════════════════════════════════════════


class TestCacheStatsCollectorBasic:
    """CacheStatsCollector 数据记录与快照测试"""

    def test_initial_state(self) -> None:
        collector = CacheStatsCollector()
        stats = collector.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert stats["total_lookups"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["total_size_bytes"] == 0

    def test_record_hit(self) -> None:
        collector = CacheStatsCollector()
        collector.record_hit(100)
        collector.record_hit(200)
        stats = collector.get_stats()
        assert stats["hits"] == 2
        assert stats["total_size_bytes"] == 300
        assert stats["total_lookups"] == 2
        assert stats["hit_rate"] == 1.0

    def test_record_miss(self) -> None:
        collector = CacheStatsCollector()
        collector.record_miss()
        collector.record_miss()
        collector.record_miss()
        stats = collector.get_stats()
        assert stats["misses"] == 3
        assert stats["hits"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["total_lookups"] == 3

    def test_mixed_hit_and_miss_hit_rate(self) -> None:
        collector = CacheStatsCollector()
        for _ in range(7):
            collector.record_hit()
        for _ in range(3):
            collector.record_miss()
        stats = collector.get_stats()
        assert stats["hits"] == 7
        assert stats["misses"] == 3
        assert stats["total_lookups"] == 10
        assert stats["hit_rate"] == 0.7

    def test_record_eviction(self) -> None:
        collector = CacheStatsCollector()
        collector.record_hit(1000)
        collector.record_eviction(400)
        stats = collector.get_stats()
        assert stats["evictions"] == 1
        assert stats["total_size_bytes"] == 600

    def test_record_eviction_does_not_underflow(self) -> None:
        """淘汰字节数超过当前大小时不出现负数 (保持原值)"""
        collector = CacheStatsCollector()
        collector.record_hit(100)
        collector.record_eviction(9999)
        stats = collector.get_stats()
        assert stats["evictions"] == 1
        assert stats["total_size_bytes"] == 100  # 大小不变, 不变为负数

    def test_record_eviction_clamps_to_zero(self) -> None:
        """淘汰字节数等于当前大小时夹紧到 0"""
        collector = CacheStatsCollector()
        collector.record_hit(500)
        collector.record_eviction(500)
        stats = collector.get_stats()
        assert stats["evictions"] == 1
        assert stats["total_size_bytes"] == 0

    def test_record_put(self) -> None:
        collector = CacheStatsCollector()
        collector.record_put(512)
        collector.record_put(256)
        stats = collector.get_stats()
        assert stats["total_size_bytes"] == 768

    def test_record_put_zero_or_negative_ignored(self) -> None:
        collector = CacheStatsCollector()
        collector.record_put(0)
        collector.record_put(-100)
        stats = collector.get_stats()
        assert stats["total_size_bytes"] == 0

    def test_reset(self) -> None:
        collector = CacheStatsCollector()
        collector.record_hit(100)
        collector.record_miss()
        collector.record_eviction()
        collector.reset()
        stats = collector.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert stats["total_size_bytes"] == 0


# ════════════════════════════════════════════════════════
# get_cache_stats 单例测试
# ════════════════════════════════════════════════════════


class TestCacheStatsSingleton:
    """get_cache_stats 单例测试"""

    def test_returns_same_instance(self) -> None:
        a = get_cache_stats()
        b = get_cache_stats()
        assert a is b

    def test_singleton_state_shared(self) -> None:
        s1 = get_cache_stats()
        s1.record_hit(50)
        s2 = get_cache_stats()
        stats = s2.get_stats()
        assert stats["hits"] == 1
        assert stats["total_size_bytes"] == 50


# ════════════════════════════════════════════════════════
# PromptCache 自动埋点测试
# ════════════════════════════════════════════════════════


class TestPromptCacheAutoRecord:
    """PromptCache.get/set 自动记录命中/未命中/淘汰"""

    def test_set_then_get_records_hit(self, temp_db_path: str) -> None:
        cache = PromptCache(db_path=temp_db_path)
        prompt = "x" * 500
        cache.set(prompt, "output1")
        result = cache.get(prompt)
        assert result == "output1"
        stats = get_cache_stats().get_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] == 0

    def test_get_unknown_records_miss(self, temp_db_path: str) -> None:
        cache = PromptCache(db_path=temp_db_path)
        result = cache.get("x" * 500)
        assert result is None
        stats = get_cache_stats().get_stats()
        assert stats["misses"] >= 1
        assert stats["hits"] == 0

    def test_mixed_hit_miss(self, temp_db_path: str) -> None:
        cache = PromptCache(db_path=temp_db_path)
        prompt = "x" * 500
        cache.set(prompt, "out")
        # 1 hit
        cache.get(prompt)
        # 1 miss
        cache.get("y" * 500)
        stats = get_cache_stats().get_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1

    def test_total_size_increases_after_put(self, temp_db_path: str) -> None:
        cache = PromptCache(db_path=temp_db_path)
        cache.set("x" * 500, "a" * 100)
        cache.set("y" * 500, "b" * 200)
        stats = get_cache_stats().get_stats()
        assert stats["total_size_bytes"] >= 300

    def test_repeated_get_hits(self, temp_db_path: str) -> None:
        """多次 get 同一 prompt 应累计 hits"""
        cache = PromptCache(db_path=temp_db_path)
        prompt = "z" * 500
        cache.set(prompt, "out")
        for _ in range(5):
            cache.get(prompt)
        stats = get_cache_stats().get_stats()
        assert stats["hits"] >= 5

    def test_reset_clears_all(self, temp_db_path: str) -> None:
        cache = PromptCache(db_path=temp_db_path)
        cache.set("x" * 500, "out")
        cache.get("x" * 500)
        get_cache_stats().reset()
        stats = get_cache_stats().get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_size_bytes"] == 0
