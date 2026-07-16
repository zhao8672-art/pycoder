"""
多平台消息网关 API 路由单元测试 — 覆盖 gateway_api.py 所有端点

测试范围:
  - GET  /api/gateway/platforms              — 列出平台
  - POST /api/gateway/send                   — 发送消息
  - GET  /api/gateway/sessions               — 列出会话
  - GET  /api/gateway/sessions/{session_id}  — 获取会话详情
  - POST /api/gateway/sessions/{session_id}/switch — 切换会话
  - WebSocket /ws/gateway                    — WebSocket 实时推送
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.gateway import (
    GatewayMessage,
    MessageGateway,
    PlatformAdapter,
)


# ── 辅助函数 ──────────────────────────────────────────────


class _MockAdapter(PlatformAdapter):
    """测试用模拟平台适配器"""

    def __init__(self, platform_name: str = "mock") -> None:
        super().__init__()
        self._platform_name = platform_name

    @property
    def platform(self) -> str:
        return self._platform_name

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send_message(self, target: str, content: str) -> bool:
        return True

    async def normalize_message(self, raw_message: object) -> GatewayMessage:
        return GatewayMessage(
            platform=self.platform,
            user_id="test_user",
            session_id="test_session",
            content=str(raw_message),
        )


def _make_mock_session(
    session_id: str = "sess-001",
    platform: str = "telegram",
    user_id: str = "user-001",
) -> MagicMock:
    """创建模拟的 Session 对象"""
    session = MagicMock()
    session.session_id = session_id
    session.platform = platform
    session.user_id = user_id
    session.created_at = time.time()
    session.last_activity = time.time()
    session.messages = []
    session.context = {}
    session.get_recent_messages.return_value = []
    return session


def _make_mock_session_manager(sessions: dict | None = None) -> MagicMock:
    """创建模拟的 SessionManager"""
    sm = MagicMock()
    sm._sessions = sessions or {}
    sm._active_session_id = None
    return sm


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> MagicMock:
    """创建模拟的 MessageGateway"""
    gw = MagicMock(spec=MessageGateway)
    gw.available_platforms = ["telegram", "discord", "cli"]
    gw.is_running = False
    gw.get_adapter.return_value = None
    return gw


@pytest.fixture
def client_with_gw(mock_gateway: MagicMock) -> TestClient:
    """注入模拟网关的 TestClient"""
    from pycoder.server.routers import gateway_api

    # 保存原始状态
    orig_gw = gateway_api._gateway
    orig_initialized = gateway_api._initialized
    orig_ws = dict(gateway_api._ws_clients)

    gateway_api._gateway = mock_gateway
    gateway_api._initialized = True
    gateway_api._ws_clients.clear()

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    gateway_api._gateway = orig_gw
    gateway_api._initialized = orig_initialized
    gateway_api._ws_clients = orig_ws


# ── GET /api/gateway/platforms 测试 ───────────────────────


class TestListPlatforms:
    """列出平台端点"""

    def test_list_platforms_success(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试列出已注册平台"""
        mock_adapter = _MockAdapter("telegram")
        mock_adapter._running = True
        mock_gateway.get_adapter.return_value = mock_adapter

        resp = client_with_gw.get("/api/gateway/platforms")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        platforms = {p["name"] for p in data}
        assert "telegram" in platforms
        assert "discord" in platforms

    def test_list_platforms_empty(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试无已注册平台"""
        mock_gateway.available_platforms = []

        with patch("pycoder.server.routers.gateway_api.get_all_adapters", return_value=[]):
            resp = client_with_gw.get("/api/gateway/platforms")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_list_platforms_with_status(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试平台状态信息"""
        running_adapter = _MockAdapter("telegram")
        running_adapter._running = True
        stopped_adapter = _MockAdapter("discord")
        stopped_adapter._running = False

        def _get_adapter(name: str) -> _MockAdapter | None:
            if name == "telegram":
                return running_adapter
            if name == "discord":
                return stopped_adapter
            return None

        mock_gateway.get_adapter.side_effect = _get_adapter

        resp = client_with_gw.get("/api/gateway/platforms")
        assert resp.status_code == 200
        data = resp.json()
        for p in data:
            if p["name"] == "telegram":
                assert p["status"] == "running"
            elif p["name"] == "discord":
                assert p["status"] == "stopped"

    def test_list_platforms_get_all_adapters_error(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试获取适配器列表出错时不影响已注册平台"""
        mock_gateway.available_platforms = ["telegram"]
        mock_adapter = _MockAdapter("telegram")
        mock_gateway.get_adapter.return_value = mock_adapter

        with patch(
            "pycoder.server.routers.gateway_api.get_all_adapters",
            side_effect=Exception("模拟错误"),
        ):
            resp = client_with_gw.get("/api/gateway/platforms")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "telegram"


# ── POST /api/gateway/send 测试 ───────────────────────────


class TestSendMessage:
    """发送消息端点"""

    def test_send_message_success(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试成功发送消息"""
        mock_gateway.send_message = AsyncMock(return_value=True)

        resp = client_with_gw.post(
            "/api/gateway/send",
            json={
                "platform": "telegram",
                "user_id": "user_123",
                "content": "你好世界",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["platform"] == "telegram"
        assert data["target"] == "user_123"
        assert "已发送" in data["message"]

    def test_send_message_failure(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试发送失败"""
        mock_gateway.send_message = AsyncMock(return_value=False)

        resp = client_with_gw.post(
            "/api/gateway/send",
            json={
                "platform": "telegram",
                "user_id": "user_123",
                "content": "你好",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "失败" in data["message"]

    def test_send_message_unavailable_platform(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试发送到不可用平台返回 400"""
        mock_gateway.available_platforms = ["telegram"]

        resp = client_with_gw.post(
            "/api/gateway/send",
            json={
                "platform": "slack",
                "user_id": "user_123",
                "content": "你好",
            },
        )
        assert resp.status_code == 400
        assert "slack" in resp.json()["detail"]

    def test_send_message_empty_platform(self, client_with_gw: TestClient) -> None:
        """测试空平台名"""
        resp = client_with_gw.post(
            "/api/gateway/send",
            json={
                "platform": "",
                "user_id": "user_123",
                "content": "你好",
            },
        )
        assert resp.status_code == 422  # Pydantic 验证失败

    def test_send_message_empty_content(self, client_with_gw: TestClient) -> None:
        """测试空消息内容"""
        resp = client_with_gw.post(
            "/api/gateway/send",
            json={
                "platform": "telegram",
                "user_id": "user_123",
                "content": "",
            },
        )
        assert resp.status_code == 422  # Pydantic 验证失败


# ── GET /api/gateway/sessions 测试 ────────────────────────


class TestListSessions:
    """列出会话端点"""

    def test_list_sessions_success(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试列出活跃会话"""
        session = _make_mock_session("sess-001", "telegram", "user-001")
        sm = _make_mock_session_manager({("telegram", "user-001"): session})
        mock_gateway._session_manager = sm

        resp = client_with_gw.get("/api/gateway/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["session_id"] == "sess-001"
        assert data["sessions"][0]["platform"] == "telegram"

    def test_list_sessions_empty(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试无会话时返回空列表"""
        sm = _make_mock_session_manager({})
        mock_gateway._session_manager = sm

        resp = client_with_gw.get("/api/gateway/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["sessions"] == []

    def test_list_sessions_no_manager(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试无会话管理器时返回空列表"""
        mock_gateway._session_manager = None

        resp = client_with_gw.get("/api/gateway/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["sessions"] == []

    def test_list_sessions_with_active(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试活跃会话标记"""
        session = _make_mock_session("active-sess", "cli", "cli_user")
        sm = _make_mock_session_manager({("cli", "cli_user"): session})
        sm._active_session_id = "active-sess"
        mock_gateway._session_manager = sm

        resp = client_with_gw.get("/api/gateway/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_session_id"] == "active-sess"
        assert data["sessions"][0]["is_active"] is True


# ── GET /api/gateway/sessions/{session_id} 测试 ───────────


class TestGetSession:
    """获取会话详情端点"""

    def test_get_session_success(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试获取存在的会话详情"""
        session = _make_mock_session("sess-001", "telegram", "user-001")
        sm = _make_mock_session_manager({("telegram", "user-001"): session})
        mock_gateway._session_manager = sm

        resp = client_with_gw.get("/api/gateway/sessions/sess-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-001"
        assert data["platform"] == "telegram"
        assert data["user_id"] == "user-001"
        assert "messages" in data

    def test_get_session_not_found(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试获取不存在的会话返回 404"""
        sm = _make_mock_session_manager({})
        mock_gateway._session_manager = sm

        resp = client_with_gw.get("/api/gateway/sessions/nonexistent")
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_get_session_no_manager(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试无会话管理器返回 404"""
        mock_gateway._session_manager = None

        resp = client_with_gw.get("/api/gateway/sessions/any-id")
        assert resp.status_code == 404
        assert "尚未初始化" in resp.json()["detail"]


# ── POST /api/gateway/sessions/{session_id}/switch 测试 ───


class TestSwitchSession:
    """切换会话端点"""

    def test_switch_session_success(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试成功切换会话"""
        session = _make_mock_session("sess-001", "telegram", "user-001")
        sm = _make_mock_session_manager({("telegram", "user-001"): session})
        mock_gateway._session_manager = sm

        resp = client_with_gw.post("/api/gateway/sessions/sess-001/switch")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["session_id"] == "sess-001"
        assert data["platform"] == "telegram"
        assert data["user_id"] == "user-001"

    def test_switch_session_not_found(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试切换不存在的会话返回 404"""
        sm = _make_mock_session_manager({})
        mock_gateway._session_manager = sm

        resp = client_with_gw.post("/api/gateway/sessions/nonexistent/switch")
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_switch_session_no_manager(self, client_with_gw: TestClient, mock_gateway: MagicMock) -> None:
        """测试无会话管理器返回 404"""
        mock_gateway._session_manager = None

        resp = client_with_gw.post("/api/gateway/sessions/any-id/switch")
        assert resp.status_code == 404
        assert "尚未初始化" in resp.json()["detail"]


# ── WebSocket /ws/gateway 测试 ────────────────────────────


class TestGatewayWebSocket:
    """WebSocket 端点测试"""

    def test_ws_connect_without_auth(self, mock_gateway: MagicMock) -> None:
        """测试 WebSocket 连接（无 API Key 时默认放行）"""
        from pycoder.server.routers import gateway_api

        # 保存状态
        orig_gw = gateway_api._gateway
        orig_initialized = gateway_api._initialized
        gateway_api._gateway = mock_gateway
        gateway_api._initialized = True

        from pycoder.server.app import app

        # 无 API Key 时，verify_ws_auth 默认放行
        with TestClient(app) as client:
            with client.websocket_connect("/ws/gateway") as ws:
                welcome = ws.receive_json()
                assert welcome["type"] == "connected"

        gateway_api._gateway = orig_gw
        gateway_api._initialized = orig_initialized

    def test_ws_ping_pong(self, mock_gateway: MagicMock) -> None:
        """测试 WebSocket ping/pong 消息"""
        from pycoder.server.routers import gateway_api

        orig_gw = gateway_api._gateway
        orig_initialized = gateway_api._initialized
        gateway_api._gateway = mock_gateway
        gateway_api._initialized = True

        with patch("pycoder.server.app.verify_ws_auth", return_value=True):
            from pycoder.server.app import app

            with TestClient(app) as client:
                with client.websocket_connect("/ws/gateway") as ws:
                    # 接收欢迎消息
                    welcome = ws.receive_json()
                    assert welcome["type"] == "connected"
                    assert "platforms" in welcome

                    # 发送 ping
                    ws.send_json({"type": "ping"})
                    pong = ws.receive_json()
                    assert pong["type"] == "pong"

        gateway_api._gateway = orig_gw
        gateway_api._initialized = orig_initialized

    def test_ws_get_platforms(self, mock_gateway: MagicMock) -> None:
        """测试通过 WebSocket 获取平台列表"""
        mock_adapter = _MockAdapter("telegram")
        mock_adapter._running = True
        mock_gateway.get_adapter.return_value = mock_adapter

        from pycoder.server.routers import gateway_api

        orig_gw = gateway_api._gateway
        orig_initialized = gateway_api._initialized
        gateway_api._gateway = mock_gateway
        gateway_api._initialized = True

        with patch("pycoder.server.app.verify_ws_auth", return_value=True):
            from pycoder.server.app import app

            with TestClient(app) as client:
                with client.websocket_connect("/ws/gateway") as ws:
                    ws.receive_json()  # 跳过欢迎消息

                    ws.send_json({"type": "get_platforms"})
                    response = ws.receive_json()
                    assert response["type"] == "platforms"
                    assert "platforms" in response

        gateway_api._gateway = orig_gw
        gateway_api._initialized = orig_initialized

    def test_ws_get_sessions(self, mock_gateway: MagicMock) -> None:
        """测试通过 WebSocket 获取会话列表"""
        session = _make_mock_session("ws-sess", "cli", "ws-user")
        sm = _make_mock_session_manager({("cli", "ws-user"): session})
        mock_gateway._session_manager = sm

        from pycoder.server.routers import gateway_api

        orig_gw = gateway_api._gateway
        orig_initialized = gateway_api._initialized
        gateway_api._gateway = mock_gateway
        gateway_api._initialized = True

        with patch("pycoder.server.app.verify_ws_auth", return_value=True):
            from pycoder.server.app import app

            with TestClient(app) as client:
                with client.websocket_connect("/ws/gateway") as ws:
                    ws.receive_json()  # 跳过欢迎消息

                    ws.send_json({"type": "get_sessions"})
                    response = ws.receive_json()
                    assert response["type"] == "sessions"
                    assert response["total"] == 1

        gateway_api._gateway = orig_gw
        gateway_api._initialized = orig_initialized

    def test_ws_unknown_message_type(self, mock_gateway: MagicMock) -> None:
        """测试 WebSocket 未知消息类型"""
        from pycoder.server.routers import gateway_api

        orig_gw = gateway_api._gateway
        orig_initialized = gateway_api._initialized
        gateway_api._gateway = mock_gateway
        gateway_api._initialized = True

        with patch("pycoder.server.app.verify_ws_auth", return_value=True):
            from pycoder.server.app import app

            with TestClient(app) as client:
                with client.websocket_connect("/ws/gateway") as ws:
                    ws.receive_json()  # 跳过欢迎消息

                    ws.send_json({"type": "unknown_command"})
                    response = ws.receive_json()
                    assert response["type"] == "unknown"

        gateway_api._gateway = orig_gw
        gateway_api._initialized = orig_initialized

    def test_broadcast_gateway_event(self, mock_gateway: MagicMock) -> None:
        """测试广播网关事件辅助函数"""
        from pycoder.server.routers import gateway_api

        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock()
        gateway_api._ws_clients["test_client"] = mock_ws

        async def _run() -> None:
            await gateway_api.broadcast_gateway_event(
                "test_event", {"key": "value"}
            )

        import asyncio
        asyncio.run(_run())

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "test_event"
        assert call_args["data"]["key"] == "value"

        # 清理
        gateway_api._ws_clients.pop("test_client", None)

    def test_broadcast_disconnected_client(self, mock_gateway: MagicMock) -> None:
        """测试广播时断开连接的客户端被自动移除"""
        from pycoder.server.routers import gateway_api

        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock(side_effect=Exception("disconnected"))
        gateway_api._ws_clients["bad_client"] = mock_ws

        async def _run() -> None:
            await gateway_api.broadcast_gateway_event("event", {})

        import asyncio
        asyncio.run(_run())

        # 断开的客户端应被移除
        assert "bad_client" not in gateway_api._ws_clients