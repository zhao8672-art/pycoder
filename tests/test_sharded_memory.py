"""P1-B: 深度记忆分片存储 + 懒加载单元测试

验证:
- ShardedMemory 基本 CRUD + LRU + 磁盘持久化
- DeepMemorySystem 子层懒加载（首次访问才初始化）
- 线程安全
- 过期清理
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from pycoder.memory.deep_memory import (
    DeepMemorySystem,
    GlobalMemory,
    IterationMemory,
    ProjectMemory,
    WorkingMemory,
)
from pycoder.memory.sharded_memory import ShardedEntry, ShardedMemory

# ──────────────────────────────────────────────────────────────
# ShardedMemory 测试
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def sharded_store(tmp_path: Path) -> ShardedMemory:
    """创建一个 ShardedMemory 实例"""
    return ShardedMemory(
        base_dir=tmp_path / "shards",
        shard_count=4,
        max_inmemory=10,
        file_prefix="test",
    )


class TestShardedMemoryBasic:
    """ShardedMemory 基本 CRUD 测试"""

    def test_put_and_get(self, sharded_store: ShardedMemory) -> None:
        """存储并读取"""
        sharded_store.put("key1", {"value": 42})
        result = sharded_store.get("key1")
        assert result == {"value": 42}

    def test_get_nonexistent(self, sharded_store: ShardedMemory) -> None:
        """读取不存在的键"""
        assert sharded_store.get("missing") is None

    def test_delete(self, sharded_store: ShardedMemory) -> None:
        """删除键"""
        sharded_store.put("key1", "value1")
        assert sharded_store.delete("key1") is True
        assert sharded_store.get("key1") is None

    def test_delete_nonexistent(self, sharded_store: ShardedMemory) -> None:
        """删除不存在的键返回 False"""
        assert sharded_store.delete("missing") is False

    def test_exists(self, sharded_store: ShardedMemory) -> None:
        """exists 不更新 LRU"""
        sharded_store.put("key1", "value1")
        assert sharded_store.exists("key1") is True
        assert sharded_store.exists("missing") is False

    def test_overwrite(self, sharded_store: ShardedMemory) -> None:
        """覆盖已存在的键"""
        sharded_store.put("key1", "v1")
        sharded_store.put("key1", "v2")
        assert sharded_store.get("key1") == "v2"

    def test_empty_key_rejected(self, sharded_store: ShardedMemory) -> None:
        """空键应被拒绝"""
        with pytest.raises(ValueError):
            sharded_store.put("", "value")

    def test_complex_value(self, sharded_store: ShardedMemory) -> None:
        """复杂嵌套值"""
        value = {
            "list": [1, 2, 3],
            "nested": {"a": "b"},
            "none": None,
            "bool": True,
        }
        sharded_store.put("complex", value)
        assert sharded_store.get("complex") == value


class TestShardedMemoryLRU:
    """LRU 淘汰测试"""

    def test_eviction_when_full(self, tmp_path: Path) -> None:
        """max_inmemory 满后淘汰最久未用"""
        store = ShardedMemory(
            base_dir=tmp_path / "lru",
            shard_count=2,
            max_inmemory=3,
        )
        store.put("a", 1)
        store.put("b", 2)
        store.put("c", 3)
        # 缓存已满，再插入一个
        store.put("d", 4)
        # a 应该被淘汰（最久未用）
        stats = store.stats()
        assert stats["cache_size"] <= 3

    def test_lru_order_updated_on_get(self, tmp_path: Path) -> None:
        """get 操作更新 LRU 顺序"""
        store = ShardedMemory(
            base_dir=tmp_path / "lru2",
            shard_count=2,
            max_inmemory=2,
        )
        store.put("a", 1)
        store.put("b", 2)
        # 访问 a，让 b 成为最久未用
        store.get("a")
        store.put("c", 3)  # 应该淘汰 b
        # a 仍在内存（更新过 LRU）
        # b 已被淘汰到磁盘，但仍可从磁盘读
        assert store.get("a") == 1
        assert store.get("b") == 2  # 从磁盘加载
        assert store.get("c") == 3


class TestShardedMemoryPersistence:
    """磁盘持久化测试"""

    def test_survives_restart(self, tmp_path: Path) -> None:
        """关闭后重新打开，数据仍在"""
        store1 = ShardedMemory(
            base_dir=tmp_path / "persist",
            shard_count=2,
            max_inmemory=5,
        )
        store1.put("key1", "value1")
        store1.put("key2", "value2")

        # 重新打开同一目录
        store2 = ShardedMemory(
            base_dir=tmp_path / "persist",
            shard_count=2,
            max_inmemory=5,
        )
        assert store2.get("key1") == "value1"
        assert store2.get("key2") == "value2"

    def test_clear(self, sharded_store: ShardedMemory) -> None:
        """clear 清空内存和磁盘"""
        sharded_store.put("k1", "v1")
        sharded_store.put("k2", "v2")
        sharded_store.clear()
        assert sharded_store.get("k1") is None
        assert sharded_store.get("k2") is None
        assert sharded_store.keys() == []

    def test_keys(self, sharded_store: ShardedMemory) -> None:
        """keys 返回所有键"""
        sharded_store.put("a", 1)
        sharded_store.put("b", 2)
        sharded_store.put("c", 3)
        keys = set(sharded_store.keys())
        assert keys == {"a", "b", "c"}


class TestShardedMemoryTTL:
    """TTL 过期测试"""

    def test_expired_entry_returns_none(self, sharded_store: ShardedMemory) -> None:
        """过期条目返回 None"""
        sharded_store.put("temp", "value", ttl=0.05)
        time.sleep(0.1)
        assert sharded_store.get("temp") is None

    def test_non_expired_entry_returns_value(self, sharded_store: ShardedMemory) -> None:
        """未过期条目正常返回"""
        sharded_store.put("temp", "value", ttl=10.0)
        assert sharded_store.get("temp") == "value"

    def test_no_ttl_persists(self, sharded_store: ShardedMemory) -> None:
        """无 TTL 的条目永不过期"""
        sharded_store.put("perm", "value")
        time.sleep(0.05)
        assert sharded_store.get("perm") == "value"


class TestShardedMemoryThreadSafety:
    """线程安全测试"""

    def test_concurrent_puts(self, tmp_path: Path) -> None:
        """多线程并发写入不丢数据"""
        store = ShardedMemory(
            base_dir=tmp_path / "conc",
            shard_count=8,
            max_inmemory=100,
        )
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                for i in range(20):
                    store.put(f"key_{idx}_{i}", f"value_{idx}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # 10 workers × 20 keys = 200 keys
        assert len(store.keys()) == 200

    def test_concurrent_gets(self, sharded_store: ShardedMemory) -> None:
        """多线程并发读取"""
        sharded_store.put("shared", "value")
        errors: list[Exception] = []
        results: list[str] = []

        def worker() -> None:
            try:
                v = sharded_store.get("shared")
                if v is not None:
                    results.append(v)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert all(r == "value" for r in results)


class TestShardedMemoryStats:
    """统计信息测试"""

    def test_stats_fields(self, sharded_store: ShardedMemory) -> None:
        """stats 包含所有字段"""
        sharded_store.put("a", 1)
        stats = sharded_store.stats()
        assert "shard_count" in stats
        assert "cache_size" in stats
        assert "index_size" in stats
        assert "max_inmemory" in stats
        assert "disk_bytes" in stats
        assert "base_dir" in stats

    def test_stats_shard_count(self, sharded_store: ShardedMemory) -> None:
        """shard_count 与配置一致"""
        stats = sharded_store.stats()
        assert stats["shard_count"] == 4


class TestShardedEntry:
    """ShardedEntry 数据类测试"""

    def test_no_ttl_never_expires(self) -> None:
        entry = ShardedEntry(key="k", value="v")
        assert entry.is_expired() is False

    def test_ttl_expires(self) -> None:
        entry = ShardedEntry(key="k", value="v", ttl=0.05)
        time.sleep(0.1)
        assert entry.is_expired() is True

    def test_ttl_not_yet_expired(self) -> None:
        entry = ShardedEntry(key="k", value="v", ttl=10.0)
        assert entry.is_expired() is False


# ──────────────────────────────────────────────────────────────
# DeepMemorySystem 懒加载测试
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def deep_system(tmp_path: Path) -> DeepMemorySystem:
    """DeepMemorySystem 实例（子层未初始化）"""
    return DeepMemorySystem(
        project_root=tmp_path / "project",
        global_dir=tmp_path / "global",
    )


class TestDeepMemoryLazyLoading:
    """DeepMemorySystem 子层懒加载测试"""

    def test_init_does_not_create_sublayers(self, deep_system: DeepMemorySystem) -> None:
        """初始化时不创建任何子层"""
        assert deep_system._working is None
        assert deep_system._iteration is None
        assert deep_system._project is None
        assert deep_system._global is None

    def test_working_lazy_init(self, deep_system: DeepMemorySystem) -> None:
        """首次访问 working 才初始化"""
        assert deep_system._working is None
        w = deep_system.working
        assert isinstance(w, WorkingMemory)
        assert deep_system._working is not None

    def test_iteration_lazy_init(self, deep_system: DeepMemorySystem) -> None:
        """首次访问 iteration 才初始化"""
        assert deep_system._iteration is None
        i = deep_system.iteration
        assert isinstance(i, IterationMemory)
        assert deep_system._iteration is not None

    def test_project_lazy_init(self, deep_system: DeepMemorySystem) -> None:
        """首次访问 project 才初始化"""
        assert deep_system._project is None
        p = deep_system.project
        assert isinstance(p, ProjectMemory)
        assert deep_system._project is not None

    def test_global_lazy_init(self, deep_system: DeepMemorySystem) -> None:
        """首次访问 global_memory 才初始化"""
        assert deep_system._global is None
        g = deep_system.global_memory
        assert isinstance(g, GlobalMemory)
        assert deep_system._global is not None

    def test_global_alias_works(self, deep_system: DeepMemorySystem) -> None:
        """global_ 别名指向 global_memory"""
        assert deep_system._global is None
        g1 = deep_system.global_
        g2 = deep_system.global_memory
        assert g1 is g2

    def test_repeated_access_returns_same_instance(self, deep_system: DeepMemorySystem) -> None:
        """重复访问返回同一实例（不重复初始化）"""
        w1 = deep_system.working
        w2 = deep_system.working
        assert w1 is w2

    def test_store_level_1_triggers_working_init(self, deep_system: DeepMemorySystem) -> None:
        """store(level=1) 触发 working 初始化"""
        import asyncio

        assert deep_system._working is None
        asyncio.run(deep_system.store(1, "key", "value"))
        assert deep_system._working is not None


# ──────────────────────────────────────────────────────────────
# 集成测试: DeepMemorySystem 端到端
# ──────────────────────────────────────────────────────────────


class TestDeepMemoryIntegration:
    """端到端测试"""

    def test_working_memory_round_trip(self, deep_system: DeepMemorySystem) -> None:
        """工作记忆存取往返"""
        import asyncio

        asyncio.run(deep_system.store(1, "current_task", "修复 Bug"))
        ctx = asyncio.run(deep_system.retrieve("current_task", level=1))
        assert any("修复 Bug" in e.content for e in ctx.entries)

    def test_stats_after_init(self, deep_system: DeepMemorySystem) -> None:
        """stats 触发子层初始化"""
        from pycoder.memory.deep_memory import MemoryStats

        stats = deep_system.get_stats()
        assert isinstance(stats, MemoryStats)
        # 访问 stats 会触发 working 初始化（get_stats 内部读 working.entry_count）
        assert deep_system._working is not None
