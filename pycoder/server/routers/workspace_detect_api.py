"""
工作区自动检测 API — 智能识别用户当前项目并默认加载

端点前缀: /api/workspace

功能:
- GET  /detect       — 自动检测当前项目路径
- POST /detect       — 手动指定项目路径
- GET  /status       — 获取当前工作区状态
- POST /config       — 保存默认项目路径配置
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from pycoder.server.services.workspace_detector import (
    DetectionResult,
    get_workspace_detector,
)
from pycoder.server.services.workspace_manager import get_workspace_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace-detect"])


@router.get("/detect")
async def detect_workspace(request: Request) -> dict:
    """自动检测用户当前工作的项目路径

    按优先级依次尝试: 用户配置 → 历史记录 → Git 根目录 → 项目标识文件 → 启发式

    Returns:
        DetectionResult 字典:
        - project_path: 检测到的项目根目录
        - confidence: 置信度 0.0~1.0
        - method: 检测方法
        - name: 项目名称
        - indicators: 检测到的标识文件列表
        - suggestions: 建议（当置信度低时）
        - status: detected | uncertain | not_found
    """
    # 尝试从 Electron 前端获取路径（query param 或 header）
    electron_path = request.query_params.get("path") or request.headers.get("X-Workspace-Path")

    detector = get_workspace_detector()
    result = detector.detect(electron_path=electron_path)

    # 如果检测到有效路径，自动初始化工作区
    if result.confidence >= 0.4:
        try:
            mgr = get_workspace_manager()
            mgr.initialize(result.project_path)
            detector.save_to_history(result.project_path)
        except Exception as e:
            logger.warning("workspace_auto_init_failed error=%s", e)

    return result.to_dict()


@router.post("/detect")
async def set_workspace_path(req: dict) -> dict:
    """手动指定项目路径

    Body: {"path": "/path/to/project", "save_default": true}

    - save_default=true 时保存为用户默认项目路径
    """
    path = req.get("path", "").strip()
    if not path:
        raise HTTPException(400, "path is required")

    target = Path(path).resolve()
    if not target.is_dir():
        raise HTTPException(400, f"目录不存在或无法访问: {path}")

    detector = get_workspace_detector()

    # 保存为默认路径
    if req.get("save_default", False):
        detector.save_default_path(str(target))

    # 保存到历史
    detector.save_to_history(str(target))

    # 初始化工作区
    mgr = get_workspace_manager()
    mgr.initialize(target)

    result = DetectionResult(
        project_path=str(target),
        confidence=1.0,
        method="manual",
        name=target.name,
        indicators=detector._find_indicators(target),
    )

    return result.to_dict()


@router.get("/status")
async def get_workspace_status() -> dict:
    """获取当前工作区状态摘要

    Returns:
        {
            "project_path": 当前项目路径,
            "project_name": 项目名称,
            "detection_method": 检测方法,
            "folders": 根文件夹数量,
            "has_rules": 是否有 AI 规则,
            "has_config": 是否有 pycoder.json,
            "indicators": 检测到的标识文件
        }
    """
    mgr = get_workspace_manager()
    detector = get_workspace_detector()

    root = Path(mgr.get_root())
    indicators = detector._find_indicators(root)

    return {
        "project_path": str(root),
        "project_name": mgr.get_name(),
        "folders": mgr.list_folders(),
        "folder_count": len(mgr.list_folders()),
        "has_rules": bool(mgr.get_rules()),
        "has_config": (root / ".pycoder" / "pycoder.json").is_file(),
        "indicators": indicators,
        "is_temp": detector._is_temp_dir(root),
    }


@router.post("/config")
async def save_default_project_path(req: dict) -> dict:
    """保存默认项目路径配置

    Body: {"path": "/path/to/project"}
    """
    path = req.get("path", "").strip()
    if not path:
        raise HTTPException(400, "path is required")

    target = Path(path).resolve()
    if not target.is_dir():
        raise HTTPException(400, f"目录不存在: {path}")

    detector = get_workspace_detector()
    success = detector.save_default_path(str(target))

    return {
        "success": success,
        "path": str(target),
        "message": "默认项目路径已保存" if success else "保存失败",
    }


@router.get("/config")
async def get_default_project_path() -> dict:
    """获取当前配置的默认项目路径"""
    detector = get_workspace_detector()
    config_path = detector._load_config_default_path()
    return {
        "default_project_path": config_path or "",
        "has_default": bool(config_path),
    }


@router.get("/history")
async def get_workspace_history() -> dict:
    """获取最近打开的工作区历史"""
    detector = get_workspace_detector()
    history = detector._load_history()
    return {
        "workspaces": history,
        "count": len(history),
    }
