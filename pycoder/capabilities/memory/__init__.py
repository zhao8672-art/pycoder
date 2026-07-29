"""记忆能力域 — 将 memory/ 系统包装为 V2 能力

能力清单：
    memory.context.retrieve — 检索上下文记忆
    memory.facts.store      — 存储事实记忆
    memory.facts.search     — 搜索事实库
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_memory_capabilities() -> None:
    """注册记忆域能力到 V2 能力总线"""
    try:
        from pycoder.bus.protocol import (
            CapabilityCategory,
            CapabilityDefinition,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )
        from pycoder.bus.registry import CapabilityRegistry

        registry = CapabilityRegistry.get_instance()

        registry.register(
            CapabilityDefinition(
                id="memory.context.retrieve",
                category=CapabilityCategory.SYSTEM,
                description="检索上下文记忆",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.NONE},
                trust_level=TrustLevel.READ_ONLY,
                handler=_handle_context_retrieve,
            )
        )

        registry.register(
            CapabilityDefinition(
                id="memory.facts.store",
                category=CapabilityCategory.SYSTEM,
                description="存储事实到长期记忆",
                execution_mode=ExecutionMode.SYNC,
                side_effects={SideEffect.FILE_WRITE},
                trust_level=TrustLevel.WORKSPACE_WRITE,
                handler=_handle_facts_store,
            )
        )

        logger.info("memory_capabilities_registered: count=2")
    except Exception as e:
        logger.warning("memory_capabilities_register_failed: %s", e)


async def _handle_context_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    """处理 memory.context.retrieve"""
    from pycoder.memory import MemoryStore

    store = MemoryStore()
    ctx = await store.retrieve_context(
        query=args.get("query", ""),
        limit=args.get("limit", 10),
    )
    return {"success": True, "context": ctx}


async def _handle_facts_store(args: dict[str, Any]) -> dict[str, Any]:
    """处理 memory.facts.store"""
    from pycoder.memory import MemoryStore

    store = MemoryStore()
    await store.store_fact(
        key=args.get("key", ""),
        value=args.get("value", ""),
        metadata=args.get("metadata", {}),
    )
    return {"success": True}
