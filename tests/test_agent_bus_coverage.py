"""AgentBus 单元测试 — 覆盖 pycoder.server.services.agent_bus

覆盖:
- MessageType / BusMessage / to_dict
- register / unregister / agents
- send (广播 / 点对点 / 未知目标)
- broadcast
- receive (含超时 / 自动注册)
- request / reply (成功 / 超时)
- get_history / get_messages_for
- events (拦截)
- stop
"""
from __future__ import annotations

import asyncio

from pycoder.server.services.agent_bus import (
    AgentBus,
    BusMessage,
    MessageType,
)


# ── MessageType ──────────────────────────────────────────


class TestMessageType:
    def test_values(self):
        assert MessageType.TASK_ASSIGN.value == "task_assign"
        assert MessageType.QUESTION.value == "question"
        assert MessageType.ANSWER.value == "answer"
        assert MessageType.INFO.value == "info"

    def test_count(self):
        assert len(list(MessageType)) >= 8


# ── BusMessage ──────────────────────────────────────────


class TestBusMessage:
    def test_defaults(self):
        m = BusMessage()
        assert m.id.startswith("msg-")
        assert m.msg_type == MessageType.INFO
        assert m.to_agent == "*"
        assert m.from_agent == ""
        assert m.content == ""
        assert m.context == {}
        assert m.timestamp > 0
        assert m.reply_to == ""

    def test_unique_ids(self):
        a = BusMessage()
        b = BusMessage()
        assert a.id != b.id

    def test_to_dict_truncates_content(self):
        m = BusMessage(content="x" * 600)
        d = m.to_dict()
        assert len(d["content"]) == 500
        assert d["type"] == "info"
        assert d["from"] == ""
        assert d["to"] == "*"

    def test_to_dict_short_content(self):
        m = BusMessage(content="short")
        assert m.to_dict()["content"] == "short"


# ── register / unregister ───────────────────────────────


class TestRegistration:
    def test_register_creates_queue(self):
        bus = AgentBus()
        bus.register("alice")
        assert "alice" in bus.agents

    def test_register_with_handler(self):
        bus = AgentBus()
        bus.register("bob", handler=None)
        assert "bob" in bus.agents

    def test_register_idempotent(self):
        bus = AgentBus()
        bus.register("alice")
        bus.register("alice")
        assert bus.agents.count("alice") == 1

    def test_unregister(self):
        bus = AgentBus()
        bus.register("alice")
        bus.unregister("alice")
        assert "alice" not in bus.agents

    def test_unregister_unknown(self):
        bus = AgentBus()
        bus.unregister("nobody")  # 不应抛异常

    def test_agents_property_returns_list(self):
        bus = AgentBus()
        bus.register("a")
        bus.register("b")
        assert set(bus.agents) == {"a", "b"}


# ── send / broadcast ────────────────────────────────────


class TestSend:
    async def test_point_to_point(self):
        bus = AgentBus()
        bus.register("alice")
        await bus.send(BusMessage(from_agent="sys", to_agent="alice", content="hi"))
        msg = await bus.receive("alice", timeout=1.0)
        assert msg is not None
        assert msg.content == "hi"

    async def test_broadcast_delivers_to_all(self):
        bus = AgentBus()
        bus.register("alice")
        bus.register("bob")
        await bus.broadcast("sys", "hello all")
        m1 = await bus.receive("alice", timeout=1.0)
        m2 = await bus.receive("bob", timeout=1.0)
        assert m1.content == "hello all"
        assert m2.content == "hello all"

    async def test_send_to_unknown_silently_drops(self):
        bus = AgentBus()
        # 不应抛异常
        await bus.send(BusMessage(to_agent="ghost", content="x"))

    async def test_broadcast_custom_type(self):
        bus = AgentBus()
        bus.register("alice")
        await bus.broadcast("sys", "task", msg_type=MessageType.TASK_ASSIGN)
        m = await bus.receive("alice", timeout=1.0)
        assert m.msg_type == MessageType.TASK_ASSIGN


# ── receive ─────────────────────────────────────────────


