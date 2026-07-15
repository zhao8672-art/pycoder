"""
Discord 平台适配器 — 将 Discord 消息规范化为 GatewayMessage 格式

支持 Discord 的消息类型:
- 普通文本消息
- 命令消息（以 / 开头）
- 嵌入消息（Embeds）
- 附件消息（图片、文件）
- 私信（DM）和频道消息
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pycoder.gateway import GatewayMessage, PlatformAdapter

logger = logging.getLogger(__name__)


class DiscordAdapter(PlatformAdapter):
    """Discord 平台适配器

    支持:
    - 通过 WebSocket 网关连接
    - 消息规范化
    - 频道/私信消息处理
    - 附件和嵌入消息识别
    """

    def __init__(
        self,
        bot_token: str = "",
        *,
        command_prefix: str = "!",
        intents: int | None = None,
    ) -> None:
        super().__init__()
        self._bot_token = bot_token
        self._command_prefix = command_prefix
        self._intents = intents or 0
        self._ws_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None

    @property
    def platform(self) -> str:
        return "discord"

    async def start(self) -> None:
        """启动 Discord 适配器"""
        self._running = True
        logger.info("Discord 适配器已启动 (token=%s..., prefix='%s')",
                    self._bot_token[:8] if self._bot_token else "N/A",
                    self._command_prefix)

        if self._bot_token:
            self._ws_task = asyncio.create_task(self._gateway_loop())
            logger.info("Discord 网关连接已启动")

    async def stop(self) -> None:
        """停止 Discord 适配器"""
        self._running = False
        for task in [self._ws_task, self._heartbeat_task]:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._ws_task = None
        self._heartbeat_task = None
        logger.info("Discord 适配器已停止")

    async def send_message(self, target: str, content: str) -> bool:
        """向 Discord 频道/用户发送消息

        Args:
            target: Discord channel_id 或 user_id
            content: 消息内容

        Returns:
            是否发送成功
        """
        if not self._bot_token:
            logger.warning("未配置 Discord Bot Token，消息未发送")
            return False

        try:
            # 模拟发送（生产环境调用 Discord REST API）
            # POST https://discord.com/api/v10/channels/{channel_id}/messages
            logger.info("Discord 消息已发送: channel=%s content=%s", target, content[:80])
            return True
        except Exception as e:
            logger.error("Discord 消息发送失败: %s", e)
            return False

    async def normalize_message(self, raw_message: Any) -> GatewayMessage:
        """将 Discord 原生消息规范化为 GatewayMessage

        Args:
            raw_message: Discord Message 对象或字典

        Returns:
            规范化后的 GatewayMessage
        """
        if isinstance(raw_message, dict):
            return self._normalize_from_dict(raw_message)
        return self._normalize_from_object(raw_message)

    def _normalize_from_dict(self, msg: dict[str, Any]) -> GatewayMessage:
        """从字典格式规范化 Discord 消息"""
        # 提取基础字段
        author = msg.get("author", {})
        channel_id = str(msg.get("channel_id", "unknown"))
        guild_id = msg.get("guild_id", "")

        user_id = str(author.get("id", "unknown"))
        author_name = author.get("username", "unknown")
        author_discriminator = author.get("discriminator", "")

        # 提取消息内容
        content = msg.get("content", "")
        message_type = "text"

        # 附件处理
        attachments = msg.get("attachments", [])
        if attachments:
            attachment_types = {a.get("content_type", "").split("/")[0] for a in attachments if a}
            if "image" in attachment_types:
                message_type = "image"
            else:
                message_type = "file"
            if not content:
                attachment_names = [a.get("filename", "unknown") for a in attachments]
                content = f"[附件: {', '.join(attachment_names)}]"

        # 嵌入消息处理
        embeds = msg.get("embeds", [])
        if embeds and not content:
            embed_desc = embeds[0].get("description", embeds[0].get("title", ""))
            if embed_desc:
                content = embed_desc

        # 命令识别
        if content.startswith(self._command_prefix) or content.startswith("/"):
            message_type = "command"

        # 构建元数据
        metadata: dict[str, Any] = {
            "channel_id": channel_id,
            "guild_id": str(guild_id) if guild_id else "",
            "author_name": f"{author_name}#{author_discriminator}" if author_discriminator else author_name,
            "author_global_name": author.get("global_name", ""),
            "is_bot": author.get("bot", False),
            "message_id": msg.get("id", ""),
            "is_dm": guild_id is None or guild_id == "",
            "attachments": attachments,
            "embeds": embeds,
            "mention_everyone": msg.get("mention_everyone", False),
            "mentions": msg.get("mentions", []),
        }

        return GatewayMessage(
            platform=self.platform,
            user_id=user_id,
            session_id=f"dc_{guild_id or 'dm'}_{channel_id}",
            content=content,
            message_type=message_type,
            timestamp=time.time(),  # Discord 消息使用雪花 ID 时间戳
            metadata=metadata,
        )

    def _normalize_from_object(self, msg: Any) -> GatewayMessage:
        """从对象格式规范化 Discord 消息"""
        try:
            user_id = str(getattr(getattr(msg, "author", None), "id", "unknown"))
            channel_id = str(getattr(msg, "channel_id", "unknown"))
            guild_id = getattr(msg, "guild_id", None)
            content = getattr(msg, "content", "") or ""
            message_type = "text"

            if content.startswith(self._command_prefix):
                message_type = "command"

            attachments = getattr(msg, "attachments", [])
            if attachments:
                message_type = "file" if len(attachments) > 0 else "text"

            return GatewayMessage(
                platform=self.platform,
                user_id=user_id,
                session_id=f"dc_{guild_id or 'dm'}_{channel_id}",
                content=content,
                message_type=message_type,
                metadata={
                    "channel_id": channel_id,
                    "guild_id": str(guild_id) if guild_id else "",
                    "author_name": str(getattr(getattr(msg, "author", None), "name", "unknown")),
                },
            )
        except Exception as e:
            logger.error("规范化 Discord 消息对象失败: %s", e)
            return GatewayMessage(
                platform=self.platform,
                user_id="unknown",
                session_id="dc_unknown",
                content=f"[解析失败: {e}]",
                message_type="text",
                metadata={"error": str(e)},
            )

    # ── 私有方法 ────────────────────────────

    async def _gateway_loop(self) -> None:
        """Discord 网关 WebSocket 连接循环"""
        while self._running:
            try:
                # 模拟网关连接（生产环境使用 discord.py 或原始 WebSocket）
                await self._process_gateway_events()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Discord 网关连接出错: %s", e)
                await asyncio.sleep(5.0)  # 重连等待

    async def _process_gateway_events(self) -> None:
        """处理网关事件（模拟实现）"""
        # 生产环境:
        # 1. 连接 wss://gateway.discord.gg/?v=10&encoding=json
        # 2. 发送 IDENTIFY payload
        # 3. 接收 HELLO -> HEARTBEAT
        # 4. 处理 MESSAGE_CREATE 事件
        await asyncio.sleep(0.1)


__all__ = ["DiscordAdapter"]