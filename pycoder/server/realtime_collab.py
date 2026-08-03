"""
实时协作编辑引擎 — 服务端权威房间状态 + 操作转换 (OT)

增强能力（相对初版）：
- 单调递增 revision 序号，操作基于 revision 做位置变换 (transform)，
  处理并发 insert/delete 冲突，保证多客户端收敛一致
- 房间状态持久化到 SQLite（默认 Path.home()/'.pycoder'/'collab_rooms.db'），
  断线重连可恢复文档内容与最新 revision
- 用户身份（用户名/颜色）与读写权限（owner/editor/viewer）
- 房间容量与操作频率限制，防止滥用

协议约定：
- 客户端发送 edit 时携带 ``base_revision``（操作所基于的服务端版本）
- 服务端将操作对 ``(base_revision, 当前 revision]`` 区间内的并发操作依次做
  transform 后应用，并广播**变换后**的操作
- insert/insert 同位置冲突按 client_id 字典序裁决，保证两端确定性收敛
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from pycoder.core.services.log import log

# ── 默认限制（构造时可覆盖，便于测试） ──
DEFAULT_MAX_CLIENTS_PER_ROOM = 8  # 单房间最大在线人数
DEFAULT_MAX_OPS_PER_SECOND = 20  # 单客户端每秒最大操作数
MAX_TEXT_LENGTH = 100_000  # 单次插入最大字符数
MAX_DOCUMENT_LENGTH = 5_000_000  # 单文档最大字符数
_OP_LOG_KEEP = 500  # 房间内保留的最大操作日志条数

# 只读角色集合
READ_ONLY_ROLES = frozenset({"viewer"})

# 成员光标颜色候选池（按加入顺序分配）
_COLOR_POOL = [
    "#ff6b6b", "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7",
    "#dda0dd", "#98d8c8", "#f7dc6f", "#bb8fce", "#85c1e9",
]

# SQLite 建表语句
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS collab_rooms (
    room_id TEXT PRIMARY KEY,
    document TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    file_path TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
)
"""


def transform_operation(op: dict, other: dict) -> dict:
    """将操作 ``op`` 对并发操作 ``other`` 做位置变换

    语义：``op`` 与 ``other`` 基于同一文档版本并发产生，本函数返回
    "假设 other 已先应用" 之后 ``op`` 应采用的形式。

    变换规则（insert/delete 位置变换）：
    - insert vs insert：other 位置 < op 位置 → 后移；同位置按
      ``(tiebreak, client_id)`` 字典序裁决，保证两端确定性收敛
    - insert vs delete：other 删除区间在 op 位置之前 → 前移；
      op 位置落入删除区间 → 吸附到区间起点
    - delete vs insert：other 插入在区间起点前 → 整体后移；
      插入在区间内 → 区间变长
    - delete vs delete：按区间重叠裁剪（起终点分别做删除映射）
    - replace：不做变换（全量覆盖，由调用方按最后写入生效处理）
    """
    op_type = op.get("type", "")
    other_type = other.get("type", "")
    if op_type == "replace" or other_type == "replace":
        return dict(op)

    result = dict(op)

    if op_type == "insert":
        pos = op.get("position", 0)
        if other_type == "insert":
            o_pos = other.get("position", 0)
            o_len = len(other.get("text", ""))
            if o_pos < pos or (
                o_pos == pos
                and (other.get("tiebreak", 1), other.get("client_id", ""))
                < (op.get("tiebreak", 1), op.get("client_id", ""))
            ):
                result["position"] = pos + o_len
        elif other_type == "delete":
            o_pos = other.get("position", 0)
            o_len = other.get("length", 0)
            if pos > o_pos:
                result["position"] = max(o_pos, pos - o_len)
    elif op_type == "delete":
        pos = op.get("position", 0)
        end = pos + op.get("length", 0)
        if other_type == "insert":
            o_pos = other.get("position", 0)
            o_len = len(other.get("text", ""))
            if o_pos <= pos:
                # 插入在区间起点（含重合边界）之前 → 整体后移
                # 边界约定：插入视为发生在被删文本之前，与 insert vs
                # delete 的吸附规则配合可保证两端收敛一致
                result["position"] = pos + o_len
            elif o_pos < end:
                # 插入落在删除区间内 → 删除长度增加
                result["length"] = op.get("length", 0) + o_len
        elif other_type == "delete":
            o_pos = other.get("position", 0)
            o_len = other.get("length", 0)
            o_end = o_pos + o_len
            # 起点映射：other 删除了 [o_pos, o_end)，其后的位置前移
            if pos >= o_end:
                new_pos = pos - o_len
            elif pos > o_pos:
                new_pos = o_pos
            else:
                new_pos = pos
            # 终点映射
            if end >= o_end:
                new_end = end - o_len
            elif end > o_pos:
                new_end = o_pos
            else:
                new_end = end
            result["position"] = new_pos
            result["length"] = max(0, new_end - new_pos)
    return result


