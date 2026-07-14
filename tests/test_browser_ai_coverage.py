"""覆盖率测试: pycoder/server/routers/browser_ai.py

目标: 行覆盖率 >= 95%

覆盖端点:
    POST /api/browser/analyze     — AI 分析页面（含 errors/scripts/question 分支 + 异常）
    POST /api/browser/diagnose    — 错误诊断（无错误 / 有错误 / 异常）
    POST /api/browser/action      — 浏览器操作（navigate/exec-js/reload/screenshot/未知）
    GET  /api/browser/capabilities — 能力清单

覆盖辅助函数:
    _call_ai  — token / done / error 事件分支 + finally close
    _get_key  — 转发 _get_api_key_for_model

测试策略:
    - mock ChatBridge 的 chat_stream 异步生成器
    - mock _get_api_key_for_model 避免 KeyError
    - 直接调用 _call_ai 验证事件分支
    - TestClient 调用端点验证 HTTP 行为
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import browser_ai as browser_mod


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def app_client():
    """创建仅包含 browser 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(browser_mod.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_get_key(monkeypatch):
    """mock _get_api_key_for_model，避免实际密钥查找"""
    monkeypatch.setattr(
        "pycoder.server.chat_handler._get_api_key_for_model",
        lambda model: "fake-api-key",
    )


@pytest.fixture
def mock_bridge_factory(mock_get_key):
    """创建可配置的 mock ChatBridge 工厂

    返回 (factory, bridge_instance) 元组，测试可自定义 bridge 行为。
    """
    bridge = MagicMock()
    bridge.configure = MagicMock()
    bridge.config = MagicMock()
    bridge.config.system_prompt = ""
    bridge.config.max_tokens = 0
    bridge.close = AsyncMock()
    bridge.chat_stream = MagicMock()

    factory = MagicMock(return_value=bridge)
    return factory, bridge


# ══════════════════════════════════════════════════════════
# 1. _call_ai 辅助函数
# ══════════════════════════════════════════════════════════


class TestCallAi:
    """直接测试 _call_ai 的三个事件分支和 finally close"""

    async def test_token_events(self, mock_get_key, monkeypatch):
        """token 事件 → 累加 content"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.close = AsyncMock()

        async def fake_stream(msg):
            yield SimpleNamespace(event_type="token", content="Hello")
            yield SimpleNamespace(event_type="token", content=" World")

        bridge.chat_stream = fake_stream
        monkeypatch.setattr(browser_mod, "ChatBridge", lambda: bridge)

        result = await browser_mod._call_ai("sys", "user", "model")
        assert result == "Hello World"
        bridge.close.assert_awaited_once()

    async def test_done_event(self, mock_get_key, monkeypatch):
        """done 事件 → 使用 event.content（优先于累积的 token）"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.close = AsyncMock()

        async def fake_stream(msg):
            yield SimpleNamespace(event_type="token", content="partial")
            yield SimpleNamespace(event_type="done", content="final answer")

        bridge.chat_stream = fake_stream
        monkeypatch.setattr(browser_mod, "ChatBridge", lambda: bridge)

        result = await browser_mod._call_ai("sys", "user")
        assert result == "final answer"
        bridge.close.assert_awaited_once()

    async def test_done_event_with_none_content(self, mock_get_key, monkeypatch):
        """done 事件但 content 为 None → 回退到累积的 token"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.close = AsyncMock()

        async def fake_stream(msg):
            yield SimpleNamespace(event_type="token", content="accumulated")
            yield SimpleNamespace(event_type="done", content=None)

        bridge.chat_stream = fake_stream
        monkeypatch.setattr(browser_mod, "ChatBridge", lambda: bridge)

        result = await browser_mod._call_ai("sys", "user")
        assert result == "accumulated"

    async def test_error_event(self, mock_get_key, monkeypatch):
        """error 事件 → 返回错误前缀"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.close = AsyncMock()

        async def fake_stream(msg):
            yield SimpleNamespace(event_type="error", content="boom")

        bridge.chat_stream = fake_stream
        monkeypatch.setattr(browser_mod, "ChatBridge", lambda: bridge)

        result = await browser_mod._call_ai("sys", "user")
        assert "AI 分析错误" in result
        assert "boom" in result

    async def test_close_called_on_exception(self, mock_get_key, monkeypatch):
        """即使 chat_stream 抛异常，finally 仍应调用 bridge.close()"""
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()
        bridge.close = AsyncMock()

        async def fake_stream(msg):
            raise RuntimeError("stream crash")
            yield  # unreachable

        bridge.chat_stream = fake_stream
        monkeypatch.setattr(browser_mod, "ChatBridge", lambda: bridge)

        with pytest.raises(RuntimeError):
            await browser_mod._call_ai("sys", "user")
        # 关键: finally 块确保 close 被调用
        bridge.close.assert_awaited_once()


# ══════════════════════════════════════════════════════════
# 2. _get_key 辅助函数
# ══════════════════════════════════════════════════════════


class TestGetKey:
    def test_forwards_to_chat_handler(self, mock_get_key):
        """_get_key 应转发到 _get_api_key_for_model"""
        result = browser_mod._get_key("deepseek-chat")
        assert result == "fake-api-key"


# ══════════════════════════════════════════════════════════
# 3. POST /analyze
# ══════════════════════════════════════════════════════════


class TestAnalyze:
    def test_analyze_with_errors_and_scripts(self, app_client, mock_get_key, monkeypatch):
        """带 errors + scripts + question → 包含错误行和脚本行"""
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            # 验证 user_msg 包含错误和脚本信息
            assert "JS 错误" in user_msg
            assert "外部脚本" in user_msg
            assert "用户问题" in user_msg
            return "AI 分析结果"

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/analyze", json={
            "context": {
                "url": "http://example.com",
                "title": "测试页面",
                "body_text": "页面内容",
                "scripts": ["https://cdn.example.com/a.js"],
                "errors": [
                    {"type": "TypeError", "message": "x is undefined", "line": 10},
                ],
                "forms": 2,
                "images": 5,
                "links": 3,
                "body_size": 2048,
            },
            "question": "这个页面有什么问题？",
            "model": "deepseek-chat",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["analysis"] == "AI 分析结果"

    def test_analyze_without_errors_scripts_question(self, app_client, mock_get_key, monkeypatch):
        """无 errors / 无 scripts / 无 question → 不含错误行和脚本行"""
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            assert "JS 错误" not in user_msg
            assert "外部脚本" not in user_msg
            assert "用户问题" not in user_msg
            return "OK"

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/analyze", json={
            "context": {
                "url": "http://example.com",
                "title": "",
                "body_text": "text",
                "scripts": [],
                "errors": [],
            },
        })
        assert resp.status_code == 200
        assert resp.json()["analysis"] == "OK"

    def test_analyze_default_context(self, app_client, mock_get_key, monkeypatch):
        """不传 context → 使用默认 BrowserContext"""
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            return "default result"

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/analyze", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_analyze_exception(self, app_client, mock_get_key, monkeypatch):
        """_call_ai 抛异常 → 500 错误"""
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            raise RuntimeError("AI service down")

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/analyze", json={})
        assert resp.status_code == 500
        assert "分析失败" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 4. POST /diagnose
