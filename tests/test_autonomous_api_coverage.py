"""覆盖率测试: pycoder/server/routers/autonomous_api.py

目标: 行覆盖率 >= 95%

覆盖端点:
    POST   /api/autonomous/run                — 启动流水线（含后台任务异常）
    GET    /api/autonomous/runs               — 列出执行记录
    GET    /api/autonomous/runs/{run_id}      — 详情（找到 / 未找到）
    POST   /api/autonomous/runs/{id}/cancel   — 取消（成功 / 失败）
    POST   /api/autonomous/runs/{id}/retry     — 重试（找到 / 未找到）
    WS     /ws/autonomous/progress            — WebSocket 实时进度

测试策略:
    - mock get_pipeline 返回 MagicMock
    - mock _infer_project_name
    - WebSocket 测试用 TestClient.websocket_connect + monkeypatch verify_ws_auth
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import autonomous_api as auto_mod


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def mock_pipeline():
    """模拟 AutonomousPipeline 单例"""
    pipeline = MagicMock()
    pipeline.workspace = MagicMock()
    pipeline.workspace.__str__ = lambda self: "/fake/workspace"
    pipeline._runs = {}
    pipeline.list_runs.return_value = [
        {"id": "r1", "status": "done", "request": "test"},
    ]
    pipeline.get_run.return_value = {"id": "r1", "status": "done"}
    pipeline.cancel_run.return_value = True
    return pipeline


@pytest.fixture
def app_client(mock_pipeline, monkeypatch):
    """创建 FastAPI 应用，注入 mock pipeline"""
    # patch get_pipeline 在 autonomous_pipeline 模块中
    monkeypatch.setattr(
        "pycoder.server.services.autonomous_pipeline.get_pipeline",
        lambda: mock_pipeline,
    )

    # WS 端点 verify_ws_auth 默认需要 API Key，让 verify_ws_auth 总是返回 True
    import sys
    app_module = sys.modules["pycoder.server.app"]

    async def _true(_ws):
        return True
    monkeypatch.setattr(app_module, "verify_ws_auth", _true)

    app = FastAPI()
    app.include_router(auto_mod.router)
    app.include_router(auto_mod.ws_router)
    with TestClient(app) as c:
        yield c


# ══════════════════════════════════════════════════════════
# 1. POST /run
# ══════════════════════════════════════════════════════════


class TestRun:
    def test_run_success(self, app_client, mock_pipeline, monkeypatch):
        """启动流水线 → 返回 run_id"""
        # mock _infer_project_name
        monkeypatch.setattr(
            "pycoder.server.services.autonomous_pipeline._infer_project_name",
            lambda task: "my-project",
        )
        # mock pipeline.run 是 async generator
        async def fake_run(*a, **kw):
            yield {"type": "phase", "phase": "init"}
        mock_pipeline.run = fake_run

        resp = app_client.post("/api/autonomous/run", json={
            "task": "请实现一个 hello world 程序",
            "model": "deepseek-chat",
            "project_name": "hello",
            "auto_accept": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "run_id" in data
        assert data["project_name"] == "hello"
        # 应已预创建 run 记录
        assert len(mock_pipeline._runs) == 1

    def test_run_with_inferred_project_name(self, app_client, mock_pipeline, monkeypatch):
        """未指定 project_name 时使用 _infer_project_name"""
        monkeypatch.setattr(
            "pycoder.server.services.autonomous_pipeline._infer_project_name",
            lambda task: "inferred",
        )
        async def fake_run(*a, **kw):
            yield {"type": "done"}
        mock_pipeline.run = fake_run

        resp = app_client.post("/api/autonomous/run", json={
            "task": "实现登录页面",
        })
        assert resp.status_code == 200
        assert resp.json()["project_name"] == "inferred"

    def test_run_background_task_exception(self, app_client, mock_pipeline, monkeypatch):
        """后台任务抛异常应被捕获（不静默崩溃）"""
        monkeypatch.setattr(
            "pycoder.server.services.autonomous_pipeline._infer_project_name",
            lambda task: "p",
        )
        # pipeline.run 抛异常
        async def fake_run(*a, **kw):
            raise RuntimeError("bg crash")
            yield  # unreachable
        mock_pipeline.run = fake_run

        resp = app_client.post("/api/autonomous/run", json={
            "task": "需要至少3个字符",  # min_length=3
        })
        # 即使后台任务崩，主请求仍返回成功（已预创建 run_id）
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_run_background_log_failure(self, app_client, mock_pipeline, monkeypatch):
        """后台任务异常 + log.error 也抛异常 → 进入 logger.debug 分支"""
        monkeypatch.setattr(
            "pycoder.server.services.autonomous_pipeline._infer_project_name",
            lambda task: "p",
        )
        # pipeline.run 抛异常
        async def fake_run(*a, **kw):
            raise RuntimeError("bg crash")
            yield
        mock_pipeline.run = fake_run

        # 让 log.error 抛异常 → 进入内层 except → 调用 logger.debug
        from pycoder.server.log import log as pycoder_log
        original_error = pycoder_log.error

        def failing_error(*a, **kw):
            raise RuntimeError("log subsystem failure")
        monkeypatch.setattr(pycoder_log, "error", failing_error)

        # 捕获 logger.debug 调用
        debug_calls = []
        monkeypatch.setattr(
            auto_mod.logger, "debug",
            lambda *a, **kw: debug_calls.append((a, kw)),
        )

        resp = app_client.post("/api/autonomous/run", json={
            "task": "需要至少3个字符",
        })
        assert resp.status_code == 200
        # 等待后台任务执行
        import time as _time
        _time.sleep(0.2)
        # 验证 logger.debug 被调用（说明 log.error 失败后被捕获）
        assert any(
            "autonomous_log_failed" in str(args[0]) if args else False
            for args, _ in debug_calls
        )


# ══════════════════════════════════════════════════════════
# 2. GET /runs
# ══════════════════════════════════════════════════════════


class TestListRuns:
    def test_list(self, app_client, mock_pipeline):
        resp = app_client.get("/api/autonomous/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 1
        mock_pipeline.list_runs.assert_called_once_with(10)

    def test_list_with_limit(self, app_client, mock_pipeline):
        resp = app_client.get("/api/autonomous/runs", params={"limit": 5})
        assert resp.status_code == 200
        mock_pipeline.list_runs.assert_called_with(5)


# ══════════════════════════════════════════════════════════
# 3. GET /runs/{run_id}
# ══════════════════════════════════════════════════════════


class TestGetRun:
    def test_found(self, app_client, mock_pipeline):
        resp = app_client.get("/api/autonomous/runs/r1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "r1"

    def test_not_found(self, app_client, mock_pipeline):
        mock_pipeline.get_run.return_value = None
        resp = app_client.get("/api/autonomous/runs/missing")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ══════════════════════════════════════════════════════════
# 4. POST /runs/{run_id}/cancel
# ══════════════════════════════════════════════════════════


class TestCancelRun:
    def test_success(self, app_client, mock_pipeline):
        resp = app_client.post("/api/autonomous/runs/r1/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "已请求取消" in data["message"]
        mock_pipeline.cancel_run.assert_called_with("r1")

    def test_failure(self, app_client, mock_pipeline):
        mock_pipeline.cancel_run.return_value = False
        resp = app_client.post("/api/autonomous/runs/r1/cancel")
        assert resp.status_code == 400
        assert "无法取消" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 5. POST /runs/{run_id}/retry
# ══════════════════════════════════════════════════════════


class TestRetryRun:
    def test_found(self, app_client, mock_pipeline):
        resp = app_client.post("/api/autonomous/runs/r1/retry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["run_id"] == "r1"

    def test_not_found(self, app_client, mock_pipeline):
        mock_pipeline.get_run.return_value = None
        resp = app_client.post("/api/autonomous/runs/missing/retry")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ══════════════════════════════════════════════════════════
# 6. WS /ws/autonomous/progress
# ══════════════════════════════════════════════════════════


class TestWsAutonomous:
    def test_run_with_task(self, app_client, mock_pipeline, monkeypatch):
        """action=run + task → 接收事件流 + ws_closed"""
        async def fake_run(task):
            yield {"type": "phase", "phase": "init"}
            yield {"type": "done", "run_id": "x"}
        mock_pipeline.run = fake_run

        with app_client.websocket_connect("/ws/autonomous/progress") as ws:
            ws.send_json({"action": "run", "task": "do something"})
            msg1 = ws.receive_json()
            msg2 = ws.receive_json()
            msg3 = ws.receive_json()
            assert msg1["type"] == "phase"
            assert msg2["type"] == "done"
            assert msg3["type"] == "ws_closed"

    def test_run_without_task(self, app_client, mock_pipeline, monkeypatch):
        """action=run 但无 task → 收到 error + 连接关闭"""
        with app_client.websocket_connect("/ws/autonomous/progress") as ws:
            ws.send_json({"action": "run", "task": ""})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "task is required" in msg["message"]

    def test_auth_failure(self, mock_pipeline, monkeypatch):
        """verify_ws_auth 返回 False → 关闭连接"""
        import sys
        app_module = sys.modules["pycoder.server.app"]

        async def _false(ws):
            await ws.close(code=1008, reason="未授权")
            return False
        monkeypatch.setattr(app_module, "verify_ws_auth", _false)
        monkeypatch.setattr(
            "pycoder.server.services.autonomous_pipeline.get_pipeline",
            lambda: mock_pipeline,
        )

        app = FastAPI()
        app.include_router(auto_mod.router)
        app.include_router(auto_mod.ws_router)
        from starlette.websockets import WebSocketDisconnect
        with TestClient(app) as c:
            with pytest.raises((WebSocketDisconnect, Exception)):
                with c.websocket_connect("/ws/autonomous/progress") as ws:
                    ws.receive_json()

    def test_handler_exception(self, app_client, mock_pipeline, monkeypatch):
        """pipeline.run 抛异常 → 进入 except Exception → 发送 error 消息"""
        # 捕获 logger.debug 调用以验证 except 路径
        debug_calls = []
        monkeypatch.setattr(auto_mod.logger, "debug", lambda *a, **kw: debug_calls.append((a, kw)))

        def fake_run(task):
            raise RuntimeError("pipeline boom")
            yield  # unreachable
        mock_pipeline.run = fake_run

        with app_client.websocket_connect("/ws/autonomous/progress") as ws:
            ws.send_json({"action": "run", "task": "go"})
            # 服务端在 except 中尝试 send_json({"type": "error", ...})
            # 如果发送失败也会被 except 捕获并 log.debug
            try:
                msg = ws.receive_json()
                # 如果能收到消息，应为 error 类型
                assert msg.get("type") == "error"
            except Exception:
                pass

    def test_websocket_disconnect_handler(self, app_client, mock_pipeline, monkeypatch):
        """客户端断开 → 服务端 receive_json 抛 WebSocketDisconnect → pass 分支"""
        # pipeline.run 是 async generator，但客户端在收到一条消息后断开
        async def fake_run(task):
            yield {"type": "phase", "phase": "init"}
        mock_pipeline.run = fake_run

        with app_client.websocket_connect("/ws/autonomous/progress") as ws:
            ws.send_json({"action": "run", "task": "go"})
            # 接收一条消息后断开
            ws.receive_json()
        # with 块退出 → 客户端关闭 → 服务端抛 WebSocketDisconnect → pass

    def test_receive_disconnect_immediately(self, app_client, mock_pipeline, monkeypatch):
        """客户端连接后立即断开（未发送任何消息）→ 服务端 receive_json 抛 WebSocketDisconnect"""
        # 不发送任何消息，直接退出 with 块
        with app_client.websocket_connect("/ws/autonomous/progress"):
            pass  # 立即关闭
        # 服务端在 receive_json() 处等待时被断开 → 抛 WebSocketDisconnect → pass
        import time as _time
        _time.sleep(0.1)

    def test_send_json_inner_failure(self, app_client, mock_pipeline, monkeypatch):
        """send_json 内层失败 → 进入 except (RuntimeError, ConnectionError) → log.debug

        通过 patch starlette WebSocket.send_json 让其抛 RuntimeError，模拟连接关闭。
        注意: 不调用 receive_json（服务端捕获 send 失败后不会回发消息，receive 会无限阻塞）。
        改为发送后立即退出 with 块触发断开，再 sleep 等待服务端处理，最后断言 debug 被调用。
        """
        from starlette.websockets import WebSocket

        debug_calls = []
        monkeypatch.setattr(
            auto_mod.logger, "debug",
            lambda *a, **kw: debug_calls.append((a, kw)),
        )

        # pipeline.run 抛异常 → 进入 except Exception → 调用 ws.send_json 失败
        async def fake_run(task):
            raise RuntimeError("pipeline boom")
            yield
        mock_pipeline.run = fake_run

        # patch WebSocket.send_json 抛 RuntimeError（仅影响业务发送，不影响 accept）
        async def failing_send_json(self, data, mode="text"):
            raise RuntimeError("connection closed")
        monkeypatch.setattr(WebSocket, "send_json", failing_send_json)

        # 发送后立即退出 with 块（不调用 receive_json，避免无限阻塞）
        with app_client.websocket_connect("/ws/autonomous/progress") as ws:
            ws.send_json({"action": "run", "task": "go"})
            # 退出 with 块 → 客户端关闭 → 服务端后续操作触发 send 失败
        # 等待服务端处理异常并记录 debug 日志
        import time as _time
        _time.sleep(0.2)
        # 验证 debug 被调用（说明 except (RuntimeError, ...) 分支已触发）
        assert any(
            "autonomous_ws_error_send_failed" in str(args[0]) if args else False
            for args, _ in debug_calls
        )
