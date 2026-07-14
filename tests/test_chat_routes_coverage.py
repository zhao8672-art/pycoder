"""覆盖率测试: pycoder/server/routers/chat_routes.py

目标: 行覆盖率 >= 80%
覆盖端点: POST /api/chat
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import chat_routes


@pytest.fixture
def client():
    """创建仅包含 chat_routes 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(chat_routes.router)
    with TestClient(app) as c:
        yield c


def _make_mock_store(session_id="s-1", existing_model="auto"):
    """构造 mock SessionStore"""
    store = MagicMock()
    session = MagicMock(id=session_id, model=existing_model)
    store.create_session.return_value = session
    store.get_session.return_value = session
    store.update_session = MagicMock()
    return store


def _make_stream(events: list[dict]):
    """构造返回指定事件序列的异步生成器函数"""

    async def _stream(*args, **kwargs):
        for e in events:
            yield e

    return _stream


class TestChatHermes:
    """POST /api/chat — hermes 模式"""

    def test_hermes_success(self, client, monkeypatch):
        """hermes 模式正常完成"""
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "deepseek-chat")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(
            chat_routes,
            "_run_chat_stream",
            _make_stream([{"type": "done"}]),
        )

        resp = client.post("/api/chat", json={"message": "hello", "hermes": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["hermes_complete"] is True

    def test_hermes_error_event(self, client, monkeypatch):
        """hermes 模式收到 error 事件"""
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "deepseek-chat")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(
            chat_routes,
            "_run_chat_stream",
            _make_stream([{"type": "error", "message": "boom"}]),
        )

        resp = client.post("/api/chat", json={"message": "hello", "hermes": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "boom"


class TestChatNonHermes:
    """POST /api/chat — 非 hermes (流式收集 token)"""

    def test_token_and_done(self, client, monkeypatch):
        """收集 token 事件 + done 事件"""
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "qwen-coder")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(
            chat_routes,
            "_run_chat_stream",
            _make_stream([
                {"type": "token", "data": "Hello "},
                {"type": "token", "data": "World"},
                {"type": "done", "usage": {"total_tokens": 10}},
            ]),
        )

        resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "Hello World"
        assert data["model"] == "qwen-coder"
        assert data["usage"] == {"total_tokens": 10}

    def test_token_with_content_key(self, client, monkeypatch):
        """token 事件使用 content 字段"""
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "auto")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(
            chat_routes,
            "_run_chat_stream",
            _make_stream([
                {"type": "token", "content": "via_content"},
                {"type": "done", "usage": {}},
            ]),
        )

        resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 200
        assert resp.json()["reply"] == "via_content"

    def test_error_event_returns_error(self, client, monkeypatch):
        """非 hermes 模式收到 error 事件"""
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "auto")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(
            chat_routes,
            "_run_chat_stream",
            _make_stream([{"type": "error", "message": "stream failed"}]),
        )

        resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 200
        assert resp.json()["error"] == "stream failed"

    def test_empty_stream(self, client, monkeypatch):
        """空事件流"""
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "auto")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(chat_routes, "_run_chat_stream", _make_stream([]))

        resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == ""
        assert data["usage"] == {}


class TestChatSession:
    """POST /api/chat — 会话管理逻辑"""

    def test_existing_session_same_model(self, client, monkeypatch):
        """已有会话且 model 相同 → 不调用 update_session"""
        store = _make_mock_store(existing_model="auto")
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "auto")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: store)
        monkeypatch.setattr(chat_routes, "_run_chat_stream", _make_stream([{"type": "done", "usage": {}}]))

        resp = client.post("/api/chat", json={"message": "hi", "session_id": "s-1"})
        assert resp.status_code == 200
        store.update_session.assert_not_called()

    def test_existing_session_different_model(self, client, monkeypatch):
        """已有会话但 model 不同 → 调用 update_session"""
        store = _make_mock_store(existing_model="old-model")
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "new-model")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: store)
        monkeypatch.setattr(chat_routes, "_run_chat_stream", _make_stream([{"type": "done", "usage": {}}]))

        resp = client.post("/api/chat", json={"message": "hi", "session_id": "s-1"})
        assert resp.status_code == 200
        store.update_session.assert_called_once_with("s-1", model="new-model")

    def test_no_session_id_creates_new(self, client, monkeypatch):
        """无 session_id → 创建新会话"""
        store = _make_mock_store(session_id="new-session")
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "auto")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: store)
        monkeypatch.setattr(chat_routes, "_run_chat_stream", _make_stream([{"type": "done", "usage": {}}]))

        resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "new-session"
        store.create_session.assert_called_once()

    def test_session_id_with_none_session(self, client, monkeypatch):
        """提供 session_id 但会话不存在 → get_session 返回 None"""
        store = _make_mock_store()
        store.get_session.return_value = None
        monkeypatch.setattr(chat_routes, "_resolve_model", lambda m: "auto")
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: store)
        monkeypatch.setattr(chat_routes, "_run_chat_stream", _make_stream([{"type": "done", "usage": {}}]))

        resp = client.post("/api/chat", json={"message": "hi", "session_id": "ghost"})
        assert resp.status_code == 200
        store.update_session.assert_not_called()

    def test_explicit_model_passed_to_resolve(self, client, monkeypatch):
        """显式指定 model 传入 _resolve_model"""
        captured = {}

        def capture(req_model):
            captured["model"] = req_model
            return "glm-4"

        monkeypatch.setattr(chat_routes, "_resolve_model", capture)
        monkeypatch.setattr(chat_routes, "get_session_store", lambda: _make_mock_store())
        monkeypatch.setattr(chat_routes, "_run_chat_stream", _make_stream([{"type": "done", "usage": {}}]))

        resp = client.post("/api/chat", json={"message": "hi", "model": "glm-4"})
        assert resp.status_code == 200
        assert captured["model"] == "glm-4"
