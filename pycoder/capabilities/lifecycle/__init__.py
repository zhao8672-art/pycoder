"""生命周期能力域 — 将 lifecycle/ 编排器包装为 V2 能力

能力清单：
    lifecycle.project.create — 创建项目
    lifecycle.project.run    — 运行项目编排
    lifecycle.project.progress — 查询进度
    lifecycle.project.cancel  — 取消编排
    lifecycle.project.list    — 列出项目
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_lifecycle_capabilities() -> None:
    """注册生命周期域能力到 V2 能力总线"""
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

        # lifecycle.project.create
        registry.register(CapabilityDefinition(
            id="lifecycle.project.create",
            category=CapabilityCategory.SYSTEM,
            description="创建新的项目生命周期编排",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.WORKSPACE_WRITE,
            handler=_handle_project_create,
        ))

        # lifecycle.project.run
        registry.register(CapabilityDefinition(
            id="lifecycle.project.run",
            category=CapabilityCategory.SYSTEM,
            description="运行项目生命周期编排（7 阶段闭环）",
            execution_mode=ExecutionMode.STREAM,
            side_effects={SideEffect.PROCESS, SideEffect.FILE_WRITE},
            trust_level=TrustLevel.PROJECT_WRITE,
            handler=_handle_project_run,
        ))

        # lifecycle.project.list
        registry.register(CapabilityDefinition(
            id="lifecycle.project.list",
            category=CapabilityCategory.SYSTEM,
            description="列出所有项目编排记录",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_project_list,
        ))

        logger.info("lifecycle_capabilities_registered: count=3")
    except Exception as e:
        logger.warning("lifecycle_capabilities_register_failed: %s", e)


async def _handle_project_create(args: dict[str, Any]) -> dict[str, Any]:
    """处理 lifecycle.project.create"""
    from pycoder.lifecycle.orchestrator import LifecycleOrchestrator
    orch = LifecycleOrchestrator()
    result = await orch.create_project(
        name=args.get("name", ""),
        workspace=args.get("workspace", ""),
        request=args.get("request", ""),
    )
    return {"success": True, "project": result}


async def _handle_project_run(args: dict[str, Any]):
    """处理 lifecycle.project.run（流式）"""
    from pycoder.lifecycle.orchestrator import LifecycleOrchestrator
    orch = LifecycleOrchestrator()
    async for event in orch.run(project_id=args.get("project_id", "")):
        yield event


async def _handle_project_list(args: dict[str, Any]) -> dict[str, Any]:
    """处理 lifecycle.project.list"""
    from pycoder.lifecycle.orchestrator import LifecycleOrchestrator
    orch = LifecycleOrchestrator()
    projects = await orch.list_projects()
    return {"success": True, "projects": projects}
