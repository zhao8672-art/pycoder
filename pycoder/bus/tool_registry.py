"""MCP 工具注册中心 — 集中查询和管理所有可用工具

设计目标:
    1. 统一工具注册入口: 兼容 CapabilityDefinition + FastAPI 路由组
    2. 多维度查询: 按名称/ID/类别/标签/全文搜索
    3. 自动注册: 通过 `register_router_group_tools()` 在路由组挂载时自动纳入
    4. 单例工厂: `get_tool_registry()` 全局访问点

使用方式:
    registry = get_tool_registry()

    # 手动注册工具
    registry.register(CapabilityDefinition(...))

    # 自动注册路由组
    register_router_group_tools("business", business_routers)

    # 查询工具
    tool = registry.get("editor.code.read")
    all_tools = registry.list_all()
    for tool in registry.list_by_category(CapabilityCategory.EDITOR):
        ...
    results = registry.search("read file")
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 协议定义
# ─────────────────────────────────────────────────────────


class ToolLike(Protocol):
    """工具接口契约 (任何含 id/name/description/category/tags 字段的对象)"""

    id: str
    name: str
    description: str
    category: Any
    tags: list[str]


# ─────────────────────────────────────────────────────────
# 工具条目包装
# ─────────────────────────────────────────────────────────


class ToolEntry:
    """工具注册条目

    兼容多种工具来源:
      - CapabilityDefinition (来自 bus.protocol)
      - FastAPI APIRouter (来自 server.routers.*)
    """

    def __init__(
        self,
        tool_id: str,
        name: str,
        description: str,
        category: str,
        tags: list[str] | None = None,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = tool_id
        self.name = name
        self.description = description
        self.category = category
        self.tags: list[str] = tags or []
        self.source = source
        self.metadata: dict[str, Any] = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return f"ToolEntry(id={self.id!r}, name={self.name!r}, category={self.category!r})"


# ─────────────────────────────────────────────────────────
# 工具注册中心
# ─────────────────────────────────────────────────────────


class ToolRegistry:
    """MCP 工具注册中心

    提供:
        - `register(tool)`: 注册一个工具
        - `get(tool_id)`: 通过 ID 获取
        - `list_all()`: 列出所有工具
        - `list_by_category(category)`: 按类别查询
        - `list_by_tag(tag)`: 按标签查询
        - `search(query)`: 自由文本搜索 (name + description)
        - `unregister(tool_id)`: 注销工具
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}
        self._by_category: dict[str, list[str]] = defaultdict(list)
        self._by_tag: dict[str, list[str]] = defaultdict(list)
        self._lock = threading.Lock()
        # 路由器组自动注册回调: group_name -> count
        self._group_stats: dict[str, int] = {}

    # ── 注册 ──────────────────────────────

    def register(self, tool: ToolLike | ToolEntry | Any) -> bool:
        """注册一个工具

        Args:
            tool: 工具对象, 接受 ToolEntry / CapabilityDefinition /
                  含 id+name+description+category+tags 字段的对象

        Returns:
            True 表示注册成功 (含覆盖), False 表示参数无效
        """
        entry = self._normalize(tool)
        if entry is None:
            return False

        with self._lock:
            if entry.id in self._tools:
                logger.debug("tool_already_registered: %s (覆盖)", entry.id)
                # 移除旧的索引
                self._remove_from_indices(entry.id, self._tools[entry.id])
            self._tools[entry.id] = entry
            self._by_category[entry.category].append(entry.id)
            for tag in entry.tags:
                self._by_tag[tag].append(entry.id)
        logger.debug("tool_registered: %s (%s)", entry.id, entry.name)
        return True

    def register_many(self, tools: list[Any]) -> int:
        """批量注册工具

        Returns:
            成功注册的数量
        """
        count = 0
        for tool in tools:
            if self.register(tool):
                count += 1
        return count

    def unregister(self, tool_id: str) -> bool:
        """注销工具"""
        with self._lock:
            if tool_id not in self._tools:
                return False
            entry = self._tools.pop(tool_id)
            self._remove_from_indices(tool_id, entry)
        return True

    def _remove_from_indices(self, tool_id: str, entry: ToolEntry) -> None:
        """从类别/标签索引中移除"""
        if tool_id in self._by_category.get(entry.category, []):
            self._by_category[entry.category].remove(tool_id)
        for tag in entry.tags:
            if tool_id in self._by_tag.get(tag, []):
                self._by_tag[tag].remove(tool_id)

    @staticmethod
    def _normalize(tool: Any) -> ToolEntry | None:
        """归一化任意工具对象为 ToolEntry"""
        if tool is None:
            return None
        if isinstance(tool, ToolEntry):
            return tool

        # duck-typing: 必须有 id 和 name
        tool_id = getattr(tool, "id", None)
        tool_name = getattr(tool, "name", None)
        if not tool_id or not tool_name:
            return None

        description = getattr(tool, "description", "") or ""
        category_obj = getattr(tool, "category", "uncategorized")
        if hasattr(category_obj, "value"):
            category = str(category_obj.value)
        else:
            category = str(category_obj)
        tags = list(getattr(tool, "tags", []) or [])
        return ToolEntry(
            tool_id=tool_id,
            name=tool_name,
            description=description,
            category=category,
            tags=tags,
        )

    # ── 查询 ──────────────────────────────

    def get(self, tool_id: str) -> ToolEntry | None:
        """通过 ID 获取工具"""
        return self._tools.get(tool_id)

    def exists(self, tool_id: str) -> bool:
        """检查工具是否存在"""
        return tool_id in self._tools

    def list_all(self) -> list[ToolEntry]:
        """列出所有工具"""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[ToolEntry]:
        """按类别列出工具

        Args:
            category: 类别字符串 (如 "editor" / "system" / "self_evo")
                      接受 CapabilityCategory 枚举或字符串
        """
        if hasattr(category, "value"):
            category = str(category.value)
        category = str(category)
        ids = self._by_category.get(category, [])
        return [self._tools[i] for i in ids if i in self._tools]

    def list_by_tag(self, tag: str) -> list[ToolEntry]:
        """按标签列出工具"""
        ids = self._by_tag.get(tag, [])
        return [self._tools[i] for i in ids if i in self._tools]

    def search(self, query: str) -> list[ToolEntry]:
        """自由文本搜索 (name + description + id)

        Args:
            query: 搜索词

        Returns:
            匹配的工具列表, 按相关度排序
        """
        if not query:
            return []
        query_lower = query.lower().strip()
        results: list[tuple[ToolEntry, int]] = []

        for entry in self._tools.values():
            score = 0
            # 精确 ID 匹配
            if query_lower == entry.id.lower():
                score += 100
            elif query_lower in entry.id.lower():
                score += 30
            # 名称匹配
            if query_lower in entry.name.lower():
                score += 50
            # 描述匹配
            if query_lower in entry.description.lower():
                score += 20
            # 标签匹配
            for tag in entry.tags:
                if query_lower in tag.lower():
                    score += 40

            if score > 0:
                results.append((entry, score))

        results.sort(key=lambda x: (x[1], x[0].id), reverse=True)
        return [r[0] for r in results]

    def categories(self) -> list[str]:
        """列出所有已注册类别"""
        return list(self._by_category.keys())

    def tags(self) -> list[str]:
        """列出所有已注册标签"""
        return list(self._by_tag.keys())

    @property
    def count(self) -> int:
        """已注册工具总数"""
        return len(self._tools)

    def stats(self) -> dict[str, Any]:
        """获取注册中心统计"""
        return {
            "total_tools": self.count,
            "categories": {cat: len(ids) for cat, ids in self._by_category.items()},
            "tags": {tag: len(ids) for tag, ids in self._by_tag.items()},
            "group_stats": dict(self._group_stats),
        }

    # ── 路由组自动注册 ────────────────────

    def register_router_group_tools(
        self,
        group_name: str,
        routers: list[Any],
    ) -> int:
        """从 FastAPI 路由器组自动注册工具

        遍历 `routers` 列表, 提取每个路由的 path / methods / endpoint 名称
        作为工具条目注册到注册中心。

        Args:
            group_name: 路由器组名称 (如 "tools" / "business")
            routers: FastAPI APIRouter 对象列表

        Returns:
            成功注册的工具数量
        """
        count = 0
        for router in routers:
            if router is None:
                continue
            # 提取路由 (APIRouter.routes)
            routes = getattr(router, "routes", [])
            for route in routes:
                entry = self._route_to_entry(group_name, route)
                if entry is not None and self.register(entry):
                    count += 1
        self._group_stats[group_name] = (
            self._group_stats.get(group_name, 0) + count
        )
        logger.info(
            "register_router_group_tools group=%s count=%d total=%d",
            group_name,
            count,
            self.count,
        )
        return count

    @staticmethod
    def _route_to_entry(group_name: str, route: Any) -> ToolEntry | None:
        """将 FastAPI 路由转为 ToolEntry"""
        path = getattr(route, "path", None)
        if not path:
            return None
        endpoint = getattr(route, "endpoint", None)
        endpoint_name = getattr(endpoint, "__name__", "unknown") if endpoint else "unknown"
        methods = getattr(route, "methods", set()) or set()
        method_str = ",".join(sorted(methods)) if methods else "GET"
        tool_id = f"{group_name}.{endpoint_name}"
        return ToolEntry(
            tool_id=tool_id,
            name=f"{endpoint_name}",
            description=f"{method_str} {path}",
            category=group_name,
            tags=[group_name, method_str.lower()],
            source="router_group",
            metadata={"path": path, "methods": list(methods)},
        )


# ─────────────────────────────────────────────────────────
# 单例工厂
# ─────────────────────────────────────────────────────────


_instance: ToolRegistry | None = None
_instance_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    """获取 ToolRegistry 全局单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ToolRegistry()
    return _instance


def reset_tool_registry() -> None:
    """重置全局注册中心 (仅用于测试)"""
    global _instance
    with _instance_lock:
        _instance = None


# ─────────────────────────────────────────────────────────
# 自动注册辅助函数
# ─────────────────────────────────────────────────────────


def register_router_group_tools(
    group_name: str,
    routers: list[Any],
) -> int:
    """便捷函数: 通过全局注册中心注册路由组工具

    Args:
        group_name: 组名
        routers: FastAPI APIRouter 列表

    Returns:
        成功注册的工具数量
    """
    return get_tool_registry().register_router_group_tools(group_name, routers)


__all__ = [
    "ToolEntry",
    "ToolRegistry",
    "get_tool_registry",
    "reset_tool_registry",
    "register_router_group_tools",
]
