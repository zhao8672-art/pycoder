"""知识更新模块 — 动态知识获取与 RAG 检索"""

from __future__ import annotations

from typing import Any

from pycoder.knowledge.knowledge_fetcher import KnowledgeChunk, KnowledgeFetcher, KnowledgeSource
from pycoder.knowledge.knowledge_index import KnowledgeIndex
from pycoder.knowledge.update_scheduler import KnowledgeUpdateScheduler

__all__ = [
    "KnowledgeFetcher",
    "KnowledgeSource",
    "KnowledgeChunk",
    "KnowledgeIndex",
    "KnowledgeUpdateScheduler",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册知识更新能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    fetcher = KnowledgeFetcher()
    index = KnowledgeIndex()
    scheduler = KnowledgeUpdateScheduler(fetcher, index)

    def _search_knowledge(params: dict, ctx: dict) -> dict:
        query = params["query"]
        results = index.search(query) if hasattr(index, "search") else []
        return {"results": results, "query": query}

    def _fetch_source(params: dict, ctx: dict) -> dict:
        source_id = params["source_id"]
        chunks = fetcher.fetch_source(source_id)
        if chunks:
            index.index_chunks(chunks)
        return {"chunks_indexed": len(chunks), "source_id": source_id}

    def _register_source(params: dict, ctx: dict) -> dict:
        source = KnowledgeSource(
            id=params["id"],
            name=params["name"],
            url=params["url"],
            category=params.get("category", "general"),
            update_interval_h=params.get("update_interval_h", 24),
        )
        fetcher.register_source(source)
        return {"success": True, "source_id": params["id"]}

    def _list_sources(params: dict, ctx: dict) -> dict:
        sources = fetcher.list_sources()
        return {"sources": [{"id": s.id, "name": s.name, "url": s.url} for s in sources]}

    def _trigger_update(params: dict, ctx: dict) -> dict:
        result = scheduler.run_update(params.get("source_id"))
        return {"result": result}

    registry.register(
        CapabilityDefinition(
            id="knowledge.search",
            name="搜索知识库",
            description="在知识库中语义搜索相关内容，返回匹配结果",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                },
                "required": ["query"],
            },
            tags=["knowledge", "search", "知识", "搜索", "RAG"],
        ),
        handler=_search_knowledge,
    )

    registry.register(
        CapabilityDefinition(
            id="knowledge.fetch",
            name="获取知识源",
            description="从指定知识源获取最新内容并索引入库",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NETWORK, SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "知识源 ID"},
                },
                "required": ["source_id"],
            },
            tags=["knowledge", "fetch", "更新", "获取"],
        ),
        handler=_fetch_source,
    )

    registry.register(
        CapabilityDefinition(
            id="knowledge.register_source",
            name="注册知识源",
            description="注册一个新的知识源用于定期更新",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "知识源唯一标识"},
                    "name": {"type": "string", "description": "知识源名称"},
                    "url": {"type": "string", "description": "知识源 URL"},
                    "category": {"type": "string", "description": "分类"},
                    "update_interval_h": {"type": "integer", "description": "更新间隔（小时）"},
                },
                "required": ["id", "name", "url"],
            },
            tags=["knowledge", "register", "source", "知识源"],
        ),
        handler=_register_source,
    )

    registry.register(
        CapabilityDefinition(
            id="knowledge.list_sources",
            name="列出知识源",
            description="列出所有已注册的知识源",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["knowledge", "list", "source", "知识源"],
        ),
        handler=_list_sources,
    )

    registry.register(
        CapabilityDefinition(
            id="knowledge.trigger_update",
            name="触发知识更新",
            description="手动触发知识源更新任务",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NETWORK, SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "知识源 ID（可选，不指定则更新全部）",
                    },
                },
            },
            tags=["knowledge", "update", "trigger", "更新"],
        ),
        handler=_trigger_update,
    )
