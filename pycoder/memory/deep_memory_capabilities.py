"""深度记忆能力注册 — 将记忆系统能力注册到 V2 能力总线"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_capabilities() -> None:
    """注册所有深度记忆能力到 V2 能力总线

    将原 247 行的巨型函数拆分为多个小函数，每个负责一类记忆能力。
    """
    _register_working_memory()
    _register_iteration_memory()
    _register_project_memory()
    _register_global_memory()
    _register_vector_memory()
    _register_memory_management()


def _register_working_memory() -> None:
    """注册工作记忆能力"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="memory.working.store",
            category=CapabilityCategory.SYSTEM,
            description="存储短期工作记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_working_store,
        ))

        registry.register(CapabilityDefinition(
            id="memory.working.retrieve",
            category=CapabilityCategory.SYSTEM,
            description="检索短期工作记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_working_retrieve,
        ))

        logger.debug("working_memory_capabilities_registered")
    except Exception as e:
        logger.warning("working_memory_register_failed: %s", e)


def _register_iteration_memory() -> None:
    """注册迭代记忆能力"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="memory.iteration.store",
            category=CapabilityCategory.SYSTEM,
            description="存储迭代记忆（当前对话上下文）",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_iteration_store,
        ))

        registry.register(CapabilityDefinition(
            id="memory.iteration.retrieve",
            category=CapabilityCategory.SYSTEM,
            description="检索迭代记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_iteration_retrieve,
        ))

        logger.debug("iteration_memory_capabilities_registered")
    except Exception as e:
        logger.warning("iteration_memory_register_failed: %s", e)


def _register_project_memory() -> None:
    """注册项目记忆能力"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="memory.project.store",
            category=CapabilityCategory.SYSTEM,
            description="存储项目级长期记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.FILE_WRITE},
            trust_level=TrustLevel.WORKSPACE_WRITE,
            handler=_handle_project_store,
        ))

        registry.register(CapabilityDefinition(
            id="memory.project.retrieve",
            category=CapabilityCategory.SYSTEM,
            description="检索项目级长期记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_project_retrieve,
        ))

        logger.debug("project_memory_capabilities_registered")
    except Exception as e:
        logger.warning("project_memory_register_failed: %s", e)


def _register_global_memory() -> None:
    """注册全局记忆能力"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="memory.global.store",
            category=CapabilityCategory.SYSTEM,
            description="存储全局级长期记忆（跨项目）",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.FILE_WRITE},
            trust_level=TrustLevel.WORKSPACE_WRITE,
            handler=_handle_global_store,
        ))

        registry.register(CapabilityDefinition(
            id="memory.global.retrieve",
            category=CapabilityCategory.SYSTEM,
            description="检索全局级长期记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_global_retrieve,
        ))

        logger.debug("global_memory_capabilities_registered")
    except Exception as e:
        logger.warning("global_memory_register_failed: %s", e)


def _register_vector_memory() -> None:
    """注册向量记忆能力"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="memory.vector.search",
            category=CapabilityCategory.SYSTEM,
            description="向量相似度搜索记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_vector_search,
        ))

        registry.register(CapabilityDefinition(
            id="memory.vector.index",
            category=CapabilityCategory.SYSTEM,
            description="索引记忆到向量数据库",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.FILE_WRITE},
            trust_level=TrustLevel.WORKSPACE_WRITE,
            handler=_handle_vector_index,
        ))

        logger.debug("vector_memory_capabilities_registered")
    except Exception as e:
        logger.warning("vector_memory_register_failed: %s", e)


def _register_memory_management() -> None:
    """注册记忆管理能力"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="memory.management.clear",
            category=CapabilityCategory.SYSTEM,
            description="清空指定级别的记忆",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.FILE_WRITE},
            trust_level=TrustLevel.SYSTEM_ACCESS,
            handler=_handle_memory_clear,
        ))

        registry.register(CapabilityDefinition(
            id="memory.management.stats",
            category=CapabilityCategory.SYSTEM,
            description="获取记忆系统统计信息",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_memory_stats,
        ))

        logger.debug("memory_management_capabilities_registered")
    except Exception as e:
        logger.warning("memory_management_register_failed: %s", e)


# ── 处理器实现 ──


async def _handle_working_store(args: dict[str, Any]) -> dict[str, Any]:
    """处理 working memory store"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    await store.store_working(
        key=args.get("key", ""),
        value=args.get("value", ""),
    )
    return {"success": True}


async def _handle_working_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    """处理 working memory retrieve"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    value = await store.retrieve_working(key=args.get("key", ""))
    return {"success": True, "value": value}


async def _handle_iteration_store(args: dict[str, Any]) -> dict[str, Any]:
    """处理 iteration memory store"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    await store.store_iteration(
        session_id=args.get("session_id", ""),
        data=args.get("data", {}),
    )
    return {"success": True}


async def _handle_iteration_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    """处理 iteration memory retrieve"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    data = await store.retrieve_iteration(session_id=args.get("session_id", ""))
    return {"success": True, "data": data}


async def _handle_project_store(args: dict[str, Any]) -> dict[str, Any]:
    """处理 project memory store"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    await store.store_project(
        project_id=args.get("project_id", ""),
        key=args.get("key", ""),
        value=args.get("value", ""),
    )
    return {"success": True}


async def _handle_project_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    """处理 project memory retrieve"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    value = await store.retrieve_project(
        project_id=args.get("project_id", ""),
        key=args.get("key", ""),
    )
    return {"success": True, "value": value}


async def _handle_global_store(args: dict[str, Any]) -> dict[str, Any]:
    """处理 global memory store"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    await store.store_global(
        key=args.get("key", ""),
        value=args.get("value", ""),
    )
    return {"success": True}


async def _handle_global_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    """处理 global memory retrieve"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    value = await store.retrieve_global(key=args.get("key", ""))
    return {"success": True, "value": value}


async def _handle_vector_search(args: dict[str, Any]) -> dict[str, Any]:
    """处理 vector search"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    results = await store.vector_search(
        query=args.get("query", ""),
        limit=args.get("limit", 10),
    )
    return {"success": True, "results": results}


async def _handle_vector_index(args: dict[str, Any]) -> dict[str, Any]:
    """处理 vector index"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    await store.vector_index(
        key=args.get("key", ""),
        value=args.get("value", ""),
        metadata=args.get("metadata", {}),
    )
    return {"success": True}


async def _handle_memory_clear(args: dict[str, Any]) -> dict[str, Any]:
    """处理 memory clear"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    await store.clear(level=args.get("level", "working"))
    return {"success": True}


async def _handle_memory_stats(args: dict[str, Any]) -> dict[str, Any]:
    """处理 memory stats"""
    from pycoder.memory import MemoryStore
    store = MemoryStore()
    stats = await store.get_stats()
    return {"success": True, "stats": stats}