class TestReceive:
    async def test_receive_auto_registers(self):
        bus = AgentBus()
        # receive 在 agent 未注册时应自动注册
        # 使用很短超时避免阻塞
        result = await bus.receive("newcomer", timeout=0.05)
        assert result is None
        assert "newcomer" in bus.agents

    async def test_receive_timeout_returns_none(self):
        bus = AgentBus()
        bus.register("alice")
        result = await bus.receive("alice", timeout=0.05)
        assert result is None


# ── request / reply ─────────────────────────────────────


class TestRequestReply:
    async def test_request_reply_success(self):
        bus = AgentBus()
        bus.register("responder")

        async def _respond():
            msg = await bus.receive("responder", timeout=2.0)
            assert msg is not None
            await bus.reply(msg, "answer-content")

        task = asyncio.create_task(_respond())
        reply = await bus.request("asker", "responder", "question?", timeout=2.0)
        await task
        assert reply is not None
        assert reply.content == "answer-content"
        assert reply.msg_type == MessageType.ANSWER
        assert reply.reply_to != ""

    async def test_request_timeout_returns_none(self):
        bus = AgentBus()
        bus.register("responder")
        # 没有人回复 → 超时
        result = await bus.request("asker", "responder", "q", timeout=0.05)
        assert result is None

    async def test_reply_delivers_to_sender(self):
        bus = AgentBus()
        bus.register("alice")
        original = BusMessage(from_agent="alice", to_agent="bob", content="orig")
        await bus.reply(original, "reply-content")
        m = await bus.receive("alice", timeout=1.0)
        assert m is not None
        assert m.content == "reply-content"


# ── history / messages ──────────────────────────────────


class TestHistory:
    async def test_get_history_empty(self):
        bus = AgentBus()
        assert bus.get_history() == []

    async def test_get_history_records(self):
        bus = AgentBus()
        await bus.broadcast("sys", "m1")
        await bus.broadcast("sys", "m2")
        hist = bus.get_history()
        assert len(hist) == 2
        assert hist[-1]["content"] == "m2"

    async def test_get_history_limit(self):
        bus = AgentBus()
        for i in range(5):
            await bus.broadcast("sys", f"m{i}")
        hist = bus.get_history(limit=2)
        assert len(hist) == 2

    async def test_history_capped_at_max(self):
        bus = AgentBus()
        # 发送超过 MAX_HISTORY 条
        for i in range(AgentBus.MAX_HISTORY + 50):
            await bus.broadcast("sys", f"m{i}")
        assert len(bus._message_log) == AgentBus.MAX_HISTORY

    async def test_get_messages_for(self):
        bus = AgentBus()
        bus.register("alice")
        await bus.send(BusMessage(from_agent="sys", to_agent="alice", content="to-alice"))
        await bus.broadcast("bob", "broadcast-msg")
        await bus.send(BusMessage(from_agent="alice", to_agent="sys", content="from-alice"))
        msgs = bus.get_messages_for("alice")
        # alice 收到 to-alice + broadcast，且发出 from-alice
        contents = [m["content"] for m in msgs]
        assert "to-alice" in contents
        assert "broadcast-msg" in contents
        assert "from-alice" in contents

    async def test_get_messages_for_limit(self):
        bus = AgentBus()
        for i in range(10):
            await bus.send(BusMessage(from_agent="x", to_agent="alice", content=f"m{i}"))
        msgs = bus.get_messages_for("alice", limit=3)
        assert len(msgs) == 3


# ── events ──────────────────────────────────────────────


class TestEvents:
    async def test_events_yields_messages(self):
        bus = AgentBus()
        bus.register("alice")
        gen = bus.events()
        # 预激生成器：让生成器体执行，替换 send 为 _intercept
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.05)
        # 现在 send 已被替换为 _intercept，broadcast 会把消息放入 q
        await bus.broadcast("sys", "event-msg")
        msg = await task
        assert msg.content == "event-msg"
        await gen.aclose()
        # 关闭后 send 应恢复为原始
        assert not hasattr(bus.send, "__wrapped__")

    async def test_stop_sets_running_false(self):
        bus = AgentBus()
        bus._running = True
        bus.stop()
        assert bus._running is False
