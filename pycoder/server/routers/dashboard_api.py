"""P1-3: 项目仪表盘 REST API

端点:
- GET  /api/dashboard/full   - 完整仪表盘快照
- GET  /api/dashboard/health - 仅健康度评分
- GET  /api/dashboard/deps   - 仅依赖概览
- GET  /api/dashboard/tasks  - 仅任务概览
- GET  /api/dashboard/project - 仅项目信息
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Query

from pycoder.server.services.dashboard import (
    DashboardBuilder,
    dashboard_to_dict,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# 简单内存缓存（避免每次都重建图）
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 30  # 30s


def _get_cached(key: str, builder: callable) -> dict:  # type: ignore
    now = time.time()
    if key in _cache and now - _cache[key][0] < _CACHE_TTL:
        return _cache[key][1]
    data = builder()
    _cache[key] = (now, data)
    return data


@router.get("/full")
async def get_full_dashboard(
    workspace: str | None = None,
    include_graph: bool = Query(default=True),
) -> dict:
    """获取完整仪表盘快照"""
    root = Path(workspace) if workspace else None
    builder = DashboardBuilder(project_root=root)

    def _build() -> dict:
        snap = builder.build(include_graph=include_graph)
        return dashboard_to_dict(snap)

    return _get_cached(f"full:{root or 'cwd'}:{include_graph}", _build)


@router.get("/health")
async def get_health_only(workspace: str | None = None) -> dict:
    """仅健康度评分（轻量级）"""
    root = Path(workspace) if workspace else None
    builder = DashboardBuilder(project_root=root)

    def _build() -> dict:
        snap = builder.build(include_graph=False)
        return {
            "overall": snap.health.overall,
            "grade": snap.health.grade,
            "factors": snap.health.factors,
            "generated_at": snap.generated_at,
        }

    return _get_cached(f"health:{root or 'cwd'}", _build)


@router.get("/deps")
async def get_deps_overview(workspace: str | None = None) -> dict:
    """依赖概览"""
    root = Path(workspace) if workspace else None
    builder = DashboardBuilder(project_root=root)

    def _build() -> dict:
        snap = builder.build(include_graph=False)
        d = {
            "dependencies": snap.dependencies.__dict__,
            "generated_at": snap.generated_at,
        }
        return d

    return _get_cached(f"deps:{root or 'cwd'}", _build)


@router.get("/tasks")
async def get_tasks_overview(workspace: str | None = None) -> dict:
    """任务调度概览"""
    root = Path(workspace) if workspace else None
    builder = DashboardBuilder(project_root=root)

    def _build() -> dict:
        snap = builder.build(include_graph=False)
        return {
            "tasks": snap.tasks.__dict__,
            "generated_at": snap.generated_at,
        }

    return _get_cached(f"tasks:{root or 'cwd'}", _build)


@router.get("/project")
async def get_project_info(workspace: str | None = None) -> dict:
    """项目基本信息"""
    root = Path(workspace) if workspace else None
    builder = DashboardBuilder(project_root=root)

    def _build() -> dict:
        snap = builder.build(include_graph=False)
        return {
            "project": snap.project.__dict__,
            "runtime": snap.runtime,
            "recent_files": snap.recent_files,
            "generated_at": snap.generated_at,
        }

    return _get_cached(f"project:{root or 'cwd'}", _build)


@router.post("/cache/clear")
async def clear_cache() -> dict:
    """清空缓存（强制重建）"""
    _cache.clear()
    return {"success": True, "message": "缓存已清空"}
