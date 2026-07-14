"""任务调度与通知 API — 任务提交、进度查询、取消、WebSocket 通知"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from pycoder.notify.notification_hub import NotificationHub
from pycoder.notify.progress_tracker import ProgressTracker
from pycoder.notify.task_scheduler import EnhancedScheduler, EnhancedTask, TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
ws_router = APIRouter(prefix="/ws", tags=["websocket"])

_hub = NotificationHub()
_scheduler = EnhancedScheduler(_hub)
_tracker = ProgressTracker()

# 启动调度器
_started = False


async def _ensure_started():
    global _started
    if not _started:
        await _scheduler.start()
        _started = True


@router.post("/submit")
async def submit_task(req: dict):
    """提交新任务"""
    await _ensure_started()
    task = EnhancedTask(
        id=req.get("id", f"task_{int(asyncio.get_event_loop().time())}"),
        name=req.get("name", "未命名任务"),
        priority=req.get("priority", 0),
        max_retries=req.get("max_retries", 0),
        retry_delay=req.get("retry_delay", 5.0),
        depends_on=req.get("depends_on", []),
    )
    task_id = await _scheduler.submit(task)
    return {"task_id": task_id, "status": "submitted"}


@router.get("/list")
async def list_tasks(status: str | None = Query(None, description="状态筛选")):
    """列出所有任务"""
    await _ensure_started()
    task_status = TaskStatus(status) if status else None
    return {"tasks": _scheduler.list_tasks(task_status)}


@router.get("/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    task = _scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status.value,
        "progress": task.progress,
        "progress_message": task.progress_message,
        "error": task.error,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


@router.get("/{task_id}/progress")
async def get_task_progress(task_id: str):
    """获取任务进度历史与预估剩余时间"""
    current = _tracker.get_current(task_id)
    history = _tracker.get_history(task_id)
    eta = _tracker.estimate_remaining(task_id)
    return {
        "task_id": task_id,
        "current": current,
        "history": history,
        "estimated_remaining_seconds": eta,
    }


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    result = await _scheduler.cancel(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在或无法取消")
    return {"success": True}


@router.put("/channels")
async def configure_channels(req: dict):
    """配置通知渠道"""
    channels = set(req.get("channels", ["websocket"]))
    _hub.configure_channels(channels)
    return {"enabled_channels": list(_hub.enabled_channels)}


@router.post("/webhooks/register")
async def register_webhook(req: dict):
    """注册 Webhook 回调 URL"""
    url = req.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="缺少 url 参数")
    _hub.add_webhook(url)
    return {"success": True, "url": url}


@router.delete("/webhooks/{url:path}")
async def remove_webhook(url: str):
    """移除 Webhook"""
    _hub.remove_webhook(url)
    return {"success": True}


@ws_router.websocket("/notifications")
async def notification_websocket(ws: WebSocket):
    """WebSocket 通知通道"""
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return
    session_id = str(id(ws))
    await ws.accept()
    _hub.register_ws(session_id, ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _hub.unregister_ws(session_id, ws)
