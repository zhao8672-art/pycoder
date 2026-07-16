"""
测试 pycoder.gateway 多平台消息网关模块

覆盖范围:
- MessageGateway 初始化与平台注册/注销
- 各平台适配器 normalize_message 方法
- SessionManager 会话创建/获取/删除/隔离
- MessageRouter 路由逻辑
- 并发会话访问
- 错误处理
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.gateway import (
    GatewayMessage,
    MessageGateway,
    PlatformAdapter,
    get_gateway,
)
from pycoder.gateway.adapters.cli import CLIAdapter
from pycoder.gateway.adapters.discord import DiscordAdapter
from pycoder.gateway.adapters.slack import SlackAdapter
from pycoder.gateway.adapters.telegram import TelegramAdapter
from pycoder.gateway.message_router import MessageRouter
from pycoder.gateway.session_manager import Session, SessionManager


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════


class _MockAdapter(PlatformAdapter):
    """测试用模拟适配器"""

    def __init__(self, platform_name: str = "mock") -> None:
        super().__init__()
        self._platform_name = platform_name
        self._sent_messages: list[tuple[str, str]] = []
        self._normalized_messages: list[GatewayMessage] = []

    @property
    def platform(self) -> str:
        return self._platform_name

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send_message(self, target: str, content: str) -> bool:
        self._sent_messages.append((target, content))
        return True

    async def normalize_message(self, raw_message: object) -> GatewayMessage:
        msg = GatewayMessage(
            platform=self.platform,
            user_id=str(getattr(raw_message, "user_id", "unknown")),
            session_id=str(getattr(raw_message, "session_id", "mock_session")),
            content=str(raw_message),
            message_type="text",
        )
        self._normalized_messages.append(msg)
        return msg


@pytest.fixture
def gateway() -> MessageGateway:
    """创建干净的消息网关实例"""
    return MessageGateway()


@pytest.fixture
def mock_adapter() -> _MockAdapter:
    """创建模拟适配器"""
    return _MockAdapter()


@pytest.fixture
def session_manager() -> SessionManager:
    """创建会话管理器"""
    return SessionManager()


@pytest.fixture
def router() -> MessageRouter:
    """创建消息路由器"""
    return MessageRouter()


@pytest.fixture
def sample_gateway_msg() -> GatewayMessage:
    """创建示例网关消息"""
    return GatewayMessage(
        platform="telegram",
        user_id="user_123",
        session_id="tg_456",
        content="你好，世界！",
        message_type="text",
    )


# ═══════════════════════════════════════════════
# GatewayMessage 测试
# ═══════════════════════════════════════════════


class TestGatewayMessage:
    """GatewayMessage 数据类测试"""

    def test_create_message(self) -> None:
        """测试创建消息"""
        msg = GatewayMessage(
            platform="telegram",
            user_id="user_1",
            session_id="sess_1",
            content="hello",
        )
        assert msg.platform == "telegram"
        assert msg.user_id == "user_1"
        assert msg.session_id == "sess_1"
        assert msg.content == "hello"
        assert msg.message_type == "text"
        assert isinstance(msg.timestamp, float)

    def test_to_dict(self) -> None:
        """测试序列化为字典"""
        msg = GatewayMessage(
            platform="discord",
            user_id="u1",
            session_id="s1",
            content="测试",
            message_type="command",
            metadata={"key": "value"},
        )
        d = msg.to_dict()
        assert d["platform"] == "discord"
        assert d["user_id"] == "u1"
        assert d["content"] == "测试"
        assert d["message_type"] == "command"
        assert d["metadata"]["key"] == "value"

    def test_from_dict(self) -> None:
        """测试从字典还原"""
        data = {
            "platform": "slack",
            "user_id": "u2",
            "session_id": "s2",
            "content": "hello",
            "message_type": "text",
            "timestamp": 1234567890.0,
            "metadata": {"a": 1},
        }
        msg = GatewayMessage.from_dict(data)
        assert msg.platform == "slack"
        assert msg.user_id == "u2"
        assert msg.timestamp == 1234567890.0
        assert msg.metadata["a"] == 1

    def test_from_dict_missing_fields(self) -> None:
        """测试从字典还原，缺失可选字段"""
        data = {
            "platform": "cli",
            "user_id": "u3",
            "session_id": "s3",
            "content": "test",
        }
        msg = GatewayMessage.from_dict(data)
        assert msg.message_type == "text"
        assert isinstance(msg.timestamp, float)
        assert msg.metadata == {}

    def test_default_values(self) -> None:
        """测试默认值"""
        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="c"
        )
        assert msg.message_type == "text"
        assert msg.metadata == {}


# ═══════════════════════════════════════════════
# MessageGateway 测试
# ═══════════════════════════════════════════════


class TestMessageGateway:
    """MessageGateway 核心功能测试"""

    def test_initialization(self, gateway: MessageGateway) -> None:
        """测试网关初始化"""
        assert gateway.is_running is False
        assert gateway.available_platforms == []
        assert gateway.get_adapter("telegram") is None

    def test_register_adapter(self, gateway: MessageGateway, mock_adapter: _MockAdapter) -> None:
        """测试注册适配器"""
        gateway.register_adapter(mock_adapter)
        assert "mock" in gateway.available_platforms
        assert gateway.get_adapter("mock") is mock_adapter

    def test_register_multiple_adapters(self, gateway: MessageGateway) -> None:
        """测试注册多个适配器"""
        a1 = _MockAdapter("p1")
        a2 = _MockAdapter("p2")
        a3 = _MockAdapter("p3")
        gateway.register_adapter(a1)
        gateway.register_adapter(a2)
        gateway.register_adapter(a3)
        assert gateway.available_platforms == ["p1", "p2", "p3"]

    def test_register_duplicate_adapter(self, gateway: MessageGateway) -> None:
        """测试重复注册同平台适配器（覆盖）"""
        a1 = _MockAdapter("mock")
        a2 = _MockAdapter("mock")
        gateway.register_adapter(a1)
        gateway.register_adapter(a2)
        assert gateway.get_adapter("mock") is a2
        assert len(gateway.available_platforms) == 1

    def test_unregister_adapter(self, gateway: MessageGateway, mock_adapter: _MockAdapter) -> None:
        """测试注销适配器"""
        gateway.register_adapter(mock_adapter)
        assert gateway.unregister_adapter("mock") is True
        assert "mock" not in gateway.available_platforms

    def test_unregister_nonexistent(self, gateway: MessageGateway) -> None:
        """测试注销不存在的适配器"""
        assert gateway.unregister_adapter("nonexistent") is False

    @pytest.mark.asyncio
    async def test_start_stop(self, gateway: MessageGateway) -> None:
        """测试网关启动和停止"""
        adapter = _MockAdapter("test")
        gateway.register_adapter(adapter)
        await gateway.start()
        assert gateway.is_running is True
        assert adapter.is_running is True
        await gateway.stop()
        assert gateway.is_running is False
        assert adapter.is_running is False

    @pytest.mark.asyncio
    async def test_start_already_running(self, gateway: MessageGateway) -> None:
        """测试重复启动"""
        adapter = _MockAdapter("test")
        gateway.register_adapter(adapter)
        await gateway.start()
        await gateway.start()  # 不应报错
        assert gateway.is_running is True
        await gateway.stop()

    @pytest.mark.asyncio
    async def test_send_message(self, gateway: MessageGateway) -> None:
        """测试通过网关发送消息"""
        adapter = _MockAdapter("test")
        gateway.register_adapter(adapter)
        result = await gateway.send_message("test", "user_1", "hello")
        assert result is True
        assert ("user_1", "hello") in adapter._sent_messages

    @pytest.mark.asyncio
    async def test_send_message_missing_platform(self, gateway: MessageGateway) -> None:
        """测试向未注册平台发送消息"""
        result = await gateway.send_message("nonexistent", "user_1", "hello")
        assert result is False

    def test_switch_session(self, gateway: MessageGateway) -> None:
        """测试切换活跃会话"""
        info = gateway.switch_session("telegram", "user_99")
        assert info["platform"] == "telegram"
        assert info["user_id"] == "user_99"

    def test_get_session_info_none(self, gateway: MessageGateway) -> None:
        """测试获取不存在的会话信息"""
        info = gateway.get_session_info("telegram", "nonexistent")
        assert info is None

    def test_get_session_info_after_switch(self, gateway: MessageGateway) -> None:
        """测试切换会话后获取信息"""
        gateway.switch_session("discord", "user_x")
        info = gateway.get_session_info("discord", "user_x")
        assert info is not None
        assert info["platform"] == "discord"
        assert info["user_id"] == "user_x"

    def test_get_gateway_singleton(self) -> None:
        """测试网关单例"""
        g1 = get_gateway()
        g2 = get_gateway()
        assert g1 is g2


# ═══════════════════════════════════════════════
# MessageRouter 测试
# ═══════════════════════════════════════════════


class TestMessageRouter:
    """MessageRouter 路由逻辑测试"""

    def test_is_command(self, router: MessageRouter) -> None:
        """测试命令识别"""
        assert router._is_command("/help") is True
        assert router._is_command("!status") is True
        assert router._is_command(".config") is True
        assert router._is_command("hello") is False
        assert router._is_command("  /help  ") is True

    def test_parse_command(self, router: MessageRouter) -> None:
        """测试命令解析"""
        cmd, args = router._parse_command("/help me please")
        assert cmd == "help"
        assert args == "me please"

        cmd, args = router._parse_command("!status")
        assert cmd == "status"
        assert args == ""

    @pytest.mark.asyncio
    async def test_route_command_help(self, router: MessageRouter) -> None:
        """测试路由 /help 命令"""
        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="/help"
        )
        result = await router.route_message(msg)
        assert result is not None
        assert "帮助" in result

    @pytest.mark.asyncio
    async def test_route_command_platforms(self, router: MessageRouter) -> None:
        """测试路由 /platforms 命令"""
        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="/platforms"
        )
        result = await router.route_message(msg)
        assert result is not None
        assert "平台" in result

    @pytest.mark.asyncio
    async def test_route_command_info(self, router: MessageRouter) -> None:
        """测试路由 /info 命令"""
        msg = GatewayMessage(
            platform="telegram",
            user_id="u",
            session_id="s",
            content="/info",
        )
        result = await router.route_message(msg)
        assert result is not None
        assert "会话" in result

    @pytest.mark.asyncio
    async def test_route_command_unknown(self, router: MessageRouter) -> None:
        """测试未知命令"""
        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="/unknown_cmd"
        )
        result = await router.route_message(msg)
        assert result is not None
        assert "未知命令" in result

    @pytest.mark.asyncio
    async def test_route_conversation_without_ai(self, router: MessageRouter) -> None:
        """测试对话消息（无 AI 大脑）"""
        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="你好"
        )
        result = await router.route_message(msg)
        assert result is not None
        assert "收到您的消息" in result

    @pytest.mark.asyncio
    async def test_route_with_ai_brain(self, router: MessageRouter) -> None:
        """测试通过 AI 大脑处理命令"""
        mock_brain = MagicMock()
        mock_brain.process_message = AsyncMock(return_value="AI 响应")
        router.set_ai_brain(mock_brain)

        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="/custom"
        )
        result = await router.route_message(msg)
        assert result == "AI 响应"
        mock_brain.process_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_conversation_with_ai(self, router: MessageRouter) -> None:
        """测试对话消息通过 AI 大脑处理"""
        mock_brain = MagicMock()
        mock_brain.process_message = AsyncMock(return_value="你好，有什么可以帮你的？")
        router.set_ai_brain(mock_brain)

        msg = GatewayMessage(
            platform="cli", user_id="u", session_id="s", content="你好啊"
        )
        result = await router.route_message(msg)
        assert result == "你好，有什么可以帮你的？"

    def test_build_context(self, router: MessageRouter) -> None:
        """测试构建上下文"""
        msg = GatewayMessage(
            platform="telegram",
            user_id="user_1",
            session_id="sess_1",
            content="hello",
            message_type="text",
        )
        ctx = router._build_context(msg)
        assert ctx["platform"] == "telegram"
        assert ctx["user_id"] == "user_1"
        assert ctx["session_id"] == "sess_1"
        assert "recent_messages" in ctx
        assert "shared_context" in ctx

    def test_build_help_message(self, router: MessageRouter) -> None:
        """测试构建帮助消息"""
        msg = router._build_help_message()
        assert "PyCoder" in msg
        assert "/help" in msg
        assert "/platforms" in msg
        assert "/info" in msg


# ═══════════════════════════════════════════════
# SessionManager 测试
# ═══════════════════════════════════════════════


class TestSessionManager:
    """SessionManager 会话管理测试"""

    def test_create_session(self, session_manager: SessionManager) -> None:
        """测试创建会话"""
        session = session_manager.get_or_create_session("telegram", "user_1")
        assert session.platform == "telegram"
        assert session.user_id == "user_1"
        assert session.session_id != ""
        assert isinstance(session.created_at, float)

    def test_get_existing_session(self, session_manager: SessionManager) -> None:
        """测试获取已存在的会话"""
        s1 = session_manager.get_or_create_session("telegram", "user_1")
        s2 = session_manager.get_or_create_session("telegram", "user_1")
        assert s1 is s2
        assert s1.session_id == s2.session_id

    def test_get_session_by_key(self, session_manager: SessionManager) -> None:
        """测试通过 platform+user_id 获取会话"""
        session_manager.get_or_create_session("discord", "user_x")
        s = session_manager.get_session("discord", "user_x")
        assert s is not None
        assert s.platform == "discord"
        assert s.user_id == "user_x"

    def test_get_nonexistent_session(self, session_manager: SessionManager) -> None:
        """测试获取不存在的会话"""
        s = session_manager.get_session("telegram", "nonexistent")
        assert s is None

    def test_session_isolation_platform(self, session_manager: SessionManager) -> None:
        """测试会话平台隔离：同一用户不同平台不共享会话"""
        s_tg = session_manager.get_or_create_session("telegram", "user_1")
        s_dc = session_manager.get_or_create_session("discord", "user_1")
        assert s_tg is not s_dc
        assert s_tg.session_id != s_dc.session_id
        assert s_tg.platform != s_dc.platform

    def test_session_isolation_user(self, session_manager: SessionManager) -> None:
        """测试会话用户隔离：同一平台不同用户不共享会话"""
        s1 = session_manager.get_or_create_session("telegram", "user_a")
        s2 = session_manager.get_or_create_session("telegram", "user_b")
        assert s1 is not s2
        assert s1.user_id != s2.user_id

    def test_close_session(self, session_manager: SessionManager) -> None:
        """测试关闭会话"""
        session_manager.get_or_create_session("telegram", "user_1")
        assert session_manager.session_count == 1
        result = session_manager.close_session("telegram", "user_1")
        assert result is True
        assert session_manager.session_count == 0

    def test_close_nonexistent_session(self, session_manager: SessionManager) -> None:
        """测试关闭不存在的会话"""
        result = session_manager.close_session("telegram", "nobody")
        assert result is False

    def test_session_count(self, session_manager: SessionManager) -> None:
        """测试会话计数"""
        assert session_manager.session_count == 0
        session_manager.get_or_create_session("tg", "u1")
        session_manager.get_or_create_session("tg", "u2")
        session_manager.get_or_create_session("dc", "u1")
        assert session_manager.session_count == 3

    def test_get_stats(self, session_manager: SessionManager) -> None:
        """测试获取统计信息"""
        session_manager.get_or_create_session("telegram", "u1")
        session_manager.get_or_create_session("telegram", "u2")
        session_manager.get_or_create_session("discord", "u1")

        stats = session_manager.get_stats()
        assert stats["total_sessions"] == 3
        assert stats["platforms"]["telegram"] == 2
        assert stats["platforms"]["discord"] == 1

    def test_active_session(self, session_manager: SessionManager) -> None:
        """测试活跃会话"""
        s = session_manager.get_or_create_session("telegram", "u1")
        session_manager.set_active_session(s.session_id)
        active = session_manager.active_session
        assert active is not None
        assert active.session_id == s.session_id

    def test_active_session_none(self, session_manager: SessionManager) -> None:
        """测试无活跃会话"""
        assert session_manager.active_session is None

    def test_session_ttl_cleanup(self) -> None:
        """测试会话过期清理"""
        # 使用超短 TTL
        sm = SessionManager(session_ttl_seconds=0.0)
        sm.get_or_create_session("tg", "u1")
        time.sleep(0.01)
        cleaned = sm.cleanup_expired_sessions()
        assert cleaned == 1
        assert sm.session_count == 0

    # ── 跨平台上下文共享 ──────────────────────

    def test_share_context(self, session_manager: SessionManager) -> None:
        """测试跨平台上下文共享"""
        session_manager.share_context("user_1", "preferred_language", "Python")
        val = session_manager.get_shared_context("user_1", "preferred_language")
        assert val == "Python"

    def test_get_all_shared_context(self, session_manager: SessionManager) -> None:
        """测试获取所有共享上下文"""
        session_manager.share_context("user_1", "lang", "zh")
        session_manager.share_context("user_1", "theme", "dark")
        ctx = session_manager.get_all_shared_context("user_1")
        assert ctx["lang"] == "zh"
        assert ctx["theme"] == "dark"

    def test_merge_shared_context(self, session_manager: SessionManager) -> None:
        """测试合并共享上下文"""
        session_manager.share_context("user_1", "a", 1)
        session_manager.merge_shared_context("user_1", {"b": 2, "c": 3})
        ctx = session_manager.get_all_shared_context("user_1")
        assert ctx["a"] == 1
        assert ctx["b"] == 2
        assert ctx["c"] == 3

    def test_get_user_sessions(self, session_manager: SessionManager) -> None:
        """测试获取同一用户所有平台的会话"""
        session_manager.get_or_create_session("telegram", "user_x")
        session_manager.get_or_create_session("discord", "user_x")
        session_manager.get_or_create_session("slack", "user_x")
        session_manager.get_or_create_session("telegram", "user_y")

        sessions = session_manager.get_user_sessions("user_x")
        assert len(sessions) == 3
        platforms = {s.platform for s in sessions}
        assert platforms == {"telegram", "discord", "slack"}

    # ── Session 数据类测试 ────────────────────

    def test_session_add_message(self, session_manager: SessionManager) -> None:
        """测试向会话添加消息"""
        session = session_manager.get_or_create_session("tg", "u1")
        msg = GatewayMessage(
            platform="tg", user_id="u1", session_id=session.session_id, content="hello"
        )
        session.add_message(msg)
        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "hello"

    def test_session_add_response(self, session_manager: SessionManager) -> None:
        """测试向会话添加 AI 响应"""
        session = session_manager.get_or_create_session("tg", "u1")
        session.add_response("AI 回复")
        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "assistant"
        assert session.messages[0]["content"] == "AI 回复"

    def test_session_get_recent_messages(self, session_manager: SessionManager) -> None:
        """测试获取最近消息"""
        session = session_manager.get_or_create_session("tg", "u1")
        for i in range(30):
            msg = GatewayMessage(
                platform="tg",
                user_id="u1",
                session_id=session.session_id,
                content=f"msg_{i}",
            )
            session.add_message(msg)
        recent = session.get_recent_messages(10)
        assert len(recent) == 10
        assert recent[-1]["content"] == "msg_29"

    def test_session_update_context(self, session_manager: SessionManager) -> None:
        """测试更新会话上下文"""
        session = session_manager.get_or_create_session("tg", "u1")
        session.update_context("topic", "coding")
        assert session.get_context("topic") == "coding"
        assert session.get_context("missing", "default") == "default"

    def test_session_to_info_dict(self, session_manager: SessionManager) -> None:
        """测试会话信息字典"""
        session = session_manager.get_or_create_session("tg", "u1")
        info = session.to_info_dict()
        assert info["platform"] == "tg"
        assert info["user_id"] == "u1"
        assert "message_count" in info
        assert "messages" not in info  # info_dict 不含完整消息历史

    def test_session_to_dict(self, session_manager: SessionManager) -> None:
        """测试会话完整字典"""
        session = session_manager.get_or_create_session("tg", "u1")
        d = session.to_dict()
        assert "messages" in d
        assert "context" in d
        assert "metadata" in d

    def test_session_message_limit(self, session_manager: SessionManager) -> None:
        """测试会话消息数量限制"""
        session = session_manager.get_or_create_session("tg", "u1")
        for i in range(150):
            msg = GatewayMessage(
                platform="tg",
                user_id="u1",
                session_id=session.session_id,
                content=f"msg_{i}",
            )
            session.add_message(msg)
        assert len(session.messages) == 100  # 被裁剪到 _max_messages


# ═══════════════════════════════════════════════
# 适配器 normalize_message 测试
# ═══════════════════════════════════════════════


class TestTelegramAdapter:
    """Telegram 适配器测试"""

    def test_normalize_text_message(self) -> None:
        """测试规范化 Telegram 文本消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 100,
                "from": {"id": 12345, "first_name": "Alice", "username": "alice"},
                "chat": {"id": 67890, "type": "private"},
                "date": 1700000000,
                "text": "你好",
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.platform == "telegram"
        assert msg.user_id == "67890"
        assert msg.content == "你好"
        assert msg.message_type == "text"
        assert msg.session_id == "tg_67890"

    def test_normalize_command(self) -> None:
        """测试规范化 Telegram 命令消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 101,
                "from": {"id": 1},
                "chat": {"id": 2, "type": "private"},
                "date": 1700000000,
                "text": "/start",
                "entities": [{"type": "bot_command"}],
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "command"
        assert msg.content == "/start"

    def test_normalize_photo(self) -> None:
        """测试规范化 Telegram 图片消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 102,
                "from": {"id": 1},
                "chat": {"id": 2, "type": "private"},
                "date": 1700000000,
                "photo": [{"file_id": "abc"}],
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "[图片]"
        assert msg.message_type == "image"

    def test_normalize_sticker(self) -> None:
        """测试规范化 Telegram 贴纸消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 103,
                "from": {"id": 1},
                "chat": {"id": 2, "type": "private"},
                "date": 1700000000,
                "sticker": {"emoji": "😀"},
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "[贴纸]"
        assert msg.message_type == "image"

    def test_normalize_document(self) -> None:
        """测试规范化 Telegram 文件消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 104,
                "from": {"id": 1},
                "chat": {"id": 2, "type": "private"},
                "date": 1700000000,
                "document": {"file_name": "report.pdf"},
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "[文件]"
        assert msg.message_type == "file"

    def test_normalize_voice(self) -> None:
        """测试规范化 Telegram 语音消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 105,
                "from": {"id": 1},
                "chat": {"id": 2, "type": "private"},
                "date": 1700000000,
                "voice": {"duration": 10},
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "[语音]"
        assert msg.message_type == "audio"

    def test_normalize_with_caption(self) -> None:
        """测试规范化带说明的媒体消息"""
        adapter = TelegramAdapter()
        raw = {
            "message": {
                "message_id": 106,
                "from": {"id": 1},
                "chat": {"id": 2},
                "date": 1700000000,
                "photo": [{}],
                "caption": "看看这张图",
            }
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "看看这张图"

    def test_normalize_from_object_error(self) -> None:
        """测试从对象规范化失败时的降级处理"""
        adapter = TelegramAdapter()

        class BrokenMessage:
            @property
            def chat(self) -> None:
                raise RuntimeError("simulated error")

        msg = adapter._normalize_from_object(BrokenMessage())
        assert msg.platform == "telegram"
        assert msg.user_id == "unknown"
        assert "解析失败" in msg.content


class TestDiscordAdapter:
    """Discord 适配器测试"""

    def test_normalize_text_message(self) -> None:
        """测试规范化 Discord 文本消息"""
        adapter = DiscordAdapter()
        raw = {
            "id": "msg_001",
            "channel_id": "ch_123",
            "guild_id": "guild_456",
            "author": {"id": "user_789", "username": "Bob", "discriminator": "1234"},
            "content": "hello world",
            "mention_everyone": False,
            "mentions": [],
            "attachments": [],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.platform == "discord"
        assert msg.user_id == "user_789"
        assert msg.content == "hello world"
        assert msg.message_type == "text"
        assert msg.session_id == "dc_guild_456_ch_123"

    def test_normalize_command(self) -> None:
        """测试规范化 Discord 命令消息"""
        adapter = DiscordAdapter(command_prefix="!")
        raw = {
            "id": "msg_002",
            "channel_id": "ch_1",
            "author": {"id": "u1", "username": "test"},
            "content": "!ping",
            "attachments": [],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "command"

    def test_normalize_slash_command(self) -> None:
        """测试规范化 Discord 斜杠命令"""
        adapter = DiscordAdapter()
        raw = {
            "id": "msg_003",
            "channel_id": "ch_1",
            "author": {"id": "u1", "username": "test"},
            "content": "/help",
            "attachments": [],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "command"

    def test_normalize_dm(self) -> None:
        """测试规范化 Discord 私信"""
        adapter = DiscordAdapter()
        raw = {
            "id": "msg_004",
            "channel_id": "dm_channel",
            "author": {"id": "u1", "username": "test"},
            "content": "hi",
            "attachments": [],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.metadata["is_dm"] is True
        assert "dm" in msg.session_id

    def test_normalize_image_attachment(self) -> None:
        """测试规范化 Discord 图片附件"""
        adapter = DiscordAdapter()
        raw = {
            "id": "msg_005",
            "channel_id": "ch_1",
            "author": {"id": "u1", "username": "test"},
            "content": "",
            "attachments": [
                {"filename": "photo.png", "content_type": "image/png"}
            ],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "image"
        assert "photo.png" in msg.content

    def test_normalize_file_attachment(self) -> None:
        """测试规范化 Discord 文件附件"""
        adapter = DiscordAdapter()
        raw = {
            "id": "msg_006",
            "channel_id": "ch_1",
            "author": {"id": "u1", "username": "test"},
            "content": "",
            "attachments": [
                {"filename": "data.zip", "content_type": "application/zip"}
            ],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "file"

    def test_normalize_embed_message(self) -> None:
        """测试规范化 Discord 嵌入消息"""
        adapter = DiscordAdapter()
        raw = {
            "id": "msg_007",
            "channel_id": "ch_1",
            "author": {"id": "u1", "username": "test"},
            "content": "",
            "attachments": [],
            "embeds": [{"title": "通知", "description": "系统更新"}],
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "系统更新"

    def test_normalize_from_object_error(self) -> None:
        """测试从对象规范化失败时的降级"""
        adapter = DiscordAdapter()

        class BrokenMessage:
            @property
            def author(self) -> None:
                raise RuntimeError("simulated error")

        msg = adapter._normalize_from_object(BrokenMessage())
        assert msg.platform == "discord"
        assert msg.user_id == "unknown"
        assert "解析失败" in msg.content


class TestSlackAdapter:
    """Slack 适配器测试"""

    def test_normalize_message_event(self) -> None:
        """测试规范化 Slack 消息事件"""
        adapter = SlackAdapter()
        raw = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U123",
                "channel": "C456",
                "text": "你好 Slack",
                "ts": "1700000000.000100",
                "team": "T789",
            },
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.platform == "slack"
        assert msg.user_id == "U123"
        assert msg.content == "你好 Slack"
        assert msg.message_type == "text"
        assert msg.session_id == "sl_C456"

    def test_normalize_slash_command(self) -> None:
        """测试规范化 Slack 斜杠命令"""
        adapter = SlackAdapter()
        raw = {
            "type": "slash_commands",
            "command": "/pycoder",
            "text": "帮我写代码",
            "user_id": "U111",
            "channel_id": "C222",
            "team_id": "T333",
            "trigger_id": "trig_001",
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "command"
        assert msg.content == "/pycoder 帮我写代码"
        assert msg.user_id == "U111"

    def test_normalize_file_share(self) -> None:
        """测试规范化 Slack 文件分享"""
        adapter = SlackAdapter()
        raw = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1",
                "channel": "C1",
                "text": "",
                "subtype": "file_share",
                "files": [{"title": "report.pdf", "name": "report.pdf"}],
                "ts": "1700000000.000100",
            },
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.message_type == "file"
        assert "report.pdf" in msg.content

    def test_normalize_app_mention(self) -> None:
        """测试规范化 Slack App Mention"""
        adapter = SlackAdapter()
        adapter._bot_user_id = "BOT123"
        raw = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U1",
                "channel": "C1",
                "text": "<@BOT123> 你好",
                "ts": "1700000000.000100",
            },
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.content == "你好"  # bot mention 被移除

    def test_normalize_blocks_text(self) -> None:
        """测试从 Slack Blocks 提取文本"""
        adapter = SlackAdapter()
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Hello "},
                            {"type": "text", "text": "World"},
                        ],
                    }
                ],
            }
        ]
        text = adapter._extract_blocks_text(blocks)
        assert text == "Hello  World"

    def test_normalize_section_block(self) -> None:
        """测试从 Slack Section Block 提取文本"""
        adapter = SlackAdapter()
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Section text"}}
        ]
        text = adapter._extract_blocks_text(blocks)
        assert text == "Section text"

    def test_normalize_thread_reply(self) -> None:
        """测试规范化 Slack 线程回复"""
        adapter = SlackAdapter()
        raw = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1",
                "channel": "C1",
                "text": "thread reply",
                "ts": "1700000000.000200",
                "thread_ts": "1700000000.000100",
            },
        }
        msg = adapter._normalize_from_dict(raw)
        assert msg.metadata["is_thread_reply"] is True
        assert "1700000000.000100" in msg.session_id

    def test_normalize_unknown_event_type(self) -> None:
        """测试未知 Slack 事件类型"""
        adapter = SlackAdapter()
        raw = {"type": "unknown_type", "data": "nothing"}
        msg = adapter._normalize_from_dict(raw)
        assert msg.platform == "slack"
        assert "未知事件" in msg.content

    def test_normalize_from_object_error(self) -> None:
        """测试从对象规范化失败时的降级"""
        adapter = SlackAdapter()

        class BrokenMessage:
            @property
            def user(self) -> None:
                raise RuntimeError("simulated error")

        msg = adapter._normalize_from_object(BrokenMessage())
        assert msg.platform == "slack"
        assert msg.user_id == "unknown"
        assert "解析失败" in msg.content


class TestCLIAdapter:
    """CLI 适配器测试"""

    def test_normalize_text(self) -> None:
        """测试规范化 CLI 文本输入"""
        adapter = CLIAdapter()
        msg = adapter._normalize_from_string("hello world")
        assert msg.platform == "cli"
        assert msg.user_id == "cli_user"
        assert msg.session_id == "cli_session"
        assert msg.content == "hello world"
        assert msg.message_type == "text"

    def test_normalize_command(self) -> None:
        """测试规范化 CLI 命令"""
        adapter = CLIAdapter()
        msg = adapter._normalize_from_string("/help")
        assert msg.message_type == "command"

    def test_normalize_exclamation_command(self) -> None:
        """测试规范化 CLI 感叹号命令"""
        adapter = CLIAdapter()
        msg = adapter._normalize_from_string("!status")
        assert msg.message_type == "command"

    def test_normalize_multiline(self) -> None:
        """测试规范化多行输入"""
        adapter = CLIAdapter()
        msg = adapter._normalize_from_string("line1\nline2\nline3")
        assert msg.metadata["is_multiline"] is True
        assert msg.metadata["line_count"] == 3

    @pytest.mark.asyncio
    async def test_normalize_non_string(self) -> None:
        """测试规范化非字符串输入"""
        adapter = CLIAdapter()
        msg = await adapter.normalize_message(12345)
        assert msg.platform == "cli"
        assert msg.content == "12345"

    def test_normalize_whitespace(self) -> None:
        """测试规范化带空白输入"""
        adapter = CLIAdapter()
        msg = adapter._normalize_from_string("  hello  ")
        assert msg.content == "hello"


# ═══════════════════════════════════════════════
# 并发会话访问测试
# ═══════════════════════════════════════════════


class TestConcurrentSessionAccess:
    """并发会话访问安全测试"""

    @pytest.mark.asyncio
    async def test_concurrent_session_creation(self) -> None:
        """测试并发创建会话不会冲突"""
        sm = SessionManager()

        async def create_session(platform: str, user_id: str) -> Session:
            return sm.get_or_create_session(platform, user_id)

        tasks = [
            create_session("tg", f"user_{i}")
            for i in range(20)
        ]
        sessions = await asyncio.gather(*tasks)
        assert len(sessions) == 20
        assert sm.session_count == 20
        # 确保所有 session_id 唯一
        ids = {s.session_id for s in sessions}
        assert len(ids) == 20

    @pytest.mark.asyncio
    async def test_concurrent_same_session(self) -> None:
        """测试并发获取同一会话返回同一实例"""
        sm = SessionManager()

        async def get_session() -> Session:
            return sm.get_or_create_session("tg", "same_user")

        tasks = [get_session() for _ in range(10)]
        sessions = await asyncio.gather(*tasks)
        assert sm.session_count == 1
        first_id = sessions[0].session_id
        for s in sessions:
            assert s.session_id == first_id

    @pytest.mark.asyncio
    async def test_concurrent_context_sharing(self) -> None:
        """测试并发跨平台上下文共享"""
        sm = SessionManager()

        async def share_context(user_id: str, key: str, value: str) -> None:
            sm.share_context(user_id, key, value)

        tasks = [
            share_context("user_1", f"key_{i}", f"value_{i}")
            for i in range(10)
        ]
        await asyncio.gather(*tasks)
        ctx = sm.get_all_shared_context("user_1")
        assert len(ctx) == 10


# ═══════════════════════════════════════════════
# 错误处理测试
# ═══════════════════════════════════════════════


class TestErrorHandling:
    """错误处理测试"""

    def test_send_to_missing_adapter(self, gateway: MessageGateway) -> None:
        """测试向未注册平台发送消息"""
        result = asyncio.run(gateway.send_message("nonexistent", "u", "msg"))
        assert result is False

    def test_get_nonexistent_adapter(self, gateway: MessageGateway) -> None:
        """测试获取不存在的适配器"""
        assert gateway.get_adapter("nonexistent") is None

    @pytest.mark.asyncio
    async def test_adapter_start_failure(self, gateway: MessageGateway) -> None:
        """测试适配器启动失败不阻塞其他适配器"""

        class FailingAdapter(_MockAdapter):
            async def start(self) -> None:
                raise RuntimeError("启动失败")

        adapter_good = _MockAdapter("good")
        adapter_bad = FailingAdapter("bad")
        gateway.register_adapter(adapter_good)
        gateway.register_adapter(adapter_bad)
        await gateway.start()
        # bad 启动失败，但 good 仍然启动且网关正常运行
        assert gateway.is_running is True
        assert adapter_good.is_running is True
        await gateway.stop()

    @pytest.mark.asyncio
    async def test_adapter_stop_failure(self, gateway: MessageGateway) -> None:
        """测试适配器停止失败不影响其他"""

        class FailingStopAdapter(_MockAdapter):
            async def stop(self) -> None:
                raise RuntimeError("停止失败")

        adapter_good = _MockAdapter("good")
        adapter_bad = FailingStopAdapter("bad")
        gateway.register_adapter(adapter_good)
        gateway.register_adapter(adapter_bad)
        await gateway.start()
        await gateway.stop()
        assert gateway.is_running is False

    def test_session_manager_nonexistent_shared_context(self) -> None:
        """测试获取不存在用户的共享上下文"""
        sm = SessionManager()
        val = sm.get_shared_context("nobody", "key", "default")
        assert val == "default"
        ctx = sm.get_all_shared_context("nobody")
        assert ctx == {}

    def test_telegram_normalize_empty_dict(self) -> None:
        """测试 Telegram 适配器处理空字典"""
        adapter = TelegramAdapter()
        msg = adapter._normalize_from_dict({})
        assert msg.platform == "telegram"
        assert msg.user_id == "unknown"

    def test_discord_normalize_empty_dict(self) -> None:
        """测试 Discord 适配器处理空字典"""
        adapter = DiscordAdapter()
        msg = adapter._normalize_from_dict({})
        assert msg.platform == "discord"
        assert msg.user_id == "unknown"

    def test_slack_normalize_empty_dict(self) -> None:
        """测试 Slack 适配器处理空字典"""
        adapter = SlackAdapter()
        msg = adapter._normalize_from_dict({})
        assert msg.platform == "slack"
        assert msg.user_id == "unknown"