"""通知与任务调度模块 — 后台任务执行、进度监控、主动推送"""
from __future__ import annotations

from typing import Any

from pycoder.notify.task_scheduler import EnhancedScheduler, EnhancedTask, TaskStatus, TaskTrigger
from pycoder.notify.notification_hub import NotificationHub, NotificationPriority
from pycoder.notify.progress_tracker import ProgressTracker

__all__ = [
    "EnhancedScheduler",
    "EnhancedTask",
    "TaskStatus",
    "TaskTrigger",
    "NotificationHub",
    "NotificationPriority",
    "ProgressTracker",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册任务调度与通知能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    hub = NotificationHub()
    scheduler = EnhancedScheduler(hub)
    tracker = ProgressTracker()

    def _send_notification(params: dict, ctx: dict) -> dict:
        import asyncio
        priority = NotificationPriority(params.get("priority", "normal"))
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(hub.send(
                params["event"], params.get("data", {}), priority,
            ))
        else:
            loop.run_until_complete(hub.send(
                params["event"], params.get("data", {}), priority,
            ))
        return {"success": True}

    def _get_task_status(params: dict, ctx: dict) -> dict:
        task = scheduler.get_task(params["task_id"])
        if not task:
            return {"error": f"任务 {params['task_id']} 不存在"}
        return {
            "id": task.id, "name": task.name,
            "status": task.status.value, "progress": task.progress,
            "progress_message": task.progress_message, "error": task.error,
        }

    def _list_tasks(params: dict, ctx: dict) -> dict:
        status_filter = params.get("status")
        task_status = TaskStatus(status_filter) if status_filter else None
        return {"tasks": scheduler.list_tasks(task_status)}

    def _cancel_task(params: dict, ctx: dict) -> dict:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(scheduler.cancel(params["task_id"]))
        else:
            loop.run_until_complete(scheduler.cancel(params["task_id"]))
        return {"success": True}

    def _get_task_progress(params: dict, ctx: dict) -> dict:
        current = tracker.get_current(params["task_id"])
        history = tracker.get_history(params["task_id"])
        eta = tracker.estimate_remaining(params["task_id"])
        return {
            "task_id": params["task_id"],
            "current": current,
            "history": history,
            "estimated_remaining_seconds": eta,
        }

    def _configure_channels(params: dict, ctx: dict) -> dict:
        channels = set(params.get("channels", ["websocket"]))
        hub.configure_channels(channels)
        return {"enabled_channels": list(hub.enabled_channels)}

    registry.register(
        CapabilityDefinition(
            id="notify.send",
            name="发送通知",
            description="通过启用的渠道发送通知（WebSocket/桌面/Webhook）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "event": {"type": "string", "description": "事件名称"},
                    "data": {"type": "object", "description": "事件数据"},
                    "priority": {"type": "string", "description": "优先级 (critical/important/normal/info)"},
                },
                "required": ["event"],
            },
            tags=["notify", "send", "通知", "推送"],
        ),
        handler=_send_notification,
    )

    registry.register(
        CapabilityDefinition(
            id="notify.task_status",
            name="查询任务状态",
            description="查询指定任务的当前状态和进度",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"},
                },
                "required": ["task_id"],
            },
            tags=["notify", "task", "status", "任务"],
        ),
        handler=_get_task_status,
    )

    registry.register(
        CapabilityDefinition(
            id="notify.task_list",
            name="列出任务",
            description="列出所有任务，可按状态筛选",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "状态筛选 (pending/running/done/failed/cancelled)"},
                },
            },
            tags=["notify", "task", "list", "任务列表"],
        ),
        handler=_list_tasks,
    )

    registry.register(
        CapabilityDefinition(
            id="notify.task_cancel",
            name="取消任务",
            description="取消一个待执行或运行中的任务",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.SELF_MODIFY],
            schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"},
                },
                "required": ["task_id"],
            },
            tags=["notify", "task", "cancel", "取消"],
        ),
        handler=_cancel_task,
    )

    registry.register(
        CapabilityDefinition(
            id="notify.task_progress",
            name="查询任务进度",
            description="查询任务进度历史与预估剩余时间",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"},
                },
                "required": ["task_id"],
            },
            tags=["notify", "task", "progress", "进度"],
        ),
        handler=_get_task_progress,
    )

    registry.register(
        CapabilityDefinition(
            id="notify.configure_channels",
            name="配置通知渠道",
            description="配置启用的通知渠道（websocket/desktop/webhook）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.SELF_MODIFY],
            schema={
                "type": "object",
                "properties": {
                    "channels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "启用的渠道列表",
                    },
                },
            },
            tags=["notify", "configure", "channels", "配置"],
        ),
        handler=_configure_channels,
    )