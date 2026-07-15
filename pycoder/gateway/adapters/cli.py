"""
CLI 平台适配器 — 终端交互适配器

支持终端命令行交互模式，将终端输入规范化为 GatewayMessage 格式。
适用于开发和调试场景，无需外部平台即可与 AI 对话。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any

from pycoder.gateway import GatewayMessage, PlatformAdapter

logger = logging.getLogger(__name__)


class CLIAdapter(PlatformAdapter):
    """CLI 终端适配器

    支持:
    - 异步 stdin 读取
    - 命令模式和对话模式
    - 彩色输出（Rich 集成）
    - Ctrl+C 优雅退出
    - 多行输入支持
    """

    def __init__(
        self,
        *,
        prompt: str = "> ",
        use_rich: bool = True,
        multiline: bool = False,
        multiline_marker: str = "\\",
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._use_rich = use_rich
        self._multiline = multiline
        self._multiline_marker = multiline_marker
        self._input_task: asyncio.Task[Any] | None = None
        self._reader: Any = None  # asyncio.StreamReader

    @property
    def platform(self) -> str:
        return "cli"

    async def start(self) -> None:
        """启动 CLI 适配器"""
        self._running = True

        # 尝试使用 Rich 美化输出
        if self._use_rich:
            try:
                from rich.console import Console
                from rich.markdown import Markdown

                self._console = Console()
                self._console.print("[bold green]PyCoder CLI 网关已启动[/]")
                self._console.print("输入消息与 AI 对话，输入 /help 查看帮助，Ctrl+C 退出")
            except ImportError:
                self._use_rich = False
                print("PyCoder CLI 网关已启动")
                print("输入消息与 AI 对话，输入 /help 查看帮助，Ctrl+C 退出")

        logger.info("CLI 适配器已启动 (prompt='%s', multiline=%s)",
                    self._prompt, self._multiline)

        # 启动异步输入循环
        self._input_task = asyncio.create_task(self._input_loop())

    async def stop(self) -> None:
        """停止 CLI 适配器"""
        self._running = False
        if self._input_task is not None:
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass
            self._input_task = None
        logger.info("CLI 适配器已停止")

    async def send_message(self, target: str, content: str) -> bool:
        """向终端输出消息

        Args:
            target: 目标标识（CLI 中忽略）
            content: 消息内容

        Returns:
            是否发送成功
        """
        try:
            if self._use_rich:
                try:
                    self._console.print(f"[bold cyan]AI:[/] {content}")
                except Exception:
                    print(f"AI: {content}")
            else:
                print(f"AI: {content}")
            return True
        except Exception as e:
            logger.error("CLI 输出失败: %s", e)
            return False

    async def normalize_message(self, raw_message: Any) -> GatewayMessage:
        """将 CLI 输入规范化为 GatewayMessage

        Args:
            raw_message: 终端输入字符串

        Returns:
            规范化后的 GatewayMessage
        """
        if isinstance(raw_message, str):
            return self._normalize_from_string(raw_message)
        return GatewayMessage(
            platform=self.platform,
            user_id="cli_user",
            session_id="cli_session",
            content=str(raw_message),
            message_type="text",
        )

    def _normalize_from_string(self, text: str) -> GatewayMessage:
        """从字符串规范化 CLI 输入"""
        stripped = text.strip()

        # 判断消息类型
        message_type = "text"
        if stripped.startswith("/"):
            message_type = "command"
        elif stripped.startswith("!"):
            message_type = "command"

        # 构建元数据
        metadata: dict[str, Any] = {
            "terminal": sys.platform,
            "is_multiline": "\n" in text,
            "line_count": text.count("\n") + 1,
        }

        return GatewayMessage(
            platform=self.platform,
            user_id="cli_user",
            session_id="cli_session",
            content=stripped,
            message_type=message_type,
            metadata=metadata,
        )

    # ── 私有方法 ────────────────────────────

    async def _input_loop(self) -> None:
        """异步输入循环 —— 持续读取终端输入"""
        # 使用 asyncio 的 stream reader 异步读取 stdin
        loop = asyncio.get_event_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self._running:
            try:
                # 显示提示符
                prompt = self._prompt
                sys.stdout.write(prompt)
                sys.stdout.flush()

                # 读取一行
                line = await self._reader.readline()
                if not line:
                    # EOF
                    break

                text = line.decode("utf-8").rstrip("\n").rstrip("\r")

                # 空行跳过
                if not text.strip():
                    continue

                # 多行输入支持
                if self._multiline and text.rstrip().endswith(self._multiline_marker):
                    text = await self._read_multiline(text.rstrip()[:-1])

                # 特殊命令处理
                if text.strip() == "/exit" or text.strip() == "/quit":
                    self._print_message("再见！")
                    self._running = False
                    break

                # 规范化并回调
                gateway_msg = await self.normalize_message(text)
                if self._message_callback is not None:
                    await self._message_callback(gateway_msg)

            except asyncio.CancelledError:
                break
            except EOFError:
                break
            except Exception as e:
                logger.error("CLI 输入循环出错: %s", e)
                await asyncio.sleep(0.1)

    async def _read_multiline(self, first_line: str) -> str:
        """读取多行输入

        Args:
            first_line: 第一行内容（已去掉续行标记）

        Returns:
            完整的多行文本
        """
        lines = [first_line]
        while self._running:
            sys.stdout.write("... ")
            sys.stdout.flush()
            line = await self._reader.readline()
            if not line:
                break
            text = line.decode("utf-8").rstrip("\n").rstrip("\r")
            if text.rstrip().endswith(self._multiline_marker):
                lines.append(text.rstrip()[:-1])
            else:
                lines.append(text)
                break
        return "\n".join(lines)

    def _print_message(self, message: str) -> None:
        """输出消息到终端"""
        if self._use_rich:
            try:
                self._console.print(f"[dim]{message}[/]")
                return
            except Exception:
                pass
        print(message)


__all__ = ["CLIAdapter"]