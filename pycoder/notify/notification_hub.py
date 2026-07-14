"""通知中心 — 多渠道消息推送

支持三种通知渠道：
- WebSocket：实时推送至前端
- Desktop：系统桌面通知（Windows/macOS/Linux）
- Webhook：HTTP POST 回调
"""
from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class NotificationPriority(Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"
    INFO = "info"


class NotificationHub:
    """通知中心

    用法:
        hub = NotificationHub()
        hub.register_ws("session_1", websocket)
        await hub.send("task_completed", {"task_id": "1"}, NotificationPriority.NORMAL)
    """

    def __init__(self):
        self._ws_clients: dict[str, set] = {}  # session_id → {ws connections}
        self._webhook_urls: list[str] = []
        self._enabled_channels: set[str] = {"websocket"}

    async def send(self, event: str, data: dict,
                   priority: NotificationPriority = NotificationPriority.NORMAL):
        """发送通知到所有启用的渠道"""
        tasks = []
        if "websocket" in self._enabled_channels:
            tasks.append(self._send_ws(event, data))
        if "desktop" in self._enabled_channels:
            tasks.append(self._send_desktop(event, data, priority))
        if "webhook" in self._enabled_channels:
            tasks.append(self._send_webhook(event, data))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_ws(self, event: str, data: dict):
        message = json.dumps(
            {"type": "notification", "event": event, "data": data},
            ensure_ascii=False,
        )
        for session_id, clients in self._ws_clients.items():
            for ws in list(clients):
                try:
                    await ws.send_text(message)
                except Exception:
                    clients.discard(ws)

    async def _send_desktop(self, event: str, data: dict,
                            priority: NotificationPriority):
        if priority in (NotificationPriority.CRITICAL, NotificationPriority.IMPORTANT):
            try:
                from plyer import notification
                notification.notify(
                    title=f"PyCoder - {event}",
                    message=data.get("progress_message", data.get("task_name", "")),
                    timeout=5,
                )
            except (ImportError, OSError, RuntimeError) as e:
                logger.debug("desktop_notification_failed: %s", e)

    async def _send_webhook(self, event: str, data: dict):
        for url in self._webhook_urls:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    await client.post(
                        url,
                        json={"event": event, "data": data},
                        timeout=10,
                    )
            except (OSError, RuntimeError, ImportError) as e:
                logger.debug("webhook_send_failed: url=%s error=%s", url, e)

    def register_ws(self, session_id: str, ws):
        if session_id not in self._ws_clients:
            self._ws_clients[session_id] = set()
        self._ws_clients[session_id].add(ws)

    def unregister_ws(self, session_id: str, ws):
        if session_id in self._ws_clients:
            self._ws_clients[session_id].discard(ws)

    def add_webhook(self, url: str):
        self._webhook_urls.append(url)

    def remove_webhook(self, url: str):
        if url in self._webhook_urls:
            self._webhook_urls.remove(url)

    def configure_channels(self, channels: set[str]):
        self._enabled_channels = channels

    @property
    def enabled_channels(self) -> set[str]:
        return self._enabled_channels.copy()

    @property
    def ws_client_count(self) -> int:
        return sum(len(clients) for clients in self._ws_clients.values())