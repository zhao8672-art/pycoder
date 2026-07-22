"""P2-3: 自我迭代安装器 REST API

端点:
- GET    /api/installer/list                    - 列出已安装模块
- GET    /api/installer/{name}                  - 获取模块详情
- POST   /api/installer/install                 - 从代码安装
- POST   /api/installer/install/file            - 从文件安装
- POST   /api/installer/{name}/load             - 加载模块
- POST   /api/installer/{name}/reload           - 热重载
- POST   /api/installer/{name}/enable           - 启用
- POST   /api/installer/{name}/disable          - 禁用
- DELETE /api/installer/{name}                  - 卸载
- POST   /api/installer/security-check          - 仅做安全检查
- GET    /api/installer/loaded                  - 列出已加载模块
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.python.self_iterating_installer import (
    get_installer,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/installer", tags=["installer"])


# ── Pydantic 模型 ──────────────────────────────────────


class InstallFromCodeRequest(BaseModel):
    name: str
    code: str
    version: str = "1.0.0"
    description: str = ""
    source: str = "local"
    auto_reload: bool = True
    skip_security: bool = False


class InstallFromFileRequest(BaseModel):
    file_path: str
    name: str | None = None
    version: str = "1.0.0"
    description: str = ""


class SecurityCheckRequest(BaseModel):
    code: str


class SecurityCheckResponse(BaseModel):
    is_safe: bool
    risk_level: str
    issues: list[str]
    dangerous_calls: list[str]


# ── 端点 ──────────────────────────────────────────────


@router.get("/list")
async def list_modules() -> dict:
    """列出已安装的模块"""
    installer = get_installer()
    modules = installer.list_installed()
    return {
        "modules": modules,
        "count": len(modules),
        "loaded": installer.get_loaded(),
    }


@router.get("/loaded")
async def get_loaded() -> dict:
    """获取已加载到 sys.modules 的模块"""
    installer = get_installer()
    return {"loaded": installer.get_loaded()}


@router.get("/{name}")
async def get_module(name: str) -> dict:
    """获取模块详情"""
    installer = get_installer()
    info = installer.get_module_info(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"模块未安装: {name}")
    from dataclasses import asdict

    d = asdict(info)
    d["loaded"] = name in installer.get_loaded()
    return d


@router.post("/install")
async def install_from_code(req: InstallFromCodeRequest) -> dict:
    """从代码安装模块"""
    installer = get_installer()
    if installer.is_installed(req.name):
        raise HTTPException(status_code=409, detail=f"模块已存在: {req.name}")

    result = installer.install_from_code(
        name=req.name,
        code=req.code,
        source=req.source,
        version=req.version,
        description=req.description,
        auto_reload=req.auto_reload,
        skip_security=req.skip_security,
    )

    if not result.success:
        return {
            "success": False,
            "error": result.error,
            "security_check": (
                {
                    "risk_level": result.security_check.risk_level,
                    "issues": result.security_check.issues,
                    "dangerous_calls": result.security_check.dangerous_calls,
                }
                if result.security_check
                else None
            ),
        }

    from dataclasses import asdict

    return {"success": True, "module": asdict(result.module) if result.module else None}


@router.post("/install/file")
async def install_from_file(req: InstallFromFileRequest) -> dict:
    """从本地文件安装"""
    installer = get_installer()
    name = req.name or Path(req.file_path).stem
    if installer.is_installed(name):
        raise HTTPException(status_code=409, detail=f"模块已存在: {name}")

    result = installer.install_from_file(
        file_path=req.file_path,
        name=req.name,
        version=req.version,
        description=req.description,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    from dataclasses import asdict

    return {"success": True, "module": asdict(result.module) if result.module else None}


@router.post("/{name}/load")
async def load_module(name: str) -> dict:
    """加载模块到 sys.modules"""
    installer = get_installer()
    return installer.load(name)


@router.post("/{name}/reload")
async def reload_module(name: str) -> dict:
    """热重载模块"""
    installer = get_installer()
    return installer.reload(name)


@router.post("/{name}/enable")
async def enable_module(name: str) -> dict:
    """启用模块"""
    installer = get_installer()
    return installer.enable(name)


@router.post("/{name}/disable")
async def disable_module(name: str) -> dict:
    """禁用模块"""
    installer = get_installer()
    return installer.disable(name)


@router.delete("/{name}")
async def uninstall_module(name: str) -> dict:
    """卸载模块"""
    installer = get_installer()
    return installer.uninstall(name)


@router.post("/security-check", response_model=SecurityCheckResponse)
async def security_check_endpoint(req: SecurityCheckRequest) -> SecurityCheckResponse:
    """仅做安全检查（不安装）"""
    installer = get_installer()
    result = installer.security_check(req.code)
    return SecurityCheckResponse(
        is_safe=result.is_safe,
        risk_level=result.risk_level,
        issues=result.issues,
        dangerous_calls=result.dangerous_calls,
    )
