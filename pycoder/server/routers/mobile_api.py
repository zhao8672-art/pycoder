"""F4 移动端支持 — 移动端精简 API

端点:
    GET /api/mobile/ping    — 连通性/鉴权自检（移动端启动时调用）
    GET /api/mobile/summary — 移动端首屏聚合数据（工作区名/会话数/运行中任务数/版本）
    GET /api/mobile/files   — 精简文件列表（只读，复用 files.py 安全路径校验，限制条数）

设计说明:
    - 移动端（响应式 Web 移动版）首屏只调用 summary 一次，避免慢网络下的多次往返。
    - 所有端点只读，不提供任何写操作，降低移动端误触/攻击面。

远程访问安全设计（重要）:
    - 本模块【不实现】任何隧道/内网穿透能力，远程接入属于部署层职责。
    - 远程访问必须满足: HTTPS（由反向代理 nginx/Caddy 终止 TLS）+ 有效 API Key。
    - 鉴权完全复用 pycoder.server.app 的 APIKeyMiddleware
      （X-API-Key 请求头，WebSocket 兼容 ?api_key= query），本模块不另起鉴权逻辑。
    - 建议部署方式: 经内网穿透（frp / cloudflared）或反向代理，
      将本机 127.0.0.1:8423 安全暴露为 https://your-domain 供移动端访问。
    - 切勿将 PYCODER_API_KEY=disabled 的实例暴露到公网（仅限本机开发调试）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from pycoder import __version__
from pycoder.server.routers.files import _safe_path, get_workspace_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobile", tags=["mobile"])

# ── 文件列表条数限制（移动端流量/渲染保护）─────────────────
DEFAULT_FILES_LIMIT = 100
MAX_FILES_LIMIT = 500


@router.get("/ping")
async def mobile_ping() -> dict:
    """移动端连通性/鉴权自检。

    能通过 APIKeyMiddleware 到达这里即说明鉴权通过，
    移动端据此确认后端可达且 API Key 有效。
    """
    return {"ok": True, "version": __version__, "mobile": True}


@router.get("/summary")
async def mobile_summary() -> dict:
    """聚合移动端首屏所需的最小数据（单次请求）。

    各子项独立容错：任一子系统不可用仅对应字段归零，不影响整体响应。
    """
    workspace = get_workspace_root()

    # 会话数（会话库不可用时降级为 0）
    session_count = 0
    try:
        from pycoder.server.session_store import get_session_store

        stats = get_session_store().get_stats()
        session_count = int(stats.get("session_count", 0))
    except Exception as e:  # noqa: BLE001 — 首屏聚合不允许因子系统失败整体 500
        logger.debug("mobile_summary_sessions_failed: %s", e)

    # 运行中任务数（任务库不可用时降级为 0）
    running_tasks = 0
    try:
        from pycoder.server.services.task_persistence import get_task_persistence

        task_stats = get_task_persistence().get_stats()
        running_tasks = int(task_stats.get("by_status", {}).get("running", 0))
    except Exception as e:  # noqa: BLE001
        logger.debug("mobile_summary_tasks_failed: %s", e)

    return {
        "workspace": str(workspace),
        "workspace_name": workspace.name,
        "session_count": session_count,
        "running_tasks": running_tasks,
        "version": __version__,
        "mobile": True,
    }


@router.get("/files")
async def list_mobile_files(
    path: str = Query(default=".", description="目录路径（相对工作区根）"),
    limit: int = Query(
        default=DEFAULT_FILES_LIMIT,
        ge=1,
        le=MAX_FILES_LIMIT,
        description="最大返回条数",
    ),
) -> dict:
    """精简文件列表（只读）。

    复用 files.py 的 _safe_path 做路径穿越防护；
    仅返回移动端浏览所需的最小字段，并按 limit 截断。
    """
    target = _safe_path(path)  # 路径穿越 → 400（files.py 统一拦截）

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {path}")

    try:
        entries = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权访问: {path}") from None

    workspace = get_workspace_root()
    truncated = len(entries) > limit

    items: list[dict] = []
    for entry in entries[:limit]:
        is_dir = entry.is_dir()
        try:
            size = entry.stat().st_size if not is_dir else 0
        except OSError:
            size = 0
        try:
            rel = str(entry.relative_to(workspace)).replace("\\", "/")
        except ValueError:
            rel = entry.name
        items.append({"name": entry.name, "is_dir": is_dir, "path": rel, "size": size})

    try:
        display_path = str(target.relative_to(workspace)).replace("\\", "/")
    except ValueError:
        display_path = "."

    return {
        "path": display_path,
        "workspace": str(workspace),
        "count": len(items),
        "truncated": truncated,
        "items": items,
    }
