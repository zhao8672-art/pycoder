"""深度记忆能力注册 — 向能力总线注册深度记忆相关能力"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register_capabilities(registry: Any) -> None:
    """向能力总线注册深度记忆能力

    注册以下能力:
    - memory.deep_store: 存储到深度记忆
    - memory.deep_retrieve: 从深度记忆检索
    - memory.deep_summarize: 摘要记忆层级
    - memory.deep_stats: 获取记忆统计
    - memory.deep_search: 语义搜索记忆
    """

    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )
    from pycoder.memory.deep_memory_system import DeepMemorySystem

    _system: DeepMemorySystem | None = None

    def _get_system() -> DeepMemorySystem:
        nonlocal _system
        if _system is None:
            _system = DeepMemorySystem(project_root=Path.cwd())
        return _system

    # ── memory.deep_store ──

    async def _deep_store(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        system = _get_system()
        entry = await system.store(
            level=params["level"],
            key=params["key"],
            value=params["value"],
            metadata=params.get("metadata"),
        )
        return {
            "id": entry.id,
            "level": entry.level,
            "key": entry.key,
            "timestamp": entry.timestamp,
        }

    # ── memory.deep_retrieve ──

    async def _deep_retrieve(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        system = _get_system()
        context = await system.retrieve(
            query=params["query"],
            level=params.get("level", "all"),
            k=params.get("k", 5),
        )
        return {
            "entries": [
                {
                    "id": e.id,
                    "level": e.level,
                    "key": e.key,
                    "content": e.content[:500],
                    "metadata": e.metadata,
                }
                for e in context.entries
            ],
            "source_levels": context.source_levels,
            "total_tokens": context.total_tokens,
            "retrieval_time_ms": context.retrieval_time_ms,
        }

    # ── memory.deep_summarize ──

    async def _deep_summarize(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        system = _get_system()
        summaries = await system.summarize(level=params.get("level", "all"))
        return {"summaries": {str(k): v for k, v in summaries.items()}}

    # ── memory.deep_stats ──

    async def _deep_stats(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        system = _get_system()
        stats = system.get_stats()
        return {
            "level_stats": {
                str(k): v for k, v in stats.level_stats.items()
            },
            "total_entries": stats.total_entries,
            "last_cleanup": stats.last_cleanup,
            "chroma_available": stats.chroma_available,
        }

    # ── memory.deep_search ──

    async def _deep_search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        system = _get_system()
        context = await system.deep_search(
            query=params["query"],
            k=params.get("k", 5),
            embedding=params.get("embedding"),
        )
        return {
            "entries": [
                {
                    "id": e.id,
                    "level": e.level,
                    "key": e.key,
                    "content": e.content[:500],
                    "metadata": e.metadata,
                }
                for e in context.entries
            ],
            "source_levels": context.source_levels,
            "total_tokens": context.total_tokens,
            "retrieval_time_ms": context.retrieval_time_ms,
        }

    # ── 注册到总线 ──

    registry.register(
        CapabilityDefinition(
            id="memory.deep_store",
            name="深度记忆存储",
            description=(
                "将数据存储到指定层级的深度记忆系统（Level 1-4），"
                "支持工作记忆、迭代记忆、项目记忆和全局记忆"
            ),
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.SELF_MODIFY],
            schema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "记忆层级 (1=工作, 2=迭代, 3=项目, 4=全局)",
                        "minimum": 1,
                        "maximum": 4,
                    },
                    "key": {"type": "string", "description": "记忆键名"},
                    "value": {"type": "string", "description": "记忆内容"},
                    "metadata": {"type": "object", "description": "附加元数据"},
                },
                "required": ["level", "key", "value"],
            },
            tags=["memory", "deep", "store", "记忆", "深度"],
        ),
        handler=_deep_store,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_retrieve",
            name="深度记忆检索",
            description="从深度记忆系统的指定层级检索记忆，支持跨级联合检索",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "level": {
                        "type": "string",
                        "description": "搜索层级 (all, 1, 2, 3, 4)",
                        "default": "all",
                    },
                    "k": {
                        "type": "integer",
                        "description": "每级返回结果数",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            tags=["memory", "deep", "retrieve", "记忆", "检索"],
        ),
        handler=_deep_retrieve,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_summarize",
            name="深度记忆摘要",
            description="生成指定层级或全部层级的记忆摘要",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": "要摘要的层级 (all, 1, 2, 3, 4)",
                        "default": "all",
                    },
                },
            },
            tags=["memory", "deep", "summarize", "记忆", "摘要"],
        ),
        handler=_deep_summarize,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_stats",
            name="深度记忆统计",
            description="获取深度记忆系统各层级的统计信息",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["memory", "deep", "stats", "记忆", "统计"],
        ),
        handler=_deep_stats,
    )

    registry.register(
        CapabilityDefinition(
            id="memory.deep_search",
            name="深度语义搜索",
            description="跨级深度语义搜索，优先在 Project 和 Global 级做向量搜索",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "k": {
                        "type": "integer",
                        "description": "返回结果数",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            tags=["memory", "deep", "search", "记忆", "搜索"],
        ),
        handler=_deep_search,
    )

    logger.info("深度记忆能力已注册（5 个能力）")
