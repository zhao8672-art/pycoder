"""
Health check and model listing routes.
Extracted from rest_routes.py for modularity.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from pycoder import __version__
from pycoder.python.env_detector import detect_environment
from pycoder.server.app_lifecycle import _server_start
from pycoder.server.session_store import get_session_store

router = APIRouter()


@router.get("/api/health")
async def health_check():
    env = detect_environment()
    try:
        db_stats = get_session_store().get_stats()
    except Exception:
        db_stats = {"error": "db unavailable"}
    return {
        "status": "ok",
        "version": __version__,
        "python": env.python_version,
        "server_uptime": round(time.time() - _server_start, 1),
        "db_stats": db_stats,
    }


@router.get("/api/models")
async def list_models():
    """列出可用模型（兼容旧版前端）"""
    from pycoder.providers.auth import get_model_manager

    mgr = get_model_manager()
    models = mgr.get_available_models()
    return {"models": models, "total": len(models), "recommended_model": mgr.recommend()[0]}


@router.get("/api/env/capabilities")
async def env_capabilities():
    """返回当前环境能力清单（支持优雅降级提示）"""
    from pycoder.server.env_checker import get_env_checker

    checker = get_env_checker()
    caps = checker.get_capabilities(force=True)
    return {
        "success": True,
        "capabilities": caps.to_dict(),
        "summary": caps.summary(),
        "hint": "缺失的能力将自动降级为替代方案，不影响核心功能",
    }
