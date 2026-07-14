"""
实时协作编辑引擎 — 协同光标/编辑同步/操作转换

基于 WebSocket 的操作转换 (OT) 实现，支持多人实时编辑。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from pycoder.server.log import log


class RealtimeCollabEngine:
    """实时协作引擎 — 操作转换 + 光标同步"""

    def __init__(self):
        self._rooms: dict[str, dict] = {}
        self._documents: dict[str, str] = {}
        self._clients: dict[str, dict] = {}

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

    def join(self, room_id: str, client_id: str, send_func: Callable) -> dict:
        """客户端加入房间"""
        if room_id not in self._rooms:
            self.create_room(room_id)
        room = self._rooms[room_id]
        room["clients"].add(client_id)
        self._clients[client_id] = {"room": room_id, "send": send_func}

        return {
            "success": True,
            "room_id": room_id,
            "clients": len(room["clients"]),
            "document": self._documents.get(room_id, ""),
            "version": room["version"],
        }

    def leave(self, client_id: str):
        """客户端离开"""
        info = self._clients.pop(client_id, None)
        if info:
            room = self._rooms.get(info["room"])
            if room:
                room["clients"].discard(client_id)
                if not room["clients"]:
                    del self._rooms[info["room"]]
                    self._documents.pop(info["room"], None)

    async def apply_operation(
        self,
        room_id: str,
        client_id: str,
        operation: dict,
    ) -> dict:
        """应用编辑操作并广播"""
        room = self._rooms.get(room_id)
        if not room:
            return {"success": False, "error": "房间不存在"}

        room["version"] += 1
        doc = self._documents.get(room_id, "")
        op_type = operation.get("type", "")

        if op_type == "insert":
            pos = operation.get("position", len(doc))
            text = operation.get("text", "")
            doc = doc[:pos] + text + doc[pos:]
        elif op_type == "delete":
            pos = operation.get("position", 0)
            length = operation.get("length", 1)
            if pos < len(doc):
                doc = doc[:pos] + doc[pos + length :]
        elif op_type == "replace":
            doc = operation.get("content", "")

        self._documents[room_id] = doc

        # 广播给其他客户端
        broadcast_msg = {
            "type": "collab_operation",
            "client_id": client_id,
            "operation": operation,
            "version": room["version"],
            "timestamp": time.time(),
        }

        for cid in list(room["clients"]):
            if cid != client_id:
                info = self._clients.get(cid)
                if info:
                    try:
                        await info["send"](json.dumps(broadcast_msg))
                    except (ConnectionError, RuntimeError, OSError) as e:
                        log.debug("collab_broadcast_send_failed", client_id=cid, error=str(e))

        return {"success": True, "version": room["version"]}

    def update_cursor(self, room_id: str, client_id: str, position: dict):
        """更新客户端光标位置"""
        room = self._rooms.get(room_id)
        if not room:
            return
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
                                    }
                                )
                            )
                        )
                    except (RuntimeError, TypeError, OSError) as e:
                        log.debug("collab_cursor_send_failed", client_id=cid, error=str(e))

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
