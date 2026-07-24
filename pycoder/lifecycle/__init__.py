"""项目管理闭环系统 — pycoder.lifecycle

7 阶段全流程闭环：任务接收 → 需求分析 → 方案设计 → 代码开发 → 测试验证 → 自愈修正 → 交付管理

设计原则（三明治架构）：
- 本模块只做"编排"，不做"实现"
- 业务逻辑委托给现有成熟模块（autonomous_pipeline/quality_gate/task_decomposer/evolution）
- 通过 Strategy 模式支持阶段替换

使用方式:
    from pycoder.lifecycle import get_orchestrator, LifecyclePhase

    orch = get_orchestrator()
    ctx = orch.create_project("实现用户注册API")
    async for event in orch.run(ctx.project_id):
        print(event["type"], event.get("phase", ""))
"""

from __future__ import annotations

import logging
from typing import Any

from pycoder.lifecycle.context import (
    PhaseArtifact,
    PhaseRecord,
    ProjectContext,
    ProjectStatus,
)
from pycoder.lifecycle.orchestrator import (
    ProjectLifecycleOrchestrator,
    get_orchestrator,
)
from pycoder.lifecycle.phases import (
    LifecyclePhase,
    PhaseStrategy,
    get_progress,
)
from pycoder.lifecycle.adapters import create_default_phases

logger = logging.getLogger(__name__)

__all__ = [
    # 编排器
    "ProjectLifecycleOrchestrator",
    "get_orchestrator",
    # 上下文
    "ProjectContext",
    "ProjectStatus",
    "PhaseRecord",
    "PhaseArtifact",
    # 阶段
    "LifecyclePhase",
    "PhaseStrategy",
    "create_default_phases",
    "get_progress",
    # 能力注册
    "register_capabilities",
]


# ══════════════════════════════════════════════════════
# V2 能力总线注册
# ══════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> int:
    """向 V2 能力总线注册项目管理闭环能力

    Args:
        registry: V2 CapabilityRegistry 实例

    Returns:
        注册的能力数量
    """
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    count_before = registry.count
    orch = get_orchestrator()

    # 1. 创建项目
    async def _handle_create(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        request = params.get("request", "")
        if not request:
            return {"error": "缺少 request 参数"}
        project_ctx = orch.create_project(
            request=request,
            workspace=params.get("workspace", ""),
            model=params.get("model", "deepseek-chat"),
            auto_apply=params.get("auto_apply", False),
            quality_gate_level=params.get("quality_gate_level", 2),
        )
        return {"project_id": project_ctx.project_id, "status": project_ctx.status.value}

    registry.register(
        CapabilityDefinition(
            id="lifecycle.create",
            name="创建项目",
            description="创建新的项目管理闭环项目，初始化 7 阶段上下文",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["lifecycle", "project", "create"],
            schema={
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "项目需求描述"},
                    "workspace": {"type": "string", "description": "工作目录"},
                    "model": {"type": "string", "description": "LLM 模型"},
                    "auto_apply": {"type": "boolean", "description": "是否自动应用"},
                },
                "required": ["request"],
            },
        ),
        handler=_handle_create,
    )

    # 2. 运行项目闭环
    async def _handle_run(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        project_id = params.get("project_id", "")
        if not project_id:
            return {"error": "缺少 project_id"}
        project_ctx = orch.get_project(project_id)
        if project_ctx is None:
            return {"error": f"项目不存在: {project_id}"}

        # 同步执行（收集所有事件，返回最终报告）
        events = []
        async for event in orch.run(project_id, resume=params.get("resume", False)):
            events.append(event)
            if event.get("type") == "done":
                return {
                    "project_id": project_id,
                    "status": event.get("status"),
                    "report": event.get("report"),
                    "events_count": len(events),
                }
        return {"project_id": project_id, "events": events[-5:]}

    registry.register(
        CapabilityDefinition(
            id="lifecycle.run",
            name="运行项目闭环",
            description="执行项目 7 阶段闭环（接收→分析→设计→开发→测试→自愈→交付）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.FULL_AUTONOMY,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.FILE_WRITE, SideEffect.PROCESS, SideEffect.LLM_CALL],
            tags=["lifecycle", "project", "run", "autonomous"],
            schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                    "resume": {"type": "boolean", "description": "是否从断点恢复"},
                },
                "required": ["project_id"],
            },
        ),
        handler=_handle_run,
    )

    # 3. 查询项目进度
    async def _handle_progress(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        project_id = params.get("project_id", "")
        return orch.get_phase_progress(project_id)

    registry.register(
        CapabilityDefinition(
            id="lifecycle.progress",
            name="查询项目进度",
            description="获取项目 7 阶段执行进度与状态",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["lifecycle", "project", "progress", "query"],
            schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                },
                "required": ["project_id"],
            },
        ),
        handler=_handle_progress,
    )

    # 4. 列出项目
    async def _handle_list(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 20)
        return {"projects": orch.list_projects(limit=limit)}

    registry.register(
        CapabilityDefinition(
            id="lifecycle.list",
            name="列出项目",
            description="列出最近的项目管理闭环项目",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["lifecycle", "project", "list"],
            schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回数量"},
                },
            },
        ),
        handler=_handle_list,
    )

    # 5. 取消项目
    async def _handle_cancel(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        project_id = params.get("project_id", "")
        ok = orch.cancel_project(project_id)
        return {"project_id": project_id, "cancelled": ok}

    registry.register(
        CapabilityDefinition(
            id="lifecycle.cancel",
            name="取消项目",
            description="取消正在执行的项目管理闭环",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["lifecycle", "project", "cancel"],
            schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 ID"},
                },
                "required": ["project_id"],
            },
        ),
        handler=_handle_cancel,
    )

    registered = registry.count - count_before
    logger.info("lifecycle_capabilities_registered count=%d", registered)
    return registered
