"""
Slack 平台适配器 — 将 Slack 消息规范化为 GatewayMessage 格式

支持 Slack 的消息类型:
- 普通文本消息
- 富文本块消息（Blocks）
- 斜杠命令（Slash Commands）
- 文件/图片共享
- 频道和私信
- 线程回复
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pycoder.gateway import GatewayMessage, PlatformAdapter

logger = logging.getLogger(__name__)


class SlackAdapter(PlatformAdapter):
    """Slack 平台适配器

    支持:
    - Socket Mode（推荐）或 Events API
    - 消息规范化
    - 频道/私信/线程消息处理
    - Blocks 和附件识别
    """

    def __init__(
        self,
        bot_token: str = "",
        *,
        app_token: str = "",
        signing_secret: str = "",
        use_socket_mode: bool = True,
    ) -> None:
        super().__init__()
        self._bot_token = bot_token
        self._app_token = app_token
        self._signing_secret = signing_secret
        self._use_socket_mode = use_socket_mode
        self._socket_task: asyncio.Task[Any] | None = None
        self._bot_user_id: str = ""

    @property
    def platform(self) -> str:
        return "slack"

    async def start(self) -> None:
        """启动 Slack 适配器"""
        self._running = True
        logger.info("Slack 适配器已启动 (token=%s..., socket_mode=%s)",
                    self._bot_token[:8] if self._bot_token else "N/A",
                    self._use_socket_mode)

        if self._bot_token and self._use_socket_mode and self._app_token:
            self._socket_task = asyncio.create_task(self._socket_mode_loop())
            logger.info("Slack Socket Mode 连接已启动")

    async def stop(self) -> None:
        """停止 Slack 适配器"""
        self._running = False
        if self._socket_task is not None:
            self._socket_task.cancel()
            try:
                await self._socket_task
            except asyncio.CancelledError:
                pass
            self._socket_task = None
        logger.info("Slack 适配器已停止")

    async def send_message(self, target: str, content: str) -> bool:
        """向 Slack 频道/用户发送消息

        Args:
            target: Slack channel_id 或 user_id
            content: 消息内容

        Returns:
            是否发送成功
        """
        if not self._bot_token:
            logger.warning("未配置 Slack Bot Token，消息未发送")
            return False

        try:
            # 模拟发送（生产环境调用 Slack Web API）
            # POST https://slack.com/api/chat.postMessage
            logger.info("Slack 消息已发送: channel=%s content=%s", target, content[:80])
            return True
        except Exception as e:
            logger.error("Slack 消息发送失败: %s", e)
            return False

    async def normalize_message(self, raw_message: Any) -> GatewayMessage:
        """将 Slack 原生消息规范化为 GatewayMessage

        Args:
            raw_message: Slack 事件 payload 对象或字典

        Returns:
            规范化后的 GatewayMessage
        """
        if isinstance(raw_message, dict):
            return self._normalize_from_dict(raw_message)
        return self._normalize_from_object(raw_message)

    def _normalize_from_dict(self, msg: dict[str, Any]) -> GatewayMessage:
        """从字典格式规范化 Slack 消息"""
        # 提取事件数据
        event = msg.get("event", msg)
        event_type = event.get("type", msg.get("type", "unknown"))

        # 支持不同的事件类型
        if event_type == "message" or event_type == "app_mention":
            return self._normalize_message_event(event)
        if event_type == "slash_commands":
            return self._normalize_slash_command(event)
        if event_type == "event_callback":
            inner_event = event.get("event", {})
            return self._normalize_message_event(inner_event)

        # 未知事件类型
        logger.warning("未知 Slack 事件类型: %s", event_type)
        return GatewayMessage(
            platform=self.platform,
            user_id="unknown",
            session_id="sl_unknown",
            content=f"[未知事件: {event_type}]",
            message_type="text",
            metadata={"event_type": event_type},
        )

    def _normalize_message_event(self, event: dict[str, Any]) -> GatewayMessage:
        """规范化 Slack 消息事件"""
        user_id = str(event.get("user", "unknown"))
        channel = str(event.get("channel", "unknown"))
        text = event.get("text", "")

        # 移除机器人 mention（如 <@U123456>）
        if self._bot_user_id and f"<@{self._bot_user_id}>" in text:
            text = text.replace(f"<@{self._bot_user_id}>", "").strip()

        # 判断消息类型
        message_type = "text"
        subtype = event.get("subtype", "")

        if subtype == "file_share":
            message_type = "file"
            if not text:
                files = event.get("files", [])
                file_names = [f.get("title", f.get("name", "unknown")) for f in files]
                text = f"[文件: {', '.join(file_names)}]"
        elif "files" in event and not text:
            message_type = "file"
            file_names = [f.get("title", f.get("name", "unknown")) for f in event["files"]]
            text = f"[文件: {', '.join(file_names)}]"
        elif text.startswith("/"):
            message_type = "command"

        # 提取 Blocks 内容（富文本）
        blocks = event.get("blocks", [])
        blocks_text = self._extract_blocks_text(blocks)
        if blocks_text and not text:
            text = blocks_text

        # 线程信息
        thread_ts = event.get("thread_ts", "")

        # 构建元数据
        metadata: dict[str, Any] = {
            "channel": channel,
            "channel_type": event.get("channel_type", ""),
            "team": event.get("team", ""),
            "ts": event.get("ts", ""),
            "thread_ts": thread_ts,
            "is_thread_reply": thread_ts != "" and thread_ts != event.get("ts", ""),
            "subtype": subtype,
            "blocks": blocks,
            "user_name": event.get("user_name", ""),
        }

        # 会话 ID：频道 + 线程
        session_id = f"sl_{channel}"
        if thread_ts:
            session_id += f"_{thread_ts}"

        return GatewayMessage(
            platform=self.platform,
            user_id=user_id,
            session_id=session_id,
            content=text,
            message_type=message_type,
            timestamp=float(event.get("ts", time.time())),
            metadata=metadata,
        )

    def _normalize_slash_command(self, event: dict[str, Any]) -> GatewayMessage:
        """规范化 Slack 斜杠命令"""
        user_id = str(event.get("user_id", event.get("user", "unknown")))
        channel = str(event.get("channel_id", event.get("channel", "unknown")))
        command = event.get("command", "")
        text = event.get("text", "")

        content = f"{command} {text}".strip()

        return GatewayMessage(
            platform=self.platform,
            user_id=user_id,
            session_id=f"sl_{channel}",
            content=content,
            message_type="command",
            timestamp=time.time(),
            metadata={
                "channel": channel,
                "command": command,
                "command_text": text,
                "team": event.get("team_id", ""),
                "trigger_id": event.get("trigger_id", ""),
            },
        )

    def _extract_blocks_text(self, blocks: list[dict[str, Any]]) -> str:
        """从 Slack Blocks 中提取文本内容

        Args:
            blocks: Slack Blocks 列表

        Returns:
            提取的文本内容
        """
        texts: list[str] = []
        for block in blocks:
            block_type = block.get("type", "")
            if block_type == "rich_text":
                for element in block.get("elements", []):
                    for section in element.get("elements", []):
                        if section.get("type") == "text":
                            texts.append(section.get("text", ""))
            elif block_type == "section":
                section_text = block.get("text", {})
                if isinstance(section_text, dict):
                    texts.append(section_text.get("text", ""))
                elif isinstance(section_text, str):
                    texts.append(section_text)
        return " ".join(texts)

    def _normalize_from_object(self, msg: Any) -> GatewayMessage:
        """从对象格式规范化 Slack 消息"""
        try:
            user_id = str(getattr(msg, "user", "unknown"))
            channel = str(getattr(msg, "channel", "unknown"))
            text = getattr(msg, "text", "") or ""

            return GatewayMessage(
                platform=self.platform,
                user_id=user_id,
                session_id=f"sl_{channel}",
                content=text,
                message_type="text",
                metadata={
                    "channel": channel,
                    "ts": str(getattr(msg, "ts", "")),
                },
            )
        except Exception as e:
            logger.error("规范化 Slack 消息对象失败: %s", e)
            return GatewayMessage(
                platform=self.platform,
                user_id="unknown",
                session_id="sl_unknown",
                content=f"[解析失败: {e}]",
                message_type="text",
                metadata={"error": str(e)},
            )

    # ── 私有方法 ────────────────────────────

    async def _socket_mode_loop(self) -> None:
        """Slack Socket Mode 连接循环"""
        while self._running:
            try:
                await self._process_socket_events()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Slack Socket Mode 连接出错: %s", e)
                await asyncio.sleep(5.0)

    async def _process_socket_events(self) -> None:
        """处理 Socket Mode 事件（模拟实现）"""
        # 生产环境:
        # 1. 调用 apps.connections.open 获取 WebSocket URL
        # 2. 连接 WebSocket
        # 3. 接收事件并处理
        await asyncio.sleep(0.1)


__all__ = ["SlackAdapter"]