"""
协作/调度/规则引擎 WebSocket API
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pycoder.core.services.log import log
from pycoder.python.multilang_debugger import get_multilang_debugger
from pycoder.server.custom_rules import get_rules_engine
from pycoder.server.realtime_collab import get_collab_engine
from pycoder.server.scheduler import get_scheduler

collab_ws_router = APIRouter()
scheduler_router = APIRouter(prefix="/api/scheduler")
rules_router = APIRouter(prefix="/api/rules")
debug_router = APIRouter(prefix="/api/debug")


@collab_ws_router.websocket("/ws/collab")
async def ws_collab(ws: WebSocket):
    """协作编辑 WebSocket 入口

    消息协议（客户端 → 服务端）：
    - ``join``:    {type, room_id, client_id?, username?, role?}
                   响应携带当前文档 + revision + 成员列表（断线恢复）
    - ``edit``:    {type, operation, base_revision, request_id?}
                   响应 ack（含变换后操作与 revision）或 nack（含原因）
    - ``sync``:    {type, room_id}
                   主动拉取当前文档 + revision（重连对齐）
    - ``cursor``:  {type, position}  广播光标（附带用户名/颜色）
    """
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return
    await ws.accept()
    engine = get_collab_engine()
    client_id = ""
    room_id = ""
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            mtype = msg.get("type", "")

            if mtype == "join":
                room_id = msg["room_id"]
                client_id = msg.get("client_id", str(id(ws))[-8:])

                async def send(x):
                    await ws.send_text(x)

                result = engine.join(
                    room_id,
                    client_id,
                    send,
                    username=msg.get("username", ""),
                    role=msg.get("role", "editor"),
                    color=msg.get("color", ""),
                )
                result["type"] = "join_result"
                await ws.send_json(result)

            elif mtype == "edit":
                result = await engine.apply_operation(
                    room_id,
                    client_id,
                    msg["operation"],
                    base_revision=msg.get("base_revision"),
                )
                # 操作确认：ack / nack（携带变换后 revision 供客户端对齐）
                result["type"] = "ack" if result.get("success") else "nack"
                if "request_id" in msg:
                    result["request_id"] = msg["request_id"]
                await ws.send_json(result)

            elif mtype == "sync":
                # 断线重连后主动同步：返回当前文档 + 最新 revision + 成员
                room = engine._rooms.get(room_id)
                if room:
                    await ws.send_json(
                        {
                            "type": "sync_result",
                            "success": True,
                            "room_id": room_id,
                            "document": engine._documents.get(room_id, ""),
                            "revision": room["version"],
                            "members": engine._build_member_list(room_id),
                        }
                    )
                else:
                    await ws.send_json(
                        {"type": "sync_result", "success": False, "error": "房间不存在"}
                    )

            elif mtype == "cursor":
                engine.update_cursor(room_id, client_id, msg.get("position", {}))

    except WebSocketDisconnect:
        engine.leave(client_id)
    except Exception as e:
        log.warning("collab_ws_error", error=str(e))


@scheduler_router.get("/tasks")
async def list_scheduled_tasks():
    return {"success": True, "tasks": get_scheduler().list_tasks()}


@scheduler_router.post("/add")
async def add_scheduled_task(req: dict):
    from pycoder.server.scheduler import ScheduledTask

    task = ScheduledTask(
        id=req.get("id", ""),
        name=req.get("name", ""),
        trigger=req.get("trigger", "interval"),
        config=req.get("config", {}),
        action=req.get("action", ""),
        action_args=req.get("action_args", {}),
    )
    return get_scheduler().add_task(task)


@scheduler_router.post("/toggle/{task_id}")
async def toggle_task(task_id: str):
    return get_scheduler().toggle_task(task_id)


@scheduler_router.delete("/{task_id}")
async def remove_task(task_id: str):
    return get_scheduler().remove_task(task_id)


@rules_router.get("/list")
async def list_rules():
    return {"success": True, "rules": get_rules_engine().list_rules()}


@rules_router.post("/add")
async def add_rule(req: dict):
    return get_rules_engine().add_rule(
        name=req.get("name", ""),
        pattern=req.get("pattern", ""),
        rule_type=req.get("type", "regex"),
        severity=req.get("severity", "warning"),
        message=req.get("message", ""),
    )


@rules_router.delete("/{rule_id}")
async def remove_rule(rule_id: str):
    return get_rules_engine().remove_rule(rule_id)


@rules_router.post("/check")
async def check_rules(req: dict):
    file_path = req.get("file")
    if file_path:
        violations = get_rules_engine().check_file(file_path)
        return {"success": True, "violations": violations}
    return get_rules_engine().check_project(req.get("project", "."))


@rules_router.get("/templates")
async def get_rule_templates():
    return {"success": True, "templates": get_rules_engine().get_templates()}


@debug_router.post("/multilang")
async def multilang_debug(req: dict):
    return get_multilang_debugger().debug(
        req["language"],
        req["code"],
        req.get("breakpoints", []),
    )


@debug_router.get("/languages")
async def list_debuggable():
    return {
        "success": True,
        "languages": get_multilang_debugger().list_debuggable(),
    }
