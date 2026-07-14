"""
V2 MCP 工具桥接 — 将 V1 MCP 工具批量注册到 V2 能力总线

在 V2 引擎初始化完成后调用 bridge_mcp_to_v2() 完成批量同步。
"""
from __future__ import annotations

import logging
from typing import Any

from pycoder.bus.protocol import (  # noqa: F401 — used in type hints & helpers
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)


def bridge_mcp_to_v2(v2_engine) -> int:
    """将 V1 MCP 内置工具批量注册到 V2 引擎的能力总线。

    应在 V2Engine.initialize() 完成后调用。

    Returns:
        成功注册的工具数量
    """
    from pycoder.server.mcp_tools import _builtin_tools

    registry = v2_engine.registry
    count = 0

    for tool_name, tool_def in _builtin_tools.items():
        # 避免重复注册
        if registry.get(f"v1.{tool_name}"):
            continue

        category = _infer_category(tool_name, tool_def.description)
        trust = _infer_trust(tool_name, tool_def.description)
        side_effects = _infer_side_effects(tool_name)

        cap_def = CapabilityDefinition(
            id=f"v1.{tool_name}",
            name=tool_name,
            description=tool_def.description,
            category=category,
            permission=trust,
            execution=ExecutionMode.SYNC,
            side_effects=side_effects,
            schema=tool_def.input_schema,
            tags=["v1_migrated", tool_name],
        )

        # 包装 V1 handler
        handler = tool_def.handler

        async def _v2_handler(params: dict, context: dict, _h=handler) -> Any:
            try:
                result = _h(params)
                if hasattr(result, '__await__'):
                    result = await result
                return result
            except Exception as e:
                return {"error": str(e)}

        registry.register(cap_def, handler=_v2_handler)
        count += 1

    logger.info("bridge_mcp_to_v2: %d tools registered into V2 bus", count)
    return count


def _infer_category(name: str, description: str) -> CapabilityCategory:
    from pycoder.bus.protocol import CapabilityCategory

    text = (name + description).lower()
    if any(kw in text for kw in ["read", "write", "file", "edit", "format", "debug", "lint"]):
        return CapabilityCategory.EDITOR
    if any(kw in text for kw in ["git", "shell", "terminal", "execute", "run", "docker", "env"]):
        return CapabilityCategory.SYSTEM
    if any(kw in text for kw in ["scan", "fix", "test", "deploy", "evolv", "learn", "analy"]):
        return CapabilityCategory.SELF_EVO
    return CapabilityCategory.SYSTEM


def _infer_trust(name: str, description: str) -> TrustLevel:
    from pycoder.bus.protocol import TrustLevel

    text = (name + description).lower()
    if any(kw in text for kw in ["delete", "remove", "push", "deploy", "evolv", "restart"]):
        return TrustLevel.PROJECT_WRITE
    if any(kw in text for kw in ["install", "uninstall", "docker", "network", "url"]):
        return TrustLevel.SYSTEM_ACCESS
    if any(kw in text for kw in ["read", "list", "search", "status", "log", "diff"]):
        return TrustLevel.READ_ONLY
    return TrustLevel.WORKSPACE_WRITE


def _infer_side_effects(name: str) -> list[SideEffect]:
    from pycoder.bus.protocol import SideEffect

    text = name.lower()
    effects = []
    if any(kw in text for kw in ["read", "list", "search", "status", "log", "diff", "show"]):
        effects.append(SideEffect.FILE_READ)
    if any(kw in text for kw in ["write", "edit", "create", "save", "set", "put"]):
        effects.append(SideEffect.FILE_WRITE)
    if any(kw in text for kw in ["delete", "remove"]):
        effects.append(SideEffect.FILE_DELETE)
    if any(kw in text for kw in ["install", "uninstall", "fetch", "http", "url", "download"]):
        effects.append(SideEffect.NETWORK)
    if any(kw in text for kw in ["run", "exec", "shell", "terminal", "git"]):
        effects.append(SideEffect.PROCESS)
    if not effects:
        effects.append(SideEffect.NONE)
    return effects
