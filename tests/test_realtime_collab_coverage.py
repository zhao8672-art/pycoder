"""覆盖率测试: pycoder/server/realtime_collab.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - RealtimeCollabEngine: create_room / join / leave / apply_operation
    update_cursor / list_rooms
  - get_collab_engine 单例
  - apply_operation 各分支: insert / delete / replace / 房间不存在

测试策略:
  - 直接调用方法，AsyncMock 模拟 send_func
  - 用 monkeypatch 重置全局单例避免污染
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pycoder.server import realtime_collab as rc_mod
from pycoder.server.realtime_collab import (
    RealtimeCollabEngine,
    get_collab_engine,
)


# ══════════════════════════════════════════════════════════
# create_room / join / leave
# ══════════════════════════════════════════════════════════

class TestRoomManagement:
    def test_create_room_with_content(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", file_path="a.py", content="hello")
        assert "r1" in e._rooms
        assert e._documents["r1"] == "hello"
        assert e._rooms["r1"]["file_path"] == "a.py"

    def test_create_room_no_content(self):
        e = RealtimeCollabEngine()
        e.create_room("r1")
        assert "r1" in e._rooms
        assert "r1" not in e._documents  # 无内容不创建 document

    def test_join_existing_room(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", content="doc")
        send = AsyncMock()
        info = e.join("r1", "c1", send)
        assert info["success"] is True
        assert info["room_id"] == "r1"
        assert info["clients"] == 1
        assert info["document"] == "doc"

    def test_join_nonexistent_room_autocreate(self):
        """加入不存在的房间 → 自动创建"""
        e = RealtimeCollabEngine()
        info = e.join("newroom", "c1", AsyncMock())
        assert info["success"] is True
        assert info["room_id"] == "newroom"
        assert info["clients"] == 1
        assert info["document"] == ""  # 无内容

    def test_join_returns_version(self):
        e = RealtimeCollabEngine()
        e.create_room("r1")
        e._rooms["r1"]["version"] = 5
        info = e.join("r1", "c1", AsyncMock())
        assert info["version"] == 5

    def test_leave_existing(self):
        e = RealtimeCollabEngine()
        e.join("r1", "c1", AsyncMock())
        e.leave("c1")
        assert "c1" not in e._clients
        # 房间应被删除（无客户端）
        assert "r1" not in e._rooms

    def test_leave_removes_empty_document(self):
        """最后一个客户端离开 → 房间+文档被删除"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="doc")
        e.join("r1", "c1", AsyncMock())
        e.leave("c1")
        assert "r1" not in e._rooms
        assert "r1" not in e._documents

    def test_leave_keeps_room_when_others_remain(self):
        e = RealtimeCollabEngine()
        e.join("r1", "c1", AsyncMock())
        e.join("r1", "c2", AsyncMock())
        e.leave("c1")
        assert "r1" in e._rooms
        assert len(e._rooms["r1"]["clients"]) == 1

    def test_leave_unknown_client(self):
        """离开不存在的客户端不抛异常"""
        e = RealtimeCollabEngine()
        e.leave("nope")  # 不抛异常


# ══════════════════════════════════════════════════════════
# apply_operation
# ══════════════════════════════════════════════════════════

