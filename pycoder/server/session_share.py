"""
会话共享 — WebSocket 多播支持 + 冲突检测

允许多个客户端共享同一个会话，实现类似 Live Share 的实时协作。
基于内存发布-订阅模式，无需外部依赖。

改进说明 (v2):
    - 新增冲突检测: 检测同一文件的并发编辑，阻止冲突写入
    - 新增编辑锁定: 用户编辑文件时锁定，其他用户看到只读提示
    - 新增操作日志: 记录所有客户端的文件操作

端点:
    WebSocket 发送 {"type": "share_join", "session_id": "xxx"}
    WebSocket 发送 {"type": "share_leave"}
    WebSocket 发送 {"type": "file_lock", "file_path": "xxx"}  # 请求编辑锁
    WebSocket 发送 {"type": "file_unlock", "file_path": "xxx"}  # 释放编辑锁
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class FileLock:
    """文件编辑锁 — 防止多人同时编辑同一文件"""

    def __init__(self):
        self._locks: dict[str, str] = {}  # file_path → client_id
        self._lock_time: dict[str, float] = {}  # file_path → timestamp

    def acquire(self, file_path: str, client_id: str, timeout_s: int = 120) -> bool:
        """尝试获取文件锁，超时自动释放"""
        now = time.time()
        # 检查锁是否超时
        if file_path in self._locks:
            locked_since = self._lock_time.get(file_path, 0)
            if now - locked_since > timeout_s:
                # 注意：标准 logging 不接受任意 kwarg，使用 %s 格式化
                logger.warning(
                    "file_lock_timeout_released: file=%s owner=%s",
                    file_path,
                    self._locks[file_path],
                )
                del self._locks[file_path]
                del self._lock_time[file_path]
            elif self._locks[file_path] != client_id:
                return False  # 被其他人锁定

        self._locks[file_path] = client_id
        self._lock_time[file_path] = now
        return True

    def release(self, file_path: str, client_id: str) -> bool:
        """释放文件锁"""
        if self._locks.get(file_path) == client_id:
            del self._locks[file_path]
            self._lock_time.pop(file_path, None)
            return True
        return False

    def get_locked_by(self, file_path: str) -> str | None:
        """获取文件锁的持有者"""
        return self._locks.get(file_path)

    def list_locks(self) -> list[dict]:
        """列出所有活跃锁"""
        return [{"file": fp, "client": cid} for fp, cid in self._locks.items()]


class SessionShareManager:
    """
    会话共享管理器 — 将一个会话的 WebSocket 消息多播给所有订阅者。

    工作方式:
      1. 客户端 A 加入会话 "s1"
      2. 客户端 B 加入同一会话 "s1"
      3. A 发送 chat 消息 → 服务器处理 → 结果多播给 A+B
      4. A 关闭 → B 继续接收
    """

    def __init__(self):
        self._rooms: dict[str, set[str]] = {}  # session_id → {client_id}
        self._clients: dict[str, dict] = {}  # client_id → {session_id, send_func}
        self._file_lock = FileLock()
        self._operation_log: list[dict] = []  # 操作日志

    @property
    def file_lock(self) -> FileLock:
        return self._file_lock

    @property
    def active_rooms(self) -> list[dict]:
        """获取活跃的共享会话列表"""
        return [
            {"session_id": sid, "clients": len(members)}
            for sid, members in self._rooms.items()
            if len(members) > 1
        ]

    def get_recent_operations(self, limit: int = 20) -> list[dict]:
        """获取最近的操作日志"""
        return self._operation_log[-limit:]

    def log_operation(self, client_id: str, op_type: str, detail: str):
        """记录操作日志"""
        self._operation_log.append(
            {
                "client_id": client_id[:8],
                "type": op_type,
                "detail": detail,
                "timestamp": time.time(),
            }
        )
        if len(self._operation_log) > 1000:
            self._operation_log = self._operation_log[-500:]

    def join(self, client_id: str, session_id: str, send_func: Callable):
        """
        客户端加入会话共享。

        Args:
            client_id: 客户端唯一 ID
            session_id: 要共享的会话 ID
            send_func: `async def send(data: str)` — 向该客户端发送数据的方法
        """
        if session_id not in self._rooms:
            self._rooms[session_id] = set()
        self._rooms[session_id].add(client_id)
        self._clients[client_id] = {"session_id": session_id, "send": send_func}
        count = len(self._rooms[session_id])
        # 注意：标准 logging 不接受任意 kwarg，使用 %s 格式化
        logger.info(
            "session_share_join: client=%s session=%s total=%s",
            client_id[:8],
            session_id[:8],
            count,
        )
        return count

    def leave(self, client_id: str):
        """客户端离开共享"""
        info = self._clients.pop(client_id, None)
        if info:
            session_id = info["session_id"]
            room = self._rooms.get(session_id)
            if room:
                room.discard(client_id)
                if not room:
                    del self._rooms[session_id]

    async def broadcast(self, session_id: str, data: dict, exclude: str = ""):
        """
        向共享会话的所有客户端广播消息。

        Args:
            session_id: 会话 ID
            data: 要广播的数据字典（会自动 JSON 序列化）
            exclude: 排除的客户端 ID（不向自己广播）
        """
        room = self._rooms.get(session_id)
        if not room or len(room) < 2:
            return  # 只有一个人，不需要广播

        payload = json.dumps(data)
        tasks = []
        for cid in room:
            if cid == exclude:
                continue
            info = self._clients.get(cid)
            if info:
                tasks.append(self._safe_send(info["send"], payload, cid))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, send_func: Callable, payload: str, cid: str):
        try:
            await send_func(payload)
        except Exception as e:
            # 注意：标准 logging 不接受任意 kwarg，使用 %s 格式化
            logger.warning(
                "session_share_send_failed: client=%s error=%s",
                cid[:8],
                e,
            )
            # 发送失败 → 自动断开
            self.leave(cid)

    def get_shared_sessions(self, session_id: str) -> int:
        """获取一个会话的共享人数"""
        room = self._rooms.get(session_id)
        return len(room) if room else 0


# 全局单例
_share_manager: SessionShareManager | None = None


def get_session_share_manager() -> SessionShareManager:
    global _share_manager
    if _share_manager is None:
        _share_manager = SessionShareManager()
    return _share_manager
