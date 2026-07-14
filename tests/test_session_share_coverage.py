"""覆盖率测试: pycoder/server/session_share.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - FileLock: acquire / release / get_locked_by / list_locks / 超时自动释放
  - SessionShareManager: join / leave / broadcast / _safe_send / get_shared_sessions
    log_operation / get_recent_operations / active_rooms / file_lock
  - get_session_share_manager 单例

测试策略:
  - 直接调用方法，用 monkeypatch 控制 time.time 模拟超时
  - 用 AsyncMock 模拟 send_func 测试 broadcast 和 _safe_send
  - 通过 monkeypatch 重置全局单例避免污染
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from pycoder.server import session_share as ss_mod
from pycoder.server.session_share import (
    FileLock,
    SessionShareManager,
    get_session_share_manager,
)


# ══════════════════════════════════════════════════════════
# FileLock
# ══════════════════════════════════════════════════════════

class TestFileLock:
    def test_acquire_new_lock(self):
        lock = FileLock()
        assert lock.acquire("a.py", "client1") is True
        assert lock.get_locked_by("a.py") == "client1"

    def test_acquire_same_client_reentry(self):
        """同一客户端重新获取锁 → True"""
        lock = FileLock()
        lock.acquire("a.py", "client1")
        assert lock.acquire("a.py", "client1") is True

    def test_acquire_other_client_blocked(self):
        """其他客户端尝试获取已锁文件 → False"""
        lock = FileLock()
        lock.acquire("a.py", "client1")
        assert lock.acquire("a.py", "client2") is False

    def test_acquire_timeout_released(self, monkeypatch):
        """超时后锁应自动释放"""
        lock = FileLock()
        # 模拟时间流逝：第一次获取时间，第二次获取时已超时
        current = [1000.0]
        monkeypatch.setattr(time, "time", lambda: current[0])
        # 第一次获取（默认 timeout_s=120）
        lock.acquire("a.py", "client1")
        # 时间推进 200 秒（远超默认 timeout_s=120）
        current[0] = 1200.0
        # 现在新客户端应能获取锁
        assert lock.acquire("a.py", "client2") is True
        assert lock.get_locked_by("a.py") == "client2"

    def test_release_by_owner(self):
        lock = FileLock()
        lock.acquire("a.py", "client1")
        assert lock.release("a.py", "client1") is True
        assert lock.get_locked_by("a.py") is None

    def test_release_by_non_owner(self):
        """非持有者释放失败"""
        lock = FileLock()
        lock.acquire("a.py", "client1")
        assert lock.release("a.py", "client2") is False
        # 锁仍由 client1 持有
        assert lock.get_locked_by("a.py") == "client1"

    def test_release_nonexistent(self):
        """释放不存在的锁 → False"""
        lock = FileLock()
        assert lock.release("nope.py", "client1") is False

    def test_list_locks_empty(self):
        lock = FileLock()
        assert lock.list_locks() == []

    def test_list_locks_with_data(self):
        lock = FileLock()
        lock.acquire("a.py", "c1")
        lock.acquire("b.py", "c2")
        locks = lock.list_locks()
        assert len(locks) == 2
        files = {l["file"] for l in locks}
        assert files == {"a.py", "b.py"}


# ══════════════════════════════════════════════════════════
# SessionShareManager - 基础方法
# ══════════════════════════════════════════════════════════

class TestSessionShareBasic:
    def test_join_first_client(self):
        m = SessionShareManager()
        send = MagicMock()
        count = m.join("c1", "s1", send)
        assert count == 1
        assert m.get_shared_sessions("s1") == 1

    def test_join_multiple_clients(self):
        m = SessionShareManager()
        m.join("c1", "s1", MagicMock())
        m.join("c2", "s1", MagicMock())
        assert m.get_shared_sessions("s1") == 2

    def test_join_returns_count(self):
        m = SessionShareManager()
        m.join("c1", "s1", MagicMock())
        count = m.join("c2", "s1", MagicMock())
        assert count == 2

    def test_leave_existing(self):
        m = SessionShareManager()
        m.join("c1", "s1", MagicMock())
        m.leave("c1")
        assert m.get_shared_sessions("s1") == 0

    def test_leave_removes_empty_room(self):
        m = SessionShareManager()
        m.join("c1", "s1", MagicMock())
        m.leave("c1")
        # 房间应被删除
        assert "s1" not in m._rooms

    def test_leave_unknown_client(self):
        """离开不存在的客户端不抛异常"""
        m = SessionShareManager()
        m.leave("nope")  # 不抛异常

    def test_leave_keeps_room_when_others_remain(self):
        m = SessionShareManager()
        m.join("c1", "s1", MagicMock())
        m.join("c2", "s1", MagicMock())
        m.leave("c1")
        assert m.get_shared_sessions("s1") == 1

    def test_active_rooms_only_multi_client(self):
        m = SessionShareManager()
        m.join("c1", "s1", MagicMock())
        m.join("c2", "s1", MagicMock())
        m.join("c3", "s2", MagicMock())  # s2 只有一人
        rooms = m.active_rooms
        assert len(rooms) == 1
        assert rooms[0]["session_id"] == "s1"
        assert rooms[0]["clients"] == 2

    def test_file_lock_property(self):
        m = SessionShareManager()
        assert isinstance(m.file_lock, FileLock)


# ══════════════════════════════════════════════════════════
# SessionShareManager - broadcast / _safe_send
# ══════════════════════════════════════════════════════════

class TestSessionShareBroadcast:
    async def test_broadcast_single_client_skipped(self):
        """房间只有一人时不广播"""
        m = SessionShareManager()
        send = AsyncMock()
        m.join("c1", "s1", send)
        await m.broadcast("s1", {"msg": "hi"})
        send.assert_not_called()

    async def test_broadcast_unknown_session(self):
        """未知 session → 不抛异常"""
        m = SessionShareManager()
        # 不抛异常
        await m.broadcast("nope", {"msg": "hi"})

    async def test_broadcast_to_others(self):
        """广播给除 exclude 外的所有客户端"""
        m = SessionShareManager()
        s1 = AsyncMock()
        s2 = AsyncMock()
        s3 = AsyncMock()
        m.join("c1", "s1", s1)
        m.join("c2", "s1", s2)
        m.join("c3", "s1", s3)

        await m.broadcast("s1", {"msg": "hi"}, exclude="c1")

        # c1 应未收到，c2/c3 应收到
        s1.assert_not_called()
        s2.assert_awaited_once()
        s3.assert_awaited_once()
        # 验证发送的是 JSON 字符串
        payload = s2.await_args.args[0]
        assert json.loads(payload) == {"msg": "hi"}

    async def test_safe_send_success(self):
        m = SessionShareManager()
        send = AsyncMock()
        await m._safe_send(send, "payload", "cid-12345678")
        send.assert_awaited_once_with("payload")

    async def test_safe_send_failure_disconnects(self):
        """发送失败 → 自动断开该客户端"""
        m = SessionShareManager()
        send = AsyncMock(side_effect=RuntimeError("conn closed"))
        m.join("c1-12345678", "s1", MagicMock())
        await m._safe_send(send, "payload", "c1-12345678")
        # 客户端应被移除
        assert m.get_shared_sessions("s1") == 0


# ══════════════════════════════════════════════════════════
# SessionShareManager - operation log
# ══════════════════════════════════════════════════════════

class TestSessionShareOperationLog:
    def test_log_operation_basic(self):
        m = SessionShareManager()
        m.log_operation("client-12345678", "edit", "modified a.py")
        ops = m.get_recent_operations()
        assert len(ops) == 1
        # client_id 截取前 8 字符：'client-1' (共 8 字符)
        assert ops[0]["client_id"] == "client-1"
        assert ops[0]["type"] == "edit"
        assert ops[0]["detail"] == "modified a.py"
        assert "timestamp" in ops[0]

    def test_get_recent_operations_limit(self):
        m = SessionShareManager()
        for i in range(25):
            m.log_operation("c", "op", f"detail-{i}")
        ops = m.get_recent_operations(limit=10)
        assert len(ops) == 10
        # 取最近 10 个
        assert ops[0]["detail"] == "detail-15"
        assert ops[-1]["detail"] == "detail-24"

    def test_get_recent_operations_default_limit(self):
        m = SessionShareManager()
        for i in range(25):
            m.log_operation("c", "op", f"d{i}")
        # 默认 limit=20
        assert len(m.get_recent_operations()) == 20

    def test_log_operation_truncates_to_500(self):
        """超过 1000 条后裁剪到 500"""
        m = SessionShareManager()
        for i in range(1001):
            m.log_operation("c", "op", f"d{i}")
        # 应裁剪到 500
        assert len(m._operation_log) == 500


# ══════════════════════════════════════════════════════════
# get_session_share_manager 单例
# ══════════════════════════════════════════════════════════

class TestGetSessionShareManager:
    def test_singleton(self, monkeypatch):
        """重置全局单例后两次获取应是同一对象"""
        monkeypatch.setattr(ss_mod, "_share_manager", None)
        m1 = get_session_share_manager()
        m2 = get_session_share_manager()
        assert m1 is m2

    def test_returns_session_share_manager(self, monkeypatch):
        monkeypatch.setattr(ss_mod, "_share_manager", None)
        assert isinstance(get_session_share_manager(), SessionShareManager)
