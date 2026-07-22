"""P0-3: 调度任务 REST API

提供完整的任务管理接口：
- GET    /api/tasks              列出所有任务
- POST   /api/tasks              创建任务
- GET    /api/tasks/{id}         获取单个任务
- DELETE /api/tasks/{id}         删除任务
- PATCH  /api/tasks/{id}/toggle  启用/禁用
- POST   /api/tasks/{id}/run     立即执行一次
- POST   /api/webhook/{id}       外部 webhook 触发器
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.server.scheduler import ScheduledTask, get_scheduler

router = APIRouter()


# ── 请求/响应模型 ──


class TaskCreate(BaseModel):
    """创建任务请求"""

    name: str = Field(..., min_length=1, max_length=200)
    trigger: str = Field(..., description="interval | cron | file_watch | webhook")
    config: dict = Field(default_factory=dict)
    action: str = Field(..., description="mcp:tool_name 或 python:module.func")
    action_args: dict = Field(default_factory=dict)
    enabled: bool = Field(default=True)


class TaskUpdate(BaseModel):
    """更新任务请求"""

    name: str | None = None
    config: dict | None = None
    action: str | None = None
    action_args: dict | None = None
    enabled: bool | None = None


# ── 路由 ──


@router.get("/api/tasks")
async def list_tasks() -> dict:
    """列出所有调度任务"""
    sched = get_scheduler()
    return {
        "success": True,
        "tasks": sched.list_tasks(),
        "total": len(sched.list_tasks()),
        "running": sched.is_running,
    }


@router.post("/api/tasks")
async def create_task(req: TaskCreate) -> dict:
    """创建新的调度任务"""
    sched = get_scheduler()
    if req.trigger not in ("interval", "cron", "file_watch", "webhook"):
        raise HTTPException(status_code=400, detail=f"不支持的触发器类型: {req.trigger}")

    # 验证文件监听参数
    if req.trigger == "file_watch":
        from pathlib import Path as _P

        watch_path = req.config.get("path", "")
        if not watch_path:
            raise HTTPException(status_code=400, detail="file_watch 任务必须指定 config.path")
        if not _P(watch_path).exists():
            raise HTTPException(status_code=400, detail=f"监听路径不存在: {watch_path}")

    # 验证 cron 参数
    if req.trigger == "cron":
        if not req.config.get("cron"):
            raise HTTPException(status_code=400, detail="cron 任务必须指定 config.cron 表达式")

    # 验证 interval 参数
    if req.trigger == "interval":
        seconds = req.config.get("seconds", 0)
        if not isinstance(seconds, (int, float)) or seconds < 1:
            raise HTTPException(status_code=400, detail="interval 任务必须指定 config.seconds >= 1")

    task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    task = ScheduledTask(
        id=task_id,
        name=req.name,
        trigger=req.trigger,
        config=req.config,
        action=req.action,
        action_args=req.action_args,
        enabled=req.enabled,
    )
    result = sched.add_task(task)
    return {
        "success": True,
        "task_id": task_id,
        "task": task.__dict__,
    }


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    """获取单个任务详情"""
    sched = get_scheduler()
    task = sched.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task": task.__dict__}


@router.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdate) -> dict:
    """更新任务配置"""
    sched = get_scheduler()
    task = sched.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if req.name is not None:
        task.name = req.name
    if req.config is not None:
        task.config = req.config
    if req.action is not None:
        task.action = req.action
    if req.action_args is not None:
        task.action_args = req.action_args
    if req.enabled is not None:
        task.enabled = req.enabled
    sched.save()
    return {"success": True, "task": task.__dict__}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict:
    """删除任务"""
    sched = get_scheduler()
    return sched.remove_task(task_id)


@router.post("/api/tasks/{task_id}/toggle")
async def toggle_task(task_id: str) -> dict:
    """启用/禁用任务"""
    sched = get_scheduler()
    task = sched.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = sched.toggle_task(task_id)
    # 重新启动/停止文件监听
    if task.trigger == "file_watch":
        if task.enabled:
            sched._stop_file_watch(task_id)
            sched._start_file_watch(task)
        else:
            sched._stop_file_watch(task_id)
    return result


@router.post("/api/tasks/{task_id}/run")
async def run_task_now(task_id: str) -> dict:
    """立即执行一次任务"""
    sched = get_scheduler()
    task = sched.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    sched._execute_action(task, trigger_meta={"source": "manual", "user_triggered": True})
    return {"success": True, "message": f"任务 {task.name} 已触发"}


@router.post("/api/webhook/{task_id}")
async def webhook_trigger(task_id: str, payload: dict | None = None) -> dict:
    """外部 webhook 触发器 — 供其他系统调用"""
    sched = get_scheduler()
    return sched.trigger_webhook(task_id, payload or {})


@router.get("/api/tasks/status")
async def scheduler_status() -> dict:
    """调度器状态"""
    sched = get_scheduler()
    return {
        "success": True,
        "running": sched.is_running,
        "task_count": len(sched.list_tasks()),
        "file_watchers": len(sched._file_observers),
        "storage": str(sched._storage),
    }


__all__ = ["router"]
