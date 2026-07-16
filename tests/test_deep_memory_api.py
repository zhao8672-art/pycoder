"""
深度记忆 API 路由单元测试 — 覆盖 deep_memory_api.py 所有端点

测试范围:
  - POST /api/memory/deep/store    — 存储到深度记忆
  - POST /api/memory/deep/retrieve — 从深度记忆检索
  - POST /api/memory/deep/summarize — 摘要记忆层级
  - GET  /api/memory/deep/stats    — 获取记忆统计
  - POST /api/memory/deep/search   — 语义搜索记忆
  - GET  /api/memory/deep/cleanup  — 清理过期记忆
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.memory.deep_memory import (
    DeepMemorySystem,
    MemoryContext,
    MemoryEntry,
    MemoryStats,
    reset_deep_memory,
)


# ── 辅助函数 ──────────────────────────────────────────────


def _make_memory_entry(
    entry_id: str = "mem-001",
    level: int = 1,
    key: str = "test_key",
    content: str = "测试记忆内容",
) -> MemoryEntry:
    """创建模拟的 MemoryEntry"""
    return MemoryEntry(
        id=entry_id,
        level=level,
        key=key,
        content=content,
        timestamp=1700000000.0,
        metadata={"source": "test"},
    )


def _make_memory_context(
    entries_count: int = 3,
) -> MemoryContext:
    """创建模拟的 MemoryContext"""
    entries = [
        _make_memory_entry(f"mem-{i:03d}", level=(i % 4) + 1, key=f"key_{i}")
        for i in range(1, entries_count + 1)
    ]
    return MemoryContext(
        entries=entries,
        source_levels=[1, 2, 3],
        total_tokens=1500,
        retrieval_time_ms=25.5,
    )


def _make_memory_stats() -> MemoryStats:
    """创建模拟的 MemoryStats"""
    return MemoryStats(
        level_stats={
            1: {"entries": 10, "tokens": 5000},
            2: {"total": 25, "by_category": {"note": 15, "error": 10}},
            3: {"total": 50, "total_sqlite": 50},
            4: {"total": 30, "total_sqlite": 30},
        },
        total_entries=115,
        total_size_bytes=102400,
        last_cleanup="2025-01-01T00:00:00Z",
        chroma_available=True,
    )


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_deep_memory() -> None:
    """每个测试前重置深度记忆实例"""
    reset_deep_memory()
    yield
    reset_deep_memory()


@pytest.fixture
def mock_system() -> MagicMock:
    """创建模拟的 DeepMemorySystem"""
    system = MagicMock(spec=DeepMemorySystem)

    # store
    system.store = AsyncMock(
        return_value=_make_memory_entry("mem-new", level=3, key="new_key")
    )

    # retrieve
    system.retrieve = AsyncMock(return_value=_make_memory_context(3))

    # summarize
    system.summarize = AsyncMock(
        return_value={
            1: "工作记忆摘要: 共 10 条",
            2: "迭代记忆摘要: 共 25 条",
            3: "项目记忆摘要: 共 50 条",
            4: "全局记忆摘要: 共 30 条",
        }
    )

    # get_stats
    system.get_stats = MagicMock(return_value=_make_memory_stats())

    # deep_search
    system.deep_search = AsyncMock(return_value=_make_memory_context(5))

    # cleanup
    system.cleanup = AsyncMock(
        return_value={1: 0, 2: 5, 3: 10, 4: 2}
    )

    return system


@pytest.fixture
def client_with_system(mock_system: MagicMock) -> TestClient:
    """注入模拟 DeepMemorySystem 的 TestClient"""
    from pycoder.server.routers import deep_memory_api

    # 替换 _get_system 函数
    with patch(
        "pycoder.server.routers.deep_memory_api.get_deep_memory",
        return_value=mock_system,
    ):
        from pycoder.server.app import app

        with TestClient(app) as c:
            yield c


# ── POST /api/memory/deep/store 测试 ──────────────────────


class TestStoreMemory:
    """存储深度记忆端点"""

    def test_store_success(self, client_with_system: TestClient) -> None:
        """测试成功存储记忆"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 3,
                "key": "architecture",
                "value": "项目使用 FastAPI + SQLAlchemy 架构",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["level"] == 3
        assert data["key"] == "new_key"
        assert "timestamp" in data

    def test_store_level_1(self, client_with_system: TestClient) -> None:
        """测试存储到工作记忆层级"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 1,
                "key": "current_task",
                "value": "修复登录 Bug",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == 3  # mock 返回 level=3

    def test_store_level_4(self, client_with_system: TestClient) -> None:
        """测试存储到全局记忆层级"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 4,
                "key": "coding_style",
                "value": "偏好使用 dataclass",
                "metadata": {"language": "python", "framework": "FastAPI"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data

    def test_store_invalid_level(self, client_with_system: TestClient) -> None:
        """测试无效层级返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 5,
                "key": "test",
                "value": "test",
            },
        )
        assert resp.status_code == 422

    def test_store_level_0(self, client_with_system: TestClient) -> None:
        """测试层级 0 返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 0,
                "key": "test",
                "value": "test",
            },
        )
        assert resp.status_code == 422

    def test_store_empty_key(self, client_with_system: TestClient) -> None:
        """测试空键名返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 1,
                "key": "",
                "value": "test",
            },
        )
        assert resp.status_code == 422

    def test_store_empty_value(self, client_with_system: TestClient) -> None:
        """测试空内容返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 1,
                "key": "test",
                "value": "",
            },
        )
        assert resp.status_code == 422

    def test_store_value_error(self, client_with_system: TestClient, mock_system: MagicMock) -> None:
        """测试存储值错误返回 400"""
        mock_system.store = AsyncMock(
            side_effect=ValueError("无效的记忆层级: 99")
        )

        resp = client_with_system.post(
            "/api/memory/deep/store",
            json={
                "level": 3,
                "key": "test",
                "value": "test",
            },
        )
        assert resp.status_code == 400
        assert "无效的记忆层级" in resp.json()["detail"]