class RealtimeCollabEngine:
    """实时协作引擎 — OT 操作转换 + 光标同步 + 房间持久化"""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        max_clients_per_room: int = DEFAULT_MAX_CLIENTS_PER_ROOM,
        max_ops_per_second: int = DEFAULT_MAX_OPS_PER_SECOND,
    ) -> None:
        self._rooms: dict[str, dict] = {}
        self._documents: dict[str, str] = {}
        self._clients: dict[str, dict] = {}
        self._op_log: dict[str, list[dict]] = {}
        self._members: dict[str, dict[str, dict]] = {}
        self._rate_limit: dict[str, list[float]] = {}
        self._max_clients = max_clients_per_room
        self._max_ops = max_ops_per_second
        self._db_path = (
            Path(db_path)
            if db_path is not None
            else Path.home() / ".pycoder" / "collab_rooms.db"
        )
        self._db: sqlite3.Connection | None = None
        self._init_db()

    # ─────────────────────────────────────────────────────
    # SQLite 持久化
    # ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """初始化 SQLite 存储（失败时降级为纯内存模式）"""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._db.execute(_SCHEMA_SQL)
            self._db.commit()
        except (OSError, sqlite3.Error) as e:
            log.warning("collab_db_init_failed", error=str(e))
            self._db = None

    def _persist_room(self, room_id: str) -> None:
        """将房间文档与 revision 写入 SQLite"""
        if self._db is None:
            return
        room = self._rooms.get(room_id)
        if room is None:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO collab_rooms"
                " (room_id, document, revision, file_path, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    room_id,
                    self._documents.get(room_id, ""),
                    room["version"],
                    room.get("file_path", ""),
                    time.time(),
                ),
            )
            self._db.commit()
        except sqlite3.Error as e:
            log.warning("collab_db_persist_failed", room_id=room_id, error=str(e))

    def _load_persisted_room(self, room_id: str) -> bool:
        """从 SQLite 恢复房间文档与 revision（用于断线重连/服务重启恢复）"""
        if self._db is None:
            return False
        try:
            row = self._db.execute(
                "SELECT document, revision, file_path FROM collab_rooms"
                " WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        except sqlite3.Error as e:
            log.warning("collab_db_load_failed", room_id=room_id, error=str(e))
            return False
        if row is None:
            return False
        document, revision, file_path = row
        self._documents[room_id] = document
        self.create_room(room_id, file_path=file_path or "")
        self._rooms[room_id]["version"] = revision
        log.info("collab_room_restored", room_id=room_id, revision=revision)
        return True

    def _prune_room(self, room_id: str) -> None:
        """清理持久化记录：长期空闲的房间从 SQLite 移除，活跃房间仅刷新时间戳"""
        if self._db is None:
            return
        try:
            row = self._db.execute(
                "SELECT revision FROM collab_rooms WHERE room_id = ?", (room_id,)
            ).fetchone()
            if row is not None and row[0] == 0:
                # 从未产生编辑的空房间直接清除，避免记录膨胀
                self._db.execute(
                    "DELETE FROM collab_rooms WHERE room_id = ?", (room_id,)
                )
                self._db.commit()
        except sqlite3.Error as e:
            log.debug("collab_db_prune_failed", room_id=room_id, error=str(e))

    # ─────────────────────────────────────────────────────
    # 房间与成员管理
    # ─────────────────────────────────────────────────────

    def create_room(self, room_id: str, file_path: str = "", content: str = ""):
        """创建协作房间"""
        self._rooms[room_id] = {
            "file_path": file_path,
            "clients": set(),
            "created_at": time.time(),
            "version": 0,
        }
        if content:
            self._documents[room_id] = content

    def join(
        self,
        room_id: str,
        client_id: str,
        send_func: Callable,
        username: str = "",
        role: str = "editor",
        color: str = "",
    ) -> dict:
        """客户端加入房间

        不存在时先尝试从 SQLite 恢复（断线重连/服务重启场景），
        否则创建新房间。返回当前文档、最新 revision 与成员列表，
        供客户端完成断线恢复同步。
        """
        if room_id not in self._rooms:
            if not self._load_persisted_room(room_id):
                self.create_room(room_id)
        room = self._rooms[room_id]

        # 容量限制：已在房间的客户端重连不占用新名额
        if (
            client_id not in room["clients"]
            and len(room["clients"]) >= self._max_clients
        ):
            return {
                "success": False,
                "error": f"房间已满（上限 {self._max_clients} 人）",
                "room_id": room_id,
            }

        room["clients"].add(client_id)
        self._clients[client_id] = {"room": room_id, "send": send_func}

        # 成员身份：用户名 / 颜色 / 读写权限
        members = self._members.setdefault(room_id, {})
        existing = members.get(client_id)
        if existing is not None:
            # 重连沿用既有身份，仅更新权限与在线状态
            existing["role"] = role or existing["role"]
            existing["online"] = True
            if username:
                existing["username"] = username
            member = existing
        else:
            member = {
                "username": username or f"用户-{client_id[-4:]}",
                "color": color or _COLOR_POOL[len(members) % len(_COLOR_POOL)],
                "role": role or "editor",
                "joined_at": time.time(),
                "online": True,
            }
            members[client_id] = member

        return {
            "success": True,
            "room_id": room_id,
            "clients": len(room["clients"]),
            "document": self._documents.get(room_id, ""),
            "version": room["version"],
            "revision": room["version"],
            "members": self._build_member_list(room_id),
            "self": {
                "client_id": client_id,
                "username": member["username"],
                "color": member["color"],
                "role": member["role"],
            },
        }

    def leave(self, client_id: str):
        """客户端离开（保留持久化文档，便于重连恢复）"""
        info = self._clients.pop(client_id, None)
        if info:
            room = self._rooms.get(info["room"])
            if room:
                room["clients"].discard(client_id)
                member = self._members.get(info["room"], {}).get(client_id)
                if member is not None:
                    member["online"] = False
                if not room["clients"]:
                    # 最后一人离开：落盘后释放内存状态
                    self._persist_room(info["room"])
                    self._prune_room(info["room"])
                    del self._rooms[info["room"]]
                    self._documents.pop(info["room"], None)
                    self._op_log.pop(info["room"], None)
                    self._members.pop(info["room"], None)
        self._rate_limit.pop(client_id, None)

    def _build_member_list(self, room_id: str) -> list[dict]:
        """构建房间成员列表（含用户名/颜色/角色/在线状态）"""
        return [
            {
                "client_id": cid,
                "username": m["username"],
                "color": m["color"],
                "role": m["role"],
                "online": m["online"],
            }
            for cid, m in self._members.get(room_id, {}).items()
        ]

    def get_member(self, room_id: str, client_id: str) -> dict | None:
        """获取房间成员信息"""
        return self._members.get(room_id, {}).get(client_id)

    def can_edit(self, room_id: str, client_id: str) -> bool:
        """校验客户端是否具备写权限

        兼容语义：房间内尚无任何成员记录（如通过 create_room 直接
        编程使用的场景）时放行；一旦有人 join 即按角色严格校验。
        """
        members = self._members.get(room_id)
        if not members:
            return True
        member = members.get(client_id)
        if member is None:
            return False
        return member["role"] not in READ_ONLY_ROLES

    # ─────────────────────────────────────────────────────
    # 频率限制
    # ─────────────────────────────────────────────────────

    def _check_rate_limit(self, client_id: str) -> bool:
        """滑动窗口限流：单客户端每秒操作数不超过上限"""
        now = time.monotonic()
        window = self._rate_limit.setdefault(client_id, [])
        # 仅保留 1 秒窗口内的时间戳
        window[:] = [t for t in window if now - t < 1.0]
        if len(window) >= self._max_ops:
            return False
        window.append(now)
        return True

    # ─────────────────────────────────────────────────────
    # 操作应用与 OT 变换
    # ─────────────────────────────────────────────────────

    def _apply_to_document(self, doc: str, operation: dict) -> str:
        """将（已变换的）操作直接应用到文档字符串"""
        op_type = operation.get("type", "")
        if op_type == "insert":
            pos = operation.get("position", len(doc))
            pos = max(0, min(pos, len(doc)))
            text = operation.get("text", "")
            doc = doc[:pos] + text + doc[pos:]
        elif op_type == "delete":
            pos = operation.get("position", 0)
            length = operation.get("length", 1)
            if pos < len(doc):
                doc = doc[:pos] + doc[pos + length:]
        elif op_type == "replace":
            doc = operation.get("content", "")
        return doc

    async def apply_operation(
        self,
        room_id: str,
        client_id: str,
        operation: dict,
        base_revision: int | None = None,
    ) -> dict:
        """应用编辑操作并广播

        Args:
            room_id: 房间 ID
            client_id: 发起操作的客户端
            operation: 操作描述（insert/delete/replace）
            base_revision: 操作所基于的服务端版本；``None`` 表示基于当前
                最新版本（兼容旧客户端）。若落后于当前版本，则对区间内
                并发操作依次做 transform 后再应用。

        Returns:
            成功时 ``{"success": True, "version"/"revision": 新版本,
            "operation": 变换后的操作}``；失败时 ``{"success": False,
            "error": 原因}``。
        """
        room = self._rooms.get(room_id)
        if not room:
            return {"success": False, "error": "房间不存在"}

        # 写权限校验
        if not self.can_edit(room_id, client_id):
            return {"success": False, "error": "无编辑权限（只读成员）"}

        # 操作频率限制
        if not self._check_rate_limit(client_id):
            return {"success": False, "error": "操作过于频繁，请稍后再试"}

        # 载荷校验
        op_type = operation.get("type", "")
        if op_type == "insert":
            if len(operation.get("text", "")) > MAX_TEXT_LENGTH:
                return {"success": False, "error": "单次插入内容过长"}
        elif op_type == "replace":
            if len(operation.get("content", "")) > MAX_DOCUMENT_LENGTH:
                return {"success": False, "error": "文档内容过长"}

        current_revision = room["version"]
        if base_revision is None:
            base_revision = current_revision
        base_revision = max(0, min(base_revision, current_revision))

        # 服务端权威 OT：对 (base_revision, current_revision] 区间内的
        # 并发操作依次变换，使后发操作感知并发修改，保证收敛一致
        log_entries = self._op_log.setdefault(room_id, [])
        concurrent = [
            e for e in log_entries
            if e["revision"] > base_revision and e["client_id"] != client_id
        ]
        transformed = dict(operation)
        transformed["client_id"] = client_id
        for entry in concurrent:
            transformed = transform_operation(transformed, entry["operation"])

        # 应用并推进版本
        room["version"] += 1
        doc = self._documents.get(room_id, "")
        doc = self._apply_to_document(doc, transformed)
        if len(doc) > MAX_DOCUMENT_LENGTH:
            room["version"] -= 1  # 回滚版本号
            return {"success": False, "error": "文档长度超出上限"}
        self._documents[room_id] = doc

        # 操作日志（供后续并发变换），按上限截断
        log_entries.append(
            {
                "revision": room["version"],
                "client_id": client_id,
                "operation": transformed,
            }
        )
        if len(log_entries) > _OP_LOG_KEEP:
            del log_entries[: len(log_entries) - _OP_LOG_KEEP]

        self._persist_room(room_id)

        # 广播给其他客户端（携带变换后的操作与最新 revision）
        broadcast_msg = {
            "type": "collab_operation",
            "client_id": client_id,
            "operation": transformed,
            "version": room["version"],
            "revision": room["version"],
            "timestamp": time.time(),
        }

        for cid in list(room["clients"]):
            if cid != client_id:
                info = self._clients.get(cid)
                if info:
                    try:
                        await info["send"](json.dumps(broadcast_msg))
                    except (ConnectionError, RuntimeError, OSError) as e:
                        log.debug(
                            "collab_broadcast_send_failed",
                            client_id=cid,
                            error=str(e),
                        )

        return {
            "success": True,
            "version": room["version"],
            "revision": room["version"],
            "operation": transformed,
        }

    # ─────────────────────────────────────────────────────
    # 光标同步
    # ─────────────────────────────────────────────────────

    def update_cursor(self, room_id: str, client_id: str, position: dict):
        """更新客户端光标位置并广播（附带用户名/颜色）"""
        room = self._rooms.get(room_id)
        if not room:
            return
        member = self._members.get(room_id, {}).get(client_id, {})
        # 广播光标位置
        for cid in room["clients"]:
            if cid != client_id:
                info = self._clients.get(cid)
                if info:
                    try:
                        asyncio = __import__("asyncio")
                        asyncio.create_task(
                            info["send"](
                                json.dumps(
                                    {
                                        "type": "cursor_update",
                                        "client_id": client_id,
                                        "position": position,
                                        "username": member.get("username", ""),
                                        "color": member.get("color", ""),
                                    }
                                )
                            )
                        )
                    except (RuntimeError, TypeError, OSError) as e:
                        log.debug(
                            "collab_cursor_send_failed",
                            client_id=cid,
                            error=str(e),
                        )

    # ─────────────────────────────────────────────────────
    # 房间查询
    # ─────────────────────────────────────────────────────

    def list_rooms(self) -> list[dict]:
        """列出所有活跃房间"""
        return [
            {
                "room_id": rid,
                "clients": len(room["clients"]),
                "file_path": room.get("file_path", ""),
                "version": room["version"],
            }
            for rid, room in self._rooms.items()
        ]


_collab_engine: RealtimeCollabEngine | None = None


def get_collab_engine() -> RealtimeCollabEngine:
    global _collab_engine
    if _collab_engine is None:
        _collab_engine = RealtimeCollabEngine()
    return _collab_engine
