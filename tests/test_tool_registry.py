"""MCP ToolRegistry 测试 — Task 4 工具注册中心"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter

from pycoder.bus.tool_registry import (
    ToolEntry,
    ToolRegistry,
    get_tool_registry,
    register_router_group_tools,
    reset_tool_registry,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """每个测试前重置全局注册中心, 确保隔离"""
    reset_tool_registry()
    yield
    reset_tool_registry()


class TestToolEntry:
    """ToolEntry 数据类测试"""

    def test_default_construction(self) -> None:
        entry = ToolEntry(
            tool_id="test.tool",
            name="Test",
            description="A test tool",
            category="testing",
        )
        assert entry.id == "test.tool"
        assert entry.name == "Test"
        assert entry.tags == []
        assert entry.source == "manual"
        assert entry.metadata == {}

    def test_to_dict(self) -> None:
        entry = ToolEntry(
            tool_id="x",
            name="X",
            description="desc",
            category="cat",
            tags=["t1", "t2"],
        )
        d = entry.to_dict()
        assert d["id"] == "x"
        assert d["name"] == "X"
        assert d["category"] == "cat"
        assert d["tags"] == ["t1", "t2"]


class TestToolRegistryBasic:
    """ToolRegistry 基础功能测试"""

    @pytest.fixture
    def registry(self) -> ToolRegistry:
        return ToolRegistry()

    def test_register_tool_entry(self, registry: ToolRegistry) -> None:
        entry = ToolEntry("t1", "T1", "Test 1", "cat1", tags=["a"])
        assert registry.register(entry) is True
        assert registry.count == 1
        assert registry.exists("t1") is True

    def test_register_none_returns_false(self, registry: ToolRegistry) -> None:
        assert registry.register(None) is False  # type: ignore[arg-type]

    def test_register_invalid_returns_false(self, registry: ToolRegistry) -> None:
        class Invalid:
            pass

        assert registry.register(Invalid()) is False  # type: ignore[arg-type]

    def test_register_capability_definition(self, registry: ToolRegistry) -> None:
        """注册 CapabilityDefinition 类型"""

        class FakeCategory:
            value = "editor"

        class FakeCap:
            id = "editor.code.read"
            name = "Read code"
            description = "Read source files"
            category = FakeCategory()
            tags = ["io", "file"]

        assert registry.register(FakeCap()) is True
        assert registry.count == 1
        entry = registry.get("editor.code.read")
        assert entry is not None
        assert entry.category == "editor"
        assert "io" in entry.tags

    def test_unregister(self, registry: ToolRegistry) -> None:
        entry = ToolEntry("t1", "T1", "desc", "cat", tags=["a"])
        registry.register(entry)
        assert registry.unregister("t1") is True
        assert registry.count == 0
        assert registry.unregister("t1") is False

    def test_get_returns_none_for_missing(self, registry: ToolRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_list_all(self, registry: ToolRegistry) -> None:
        for i in range(3):
            registry.register(ToolEntry(f"t{i}", f"T{i}", "d", "c"))
        all_tools = registry.list_all()
        assert len(all_tools) == 3


class TestToolRegistryQuery:
    """ToolRegistry 查询功能测试"""

    @pytest.fixture
    def registry(self) -> ToolRegistry:
        r = ToolRegistry()
        r.register(ToolEntry("editor.read", "Read", "Read files", "editor", tags=["io"]))
        r.register(ToolEntry("editor.write", "Write", "Write files", "editor", tags=["io", "fs"]))
        r.register(ToolEntry("system.shell", "Shell", "Execute shell commands", "system", tags=["process"]))
        r.register(ToolEntry("plugin.x", "Plugin X", "Sample plugin", "plugin", tags=["sample"]))
        return r

    def test_list_by_category(self, registry: ToolRegistry) -> None:
        editor_tools = registry.list_by_category("editor")
        assert len(editor_tools) == 2
        assert all(t.category == "editor" for t in editor_tools)

    def test_list_by_category_with_enum_value(self, registry: ToolRegistry) -> None:
        # 模拟传入枚举值
        class C:
            value = "editor"

        tools = registry.list_by_category(C())  # type: ignore[arg-type]
        assert len(tools) == 2

    def test_list_by_tag(self, registry: ToolRegistry) -> None:
        io_tools = registry.list_by_tag("io")
        assert len(io_tools) == 2

    def test_search_by_id(self, registry: ToolRegistry) -> None:
        results = registry.search("editor.read")
        assert len(results) >= 1
        assert results[0].id == "editor.read"

    def test_search_by_name(self, registry: ToolRegistry) -> None:
        results = registry.search("Write")
        assert any(t.id == "editor.write" for t in results)

    def test_search_by_description(self, registry: ToolRegistry) -> None:
        results = registry.search("shell")
        assert any(t.id == "system.shell" for t in results)

    def test_search_no_results(self, registry: ToolRegistry) -> None:
        results = registry.search("nonexistent_keyword_xyz")
        assert results == []

    def test_search_empty_query(self, registry: ToolRegistry) -> None:
        results = registry.search("")
        assert results == []

    def test_categories(self, registry: ToolRegistry) -> None:
        cats = registry.categories()
        assert set(cats) == {"editor", "system", "plugin"}

    def test_tags(self, registry: ToolRegistry) -> None:
        tags = registry.tags()
        assert set(tags) >= {"io", "fs", "process", "sample"}

    def test_stats(self, registry: ToolRegistry) -> None:
        stats = registry.stats()
        assert stats["total_tools"] == 4
        assert "editor" in stats["categories"]


class TestToolRegistrySingleton:
    """单例工厂测试"""

    def test_get_tool_registry_returns_same_instance(self) -> None:
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2

    def test_reset_tool_registry(self) -> None:
        r1 = get_tool_registry()
        r1.register(ToolEntry("x", "X", "d", "c"))
        assert r1.count == 1
        reset_tool_registry()
        r2 = get_tool_registry()
        assert r2 is not r1
        assert r2.count == 0


class TestToolRegistryRouterGroup:
    """路由组自动注册测试"""

    def test_register_router_group_tools(self) -> None:
        router = APIRouter()

        @router.get("/test1")
        async def test_endpoint_1() -> dict[str, str]:
            return {"ok": "1"}

        @router.post("/test2")
        async def test_endpoint_2() -> dict[str, str]:
            return {"ok": "2"}

        count = register_router_group_tools("test_group", [router])
        registry = get_tool_registry()
        # 至少注册 2 个端点
        assert count == 2
        assert registry.count == 2
        # 应有 group 统计
        assert "test_group" in registry._group_stats

    def test_register_router_group_tools_empty(self) -> None:
        count = register_router_group_tools("empty_group", [])
        assert count == 0

    def test_register_router_group_with_none(self) -> None:
        count = register_router_group_tools("none_group", [None])
        assert count == 0
