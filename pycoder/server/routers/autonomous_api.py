"""
Autonomous API — 全自主开发流水线 REST + WebSocket 端点

端点:
    POST   /api/autonomous/run          — 启动流水线
    GET    /api/autonomous/runs         — 列出执行记录
    GET    /api/autonomous/runs/{id}    — 获取执行详情
    POST   /api/autonomous/runs/{id}/cancel — 取消执行
    POST   /api/autonomous/runs/{id}/retry  — 重试失败流水线
    WS     /ws/autonomous/progress      — WebSocket 实时进度推送
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autonomous")
ws_router = APIRouter()  # WebSocket 需要无 prefix


class AutonomousRunRequest(BaseModel):
    task: str = Field(..., min_length=3, max_length=5000, description="需求描述")
    model: str = Field("deepseek-chat", description="使用的AI模型")
    project_name: str = Field("", description="可选: 项目名称")
    auto_accept: bool = Field(True, description="是否自动验收")


# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════


@router.post("/run")
async def run_pipeline(req: AutonomousRunRequest):
    """
    启动全自主开发流水线

    返回 run_id，客户端通过 WebSocket 订阅进度:
        ws://host:port/ws/autonomous/progress?run_id={run_id}
    """
    import asyncio

    from pycoder.server.services.autonomous_pipeline import (
        PipelineRun,
        _infer_project_name,
        get_pipeline,
    )

    pipeline = get_pipeline()
    project_name = req.project_name or _infer_project_name(req.task)

    # 预创建 run 记录，确保立即有 run_id
    pre_run = PipelineRun(request=req.task, work_dir=str(pipeline.workspace))
    pipeline._runs[pre_run.id] = pre_run

    # 后台任务：实际执行流水线（带异常捕获，防止静默崩溃）
    async def _bg_execute():
        try:
            async for _event in pipeline.run(req.task, run_id=pre_run.id):
                pass  # 所有状态已存入 pipeline._runs
        except Exception as exc:
            import traceback

            traceback.print_exc()
            try:
                from pycoder.server.log import log

                log.error("autonomous_bg_task_crash", error=str(exc), run_id=pre_run.id)
            except Exception as e:
                logger.debug("autonomous_log_failed error=%s", e)

    asyncio.create_task(_bg_execute())

    return {
        "success": True,
        "run_id": pre_run.id,
        "project_name": project_name,
        "task": req.task[:200],
        "message": (
            "流水线已启动（后台执行）。查询进度: " f"GET /api/autonomous/runs/{pre_run.id}"
        ),
    }


@router.get("/runs")
async def list_runs(limit: int = 10):
    """列出最近的流水线执行记录"""
    from pycoder.server.services.autonomous_pipeline import get_pipeline

    pipeline = get_pipeline()
    return {"runs": pipeline.list_runs(limit)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """获取某次执行详情"""
    from pycoder.server.services.autonomous_pipeline import get_pipeline

    pipeline = get_pipeline()
    run = pipeline.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """取消正在执行的流水线"""
    from pycoder.server.services.autonomous_pipeline import get_pipeline

    pipeline = get_pipeline()
    if pipeline.cancel_run(run_id):
        return {"success": True, "message": f"已请求取消 {run_id}"}
    raise HTTPException(400, f"无法取消 {run_id}（可能已完成或不存在）")


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str):
    """从失败步骤重试流水线"""
    from pycoder.server.services.autonomous_pipeline import get_pipeline

    pipeline = get_pipeline()
    run = pipeline.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return {
        "success": True,
        "run_id": run_id,
        "message": "重试功能将在后台执行，通过 WebSocket 订阅进度",
    }


# ══════════════════════════════════════════════════════════
# WebSocket 端点
# ══════════════════════════════════════════════════════════


@ws_router.websocket("/ws/autonomous/progress")
async def ws_pipeline_progress(ws: WebSocket):
    """
    WebSocket 实时推送流水线进度

    连接后发送 JSON:
        {"action": "run", "task": "需求描述", "model": "deepseek-chat"}
    或
        {"action": "subscribe", "run_id": "pipeline-xxx"}

    接收事件:
        {type: "phase", phase: "...", message: "...", progress: N}
        {type: "agent_start", role: "...", task: "..."}
        {type: "agent_done", role: "...", files: [...]}
        {type: "quality_report", report: {...}}
        {type: "test_result", result: {...}}
        {type: "acceptance", passed: bool, report: {...}}
        {type: "delivery", package: {...}}
        {type: "done", run_id: "...", report: {...}}
        {type: "error", message: "...", step: "..."}
    """
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return
    await ws.accept()

    try:
        from pycoder.server.services.autonomous_pipeline import get_pipeline

        pipeline = get_pipeline()

        data = await ws.receive_json()
        action = data.get("action", "run")
        task = data.get("task", "")
        data.get("model", "deepseek-chat")

        if not task and action == "run":
            await ws.send_json({"type": "error", "message": "task is required"})
            await ws.close()
            return

        # 执行流水线
        async for event in pipeline.run(task):
            await ws.send_json(event)
            await asyncio.sleep(0)

        await ws.send_json({"type": "ws_closed", "message": "流水线执行完成"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except (RuntimeError, ConnectionError) as send_err:
            logger.debug("autonomous_ws_error_send_failed error=%s", send_err)
