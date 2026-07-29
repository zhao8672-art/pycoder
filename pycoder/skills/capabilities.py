"""技能市场能力注册 — 向 V2 能力总线注册技能市场相关能力"""

from __future__ import annotations

import logging
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)


def register_capabilities(registry: Any) -> None:
    """向总线注册技能市场相关能力"""
    # ── skills.marketplace.search ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.search",
            name="搜索技能",
            description="在技能市场中搜索技能，支持关键词、分类和标签过滤",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "search", "技能", "搜索"],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类过滤"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签过滤",
                    },
                },
            },
        ),
        handler=_handle_search_skills,
    )

    # ── skills.marketplace.install ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.install",
            name="安装技能",
            description="安装指定的技能到本地",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            tags=["skills", "marketplace", "install", "技能", "安装"],
            schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "要安装的技能 ID"},
                },
                "required": ["skill_id"],
            },
        ),
        handler=_handle_install_skill,
    )

    # ── skills.marketplace.list ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.list",
            name="列出技能",
            description="列出技能市场中的技能，支持分类过滤和排序",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "list", "技能", "列表"],
            schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "分类过滤"},
                    "sort_by": {
                        "type": "string",
                        "enum": ["rating", "install_count", "name", "updated_at"],
                        "description": "排序方式",
                    },
                    "limit": {"type": "integer", "description": "最大返回数量，默认 50"},
                },
            },
        ),
        handler=_handle_list_skills,
    )

    # ── v1.skills_market (向下兼容) ──
    registry.register(
        CapabilityDefinition(
            id="v1.skills_market",
            name="技能市场(旧名兼容)",
            description="技能市场管理（向下兼容 V1 名称）。支持 list/install/search 操作",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "v1", "legacy", "兼容"],
            schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "install", "search"],
                        "description": "操作类型",
                    },
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类过滤"},
                    "skill_id": {"type": "string", "description": "技能 ID"},
                    "limit": {"type": "integer", "description": "最大返回数量"},
                },
                "required": [],
            },
        ),
        handler=_handle_v1_skills_market,
    )

    # ── skills.marketplace.info ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.info",
            name="获取技能详情",
            description="获取指定技能的详细信息，包括 Markdown 内容和评分",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "info", "技能", "详情"],
            schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "技能 ID"},
                },
                "required": ["skill_id"],
            },
        ),
        handler=_handle_get_skill,
    )

    # ── skills.marketplace.stats ──
    registry.register(
        CapabilityDefinition(
            id="skills.marketplace.stats",
            name="获取市场统计",
            description="获取技能市场的统计信息，包括技能总数、安装数、评分等",
            category=CapabilityCategory.PLUGIN,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["skills", "marketplace", "stats", "技能", "统计"],
            schema={
                "type": "object",
                "properties": {},
            },
        ),
        handler=_handle_get_stats,
    )

    logger.info("技能市场能力已注册")


# ── 能力处理器 ──────────────────────────────────────


async def _handle_search_skills(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理技能搜索"""
    from pycoder.skills import get_marketplace

    marketplace = get_marketplace()
    return await marketplace.search_skills(
        query=params.get("query", ""),
        category=params.get("category", ""),
        tags=params.get("tags"),
    )


async def _handle_install_skill(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理技能安装"""
    from pycoder.skills import get_marketplace

    marketplace = get_marketplace()
    return await marketplace.install_skill(params["skill_id"])


async def _handle_list_skills(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理技能列表"""
    from pycoder.skills import get_marketplace

    marketplace = get_marketplace()
    return await marketplace.list_skills(
        category=params.get("category", ""),
        sort_by=params.get("sort_by", "rating"),
        limit=params.get("limit", 50),
    )


async def _handle_get_skill(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理获取技能详情"""
    from pycoder.skills import get_marketplace

    marketplace = get_marketplace()
    return await marketplace.get_skill(params["skill_id"])


async def _handle_get_stats(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理获取市场统计"""
    from pycoder.skills import get_marketplace

    marketplace = get_marketplace()
    return marketplace.get_stats()


async def _handle_v1_skills_market(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """V1 兼容：skills_market 多合一调度"""
    from pycoder.skills import get_marketplace

    action = params.get("action", "list")
    marketplace = get_marketplace()

    if action == "install":
        sid = params.get("skill_id", "")
        if not sid:
            return {"error": "install requires 'skill_id'"}
        return await marketplace.install_skill(sid)

    if action == "search":
        return await marketplace.search_skills(
            query=params.get("query", ""),
            category=params.get("category", ""),
            limit=params.get("limit", 20),
        )

    return await marketplace.list_skills(
        category=params.get("category", ""),
        sort_by=params.get("sort_by", "rating"),
        limit=params.get("limit", 50),
    )