# ══════════════════════════════════════════════════════════


class TestDiagnose:
    def test_no_errors(self, app_client, mock_get_key, monkeypatch):
        """无错误 → 返回正常消息，不调用 AI"""
        called = []
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            called.append(True)
            return "should not be called"

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/diagnose", json={
            "errors": [],
            "url": "http://example.com",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "未检测到 JS 错误" in resp.json()["diagnosis"]
        assert len(called) == 0  # 不应调用 AI

    def test_with_errors(self, app_client, mock_get_key, monkeypatch):
        """有错误 → 调用 AI 诊断"""
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            assert "TypeError" in user_msg
            assert "ReferenceError" in user_msg
            return "诊断结果：修复代码..."

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/diagnose", json={
            "errors": [
                {"type": "TypeError", "message": "x is undefined", "line": 10},
                {"type": "ReferenceError", "message": "y is not defined", "line": 20},
            ],
            "url": "http://example.com",
        })
        assert resp.status_code == 200
        assert resp.json()["diagnosis"] == "诊断结果：修复代码..."

    def test_diagnose_exception(self, app_client, mock_get_key, monkeypatch):
        """_call_ai 抛异常 → 500"""
        async def fake_call_ai(sys_prompt, user_msg, model="deepseek-chat"):
            raise RuntimeError("AI crash")

        monkeypatch.setattr(browser_mod, "_call_ai", fake_call_ai)

        resp = app_client.post("/api/browser/diagnose", json={
            "errors": [{"type": "Error", "message": "boom", "line": 1}],
        })
        assert resp.status_code == 500
        assert "诊断失败" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 5. POST /action
# ══════════════════════════════════════════════════════════


class TestBrowserAction:
    def test_navigate(self, app_client):
        """navigate → 返回导航 IPC"""
        resp = app_client.post("/api/browser/action", json={
            "action": "navigate",
            "url": "https://docs.python.org/3/",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["action"] == "navigate"
        assert data["electron_ipc"] == "browser:navigate"
        assert data["payload"]["url"] == "https://docs.python.org/3/"

    def test_exec_js(self, app_client):
        """exec-js → 返回执行 JS IPC"""
        resp = app_client.post("/api/browser/action", json={
            "action": "exec-js",
            "code": "document.title = 'hello'",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "exec-js"
        assert data["electron_ipc"] == "browser:exec-js"
        assert data["payload"]["code"] == "document.title = 'hello'"

    def test_reload(self, app_client):
        """reload → 返回刷新 IPC"""
        resp = app_client.post("/api/browser/action", json={
            "action": "reload",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "reload"
        assert data["electron_ipc"] == "browser:reload"

    def test_screenshot(self, app_client):
        """screenshot → 返回截图 IPC"""
        resp = app_client.post("/api/browser/action", json={
            "action": "screenshot",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "screenshot"
        assert data["electron_ipc"] == "browser:screenshot"

    def test_unknown_action(self, app_client):
        """未知 action → 400 错误"""
        resp = app_client.post("/api/browser/action", json={
            "action": "unknown-cmd",
        })
        assert resp.status_code == 400
        assert "未知操作" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 6. GET /capabilities
# ══════════════════════════════════════════════════════════


class TestCapabilities:
    def test_returns_capability_list(self, app_client):
        """返回能力清单结构"""
        resp = app_client.get("/api/browser/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        caps = data["capabilities"]
        assert "browser_inspect" in caps
        assert "browser_control" in caps
        assert "browser_ai_analyze" in caps
        # 验证内层结构
        assert "tools" in caps["browser_inspect"]
        assert "tools" in caps["browser_control"]
        assert "endpoints" in caps["browser_ai_analyze"]
