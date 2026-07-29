"""LSP 协议层 — JSON-RPC 2.0 over stdio 消息编解码

实现 LSP (Language Server Protocol) 底层通信:
- 消息帧编码/解码 (Content-Length header)
- JSON-RPC 2.0 请求/响应/通知
- 异步消息收发

参考: https://microsoft.github.io/language-server-protocol/
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── LSP 协议常量 ──────────────────────────────────────────

CONTENT_LENGTH_HEADER = b"Content-Length: "
HEADER_SEPARATOR = b"\r\n\r\n"


@dataclass
class LSPMessage:
    """LSP 消息（JSON-RPC 2.0）"""

    jsonrpc: str = "2.0"
    id: int | None = None  # 请求 ID (通知无 id)
    method: str = ""  # 方法名 (请求/通知)
    params: dict[str, Any] | None = None  # 请求/通知参数
    result: Any = None  # 响应结果
    error: dict[str, Any] | None = None  # 响应错误

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LSPMessage:
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            method=data.get("method", ""),
            params=data.get("params"),
            result=data.get("result"),
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            d["id"] = self.id
        if self.method:
            d["method"] = self.method
        if self.params is not None:
            d["params"] = self.params
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
        return d

    def is_request(self) -> bool:
        """是否为请求（有 id + method）"""
        return self.id is not None and bool(self.method)

    def is_notification(self) -> bool:
        """是否为通知（无 id + 有 method）"""
        return self.id is None and bool(self.method)

    def is_response(self) -> bool:
        """是否为响应（有 id + 无 method）"""
        return self.id is not None and not self.method


# ── 消息帧编解码 ──────────────────────────────────────────


def encode_message(message: LSPMessage) -> bytes:
    """将 LSPMessage 编码为 LSP 消息帧字节流

    帧格式:
        Content-Length: <n>\\r\\n\\r\\n<json-body>
    """
    body = json.dumps(message.to_dict(), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


async def decode_message(reader: asyncio.StreamReader) -> LSPMessage | None:
    """从流读取器异步解码一条 LSP 消息

    Args:
        reader: asyncio 流读取器 (subprocess.stdout)

    Returns:
        LSPMessage 或 None (流已关闭)
    """
    # 读取 header 直到空行
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line:
            return None  # EOF
        line = line.rstrip(b"\r\n")
        if not line:
            break  # header 结束
        if b":" in line:
            key, _, value = line.partition(b":")
            headers[key.decode("ascii").strip().lower()] = value.decode("ascii").strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length == 0:
        return None

    # 读取 body
    body = await reader.readexactly(content_length)
    data = json.loads(body.decode("utf-8"))
    return LSPMessage.from_dict(data)


# ── JSON-RPC 错误码 ───────────────────────────────────────

# 标准错误码 (参考 JSON-RPC 2.0 + LSP 扩展)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR_START = -32099
SERVER_NOT_INITIALIZED = -32002
REQUEST_CANCELLED = -32800
CONTENT_MODIFIED = -32801


def make_error_response(
    request_id: int, code: int, message: str, data: Any = None
) -> LSPMessage:
    """构造 JSON-RPC 错误响应"""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return LSPMessage(id=request_id, error=error)


def make_request(
    request_id: int, method: str, params: dict[str, Any] | None = None
) -> LSPMessage:
    """构造 JSON-RPC 请求"""
    return LSPMessage(id=request_id, method=method, params=params)


def make_notification(method: str, params: dict[str, Any] | None = None) -> LSPMessage:
    """构造 JSON-RPC 通知 (无 id，无需响应)"""
    return LSPMessage(method=method, params=params)


def make_response(request_id: int, result: Any) -> LSPMessage:
    """构造 JSON-RPC 成功响应"""
    return LSPMessage(id=request_id, result=result)
