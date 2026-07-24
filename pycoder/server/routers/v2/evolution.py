"""
V2 自我进化 REST + WebSocket API 端点

V1 全部功能已在 V2 引擎中原生实现，本路由提供完全兼容的 API。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from pycoder.server.log import log

router = APIRouter(prefix="/api/v2/evolution", tags=["v2-evolution"])
ws_router = APIRouter(prefix="/api/v2", tags=["v2-ws"])

EVOLUTION_TOKEN_DIR = Path.home() / ".pycoder"
EVOLUTION_TOKEN_FILE = EVOLUTION_TOKEN_DIR / "evolution_token.json"


def _get_evolution_engine(request: Request):
    """获取 V2 进化引擎"""
    v2 = request.app.state.v2_engine
    if not v2 or not hasattr(v2, "evolution"):
        raise RuntimeError("V2 进化引擎未初始化")
    return v2.evolution


# ══════════════════════════════════════════════════════════
# 统计与任务
# ══════════════════════════════════════════════════════════


@router.get("/stats")
async def get_stats(request: Request):
    engine = _get_evolution_engine(request)
    return {"success": True, "stats": engine.get_evolution_stats()}


@router.get("/tasks")
async def list_tasks(request: Request, limit: int = 20):
    engine = _get_evolution_engine(request)
    return {"success": True, "tasks": engine.list_tasks(limit=limit), "total": len(engine._tasks)}


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str):
    engine = _get_evolution_engine(request)
    task = engine.get_task(task_id)
    if not task:
        return {"success": False, "error": "Task not found"}
    return {"success": True, "task": task}


# ══════════════════════════════════════════════════════════
# 进化管线
# ══════════════════════════════════════════════════════════


@router.post("/run")
async def run_evolution(request: Request, req: dict | None = None):
    payload = req or {}
    engine = _get_evolution_engine(request)
    events = []
    async for event in engine.evolve(
        task_type=payload.get("type", "fix"),
        target=payload.get("target", ""),
        custom_prompt=payload.get("custom", ""),
        auto_apply=payload.get("auto_apply", False),
        dry_run=payload.get("dry_run", False),
    ):
        events.append(event)

    final = events[-1] if events else {"type": "error", "message": "No events"}
    return {"success": final.get("type") == "done", "result": final, "all_events": events}


# ══════════════════════════════════════════════════════════
# 手动触发自进化闭环 (SCAN→FIX→TEST→LEARN)
# ══════════════════════════════════════════════════════════


@router.post("/test-cycle")
async def test_evolution_cycle(request: Request, req: dict | None = None):
    """手动触发完整自进化闭环: 扫描→优先级→修复→测试→学习"""
    payload = req or {}
    engine = _get_evolution_engine(request)
    events = []
    summary: dict = {}
    async for event in engine.run_cycle(
        task_type=payload.get("type", "auto"),
        target=payload.get("target", ""),
        auto_apply=payload.get("auto_apply", False),
        dry_run=payload.get("dry_run", True),
    ):
        events.append(event)
        if event.get("type") == "issues_found":
            summary["issues_found"] = event.get("count", 0)
        elif event.get("type") == "done":
            summary["status"] = "done"
            summary["message"] = event.get("message", "")

    return {
        "success": True,
        "summary": summary,
        "phase_count": len(events),
        "phases": [e.get("type") for e in events],
    }


# ══════════════════════════════════════════════════════════
# 监控
# ══════════════════════════════════════════════════════════


@router.post("/watch/start")
async def start_watcher(request: Request, req: dict | None = None):
    payload = req or {}
    _get_evolution_engine(request)
    try:
        from pycoder.server.scheduler import ScheduledTask, get_scheduler

        scheduler = get_scheduler()
        scheduler.add_task(
            ScheduledTask(
                id="evo-watch",
                name="自我进化监控",
                trigger="interval",
                config={"seconds": payload.get("interval", 300)},
                action="python:pycoder.server.app._scheduled_self_scan",
                action_args={},
            )
        )
        return {"success": True, "active": True, "interval": payload.get("interval", 300)}
    except ImportError:
        return {"success": False, "error": "调度器不可用"}


@router.post("/watch/stop")
async def stop_watcher(request: Request):
    try:
        from pycoder.server.scheduler import get_scheduler

        scheduler = get_scheduler()
        scheduler.remove_task("evo-watch")
        return {"success": True, "active": False}
    except ImportError:
        return {"success": False, "error": "调度器不可用"}


@router.get("/watch/status")
async def watch_status(request: Request):
    try:
        from pycoder.server.scheduler import get_scheduler

        scheduler = get_scheduler()
        task = scheduler.get_task("evo-watch")
        return {"success": True, "active": task is not None and task.enabled}
    except ImportError:
        return {"success": True, "active": False}


# ══════════════════════════════════════════════════════════
# 自优化 API
# ══════════════════════════════════════════════════════════


@router.post("/optimize/analyze-usage")
async def analyze_usage(days: int = 30):
    from pycoder.capabilities.self_evo.learning.self_optimizer import get_self_optimizer

    opt = get_self_optimizer()
    report = opt.analyze_usage(days=days)
    return {
        "success": True,
        "sessions": report.total_sessions,
        "topics": report.top_topics[:10],
        "errors": report.top_error_types[:10],
        "hints": report.optimization_hints,
        "common": report.common_issues,
    }


@router.post("/optimize/prompts")
async def optimize_prompts():
    from pycoder.capabilities.self_evo.learning.self_optimizer import get_self_optimizer

    opt = get_self_optimizer()
    results = opt.optimize_prompts()
    return {
        "success": True,
        "results": [
            {
                "agent": r.agent_id,
                "lines": r.original_lines,
                "issues": len(r.changes),
                "changes": r.changes,
                "expected": r.expected_improvement,
            }
            for r in results
        ],
    }


@router.post("/optimize/heal")
async def auto_heal(target: str = "pycoder", dry_run: bool = False):
    from pycoder.capabilities.self_evo.learning.self_optimizer import get_self_optimizer

    opt = get_self_optimizer()
    report = await opt.auto_heal(dry_run=dry_run)
    return {
        "success": True,
        "task_id": report.task_id,
        "issues_found": report.issues_found,
        "fixes_applied": report.fixes_applied,
        "test_passed": report.test_passed,
        "error": report.error,
        "dry_run": dry_run,
    }


@router.get("/optimize/report")
async def optimization_report():
    from pycoder.capabilities.self_evo.learning.self_optimizer import get_self_optimizer

    opt = get_self_optimizer()
    return {"success": True, "report": opt.generate_optimization_markdown()}


# ══════════════════════════════════════════════════════════
# 信任管理（替代 V1 审批/令牌）
# ══════════════════════════════════════════════════════════


@router.get("/approvals")
async def list_pending_approvals(request: Request):
    engine = _get_evolution_engine(request)
    pending = [t.to_dict() for t in engine._tasks if t.status == "awaiting_approval"]
    return {"success": True, "approvals": pending, "total": len(pending)}


@router.post("/approve/{approval_id}")
async def approve_evolution(request: Request, approval_id: str):
    engine = _get_evolution_engine(request)
    if hasattr(engine.v2, "permission") and engine.v2.permission:
        engine.v2.permission.escalate_trust("用户审批通过进化请求")
    return {"success": True, "message": "信任级别已升级，请重新提交进化任务"}


@router.post("/reject/{approval_id}")
async def reject_evolution(request: Request, approval_id: str):
    engine = _get_evolution_engine(request)
    for t in engine._tasks:
        if t.id == approval_id:
            t.status = "skipped"
            t.completed_at = time.time()
            return {"success": True, "task_id": approval_id, "status": "skipped"}
    return {"success": False, "error": "审批ID不存在"}


@router.post("/token/generate")
async def generate_token(request: Request, req: dict):
    files = req.get("files", [])
    if not files:
        return {"success": False, "error": "files 不能为空"}
    if hasattr(request.app.state.v2_engine, "permission"):
        request.app.state.v2_engine.permission.escalate_trust("生成进化令牌")
    return {"success": True, "files": files, "message": "信任级别已升级"}


@router.delete("/token")
async def clear_token(request: Request):
    return {"success": True, "message": "信任级别管理已迁移到 /api/v2/trust"}


@router.get("/token/status")
async def token_status(request: Request):
    if hasattr(request.app.state.v2_engine, "permission"):
        trust = request.app.state.v2_engine.permission.get_trust_report()
        return {
            "success": True,
            "trust_level": trust.get("level", 0),
            "label": trust.get("label", ""),
        }
    return {"success": True, "exists": False}


# ══════════════════════════════════════════════════════════
# WebSocket
# ══════════════════════════════════════════════════════════


@ws_router.websocket("/ws/evolution")
async def ws_evolution(ws: WebSocket):
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return
    await ws.accept()

    try:
        # 获取 V2 引擎
        engine = ws.app.state.v2_engine.evolution

        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")

            if msg_type == "evolve":
                async for event in engine.evolve(
                    task_type=msg.get("task_type", "fix"),
                    target=msg.get("target", ""),
                    custom_prompt=msg.get("custom", ""),
                    auto_apply=msg.get("auto_apply", False),
                    dry_run=msg.get("dry_run", False),
                ):
                    await ws.send_json(event)
                    await asyncio.sleep(0)

            elif msg_type == "stats":
                await ws.send_json({"type": "stats", "stats": engine.get_evolution_stats()})

            elif msg_type == "tasks":
                tasks = engine.list_tasks(limit=20)
                await ws.send_json({"type": "task_list", "tasks": tasks})

            elif msg_type == "approve":
                if hasattr(engine.v2, "permission") and engine.v2.permission:
                    engine.v2.permission.escalate_trust("WS审批")
                await ws.send_json({"type": "approved", "message": "信任级别已升级"})

            elif msg_type == "reject":
                approval_id = msg.get("approval_id", "")
                for t in engine._tasks:
                    if t.id == approval_id:
                        t.status = "skipped"
                        t.completed_at = time.time()
                await ws.send_json({"type": "rejected", "approval_id": approval_id})

            elif msg_type == "approvals":
                pending = [t.to_dict() for t in engine._tasks if t.status == "awaiting_approval"]
                await ws.send_json({"type": "approvals", "approvals": pending})

            else:
                await ws.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )

    except WebSocketDisconnect:
        log.info("evolution_ws_disconnect")
    except Exception as e:
        log.error("evolution_ws_error", error=str(e))
