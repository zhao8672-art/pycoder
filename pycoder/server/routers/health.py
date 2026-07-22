"""
Health check and model listing routes.
Extracted from rest_routes.py for modularity.

PERF-001/002 修复：将 /api/health 拆分为：
    - /api/health/live  轻量级存活探针（< 5ms，永不失败）
    - /api/health/ready 深度就绪检查（包含子系统状态）
    - /api/health       兼容旧路径，等价 /api/health/ready
"""
from __future__ import annotations

import asyncio
import time
from functools import lru_cache

from fastapi import APIRouter

from pycoder import __version__
from pycoder.python.env_detector import detect_environment
from pycoder.server.app_lifecycle import _server_start
from pycoder.server.session_store import get_session_store

router = APIRouter()

# ── 轻量级 /api/health 响应缓存（PERF-001 修复）──
_HEALTH_CACHE: dict = {"data": None, "expires_at": 0.0}
_HEALTH_TTL_SEC = 2.0  # 2 秒内复用相同响应


async def _collect_health_async() -> dict:
    """异步收集健康信息，避免阻塞事件循环。"""
    env = detect_environment()

    # 并行收集子系统状态（不串行等待）
    async def _get_db_stats():
        def _sync():
            try:
                return get_session_store().get_stats()
            except Exception:
                return {"error": "db unavailable"}
        return await asyncio.get_event_loop().run_in_executor(None, _sync)

    db_stats = await _get_db_stats()

    return {
        "status": "ok",
        "version": __version__,
        "python": env.python_version,
        "server_uptime": round(time.time() - _server_start, 1),
        "db_stats": db_stats,
    }


@router.get("/api/health/live")
async def health_live():
    """轻量级存活探针（kubernetes 风格）— 永不失败，< 5ms 响应。"""
    return {
        "status": "alive",
        "version": __version__,
        "uptime_seconds": round(time.time() - _server_start, 1),
    }


@router.get("/api/health/ready")
async def health_ready():
    """深度就绪检查 — 验证所有子系统可用性。"""
    now = time.time()
    if _HEALTH_CACHE["data"] and now < _HEALTH_CACHE["expires_at"]:
        return _HEALTH_CACHE["data"]
    data = await _collect_health_async()
    _HEALTH_CACHE["data"] = data
    _HEALTH_CACHE["expires_at"] = now + _HEALTH_TTL_SEC
    return data


@router.options("/api/health", include_in_schema=False)
async def health_options():
    """显式 OPTIONS 处理 — 支持非浏览器客户端探测（修复 BUG-009）"""
    return {}


@router.options("/api/health/live", include_in_schema=False)
async def health_live_options():
    return {}


@router.options("/api/health/ready", include_in_schema=False)
async def health_ready_options():
    return {}


@router.get("/api/health")
async def health_check():
    """兼容旧路径 — 等价 /api/health/ready。"""
    return await health_ready()


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
