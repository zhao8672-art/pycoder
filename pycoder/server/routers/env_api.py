"""环境管理 API — 工具检测、安装指南、版本校验

端点:
  GET  /api/env/report    — 获取完整环境检测报告
  GET  /api/env/tools     — 列出所有已定义工具
  GET  /api/env/tools/{name} — 检测指定工具状态
  GET  /api/env/tools/{name}/guide — 获取安装指南
  POST /api/env/tools/{name}/install — 触发自动安装
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pycoder.env.auto_installer import AutoInstaller
from pycoder.env.tool_detector import ToolDetector

router = APIRouter(prefix="/api/env", tags=["env"])

_detector = ToolDetector()
_installer = AutoInstaller(_detector)


@router.get("/report")
async def get_env_report():
    """获取完整环境检测报告

    返回所有工具的检测状态，包括已安装/缺失/版本问题。
    """
    report = _detector.get_report()
    return {
        "all_ok": report["all_ok"],
        "required_missing": [
            {"name": s.name, "error": s.error} for s in report["required_missing"]
        ],
        "optional_missing": [
            {"name": s.name, "error": s.error} for s in report["optional_missing"]
        ],
        "version_issues": [
            {"name": s.name, "version": s.version, "error": s.error}
            for s in report["version_issues"]
        ],
        "all_statuses": [
            {
                "name": s.name,
                "installed": s.installed,
                "version": s.version,
                "meets_minimum": s.meets_minimum,
                "error": s.error,
            }
            for s in report["all_statuses"]
        ],
    }


@router.get("/tools")
async def list_tools():
    """列出所有预定义工具及其检测状态"""
    results = _detector.detect_all()
    return {
        "tools": [
            {
                "name": r.name,
                "installed": r.installed,
                "version": r.version,
                "meets_minimum": r.meets_minimum,
                "error": r.error,
            }
            for r in results
        ],
    }


@router.get("/tools/{tool_name}")
async def check_tool(tool_name: str):
    """检测指定工具的可用性和版本"""
    req = _detector.get_tool_by_name(tool_name)
    if not req:
        raise HTTPException(status_code=404, detail=f"未知工具: {tool_name}")

    status = _detector._detect_one(req)
    return {
        "name": status.name,
        "installed": status.installed,
        "version": status.version,
        "meets_minimum": status.meets_minimum,
        "error": status.error,
        "required": req.required,
        "display_name": req.display_name,
        "min_version": req.min_version,
    }


@router.get("/tools/{tool_name}/guide")
async def get_install_guide(tool_name: str):
    """获取指定工具的安装指南（Markdown 格式）"""
    req = _detector.get_tool_by_name(tool_name)
    if not req:
        raise HTTPException(status_code=404, detail=f"未知工具: {tool_name}")

    guide = _installer.get_install_guide(tool_name)
    return {
        "tool_name": tool_name,
        "display_name": req.display_name,
        "guide": guide,
        "platform": _installer.get_platform(),
        "min_version": req.min_version,
    }


@router.get("/guides/all")
async def get_all_missing_guides():
    """获取所有缺失工具的安装指南"""
    guide = _installer.get_all_missing_guides()
    version_fix = _installer.get_version_fix_guides()
    return {
        "missing_guides": guide,
        "version_fix_guides": version_fix,
    }
