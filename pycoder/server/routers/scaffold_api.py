"""
脚手架生成器 API — 项目模板生成和管理
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pycoder.python.scaffold_generator import get_scaffold_generator

router = APIRouter(prefix="/api/scaffold")


@router.get("/templates")
async def list_templates():
    g = get_scaffold_generator()
    return {"success": True, "templates": g.list_templates()}


@router.post("/generate")
async def generate(req: dict):
    framework = req.get("framework", "fastapi")
    target = req.get("target_dir", "")
    name = req.get("name", "my-project")
    g = get_scaffold_generator()
    result = g.generate(framework, target, name)
    return {
        "success": result.success,
        "project_dir": result.project_dir,
        "files_created": result.files_created,
        "error": result.error,
    }


@router.post("/templates/save")
async def save_template(req: dict):
    name = req.get("name", "")
    description = req.get("description", "")
    files = req.get("files", {})
    if not name:
        raise HTTPException(400, "模板名称不能为空")
    g = get_scaffold_generator()
    ok = g.save_template(name, description, files)
    return {"success": ok}


@router.delete("/templates/{name}")
async def delete_template(name: str):
    g = get_scaffold_generator()
    ok = g.delete_template(name)
    return {"success": ok}
