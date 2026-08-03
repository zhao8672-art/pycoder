"""功能测试: pycoder/server/realtime_collab.py 增强能力

覆盖内容:
  - OT 变换: 并发 insert/insert（不同位置 + 同位置 tiebreak 收敛）
  - OT 变换: insert/delete、delete/delete 变换收敛
  - revision 单调递增
  - SQLite 持久化与断线重连恢复（文档 + 最新 revision）
  - 用户身份（用户名/颜色）与读写权限校验
  - 房间容量限制与操作频率限制

测试策略:
  - 直接调用引擎方法，AsyncMock 模拟 send_func
  - 每个测试使用 tmp_path 下的独立 SQLite，避免污染真实存储
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from pycoder.server.realtime_collab import (
    RealtimeCollabEngine,
    transform_operation,
)


@pytest.fixture
def engine(tmp_path):
    """构建使用临时 SQLite 的引擎实例"""
    return RealtimeCollabEngine(db_path=tmp_path / "collab_test.db")


# ══════════════════════════════════════════════════════════
# 并发 insert/insert 变换
# ══════════════════════════════════════════════════════════


class TestConcurrentInsertInsert:
    async def test_different_positions(self, engine):
        """不同位置并发插入 → 后发操作位置正确偏移"""
        engine.create_room("r1", content="hello")
        engine.join("r1", "c1", AsyncMock())
        engine.join("r1", "c2", AsyncMock())

        # c1 基于 rev0 在开头插入 "A"
        r1 = await engine.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "A"},
            base_revision=0,
        )
        assert r1["success"] is True
        assert engine._documents["r1"] == "Ahello"

        # c2 基于 rev0 在末尾插入 "B"（与 c1 并发）→ 位置应 +1
        r2 = await engine.apply_operation(
            "r1", "c2", {"type": "insert", "position": 5, "text": "B"},
            base_revision=0,
        )
        assert r2["success"] is True
        assert r2["operation"]["position"] == 6
        assert engine._documents["r1"] == "AhelloB"

    async def test_same_position_deterministic_convergence(self, engine):
        """同位置并发插入 → 按 client_id 字典序裁决，两端收敛一致"""
        # 顺序一：c1 先、c2 并发后发
        e1 = RealtimeCollabEngine()
        e1.create_room("r", content="ab")
        e1.join("r", "c1", AsyncMock())
        e1.join("r", "c2", AsyncMock())
        await e1.apply_operation(
            "r", "c1", {"type": "insert", "position": 1, "text": "X"},
            base_revision=0,
        )
        r = await e1.apply_operation(
            "r", "c2", {"type": "insert", "position": 1, "text": "Y"},
            base_revision=0,
        )
        # c1 字典序更小 → c1 的 X 在前，c2 的 Y 被推移到其后
        assert r["operation"]["position"] == 2
        doc_order1 = e1._documents["r"]

        # 顺序二：c2 先、c1 并发后发 → 结果必须一致
        e2 = RealtimeCollabEngine()
        e2.create_room("r", content="ab")
        e2.join("r", "c1", AsyncMock())
        e2.join("r", "c2", AsyncMock())
        await e2.apply_operation(
            "r", "c2", {"type": "insert", "position": 1, "text": "Y"},
            base_revision=0,
        )
        await e2.apply_operation(
            "r", "c1", {"type": "insert", "position": 1, "text": "X"},
            base_revision=0,
        )
        doc_order2 = e2._documents["r"]

        assert doc_order1 == "aXYb"
        assert doc_order2 == doc_order1  # 收敛一致


# ══════════════════════════════════════════════════════════
# insert/delete 与 delete/delete 变换
# ══════════════════════════════════════════════════════════


class TestInsertDeleteTransform:
    async def test_insert_after_concurrent_delete(self, engine):
        """insert 位置在并发删除区间之后 → 位置前移"""
        engine.create_room("r1", content="hello world")
        engine.join("r1", "c1", AsyncMock())
        engine.join("r1", "c2", AsyncMock())

        # c1 删除 " world"（pos=5, len=6）
        await engine.apply_operation(
            "r1", "c1", {"type": "delete", "position": 5, "length": 6},
            base_revision=0,
        )
        assert engine._documents["r1"] == "hello"

        # c2 基于 rev0 在原位置 11 插入 "!" → 应变换到位置 5
        r = await engine.apply_operation(
            "r1", "c2", {"type": "insert", "position": 11, "text": "!"},
            base_revision=0,
        )
        assert r["operation"]["position"] == 5
        assert engine._documents["r1"] == "hello!"

    async def test_insert_inside_concurrent_delete_snaps_to_start(self, engine):
        """insert 位置落入并发删除区间 → 吸附到区间起点"""
        engine.create_room("r1", content="abcdef")
        engine.join("r1", "c1", AsyncMock())
        engine.join("r1", "c2", AsyncMock())

        # c1 删除 [2, 5) 即 "cde"
        await engine.apply_operation(
            "r1", "c1", {"type": "delete", "position": 2, "length": 3},
            base_revision=0,
        )
        assert engine._documents["r1"] == "abf"

        # c2 基于 rev0 在 pos=3（已删区间内）插入 → 吸附到 2
        r = await engine.apply_operation(
            "r1", "c2", {"type": "insert", "position": 3, "text": "Z"},
            base_revision=0,
        )
        assert r["operation"]["position"] == 2
        assert engine._documents["r1"] == "abZf"

    async def test_delete_overlapping_concurrent_delete(self, engine):
        """delete 与并发 delete 重叠 → 区间裁剪，不重复删除"""
        engine.create_room("r1", content="abcdef")
        engine.join("r1", "c1", AsyncMock())
        engine.join("r1", "c2", AsyncMock())

        # c1 删除 [1, 5) 即 "bcde"
        await engine.apply_operation(
            "r1", "c1", {"type": "delete", "position": 1, "length": 4},
            base_revision=0,
        )
        assert engine._documents["r1"] == "af"

        # c2 基于 rev0 删除 [2, 4) 即 "cd"（已被 c1 删除）→ 裁剪为空操作
        r = await engine.apply_operation(
            "r1", "c2", {"type": "delete", "position": 2, "length": 2},
            base_revision=0,
        )
        assert r["success"] is True
        assert r["operation"]["length"] == 0
        assert engine._documents["r1"] == "af"

    async def test_delete_before_concurrent_insert(self, engine):
        """delete 区间之前发生并发插入 → 整体后移"""
        engine.create_room("r1", content="abcdef")
        engine.join("r1", "c1", AsyncMock())
        engine.join("r1", "c2", AsyncMock())

        # c1 在开头插入 "XX"
        await engine.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "XX"},
            base_revision=0,
        )
        # c2 基于 rev0 删除 [0, 2) → 应后移到 [2, 4)
        r = await engine.apply_operation(
            "r1", "c2", {"type": "delete", "position": 0, "length": 2},
            base_revision=0,
        )
        assert r["operation"]["position"] == 2
        assert engine._documents["r1"] == "XXcdef"


class TestTransformOperationPure:
    """transform_operation 纯函数边界行为"""

    def test_replace_not_transformed(self):
        op = {"type": "replace", "content": "new"}
        assert transform_operation(op, {"type": "insert", "position": 0, "text": "x"}) == op

    def test_insert_before_insert(self):
        op = {"type": "insert", "position": 5, "text": "B"}
        other = {"type": "insert", "position": 2, "text": "AA"}
        assert transform_operation(op, other)["position"] == 7

    def test_insert_after_insert_unaffected(self):
        op = {"type": "insert", "position": 1, "text": "B"}
        other = {"type": "insert", "position": 5, "text": "AA"}
        assert transform_operation(op, other)["position"] == 1

    def test_delete_inside_insert_extends_length(self):
        """插入落在删除区间内部 → 删除长度增加（连带删除新内容）"""
        op = {"type": "delete", "position": 2, "length": 3}
        other = {"type": "insert", "position": 3, "text": "XX"}
        result = transform_operation(op, other)
        assert result["position"] == 2
        assert result["length"] == 5


# ══════════════════════════════════════════════════════════
# revision 单调性
# ══════════════════════════════════════════════════════════


class TestRevisionMonotonic:
    async def test_revision_increments(self, engine):
        """每次成功操作 revision 严格 +1"""
        engine.create_room("r1", content="")
        engine.join("r1", "c1", AsyncMock())
        revisions = []
        for i in range(3):
            r = await engine.apply_operation(
                "r1", "c1", {"type": "insert", "position": i, "text": str(i)},
            )
            assert r["success"] is True
            revisions.append(r["revision"])
        assert revisions == [1, 2, 3]

    async def test_revision_not_advanced_on_failure(self, engine):
        """失败操作不推进 revision"""
        engine.create_room("r1", content="x")
        engine.join("r1", "c1", AsyncMock(), role="viewer")
        r = await engine.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "y"},
        )
        assert r["success"] is False
        assert engine._rooms["r1"]["version"] == 0

    async def test_join_reports_current_revision(self, engine):
        """join 返回的 revision 与当前版本一致"""
        engine.create_room("r1", content="doc")
        engine.join("r1", "c1", AsyncMock())
        await engine.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "!"},
        )
        info = engine.join("r1", "c2", AsyncMock())
        assert info["revision"] == 1
        assert info["document"] == "!doc"


# ══════════════════════════════════════════════════════════
# SQLite 持久化与断线恢复
# ══════════════════════════════════════════════════════════


class TestPersistence:
    async def test_reconnect_restores_document_and_revision(self, tmp_path):
        """同一引擎内：全部离开后重新 join → 从 SQLite 恢复"""
        db = tmp_path / "rooms.db"
        e = RealtimeCollabEngine(db_path=db)
        e.create_room("r1", content="hello")
        e.join("r1", "c1", AsyncMock())
        await e.apply_operation(
            "r1", "c1", {"type": "insert", "position": 5, "text": "!"},
        )
        e.leave("c1")  # 最后一人离开 → 落盘并释放内存
        assert "r1" not in e._rooms

        # 断线重连：join 应恢复文档与 revision
        info = e.join("r1", "c2", AsyncMock())
        assert info["success"] is True
        assert info["document"] == "hello!"
        assert info["revision"] == 1

    async def test_new_engine_instance_recovers_room(self, tmp_path):
        """服务重启场景：新引擎实例从同一 SQLite 恢复房间"""
        db = tmp_path / "rooms.db"
        e1 = RealtimeCollabEngine(db_path=db)
        e1.create_room("r1", content="base")
        e1.join("r1", "c1", AsyncMock())
        await e1.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "# "},
        )
        e1.leave("c1")

        # 模拟服务重启：全新引擎 + 同一 DB 文件
        e2 = RealtimeCollabEngine(db_path=db)
        assert "r1" not in e2._rooms  # 内存中不存在
        info = e2.join("r1", "c2", AsyncMock())
        assert info["document"] == "# base"
        assert info["revision"] == 1
        # 恢复后继续编辑，revision 继续递增
        r = await e2.apply_operation(
            "r1", "c2", {"type": "insert", "position": 6, "text": "!"},
        )
        assert r["revision"] == 2
        assert e2._documents["r1"] == "# base!"

    async def test_empty_room_record_pruned(self, tmp_path):
        """从未编辑的空房间在最后一人离开后不留持久化记录"""
        db = tmp_path / "rooms.db"
        e = RealtimeCollabEngine(db_path=db)
        e.join("r1", "c1", AsyncMock())
        e.leave("c1")
        row = e._db.execute(
            "SELECT COUNT(*) FROM collab_rooms WHERE room_id = 'r1'"
        ).fetchone()
        assert row[0] == 0


# ══════════════════════════════════════════════════════════
# 身份与权限
# ══════════════════════════════════════════════════════════


class TestIdentityPermission:
    def test_join_assigns_identity(self, engine):
        """join 分配用户名/颜色/角色并出现在成员列表"""
        info = engine.join("r1", "c1", AsyncMock(), username="小明", role="owner")
        assert info["self"]["username"] == "小明"
        assert info["self"]["role"] == "owner"
        assert info["self"]["color"].startswith("#")
        members = info["members"]
        assert len(members) == 1
        assert members[0]["username"] == "小明"
        assert members[0]["online"] is True

    def test_reconnect_keeps_identity(self, engine):
        """重连沿用既有身份（颜色不变）"""
        engine.join("r1", "c1", AsyncMock(), username="小明")
        color1 = engine.get_member("r1", "c1")["color"]
        # c2 加入保持房间存活，c1 离开后成员记录保留
        engine.join("r1", "c2", AsyncMock())
        engine.leave("c1")
        engine.join("r1", "c1", AsyncMock())
        assert engine.get_member("r1", "c1")["color"] == color1

    async def test_viewer_cannot_edit(self, engine):
        """viewer 角色的编辑操作被拒绝"""
        engine.join("r1", "owner", AsyncMock(), role="owner")
        engine.join("r1", "v1", AsyncMock(), role="viewer")
        r = await engine.apply_operation(
            "r1", "v1", {"type": "insert", "position": 0, "text": "x"},
        )
        assert r["success"] is False
        assert "权限" in r["error"]

    async def test_editor_can_edit(self, engine):
        """editor 角色可正常编辑"""
        engine.join("r1", "e1", AsyncMock(), role="editor")
        r = await engine.apply_operation(
            "r1", "e1", {"type": "insert", "position": 0, "text": "x"},
        )
        assert r["success"] is True

    async def test_unknown_client_cannot_edit(self, engine):
        """房间已有成员时，未加入的客户端无权编辑"""
        engine.create_room("r1", content="x")
        engine.join("r1", "owner", AsyncMock(), role="owner")
        r = await engine.apply_operation(
            "r1", "ghost", {"type": "insert", "position": 0, "text": "y"},
        )
        assert r["success"] is False

    async def test_unmanaged_room_allows_edit(self, engine):
        """兼容旧用法：无成员记录的房间（仅 create_room）允许直接编辑"""
        engine.create_room("r1", content="x")
        r = await engine.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "y"},
        )
        assert r["success"] is True
        assert engine._documents["r1"] == "yx"

    async def test_leave_marks_member_offline(self, engine):
        """离开后成员标记为离线（房间仍有其他人时）"""
        engine.join("r1", "c1", AsyncMock(), username="A")
        engine.join("r1", "c2", AsyncMock(), username="B")
        engine.leave("c1")
        member = engine.get_member("r1", "c1")
        assert member["online"] is False


# ══════════════════════════════════════════════════════════
# 容量与频率限制
# ══════════════════════════════════════════════════════════


class TestCapacityLimit:
    def test_room_full_rejects_new_client(self, tmp_path):
        """房间达到容量上限 → 新客户端被拒绝"""
        e = RealtimeCollabEngine(
            db_path=tmp_path / "c.db", max_clients_per_room=2,
        )
        assert e.join("r1", "c1", AsyncMock())["success"] is True
        assert e.join("r1", "c2", AsyncMock())["success"] is True
        r = e.join("r1", "c3", AsyncMock())
        assert r["success"] is False
        assert "已满" in r["error"]

    def test_rejoin_does_not_consume_slot(self, tmp_path):
        """已在房间的客户端重连不占用新名额"""
        e = RealtimeCollabEngine(
            db_path=tmp_path / "c.db", max_clients_per_room=2,
        )
        e.join("r1", "c1", AsyncMock())
        e.join("r1", "c2", AsyncMock())
        # c1 重复 join（重连）应成功
        assert e.join("r1", "c1", AsyncMock())["success"] is True

    def test_leave_frees_slot(self, tmp_path):
        """离开释放名额后新客户端可加入"""
        e = RealtimeCollabEngine(
            db_path=tmp_path / "c.db", max_clients_per_room=2,
        )
        e.join("r1", "c1", AsyncMock())
        e.join("r1", "c2", AsyncMock())
        e.leave("c1")
        assert e.join("r1", "c3", AsyncMock())["success"] is True


class TestRateLimit:
    async def test_ops_rate_limited(self, tmp_path):
        """超出每秒操作上限 → 操作被拒绝"""
        e = RealtimeCollabEngine(
            db_path=tmp_path / "rl.db", max_ops_per_second=3,
        )
        e.create_room("r1", content="")
        e.join("r1", "c1", AsyncMock())
        results = []
        for _ in range(4):
            r = await e.apply_operation(
                "r1", "c1", {"type": "insert", "position": 0, "text": "x"},
            )
            results.append(r["success"])
        assert results == [True, True, True, False]

    async def test_rate_limit_per_client(self, tmp_path):
        """限流按客户端隔离，互不影响"""
        e = RealtimeCollabEngine(
            db_path=tmp_path / "rl.db", max_ops_per_second=1,
        )
        e.create_room("r1", content="")
        e.join("r1", "c1", AsyncMock())
        e.join("r1", "c2", AsyncMock())
        r1 = await e.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "a"},
        )
        r2 = await e.apply_operation(
            "r1", "c2", {"type": "insert", "position": 0, "text": "b"},
        )
        assert r1["success"] is True
        assert r2["success"] is True  # c2 的配额独立

    async def test_oversized_insert_rejected(self, engine):
        """单次插入超长文本被拒绝"""
        engine.create_room("r1", content="")
        engine.join("r1", "c1", AsyncMock())
        r = await engine.apply_operation(
            "r1", "c1",
            {"type": "insert", "position": 0, "text": "x" * 100_001},
        )
        assert r["success"] is False


# ══════════════════════════════════════════════════════════
# 广播消息内容（ack / 变换后操作）
# ══════════════════════════════════════════════════════════


class TestBroadcast:
    async def test_broadcast_carries_transformed_operation(self, engine):
        """广播携带变换后的操作与最新 revision"""
        engine.create_room("r1", content="ab")
        s2 = AsyncMock()
        engine.join("r1", "c1", AsyncMock())
        engine.join("r1", "c2", s2)

        # c1 先插入，c2 收到广播
        await engine.apply_operation(
            "r1", "c1", {"type": "insert", "position": 0, "text": "X"},
            base_revision=0,
        )
        msg = json.loads(s2.await_args.args[0])
        assert msg["type"] == "collab_operation"
        assert msg["revision"] == 1
        assert msg["operation"]["position"] == 0

        # c2 基于 rev0 并发操作 → 广播给 c1 的应是变换后操作
        s1 = AsyncMock()
        engine._clients["c1"]["send"] = s1
        r = await engine.apply_operation(
            "r1", "c2", {"type": "insert", "position": 0, "text": "Y"},
            base_revision=0,
        )
        assert r["operation"]["position"] == 1  # 变换后位置
        msg2 = json.loads(s1.await_args.args[0])
        assert msg2["operation"]["position"] == 1
        assert msg2["revision"] == 2
