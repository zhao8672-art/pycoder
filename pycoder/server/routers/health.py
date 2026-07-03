"""
Health check and model listing routes.
Extracted from rest_routes.py for modularity.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from pycoder import __version__
from pycoder.python.env_detector import detect_environment
from pycoder.server.app_lifecycle import _server_start, get_uptime
from pycoder.providers.auth import get_model_manager
from pycoder.server.session_store import get_session_store

router = APIRouter()

@router.get("/api/health")
async def health_check():
    env = detect_environment()
    try:
        db_stats = get_session_store().get_stats()
    except Exception:
        db_stats = {"error": "db unavailable"}
    return {"status": "ok", "version": __version__, "python": env.python_version, "server_uptime": round(time.time() - _server_start, 1), "db_stats": db_stats}


@router.get("/api/models")
async def list_models():
    try:
        from pycoder.providers.auth import get_model_manager
        mgr = get_model_manager()
        models = mgr.get_available_models()
        if not models:
            raise ValueError("no models")
        recommended_model, _ = mgr.recommend(task_type="coding")
        return {"models": models, "total": len(models), "recommended_model": recommended_model}
    except Exception:
        models = []
        for mod in ["deepseek-chat", "deepseek-v4-pro", "deepseek-v4-flash", "qwen3.6-plus", "qwen3.6-flash", "glm-5", "glm-4.7-flash"]:
            models.append({"id": mod, "name": mod, "provider": mod.split("-")[0]})
        return {"models": models, "total": len(models), "recommended_model": "deepseek-chat"}
