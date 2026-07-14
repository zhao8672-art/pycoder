"""跨工作区模块 — 安全跨工作区数据共享与交互"""

from __future__ import annotations

from typing import Any

from pycoder.workspace.share_sandbox import ShareSandbox
from pycoder.workspace.workspace_registry import ShareLevel, WorkspaceEntry, WorkspaceRegistry

__all__ = [
    "WorkspaceRegistry",
    "WorkspaceEntry",
    "ShareLevel",
    "ShareSandbox",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册跨工作区能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    ws_registry = WorkspaceRegistry()
    ws_sandbox = ShareSandbox(ws_registry)

    def _register_workspace(params: dict, ctx: dict) -> dict:
        entry = WorkspaceEntry(
            id=params["id"],
            path=params["path"],
            name=params["name"],
        )
        ws_registry.register(entry)
        return {"success": True, "workspace_id": params["id"]}

    def _list_workspaces(params: dict, ctx: dict) -> dict:
        caller = params.get("caller_id")
        if caller:
            entries = ws_registry.list_accessible(caller)
        else:
            entries = ws_registry.list_all()
        return {"workspaces": [{"id": e.id, "name": e.name, "path": e.path} for e in entries]}

    def _read_shared_file(params: dict, ctx: dict) -> dict:
        content = ws_sandbox.read_file(params["caller_ws"], params["target_ws"], params["rel_path"])
        return {"content": content}

    def _write_shared_file(params: dict, ctx: dict) -> dict:
        ws_sandbox.write_file(
            params["caller_ws"], params["target_ws"], params["rel_path"], params["content"]
        )
        return {"success": True}

    def _set_share_policy(params: dict, ctx: dict) -> dict:
        level = ShareLevel[params["share_level"]]
        ws_registry.set_share_policy(
            params["workspace_id"],
            level,
            params.get("allowed_workspaces", []),
            params.get("shared_paths", []),
        )
        return {"success": True}

    registry.register(
        CapabilityDefinition(
            id="workspace.register",
            name="注册工作区",
            description="注册一个新的工作区，用于跨工作区数据共享",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "工作区唯一标识"},
                    "path": {"type": "string", "description": "工作区路径"},
                    "name": {"type": "string", "description": "工作区名称"},
                },
                "required": ["id", "path", "name"],
            },
            tags=["workspace", "register", "工作区", "注册"],
        ),
        handler=_register_workspace,
    )

    registry.register(
        CapabilityDefinition(
            id="workspace.list",
            name="列出工作区",
            description="列出所有已注册的工作区，支持按权限过滤",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "caller_id": {
                        "type": "string",
                        "description": "调用方工作区 ID（用于过滤可访问的）",
                    },
                },
            },
            tags=["workspace", "list", "工作区", "列表"],
        ),
        handler=_list_workspaces,
    )

    registry.register(
        CapabilityDefinition(
            id="workspace.read_shared",
            name="跨工作区读取文件",
            description="从其他工作区安全读取共享文件（需目标工作区授权）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "caller_ws": {"type": "string", "description": "调用方工作区 ID"},
                    "target_ws": {"type": "string", "description": "目标工作区 ID"},
                    "rel_path": {"type": "string", "description": "相对路径"},
                },
                "required": ["caller_ws", "target_ws", "rel_path"],
            },
            tags=["workspace", "read", "share", "跨工作区", "读取"],
        ),
        handler=_read_shared_file,
    )

    registry.register(
        CapabilityDefinition(
            id="workspace.write_shared",
            name="跨工作区写入文件",
            description="向其他工作区安全写入共享文件（需目标工作区开启读写共享）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            rollback_support=True,
            schema={
                "type": "object",
                "properties": {
                    "caller_ws": {"type": "string", "description": "调用方工作区 ID"},
                    "target_ws": {"type": "string", "description": "目标工作区 ID"},
                    "rel_path": {"type": "string", "description": "相对路径"},
                    "content": {"type": "string", "description": "写入内容"},
                },
                "required": ["caller_ws", "target_ws", "rel_path", "content"],
            },
            tags=["workspace", "write", "share", "跨工作区", "写入"],
        ),
        handler=_write_shared_file,
    )

    registry.register(
        CapabilityDefinition(
            id="workspace.set_share_policy",
            name="设置共享策略",
            description="设置工作区的共享策略（共享级别、允许列表、路径白名单）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "工作区 ID"},
                    "share_level": {
                        "type": "string",
                        "description": "共享级别: NONE/READ/READ_WRITE",
                    },
                    "allowed_workspaces": {"type": "array", "items": {"type": "string"}},
                    "shared_paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["workspace_id", "share_level"],
            },
            tags=["workspace", "policy", "share", "共享策略"],
        ),
        handler=_set_share_policy,
    )
