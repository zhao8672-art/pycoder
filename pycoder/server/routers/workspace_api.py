"""跨工作区 API — 工作区注册、共享文件读取、共享策略管理"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from pycoder.workspace.share_sandbox import ShareSandbox
from pycoder.workspace.workspace_registry import ShareLevel, WorkspaceEntry, WorkspaceRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

_registry = WorkspaceRegistry()
_sandbox = ShareSandbox(_registry)


@router.post("/register")
async def register_workspace(req: dict):
    """注册新工作区"""
    ws_id = req.get("id", "")
    path = req.get("path", "")
    name = req.get("name", "")
    share_level = req.get("share_level", "none")
    allowed = req.get("allowed_workspaces", [])
    shared_paths = req.get("shared_paths", [])

    if not ws_id or not path or not name:
        raise HTTPException(status_code=400, detail="缺少必填参数: id, path, name")

    try:
        level = ShareLevel(share_level)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的共享级别: {share_level}") from None

    entry = WorkspaceEntry(
        id=ws_id,
        path=path,
        name=name,
        share_level=level,
        allowed_workspaces=allowed,
        shared_paths=shared_paths,
    )
    _registry.register(entry)
    return {"success": True, "workspace_id": ws_id}


@router.delete("/{workspace_id}")
async def unregister_workspace(workspace_id: str):
    """注销工作区"""
    if not _registry.get(workspace_id):
        raise HTTPException(status_code=404, detail="工作区不存在")
    _registry.unregister(workspace_id)
    return {"success": True}


@router.get("/list")
async def list_workspaces():
    """列出所有已注册工作区"""
    entries = _registry.list_all()
    return {
        "workspaces": [
            {
                "id": e.id,
                "name": e.name,
                "path": e.path,
                "share_level": e.share_level.value,
                "allowed_workspaces": e.allowed_workspaces,
                "shared_paths": e.shared_paths,
            }
            for e in entries
        ]
    }


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str):
    """获取工作区详情"""
    entry = _registry.get(workspace_id)
    if not entry:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return {
        "id": entry.id,
        "name": entry.name,
        "path": entry.path,
        "share_level": entry.share_level.value,
        "allowed_workspaces": entry.allowed_workspaces,
        "shared_paths": entry.shared_paths,
    }


@router.get("/{workspace_id}/files/{file_path:path}")
async def read_shared_file(
    workspace_id: str,
    file_path: str,
    caller_ws: str = Query("", description="调用方工作区 ID"),
):
    """跨工作区读取文件"""
    try:
        content = _sandbox.read_file(caller_ws, workspace_id, file_path)
        return {"content": content, "workspace_id": workspace_id, "file_path": file_path}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{workspace_id}/share-policy")
async def set_share_policy(workspace_id: str, req: dict):
    """设置共享策略"""
    entry = _registry.get(workspace_id)
    if not entry:
        raise HTTPException(status_code=404, detail="工作区不存在")

    level = req.get("share_level", entry.share_level.value)
    allowed = req.get("allowed_workspaces", entry.allowed_workspaces)
    shared_paths = req.get("shared_paths", entry.shared_paths)

    try:
        share_level = ShareLevel(level)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的共享级别: {level}") from None

    _registry.set_share_policy(workspace_id, share_level, allowed, shared_paths)
    return {"success": True}
