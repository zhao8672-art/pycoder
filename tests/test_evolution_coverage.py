"""覆盖率测试: pycoder/server/routers/v2/evolution.py (V2 进化路由)

目标: 行覆盖率 >= 95%

覆盖端点:
    GET  /api/v2/evolution/stats                  — 进化统计
    GET  /api/v2/evolution/tasks                  — 任务列表
    GET  /api/v2/evolution/tasks/{task_id}        — 任务详情
    POST /api/v2/evolution/run                    — 触发进化
    POST /api/v2/evolution/watch/start            — 启动监控
    POST /api/v2/evolution/watch/stop             — 停止监控
    GET  /api/v2/evolution/watch/status           — 监控状态
    POST /api/v2/evolution/optimize/analyze-usage — 使用分析
    POST /api/v2/evolution/optimize/prompts       — 提示词优化
    POST /api/v2/evolution/optimize/heal          — 自修复
    GET  /api/v2/evolution/optimize/report        — 优化报告
    WS   /api/v2/ws/evolution                     — WebSocket 进化流

测试策略:
    - mock V2 engine 返回 MagicMock
    - mock get_self_optimizer 返回 MagicMock
    - WebSocket 测试用 TestClient.websocket_connect
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers.v2 import evolution as evo_mod


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def mock_engine():
    """模拟 V2 进化引擎"""
    engine = MagicMock()
    engine.get_evolution_stats.return_value = {
        "total_tasks": 5, "successful": 3, "failed": 1,
    }
    engine.list_tasks.return_value = [{"id": "t1", "status": "done"}]
    engine.get_task.return_value = {"id": "t1", "status": "done"}
    engine._tasks = []
    return engine


@pytest.fixture
def app_client(mock_engine):
    """创建 FastAPI 应用，注入 mock V2 引擎"""
    app = FastAPI()

    # 创建 mock v2_engine 并挂载到 app.state
    v2 = MagicMock()
    v2.evolution = mock_engine
    app.state.v2_engine = v2

    app.include_router(evo_mod.router)
    app.include_router(evo_mod.ws_router)

    # WS 端点需要 verify_ws_auth — 直接禁用 _API_KEY 使真实函数短路
    # 注意：import pycoder.server.app 返回的是 FastAPI 实例（因为 __init__.py 做了
    # from pycoder.server.app import app），不是模块对象。必须通过 sys.modules 获取
    # 真正的模块对象来设置 _API_KEY。
    import sys
    app_mod = sys.modules["pycoder.server.app"]
    app_mod._API_KEY = ""

    with TestClient(app) as c:
        yield c


# ══════════════════════════════════════════════════════════
# 1. GET /stats
# ══════════════════════════════════════════════════════════


class TestStats:
    def test_get_stats(self, app_client, mock_engine):
        resp = app_client.get("/api/v2/evolution/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["total_tasks"] == 5
        mock_engine.get_evolution_stats.assert_called_once()


# ══════════════════════════════════════════════════════════
# 2. GET /tasks
# ══════════════════════════════════════════════════════════


class TestTasksList:
    def test_list_tasks(self, app_client, mock_engine):
        resp = app_client.get("/api/v2/evolution/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["tasks"]) == 1
        assert data["total"] == 0  # _tasks is empty list
        mock_engine.list_tasks.assert_called_once_with(limit=20)

    def test_list_tasks_with_limit(self, app_client, mock_engine):
        resp = app_client.get("/api/v2/evolution/tasks", params={"limit": 5})
        assert resp.status_code == 200
        mock_engine.list_tasks.assert_called_with(limit=5)


# ══════════════════════════════════════════════════════════
# 3. GET /tasks/{task_id}
# ══════════════════════════════════════════════════════════


class TestTaskDetail:
    def test_found(self, app_client, mock_engine):
        resp = app_client.get("/api/v2/evolution/tasks/abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task"]["id"] == "t1"
        mock_engine.get_task.assert_called_with("abc")

    def test_not_found(self, app_client, mock_engine):
        mock_engine.get_task.return_value = None
        resp = app_client.get("/api/v2/evolution/tasks/missing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "Task not found"


# ══════════════════════════════════════════════════════════
# 4. POST /run
# ══════════════════════════════════════════════════════════


class TestRunEvolution:
    def test_with_done_event(self, app_client, mock_engine):
        async def fake_evolve(*a, **kw):
            yield {"type": "phase", "message": "scanning"}
            yield {"type": "done", "message": "完成"}
        mock_engine.evolve = fake_evolve

        resp = app_client.post("/api/v2/evolution/run", json={
            "type": "fix", "target": "src", "custom": "请修复",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["type"] == "done"
        assert len(data["all_events"]) == 2

    def test_with_error_event(self, app_client, mock_engine):
        async def fake_evolve(*a, **kw):
            yield {"type": "error", "message": "boom"}
        mock_engine.evolve = fake_evolve

        resp = app_client.post("/api/v2/evolution/run", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_no_events(self, app_client, mock_engine):
        async def fake_evolve(*a, **kw):
            return
            yield
        mock_engine.evolve = fake_evolve

        resp = app_client.post("/api/v2/evolution/run", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["result"]["type"] == "error"


# ══════════════════════════════════════════════════════════
# 5. POST /watch/*
# ══════════════════════════════════════════════════════════


class TestWatcher:
    def test_start(self, app_client, mock_engine):
        resp = app_client.post("/api/v2/evolution/watch/start", json={"interval": 120})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_stop(self, app_client, mock_engine):
        resp = app_client.post("/api/v2/evolution/watch/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_status(self, app_client, mock_engine):
        resp = app_client.get("/api/v2/evolution/watch/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "active" in data


# ══════════════════════════════════════════════════════════
# 6. POST /optimize/*  (SelfOptimizer)
# ══════════════════════════════════════════════════════════


class TestOptimize:
    @pytest.fixture
    def mock_optimizer(self, monkeypatch):
        opt = MagicMock()
        opt.analyze_usage.return_value = SimpleNamespace(
            total_sessions=10,
            top_topics=[("bug", 5), ("test", 3)],
            top_error_types=[("NameError", 2)],
            optimization_hints=["提示1"],
            common_issues=["issue1"],
        )
        opt.optimize_prompts.return_value = [
            SimpleNamespace(
                agent_id="agent1", original_lines=10,
                changes=["change1", "change2"],
                expected_improvement="提升 20%",
            ),
        ]
        opt.auto_heal = AsyncMock(return_value=SimpleNamespace(
            task_id="HEAL-1", issues_found=3, fixes_applied=2,
            test_passed=True, error="",
        ))
        opt.generate_optimization_markdown.return_value = "# Report"
        monkeypatch.setattr(
            "pycoder.capabilities.self_evo.learning.self_optimizer.get_self_optimizer",
            lambda: opt,
        )
        return opt

    def test_analyze_usage(self, app_client, mock_optimizer):
        resp = app_client.post(
            "/api/v2/evolution/optimize/analyze-usage",
            params={"days": 7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["sessions"] == 10
        assert len(data["topics"]) == 2
        assert data["hints"] == ["提示1"]
        mock_optimizer.analyze_usage.assert_called_once_with(days=7)

    def test_optimize_prompts(self, app_client, mock_optimizer):
        resp = app_client.post("/api/v2/evolution/optimize/prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["results"]) == 1
        assert data["results"][0]["agent"] == "agent1"
        assert data["results"][0]["issues"] == 2

    def test_auto_heal(self, app_client, mock_optimizer):
        resp = app_client.post(
            "/api/v2/evolution/optimize/heal",
            params={"dry_run": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "HEAL-1"
        assert data["issues_found"] == 3
        assert data["fixes_applied"] == 2
        assert data["test_passed"] is True
        assert data["dry_run"] is True
        mock_optimizer.auto_heal.assert_awaited_once_with(dry_run=True)

    def test_optimization_report(self, app_client, mock_optimizer):
        resp = app_client.get("/api/v2/evolution/optimize/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["report"] == "# Report"


# ══════════════════════════════════════════════════════════
# 7. WS /api/v2/ws/evolution
# ══════════════════════════════════════════════════════════


class TestWsEvolution:
    def test_evolve_message(self, app_client, mock_engine):
        async def fake_evolve(*a, **kw):
            yield {"type": "phase", "phase": "analyzing"}
            yield {"type": "done", "message": "完成"}
        mock_engine.evolve = fake_evolve

        with app_client.websocket_connect("/api/v2/ws/evolution") as ws:
            ws.send_text(json.dumps({
                "type": "evolve", "task_type": "fix", "target": "src",
            }))
            msg1 = ws.receive_json()
            msg2 = ws.receive_json()
            assert msg1["type"] == "phase"
            assert msg2["type"] == "done"

    def test_stats_message(self, app_client, mock_engine):
        with app_client.websocket_connect("/api/v2/ws/evolution") as ws:
            ws.send_text(json.dumps({"type": "stats"}))
            msg = ws.receive_json()
            assert msg["type"] == "stats"
            assert "stats" in msg

    def test_tasks_message(self, app_client, mock_engine):
        with app_client.websocket_connect("/api/v2/ws/evolution") as ws:
            ws.send_text(json.dumps({"type": "tasks"}))
            msg = ws.receive_json()
            assert msg["type"] == "task_list"
            assert len(msg["tasks"]) == 1

    def test_unknown_message(self, app_client, mock_engine):
        with app_client.websocket_connect("/api/v2/ws/evolution") as ws:
            ws.send_text(json.dumps({"type": "unknown"}))
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Unknown message type" in msg["message"]

    def test_disconnect(self, app_client, mock_engine):
        with app_client.websocket_connect("/api/v2/ws/evolution") as ws:
            ws.send_text(json.dumps({"type": "stats"}))
            ws.receive_json()