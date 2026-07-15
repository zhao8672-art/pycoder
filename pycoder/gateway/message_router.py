"""
消息路由器 — 将网关消息路由到 AI 大脑并返回响应

负责:
1. 解析消息意图（命令 vs 对话）
2. 将消息发送到 AI 大脑处理
3. 构建上下文（结合会话历史 + 跨平台共享上下文）
4. 返回 AI 响应
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class MessageRouter:
    """
    消息路由器 —— 与 AI 大脑桥接

    将网关消息转换为 AI 大脑可理解的格式，处理后将响应返回。
    支持命令前缀识别和自然语言对话两种模式。
    """

    # 命令前缀（可配置）
    COMMAND_PREFIXES: list[str] = ["/", "!", "."]

    def __init__(self) -> None:
        # AI 大脑引用（延迟注入）
        self._ai_brain: Any = None
        # 会话管理器引用（延迟注入）
        self._session_manager: Any = None

    def set_ai_brain(self, brain: Any) -> None:
        """设置 AI 大脑实例

        Args:
            brain: AI 大脑实例（需支持 async process_message 方法）
        """
        self._ai_brain = brain

    def set_session_manager(self, session_manager: Any) -> None:
        """设置会话管理器实例

        Args:
            session_manager: SessionManager 实例
        """
        self._session_manager = session_manager

    async def route_message(self, gateway_msg: Any) -> str | None:
        """
        路由消息到 AI 大脑处理

        Args:
            gateway_msg: GatewayMessage 实例

        Returns:
            AI 响应文本，如果无需响应则返回 None
        """
        # 判断消息类型
        if self._is_command(gateway_msg.content):
            return await self._handle_command(gateway_msg)
        else:
            return await self._handle_conversation(gateway_msg)

    # ── 消息分类 ────────────────────────────

    def _is_command(self, content: str) -> bool:
        """判断是否为命令消息

        Args:
            content: 消息内容

        Returns:
            是否为命令
        """
        stripped = content.strip()
        return any(stripped.startswith(prefix) for prefix in self.COMMAND_PREFIXES)

    def _parse_command(self, content: str) -> tuple[str, str]:
        """解析命令消息

        Args:
            content: 消息内容

        Returns:
            (命令名, 参数) 元组
        """
        stripped = content.strip()
        parts = stripped.split(maxsplit=1)
        command = parts[0].lstrip("/!.")
        args = parts[1] if len(parts) > 1 else ""
        return command, args

    # ── 消息处理 ────────────────────────────

    async def _handle_command(self, gateway_msg: Any) -> str | None:
        """处理命令消息

        Args:
            gateway_msg: GatewayMessage 实例

        Returns:
            命令执行结果
        """
        command, args = self._parse_command(gateway_msg.content)

        # 内置命令处理
        if command == "help" or command == "帮助":
            return self._build_help_message()

        if command == "platforms" or command == "平台":
            return self._build_platforms_message(gateway_msg)

        if command == "info" or command == "信息":
            return self._build_session_info(gateway_msg)

        # 尝试通过 AI 大脑处理
        if self._ai_brain is not None:
            try:
                context = self._build_context(gateway_msg)
                result = await self._ai_brain.process_message(
                    gateway_msg.content, context
                )
                return result if isinstance(result, str) else str(result)
            except Exception as e:
                logger.error("AI 大脑处理命令失败: %s", e)
                return f"命令执行出错: {e}"

        return f"未知命令: {command}。输入 /help 查看可用命令。"

    async def _handle_conversation(self, gateway_msg: Any) -> str | None:
        """处理对话消息

        Args:
            gateway_msg: GatewayMessage 实例

        Returns:
            AI 响应文本
        """
        # 构建上下文
        context = self._build_context(gateway_msg)

        # 通过 AI 大脑处理
        if self._ai_brain is not None:
            try:
                result = await self._ai_brain.process_message(
                    gateway_msg.content, context
                )
                return result if isinstance(result, str) else str(result)
            except Exception as e:
                logger.error("AI 大脑处理对话失败: %s", e)
                return f"抱歉，处理您的消息时出错: {e}"

        # 无 AI 大脑时的默认回复
        logger.warning("AI 大脑未配置，返回默认回复")
        return (
            f"收到您的消息（{gateway_msg.platform}@{gateway_msg.user_id}）："
            f"{gateway_msg.content[:100]}"
        )

    # ── 上下文构建 ──────────────────────────

    def _build_context(self, gateway_msg: Any) -> dict[str, Any]:
        """构建消息上下文

        组合会话历史 + 跨平台共享上下文，发送给 AI 大脑。

        Args:
            gateway_msg: GatewayMessage 实例

        Returns:
            上下文字典
        """
        context: dict[str, Any] = {
            "platform": gateway_msg.platform,
            "user_id": gateway_msg.user_id,
            "session_id": gateway_msg.session_id,
            "message_type": gateway_msg.message_type,
            "timestamp": gateway_msg.timestamp,
            "recent_messages": [],
            "shared_context": {},
        }

        # 添加会话历史
        if self._session_manager is not None:
            session = self._session_manager.get_session(
                gateway_msg.platform, gateway_msg.user_id
            )
            if session is not None:
                context["recent_messages"] = session.get_recent_messages(20)

            # 添加跨平台共享上下文
            shared = self._session_manager.get_all_shared_context(gateway_msg.user_id)
            if shared:
                context["shared_context"] = shared

        return context

    # ── 内置命令响应 ────────────────────────

    def _build_help_message(self) -> str:
        """构建帮助消息"""
        return (
            "**PyCoder 消息网关帮助**\n\n"
            "可用命令:\n"
            "  /help — 显示此帮助信息\n"
            "  /platforms — 列出可用平台\n"
            "  /info — 显示当前会话信息\n\n"
            "直接发送消息即可与 AI 对话。"
        )

    def _build_platforms_message(self, gateway_msg: Any) -> str:
        """构建平台列表消息"""
        lines = ["**可用平台:**"]
        if self._session_manager is not None:
            stats = self._session_manager.get_stats()
            for platform, count in stats.get("platforms", {}).items():
                lines.append(f"  - {platform}: {count} 个会话")
        if len(lines) == 1:
            lines.append("  (暂无平台注册)")
        return "\n".join(lines)

    def _build_session_info(self, gateway_msg: Any) -> str:
        """构建会话信息消息"""
        info_lines = [
            f"**会话信息**",
            f"  平台: {gateway_msg.platform}",
            f"  用户: {gateway_msg.user_id}",
            f"  会话: {gateway_msg.session_id}",
        ]
        if self._session_manager is not None:
            session = self._session_manager.get_session(
                gateway_msg.platform, gateway_msg.user_id
            )
            if session is not None:
                info_lines.append(f"  消息数: {len(session.messages)}")
                info_lines.append(
                    f"  创建时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(session.created_at))}"
                )
        return "\n".join(info_lines)


__all__ = ["MessageRouter"]