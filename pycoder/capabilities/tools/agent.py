"""Agent 配置工具 — list_agent_configs"""

from __future__ import annotations

from typing import Any

from pycoder.bus.protocol import CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler


def register(registry: Any) -> None:
    registry.register(
        CapabilityDefinition(
            id="tools.agent.list_configs", name="Agent 配置",
            description="列出 PyCoder 系统 Agent 角色的详细配置",
            permission=TOOL_PERMISSIONS["tools.agent.list_configs"],
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={"type": "object", "properties": {}},
            tags=["agent", "config"],
        ),
        handler=wrap_handler(_handle_list_agent_configs),
    )


async def _handle_list_agent_configs(params: dict, context: dict) -> dict:
    from pycoder.server.services.agent_definitions import AGENT_ROLES as roles
    agent_list = []
    for role_id, role in roles.items():
        agent_list.append({
            "id": role_id, "name": role.name,
            "description": role.description,
            "model": role.model, "tools": role.tools,
            "skills": role.skills,
        })
    return {"success": True, "count": len(agent_list), "agents": agent_list}
