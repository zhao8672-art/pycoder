"""LSP 客户端 — 与 LSP 服务器交互的高级 API

封装 LSP 协议通信，提供简洁的异步 API:
    - initialize / shutdown  生命周期管理
    - did_open / did_change  文档同步
    - completion             代码补全
    - definition             定义跳转
    - hover                  悬停提示
    - references             引用查找
    - document_symbol        文档符号

用法:
    client = LSPClient(workspace="/path/to/project")
    await client.start()
    await client.initialize()
    await client.did_open("main.py", "print('hello')")
    completions = await client.completion("main.py", line=1, character=0)
    await client.shutdown()
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycoder.lsp.protocol import (
    LSPMessage,
    decode_message,
    encode_message,
    make_notification,
    make_request,
)

logger = logging.getLogger(__name__)


@dataclass
class LSPClientConfig:
    """LSP 客户端配置"""

    command: list[str] = field(default_factory=lambda: ["pyright-langserver", "--stdio"])
    workspace: str = ""
    initialization_timeout: float = 30.0
    request_timeout: float = 10.0
    language_id: str = "python"


@dataclass
class CompletionItem:
    """代码补全项"""

    label: str = ""
    kind: int = 0  # LSP CompletionItemKind
    detail: str = ""
    documentation: str = ""
    insert_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "detail": self.detail,
            "documentation": self.documentation,
            "insertText": self.insert_text,
        }


@dataclass
class Location:
    """定义/引用位置"""

    uri: str = ""
    line: int = 0
    character: int = 0
    end_line: int = 0
    end_character: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "range": {
                "start": {"line": self.line, "character": self.character},
                "end": {"line": self.end_line, "character": self.end_character},
            },
        }


@dataclass
class Hover:
    """悬停提示"""

    contents: str = ""
    line: int = 0
    character: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "contents": self.contents,
            "range": {
                "start": {"line": self.line, "character": self.character},
                "end": {"line": self.line, "character": self.character},
            },
        }


@dataclass
class DocumentSymbol:
    """文档符号"""

    name: str = ""
    kind: int = 0  # LSP SymbolKind
    line: int = 0
    character: int = 0
    detail: str = ""
    children: list[DocumentSymbol] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "range": {
                "start": {"line": self.line, "character": self.character},
                "end": {"line": self.line, "character": self.character},
            },
            "detail": self.detail,
            "children": [c.to_dict() for c in self.children],
        }


class LSPClient:
    """LSP 客户端 — 与 LSP 服务器交互

    线程安全性: 单实例非线程安全，每个工作区建议使用独立实例。
    异步: 所有方法均为 async，需在 asyncio 事件循环中调用。
    """

    def __init__(self, config: LSPClientConfig | None = None) -> None:
        self._config = config or LSPClientConfig()
        self._process: asyncio.subprocess.Process | None = None
        self._next_id: int = 1
        self._pending: dict[int, asyncio.Future[LSPMessage]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._initialized: bool = False
        self._shutdown: bool = False
        self._server_capabilities: dict[str, Any] = {}

    # ══════════════════════════════════════════════════════
    # 生命周期管理
    # ══════════════════════════════════════════════════════

    async def start(self) -> bool:
        """启动 LSP 服务器子进程"""
        if self._process is not None:
            return True
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._config.workspace or None,
            )
            # 启动后台读取任务
            self._reader_task = asyncio.create_task(self._read_loop())
            logger.info("lsp_started: %s", self._config.command)
            return True
        except FileNotFoundError:
            logger.warning("lsp_not_installed: %s", self._config.command[0])
            return False
        except OSError as e:
            logger.error("lsp_start_failed: %s", e)
            return False

    async def initialize(self) -> dict[str, Any]:
        """LSP initialize 握手

        Returns:
            服务器能力 (capabilities)
        """
        if self._initialized:
            return self._server_capabilities
        if self._process is None:
            raise RuntimeError("LSP client not started, call start() first")

        root_uri = ""
        if self._config.workspace:
            root_path = Path(self._config.workspace).resolve()
            root_uri = root_path.as_uri()

        params = {
            "processId": os.getpid(),
            "rootUri": root_uri or None,
            "capabilities": {
                "textDocument": {
                    "completion": {
                        "completionItem": {
                            "snippetSupport": False,
                            "documentationFormat": ["markdown", "plaintext"],
                        }
                    },
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                },
            },
            "workspace": {"configuration": True},
        }

        response = await self._request("initialize", params, timeout=self._config.initialization_timeout)
        self._server_capabilities = response.result or {}
        # 发送 initialized 通知
        await self._notify("initialized", {})
        self._initialized = True
        logger.info("lsp_initialized: caps=%s", list(self._server_capabilities.keys()))
        return self._server_capabilities

    async def shutdown(self) -> None:
        """LSP shutdown 请求"""
        if self._shutdown or self._process is None:
            return
        try:
            await self._request("shutdown", None)
            await self._notify("exit", None)
        except Exception as e:
            logger.debug("lsp_shutdown_error: %s", e)
        finally:
            self._shutdown = True
            self._initialized = False

    async def stop(self) -> None:
        """停止 LSP 服务器子进程"""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (TimeoutError, OSError):
                try:
                    self._process.kill()
                except OSError:
                    pass
            self._process = None
        self._initialized = False
        self._shutdown = False
        self._pending.clear()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def server_capabilities(self) -> dict[str, Any]:
        return self._server_capabilities

    # ══════════════════════════════════════════════════════
    # 文档同步
    # ══════════════════════════════════════════════════════

    async def did_open(self, file_path: str, text: str, language_id: str = "") -> None:
        """textDocument/didOpen 通知"""
        uri = self._path_to_uri(file_path)
        await self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id or self._config.language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )

    async def did_change(self, file_path: str, text: str, version: int = 2) -> None:
        """textDocument/didChange 通知 (全量同步)"""
        uri = self._path_to_uri(file_path)
        await self._notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            },
        )

    async def did_close(self, file_path: str) -> None:
        """textDocument/didClose 通知"""
        uri = self._path_to_uri(file_path)
        await self._notify(
            "textDocument/didClose",
            {"textDocument": {"uri": uri}},
        )

    # ══════════════════════════════════════════════════════
    # 语言功能
    # ══════════════════════════════════════════════════════

    async def completion(
        self, file_path: str, line: int, character: int
    ) -> list[CompletionItem]:
        """textDocument/completion 代码补全

        Args:
            file_path: 文件路径
            line: 行号 (0-based)
            character: 列号 (0-based)

        Returns:
            补全项列表
        """
        response = await self._request(
            "textDocument/completion",
            self._text_document_position(file_path, line, character),
        )
        result = response.result
        if result is None:
            return []
        # LSP 返回 CompletionItem[] 或 CompletionList
        items = result if isinstance(result, list) else result.get("items", [])
        return [self._parse_completion_item(item) for item in items]

    async def definition(
        self, file_path: str, line: int, character: int
    ) -> list[Location]:
        """textDocument/definition 定义跳转

        Returns:
            定义位置列表 (通常只有 1 个)
        """
        response = await self._request(
            "textDocument/definition",
            self._text_document_position(file_path, line, character),
        )
        return self._parse_locations(response.result)

    async def hover(self, file_path: str, line: int, character: int) -> Hover | None:
        """textDocument/hover 悬停提示"""
        response = await self._request(
            "textDocument/hover",
            self._text_document_position(file_path, line, character),
        )
        if not response.result:
            return None
        return self._parse_hover(response.result)

    async def references(
        self, file_path: str, line: int, character: int, include_declaration: bool = True
    ) -> list[Location]:
        """textDocument/references 引用查找"""
        params = self._text_document_position(file_path, line, character)
        params["context"] = {"includeDeclaration": include_declaration}
        response = await self._request("textDocument/references", params)
        return self._parse_locations(response.result)

    async def document_symbol(self, file_path: str) -> list[DocumentSymbol]:
        """textDocument/documentSymbol 文档符号"""
        uri = self._path_to_uri(file_path)
        response = await self._request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
        )
        if not response.result:
            return []
        return [self._parse_symbol(s) for s in response.result]

    # ══════════════════════════════════════════════════════
    # 内部通信实现
    # ══════════════════════════════════════════════════════

    async def _request(
        self, method: str, params: dict[str, Any] | None, timeout: float | None = None
    ) -> LSPMessage:
        """发送 JSON-RPC 请求并等待响应"""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("LSP client not started")

        request_id = self._next_id
        self._next_id += 1
        msg = make_request(request_id, method, params)
        future: asyncio.Future[LSPMessage] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # 编码并发送
        data = encode_message(msg)
        self._process.stdin.write(data)
        await self._process.stdin.drain()

        # 等待响应
        try:
            return await asyncio.wait_for(
                future, timeout=timeout or self._config.request_timeout
            )
        except TimeoutError:
            self._pending.pop(request_id, None)
            raise

    async def _notify(self, method: str, params: dict[str, Any] | None) -> None:
        """发送 JSON-RPC 通知 (无需响应)"""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("LSP client not started")
        msg = make_notification(method, params)
        data = encode_message(msg)
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """后台读取服务器消息并分发到对应 Future"""
        if self._process is None or self._process.stdout is None:
            return
        reader = self._process.stdout
        while True:
            try:
                msg = await decode_message(reader)
                if msg is None:
                    break  # EOF
                if msg.is_response() and msg.id is not None:
                    future = self._pending.pop(msg.id, None)
                    if future and not future.done():
                        future.set_result(msg)
                elif msg.is_notification():
                    # 服务器通知 (如 textDocument/publishDiagnostics)
                    logger.debug("lsp_notification: %s", msg.method)
                elif msg.is_request():
                    # 服务器发起的请求 (如 workspace/configuration)
                    logger.debug("lsp_server_request: %s", msg.method)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("lsp_read_error: %s", e)
                break

        # 流结束，取消所有 pending 请求
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("LSP server closed connection"))
        self._pending.clear()

    # ══════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _path_to_uri(file_path: str) -> str:
        """文件路径转 file:// URI"""
        return Path(file_path).resolve().as_uri()

    def _text_document_position(
        self, file_path: str, line: int, character: int
    ) -> dict[str, Any]:
        """构造 TextDocumentPositionParams"""
        return {
            "textDocument": {"uri": self._path_to_uri(file_path)},
            "position": {"line": line, "character": character},
        }

    @staticmethod
    def _parse_completion_item(item: dict[str, Any]) -> CompletionItem:
        return CompletionItem(
            label=item.get("label", ""),
            kind=item.get("kind", 0),
            detail=item.get("detail", ""),
            documentation=(
                item.get("documentation", "")
                if isinstance(item.get("documentation"), str)
                else item.get("documentation", {}).get("value", "")
            ),
            insert_text=item.get("insertText", ""),
        )

    @classmethod
    def _parse_locations(cls, result: Any) -> list[Location]:
        """解析 Location / Location[] / LocationLink[]"""
        if result is None:
            return []
        if isinstance(result, dict):
            return [cls._parse_location(result)]
        if isinstance(result, list):
            return [cls._parse_location(item) for item in result]
        return []

    @staticmethod
    def _parse_location(item: dict[str, Any]) -> Location:
        rng = item.get("range", {})
        start = rng.get("start", {})
        end = rng.get("end", {})
        return Location(
            uri=item.get("uri", ""),
            line=start.get("line", 0),
            character=start.get("character", 0),
            end_line=end.get("line", 0),
            end_character=end.get("character", 0),
        )

    @staticmethod
    def _parse_hover(result: dict[str, Any]) -> Hover:
        contents = result.get("contents", "")
        if isinstance(contents, dict):
            contents = contents.get("value", "")
        elif isinstance(contents, list):
            contents = "\n".join(
                c.get("value", "") if isinstance(c, dict) else str(c) for c in contents
            )
        rng = result.get("range", {})
        start = rng.get("start", {})
        return Hover(
            contents=contents,
            line=start.get("line", 0),
            character=start.get("character", 0),
        )

    @classmethod
    def _parse_symbol(cls, item: dict[str, Any]) -> DocumentSymbol:
        rng = item.get("range", {})
        start = rng.get("start", {})
        children = [cls._parse_symbol(c) for c in item.get("children", [])]
        return DocumentSymbol(
            name=item.get("name", ""),
            kind=item.get("kind", 0),
            line=start.get("line", 0),
            character=start.get("character", 0),
            detail=item.get("detail", ""),
            children=children,
        )