class TestApplyOperation:
    async def test_room_not_exists(self):
        e = RealtimeCollabEngine()
        r = await e.apply_operation("nope", "c1", {"type": "insert"})
        assert r["success"] is False
        assert "房间不存在" in r["error"]

    async def test_insert_operation(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", content="hello")
        r = await e.apply_operation("r1", "c1", {
            "type": "insert", "position": 2, "text": "XXX",
        })
        assert r["success"] is True
        assert r["version"] == 1
        assert e._documents["r1"] == "heXXXllo"

    async def test_insert_default_position(self):
        """insert 无 position → 默认在末尾"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="hi")
        r = await e.apply_operation("r1", "c1", {"type": "insert", "text": "!"})
        assert r["success"] is True
        assert e._documents["r1"] == "hi!"

    async def test_delete_operation(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", content="hello")
        r = await e.apply_operation("r1", "c1", {
            "type": "delete", "position": 0, "length": 2,
        })
        assert r["success"] is True
        assert e._documents["r1"] == "llo"

    async def test_delete_default_position(self):
        """delete 无 position/length → 默认 0,1"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="hi")
        r = await e.apply_operation("r1", "c1", {"type": "delete"})
        assert r["success"] is True
        assert e._documents["r1"] == "i"

    async def test_delete_at_end_skipped(self):
        """pos >= len(doc) → 不删除"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="hi")
        r = await e.apply_operation("r1", "c1", {
            "type": "delete", "position": 10, "length": 5,
        })
        assert r["success"] is True
        assert e._documents["r1"] == "hi"  # 未变

    async def test_replace_operation(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", content="old")
        r = await e.apply_operation("r1", "c1", {
            "type": "replace", "content": "brand new",
        })
        assert r["success"] is True
        assert e._documents["r1"] == "brand new"

    async def test_replace_empty_content(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", content="old")
        r = await e.apply_operation("r1", "c1", {"type": "replace"})
        assert r["success"] is True
        assert e._documents["r1"] == ""

    async def test_unknown_op_type(self):
        """未知 op_type → 不修改文档但版本+1"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="doc")
        r = await e.apply_operation("r1", "c1", {"type": "unknown"})
        assert r["success"] is True
        assert r["version"] == 1
        assert e._documents["r1"] == "doc"

    async def test_broadcast_to_others(self):
        """操作应广播给其他客户端"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        s1 = AsyncMock()
        s2 = AsyncMock()
        e.join("r1", "c1", s1)
        e.join("r1", "c2", s2)
        # c3 触发操作 → c1, c2 都应收到广播
        s3 = AsyncMock()
        e.join("r1", "c3", s3)

        await e.apply_operation("r1", "c3", {"type": "insert", "position": 0, "text": "a"})

        s1.assert_awaited_once()
        s2.assert_awaited_once()
        s3.assert_not_called()  # 发起者不收到广播
        # 验证广播内容
        msg = json.loads(s1.await_args.args[0])
        assert msg["type"] == "collab_operation"
        assert msg["client_id"] == "c3"
        assert msg["version"] == 1

    async def test_broadcast_send_failure_handled(self):
        """其他客户端 send 抛 ConnectionError → 静默捕获，不阻断"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        bad_send = AsyncMock(side_effect=ConnectionError("conn lost"))
        good_send = AsyncMock()
        e.join("r1", "c1", bad_send)
        e.join("r1", "c2", good_send)
        # c3 触发操作
        e.join("r1", "c3", AsyncMock())

        r = await e.apply_operation("r1", "c3", {"type": "insert", "position": 0, "text": "y"})
        # 应成功（即使 c1 send 失败）
        assert r["success"] is True
        # c2 应仍收到
        good_send.assert_awaited_once()

    async def test_broadcast_runtime_error_handled(self):
        """RuntimeError 也应被捕获"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        bad_send = AsyncMock(side_effect=RuntimeError("boom"))
        e.join("r1", "c1", bad_send)
        e.join("r1", "c2", AsyncMock())

        r = await e.apply_operation("r1", "c2", {"type": "insert", "position": 0, "text": "y"})
        assert r["success"] is True

    async def test_broadcast_os_error_handled(self):
        """OSError 也应被捕获"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        bad_send = AsyncMock(side_effect=OSError("net err"))
        e.join("r1", "c1", bad_send)
        e.join("r1", "c2", AsyncMock())

        r = await e.apply_operation("r1", "c2", {"type": "insert", "position": 0, "text": "y"})
        assert r["success"] is True

    async def test_broadcast_to_unknown_client_skipped(self):
        """room 中包含未注册客户端 → 跳过（防御性）"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        s1 = AsyncMock()
        e.join("r1", "c1", s1)
        # 直接往 room 添加一个不存在的 client_id
        e._rooms["r1"]["clients"].add("ghost")
        # 不应抛异常
        r = await e.apply_operation("r1", "c1", {"type": "insert", "position": 0, "text": "y"})
        assert r["success"] is True


# ══════════════════════════════════════════════════════════
# update_cursor
# ══════════════════════════════════════════════════════════

class TestUpdateCursor:
    def test_room_not_exists(self):
        """房间不存在 → 静默返回"""
        e = RealtimeCollabEngine()
        # 不抛异常
        e.update_cursor("nope", "c1", {"line": 1, "column": 2})

    async def test_update_cursor_schedules_task(self):
        """光标更新应通过 asyncio.create_task 调度发送"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        s1 = AsyncMock()
        e.join("r1", "c1", s1)
        s2 = AsyncMock()
        e.join("r1", "c2", s2)

        # 触发 update_cursor，c2 应被异步通知
        e.update_cursor("r1", "c1", {"line": 5, "column": 10})
        # 等待事件循环处理完待办任务
        await asyncio.sleep(0.01)
        s2.assert_awaited_once()
        msg = json.loads(s2.await_args.args[0])
        assert msg["type"] == "cursor_update"
        assert msg["client_id"] == "c1"
        assert msg["position"]["line"] == 5

    async def test_update_cursor_send_failure_handled(self):
        """send 抛 RuntimeError → 静默捕获"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        bad_send = AsyncMock(side_effect=RuntimeError("boom"))
        e.join("r1", "c1", bad_send)
        e.join("r1", "c2", AsyncMock())

        # c2 触发 update_cursor，c1 send 会失败但不抛
        e.update_cursor("r1", "c2", {"line": 1})
        await asyncio.sleep(0.01)
        # 不抛异常即通过

    async def test_update_cursor_to_unknown_client_skipped(self):
        """room 中包含未注册 client_id → 跳过"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        e.join("r1", "c1", AsyncMock())
        e._rooms["r1"]["clients"].add("ghost")
        # 不应抛异常
        e.update_cursor("r1", "c1", {"line": 1})
        await asyncio.sleep(0.01)

    async def test_update_cursor_create_task_type_error(self):
        """info['send'] 返回非协程 → asyncio.create_task 抛 TypeError → 静默捕获"""
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        # 使用普通 MagicMock — 调用时返回非协程对象
        bad_send = MagicMock(return_value="not-a-coroutine")
        e.join("r1", "c1", bad_send)
        e.join("r1", "c2", AsyncMock())

        # update_cursor 内部 asyncio.create_task 会因参数非协程抛 TypeError
        # 不应抛出异常
        e.update_cursor("r1", "c2", {"line": 1})
        await asyncio.sleep(0.01)

    async def test_update_cursor_create_task_os_error(self, monkeypatch):
        """asyncio.create_task 抛 OSError → 静默捕获"""
        import asyncio as aio
        e = RealtimeCollabEngine()
        e.create_room("r1", content="x")
        e.join("r1", "c1", AsyncMock())
        e.join("r1", "c2", AsyncMock())

        real_create_task = aio.create_task

        def boom(coro):
            # 先关闭协程避免警告
            coro.close()
            raise OSError("system err")
        monkeypatch.setattr(aio, "create_task", boom)

        # 不应抛出异常
        e.update_cursor("r1", "c2", {"line": 1})
        await asyncio.sleep(0.01)


# ══════════════════════════════════════════════════════════
# list_rooms
# ══════════════════════════════════════════════════════════

class TestListRooms:
    def test_empty(self):
        e = RealtimeCollabEngine()
        assert e.list_rooms() == []

    def test_with_rooms(self):
        e = RealtimeCollabEngine()
        e.create_room("r1", file_path="a.py", content="x")
        e.create_room("r2", file_path="b.py", content="y")
        e._rooms["r1"]["version"] = 3
        rooms = e.list_rooms()
        assert len(rooms) == 2
        ids = {r["room_id"] for r in rooms}
        assert ids == {"r1", "r2"}
        # 验证字段
        for r in rooms:
            assert "clients" in r
            assert "file_path" in r
            assert "version" in r


# ══════════════════════════════════════════════════════════
# get_collab_engine 单例
# ══════════════════════════════════════════════════════════

class TestGetCollabEngine:
    def test_singleton(self, monkeypatch):
        monkeypatch.setattr(rc_mod, "_collab_engine", None)
        e1 = get_collab_engine()
        e2 = get_collab_engine()
        assert e1 is e2

    def test_returns_engine(self, monkeypatch):
        monkeypatch.setattr(rc_mod, "_collab_engine", None)
        assert isinstance(get_collab_engine(), RealtimeCollabEngine)
