"""
Telegram 平台适配器 — 将 Telegram 消息规范化为 GatewayMessage 格式

使用 python-telegram-bot 风格的异步适配器，但实现为 mock-ready 模式，
方便在没有实际 Bot Token 时进行测试和开发。

设计模式:
- 异步轮询/Webhook 双模式
- 消息规范化：将 Telegram Message 对象转换为 GatewayMessage
- 支持文本、命令、文件、图片等消息类型
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pycoder.gateway import GatewayMessage, PlatformAdapter

logger = logging.getLogger(__name__)


class TelegramAdapter(PlatformAdapter):
    """Telegram 平台适配器

    支持:
    - 异步轮询模式（长轮询获取更新）
    - 消息规范化
    - 文本、命令、图片、文件消息类型识别
    """

    def __init__(
        self,
        bot_token: str = "",
        *,
        polling_interval: float = 2.0,
        use_webhook: bool = False,
        webhook_url: str = "",
    ) -> None:
        super().__init__()
        self._bot_token = bot_token
        self._polling_interval = polling_interval
        self._use_webhook = use_webhook
        self._webhook_url = webhook_url
        self._poll_task: asyncio.Task[Any] | None = None
        self._last_update_id: int = 0

    @property
    def platform(self) -> str:
        return "telegram"

    async def start(self) -> None:
        """启动 Telegram 适配器

        根据配置选择轮询或 Webhook 模式。
        """
        self._running = True
        logger.info("Telegram 适配器已启动 (token=%s..., polling=%s)",
                    self._bot_token[:8] if self._bot_token else "N/A",
                    not self._use_webhook)

        if self._use_webhook and self._webhook_url:
            await self._start_webhook()
        elif self._bot_token:
            self._poll_task = asyncio.create_task(self._polling_loop())
            logger.info("Telegram 轮询已启动，间隔 %.1fs", self._polling_interval)

    async def stop(self) -> None:
        """停止 Telegram 适配器"""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("Telegram 适配器已停止")

    async def send_message(self, target: str, content: str) -> bool:
        """向 Telegram 用户发送消息

        Args:
            target: Telegram chat_id
            content: 消息内容

        Returns:
            是否发送成功
        """
        if not self._bot_token:
            logger.warning("未配置 Telegram Bot Token，消息未发送")
            return False

        # 实际发送逻辑：调用 Telegram Bot API
        # GET/POST https://api.telegram.org/bot<token>/sendMessage
        try:
            # 模拟发送（生产环境应替换为实际 HTTP 请求）
            logger.info("Telegram 消息已发送: chat_id=%s content=%s", target, content[:80])
            return True
        except Exception as e:
            logger.error("Telegram 消息发送失败: %s", e)
            return False

    async def normalize_message(self, raw_message: Any) -> GatewayMessage:
        """将 Telegram 原生消息规范化为 GatewayMessage

        Args:
            raw_message: Telegram Update 对象或字典

        Returns:
            规范化后的 GatewayMessage
        """
        if isinstance(raw_message, dict):
            return self._normalize_from_dict(raw_message)
        return self._normalize_from_object(raw_message)

    def _normalize_from_dict(self, msg: dict[str, Any]) -> GatewayMessage:
        """从字典格式规范化 Telegram 消息"""
        # 提取 message 字段
        message = msg.get("message", msg)
        chat = message.get("chat", {})
        from_user = message.get("from", {})

        user_id = str(chat.get("id", from_user.get("id", "unknown")))
        chat_id = str(chat.get("id", "unknown"))

        # 提取文本内容
        content = message.get("text", message.get("caption", ""))
        if not content and "sticker" in message:
            content = "[贴纸]"
        if not content and "photo" in message:
            content = "[图片]"
        if not content and "document" in message:
            content = "[文件]"
        if not content and "voice" in message:
            content = "[语音]"

        # 判断消息类型
        message_type = "text"
        if content.startswith("/"):
            message_type = "command"
        elif "photo" in message:
            message_type = "image"
        elif "document" in message:
            message_type = "file"
        elif "voice" in message:
            message_type = "audio"
        elif "sticker" in message:
            message_type = "image"

        # 提取实体信息
        entities = message.get("entities", [])
        metadata: dict[str, Any] = {
            "chat_id": chat_id,
            "chat_type": chat.get("type", "private"),
            "first_name": from_user.get("first_name", ""),
            "last_name": from_user.get("last_name", ""),
            "username": from_user.get("username", ""),
            "message_id": message.get("message_id", 0),
            "entities": entities,
        }

        return GatewayMessage(
            platform=self.platform,
            user_id=user_id,
            session_id=f"tg_{chat_id}",
            content=content,
            message_type=message_type,
            timestamp=float(message.get("date", time.time())),
            metadata=metadata,
        )

    def _normalize_from_object(self, msg: Any) -> GatewayMessage:
        """从对象格式规范化 Telegram 消息"""
        # 尝试提取属性
        try:
            chat_id = str(getattr(getattr(msg, "chat", None), "id", "unknown"))
            user_id = str(getattr(getattr(msg, "from_user", None), "id", chat_id))
            content = getattr(msg, "text", "") or getattr(msg, "caption", "")
            message_type = "command" if content.startswith("/") else "text"
            message_id = getattr(msg, "message_id", 0)
            date = getattr(msg, "date", None)
            timestamp = float(date.timestamp()) if date else time.time()

            return GatewayMessage(
                platform=self.platform,
                user_id=user_id,
                session_id=f"tg_{chat_id}",
                content=content,
                message_type=message_type,
                timestamp=timestamp,
                metadata={
                    "chat_id": chat_id,
                    "message_id": message_id,
                },
            )
        except Exception as e:
            logger.error("规范化 Telegram 消息对象失败: %s", e)
            return GatewayMessage(
                platform=self.platform,
                user_id="unknown",
                session_id="tg_unknown",
                content=f"[解析失败: {e}]",
                message_type="text",
                metadata={"error": str(e)},
            )

    # ── 私有方法 ────────────────────────────

    async def _polling_loop(self) -> None:
        """长轮询循环 —— 定期获取 Telegram 更新"""
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    gateway_msg = await self.normalize_message(update)
                    if self._message_callback is not None:
                        await self._message_callback(gateway_msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Telegram 轮询出错: %s", e)
            await asyncio.sleep(self._polling_interval)

    async def _get_updates(self) -> list[dict[str, Any]]:
        """获取 Telegram 更新（模拟实现）

        生产环境应调用:
          GET https://api.telegram.org/bot<token>/getUpdates?offset=<offset>

        Returns:
            更新列表
        """
        # 模拟空更新列表（生产环境替换为实际 API 调用）
        return []

    async def _start_webhook(self) -> None:
        """启动 Webhook 模式"""
        logger.info("Telegram Webhook 模式已配置: %s", self._webhook_url)
        # 生产环境:
        # 1. 设置 webhook: POST https://api.telegram.org/bot<token>/setWebhook
        # 2. 启动 HTTP 服务器接收更新


__all__ = ["TelegramAdapter"]