# ── POST /api/memory/deep/retrieve 测试 ───────────────────


class TestRetrieveMemory:
    """检索深度记忆端点"""

    def test_retrieve_success(self, client_with_system: TestClient) -> None:
        """测试成功检索记忆"""
        resp = client_with_system.post(
            "/api/memory/deep/retrieve",
            json={
                "query": "数据库架构",
                "level": "all",
                "k": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert len(data["entries"]) == 3
        assert "source_levels" in data
        assert "total_tokens" in data
        assert "retrieval_time_ms" in data
        for entry in data["entries"]:
            assert "id" in entry
            assert "level" in entry
            assert "key" in entry
            assert "content" in entry

    def test_retrieve_specific_level(self, client_with_system: TestClient) -> None:
        """测试检索特定层级"""
        resp = client_with_system.post(
            "/api/memory/deep/retrieve",
            json={
                "query": "代码风格",
                "level": 4,
                "k": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_retrieve_level_all_string(self, client_with_system: TestClient) -> None:
        """测试 level 为字符串 "all" """
        resp = client_with_system.post(
            "/api/memory/deep/retrieve",
            json={
                "query": "测试",
                "level": "all",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_retrieve_default_k(self, client_with_system: TestClient) -> None:
        """测试默认 k 值"""
        resp = client_with_system.post(
            "/api/memory/deep/retrieve",
            json={
                "query": "默认参数",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_retrieve_empty_query(self, client_with_system: TestClient) -> None:
        """测试空查询返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/retrieve",
            json={
                "query": "",
            },
        )
        assert resp.status_code == 422

    def test_retrieve_entry_content_truncated(self, client_with_system: TestClient) -> None:
        """测试内容被截断到 500 字符"""
        resp = client_with_system.post(
            "/api/memory/deep/retrieve",
            json={
                "query": "长内容",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["entries"]:
            assert len(entry["content"]) <= 500


# ── POST /api/memory/deep/summarize 测试 ──────────────────


class TestSummarizeMemory:
    """摘要记忆端点"""

    def test_summarize_all_levels(self, client_with_system: TestClient) -> None:
        """测试摘要所有层级"""
        resp = client_with_system.post(
            "/api/memory/deep/summarize",
            json={"level": "all"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summaries" in data
        assert "1" in data["summaries"]
        assert "2" in data["summaries"]
        assert "3" in data["summaries"]
        assert "4" in data["summaries"]

    def test_summarize_specific_level(self, client_with_system: TestClient) -> None:
        """测试摘要特定层级"""
        resp = client_with_system.post(
            "/api/memory/deep/summarize",
            json={"level": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summaries" in data

    def test_summarize_default_level(self, client_with_system: TestClient) -> None:
        """测试默认层级（不传 level）"""
        resp = client_with_system.post(
            "/api/memory/deep/summarize",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summaries" in data


# ── GET /api/memory/deep/stats 测试 ───────────────────────


class TestMemoryStats:
    """记忆统计端点"""

    def test_get_stats_success(self, client_with_system: TestClient) -> None:
        """测试成功获取统计信息"""
        resp = client_with_system.get("/api/memory/deep/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "level_stats" in data
        assert "total_entries" in data
        assert data["total_entries"] == 115
        assert "total_size_bytes" in data
        assert "last_cleanup" in data
        assert "chroma_available" in data
        assert data["chroma_available"] is True

    def test_get_stats_zero_entries(self, client_with_system: TestClient, mock_system: MagicMock) -> None:
        """测试零条目统计"""
        mock_system.get_stats = MagicMock(
            return_value=MemoryStats(
                level_stats={1: {"entries": 0}, 2: {}, 3: {}, 4: {}},
                total_entries=0,
                total_size_bytes=0,
                last_cleanup="",
                chroma_available=False,
            )
        )

        resp = client_with_system.get("/api/memory/deep/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 0
        assert data["chroma_available"] is False

    def test_get_stats_level_stats_keys(self, client_with_system: TestClient) -> None:
        """测试层级统计包含所有层级"""
        resp = client_with_system.get("/api/memory/deep/stats")
        assert resp.status_code == 200
        data = resp.json()
        for level in ["1", "2", "3", "4"]:
            assert level in data["level_stats"], f"缺少层级 {level}"


# ── POST /api/memory/deep/search 测试 ─────────────────────


class TestSemanticSearch:
    """语义搜索端点"""

    def test_search_success(self, client_with_system: TestClient) -> None:
        """测试成功语义搜索"""
        resp = client_with_system.post(
            "/api/memory/deep/search",
            json={
                "query": "FastAPI 最佳实践",
                "k": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert len(data["entries"]) == 5
        assert "source_levels" in data
        assert "total_tokens" in data
        assert "retrieval_time_ms" in data
        for entry in data["entries"]:
            assert "id" in entry
            assert "level" in entry
            assert "key" in entry
            assert "content" in entry
            assert "metadata" in entry

    def test_search_default_k(self, client_with_system: TestClient) -> None:
        """测试默认 k 值"""
        resp = client_with_system.post(
            "/api/memory/deep/search",
            json={"query": "默认搜索"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_search_empty_query(self, client_with_system: TestClient) -> None:
        """测试空查询返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/search",
            json={"query": ""},
        )
        assert resp.status_code == 422

    def test_search_large_k(self, client_with_system: TestClient) -> None:
        """测试大 k 值"""
        resp = client_with_system.post(
            "/api/memory/deep/search",
            json={
                "query": "大结果集",
                "k": 100,
            },
        )
        assert resp.status_code == 200

    def test_search_invalid_k(self, client_with_system: TestClient) -> None:
        """测试无效 k 值返回 422"""
        resp = client_with_system.post(
            "/api/memory/deep/search",
            json={
                "query": "test",
                "k": 0,
            },
        )
        assert resp.status_code == 422

        resp = client_with_system.post(
            "/api/memory/deep/search",
            json={
                "query": "test",
                "k": 101,
            },
        )
        assert resp.status_code == 422


# ── GET /api/memory/deep/cleanup 测试 ─────────────────────


class TestCleanupMemory:
    """清理记忆端点"""

    def test_cleanup_all(self, client_with_system: TestClient) -> None:
        """测试清理所有层级"""
        resp = client_with_system.get("/api/memory/deep/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert "cleaned" in data
        assert "1" in data["cleaned"]
        assert "2" in data["cleaned"]
        assert "3" in data["cleaned"]
        assert "4" in data["cleaned"]

    def test_cleanup_specific_level(self, client_with_system: TestClient) -> None:
        """测试清理特定层级"""
        resp = client_with_system.get("/api/memory/deep/cleanup?level=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "cleaned" in data

    def test_cleanup_all_string(self, client_with_system: TestClient) -> None:
        """测试清理所有（字符串 all）"""
        resp = client_with_system.get("/api/memory/deep/cleanup?level=all")
        assert resp.status_code == 200
        data = resp.json()
        assert "cleaned" in data

    def test_cleanup_level_1(self, client_with_system: TestClient) -> None:
        """测试清理工作记忆"""
        resp = client_with_system.get("/api/memory/deep/cleanup?level=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "cleaned" in data