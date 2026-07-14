"""Agent 配置工具 — list_agent_configs"""

from __future__ import annotations

from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.SYSTEM


def register(registry: Any) -> None:
    registry.register(
        CapabilityDefinition(
            id="tools.agent.list_configs",
            name="Agent 配置",
            description="列出 PyCoder 系统 Agent 角色的详细配置",
            permission=TOOL_PERMISSIONS["tools.agent.list_configs"],
            category=_CT,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={"type": "object", "properties": {}},
            tags=["agent", "config"],
        ),
        handler=wrap_handler(_handle_list_agent_configs),
    )

    # P2: 自进化代码扫描
    registry.register(
        CapabilityDefinition(
            id="tools.agent.self_scan",
            name="代码自扫描",
            description="扫描项目代码发现Bug、安全问题、性能瓶颈（AST静态分析，无需外部API）",
            permission=TOOL_PERMISSIONS["tools.agent.list_configs"],
            category=_CT,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "pycoder"},
                    "max_issues": {"type": "integer", "default": 30},
                },
            },
            tags=["scan", "code", "quality", "扫描"],
        ),
        handler=wrap_handler(_handle_self_scan),
    )


async def _handle_list_agent_configs(params: dict, context: dict) -> dict:
    from pycoder.server.services.agent_definitions import AGENT_ROLES as roles

    agent_list = []
    for role_id, role in roles.items():
        agent_list.append(
            {
                "id": role_id,
                "name": role.name,
                "description": role.description,
                "model": role.model,
                "tools": role.tools,
                "skills": role.skills,
            }
        )
    return {"success": True, "count": len(agent_list), "agents": agent_list}


async def _handle_self_scan(params: dict, context: dict) -> dict:
    """执行代码自扫描（AST 静态分析）"""
    try:
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        eng = SelfEvolutionEngine()
        path = params.get("path", "pycoder")
        max_issues = params.get("max_issues", 30)
        report = await eng.scan(path, use_llm=False)
        issues = []
        for i in report.issues[:max_issues]:
            issues.append(
                {
                    "file": i.file,
                    "line": i.line,
                    "severity": i.severity,
                    "type": i.issue_type,
                    "title": i.title,
                }
            )
        return {
            "success": True,
            "files_scanned": report.files_scanned,
            "total_issues": len(issues),
            "issues": issues,
            "summary": report.summary,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
