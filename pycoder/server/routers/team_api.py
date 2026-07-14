"""
Team API — Agent 团队 REST + WebSocket 端点
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team")

# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════


@router.post("/start")
async def team_start(req: dict):
    """启动 Agent 团队执行任务: {task: "需求描述"}"""
    task = req.get("task", "")
    if not task:
        raise HTTPException(400, "task is required")

    from pycoder.server.services.team import get_coordinator

    orch = get_coordinator()

    # FIX #3: 全程执行，不中途break
    run_id = None
    async for event in orch.execute(task):
        if event["type"] == "team_start":
            run_id = event["run_id"]
        # 继续执行直到完成，不再break

    return {
        "success": True,
        "run_id": run_id,
        "message": "Team execution completed",
    }


@router.get("/status/{run_id}")
async def team_status(run_id: str):
    """查询团队执行状态"""
    from pycoder.server.services.team import get_coordinator

    orch = get_coordinator()
    run = orch.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return {
        "id": run.id,
        "request": run.request,
        "status": run.status,
        "progress": run.progress,
        "tasks": run.tasks,
        "review_rounds": run.review_rounds,
        "current_agent": run.current_agent,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


@router.get("/runs")
async def team_runs(limit: int = 10):
    """列出所有团队执行记录"""
    from pycoder.server.services.team import get_coordinator

    orch = get_coordinator()
    return {"runs": orch.list_runs(limit)}


# ══════════════════════════════════════════════════════════
# WebSocket 端点
# ══════════════════════════════════════════════════════════


@router.websocket("/ws")
async def team_websocket(ws: WebSocket):
    """WebSocket — 实时 Agent 团队执行进度流"""
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return
    await ws.accept()
    try:
        data = await ws.receive_json()
        task = data.get("task", "")
        if not task:
            await ws.send_json({"type": "error", "message": "task is required"})
            await ws.close()
            return

        from pycoder.server.services.team import get_coordinator

        orch = get_coordinator()

        async for event in orch.execute(task):
            await ws.send_json(event)
            await asyncio.sleep(0)

        await ws.close()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except (RuntimeError, ConnectionError) as send_err:
            logger.debug("team_ws_error_send_failed error=%s", send_err)
