"""
工作区管理 API — 多根工作区、pycoder.json、AI 规则、脚手架

端点前缀: /api/workspace/manage
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from pycoder.server.services.workspace_manager import get_workspace_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace/manage", tags=["workspace-manage"])


@router.get("/config")
async def get_config():
    """获取完整工作区配置"""
    mgr = get_workspace_manager()
    return mgr.get_config()


@router.post("/config/name")
async def update_name(req: dict):
    """更新工作区名称"""
    name = req.get("name", "")
    if not name:
        raise HTTPException(400, "name is required")
    return get_workspace_manager().update_name(name)


@router.post("/config/description")
async def update_description(req: dict):
    """更新工作区描述"""
    desc = req.get("description", "")
    return get_workspace_manager().update_description(desc)


@router.get("/folders")
async def list_folders():
    """列出所有根文件夹"""
    return {"folders": get_workspace_manager().list_folders()}


@router.post("/folders/add")
async def add_folder(req: dict):
    """添加文件夹到工作区"""
    path = req.get("path", "")
    name = req.get("name", "")
    if not path:
        raise HTTPException(400, "path is required")
    result = get_workspace_manager().add_folder(path, name)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "添加失败"))
    return result


@router.post("/folders/remove")
async def remove_folder(req: dict):
    """从工作区移除文件夹"""
    path = req.get("path", "")
    if not path:
        raise HTTPException(400, "path is required")
    result = get_workspace_manager().remove_folder(path)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "移除失败"))
    return result


@router.post("/folders/reorder")
async def reorder_folders(req: dict):
    """重新排序根文件夹"""
    paths = req.get("paths", [])
    if not paths:
        raise HTTPException(400, "paths is required")
    result = get_workspace_manager().reorder_folders(paths)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "排序失败"))
    return result


@router.get("/rules")
async def get_rules():
    """获取 AI 规则"""
    content = get_workspace_manager().get_rules()
    return {"content": content}


@router.post("/rules")
async def save_rules(req: dict):
    """保存 AI 规则"""
    content = req.get("content", "")
    result = get_workspace_manager().save_rules(content)
    if not result.get("success"):
        raise HTTPException(500, result.get("error", "保存失败"))
    return result


@router.get("/ai-context")
async def get_ai_context():
    """获取 AI 上下文提示词"""
    prompt = get_workspace_manager().build_ai_context_prompt()
    return {"prompt": prompt}


@router.get("/settings")
async def get_settings():
    """获取工作区设置"""
    return {"settings": get_workspace_manager().get_settings()}


@router.post("/settings")
async def update_settings(req: dict):
    """更新工作区设置"""
    settings = req.get("settings", {})
    if not settings:
        raise HTTPException(400, "settings is required")
    return get_workspace_manager().update_settings(settings)


@router.post("/save")
async def save_config():
    """手动保存工作区配置到 pycoder.json"""
    return get_workspace_manager().save()


@router.post("/init")
async def init_workspace(req: dict):
    """初始化工作区（切换到指定根目录）"""
    path = req.get("path", "")
    if not path:
        raise HTTPException(400, "path is required")
    target = Path(path).resolve()
    if not target.is_dir():
        raise HTTPException(400, f"目录不存在: {path}")
    get_workspace_manager().initialize(target)
    return {"success": True, "workspace": str(target), "name": target.name}


@router.post("/scaffold")
async def scaffold_project(req: dict):
    """从模板创建新项目"""
    name = req.get("name", "")
    template = req.get("template", "basic")
    if not name:
        raise HTTPException(400, "name is required")
    result = get_workspace_manager().scaffold_project(name, template)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "创建失败"))
    return result


@router.get("/templates")
async def list_templates():
    """列出可用项目模板"""
    return {
        "templates": [
            {"id": "basic", "name": "基础 Python 项目", "description": "Python 项目骨架，含 pytest"},
            {"id": "fastapi", "name": "FastAPI 项目", "description": "FastAPI Web 服务项目"},
            {"id": "react", "name": "React + Vite 项目", "description": "TypeScript React 前端项目"},
        ]
    }
