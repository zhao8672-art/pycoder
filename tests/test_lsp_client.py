"""LSP 协议与客户端单元测试

测试覆盖:
    - LSP 消息编解码 (JSON-RPC 2.0 帧)
    - LSPMessage 数据类 (请求/通知/响应)
    - LSPClient 配置与状态管理
    - 数据类转换 (CompletionItem/Location/Hover/DocumentSymbol)
"""
from __future__ import annotations

import asyncio
import json

import pytest

from pycoder.lsp.protocol import (
    CONTENT_LENGTH_HEADER,
    LSPMessage,
    decode_message,
    encode_message,
    make_error_response,
    make_notification,
    make_request,
    make_response,
)
from pycoder.lsp.client import (
    CompletionItem,
    DocumentSymbol,
    Hover,
    Location,
    LSPClient,
    LSPClientConfig,
)


# ════════════════════════════════════════════════════════
# 协议层测试
# ════════════════════════════════════════════════════════


class TestLSPMessage:
    """LSP 消息数据类测试"""

    def test_request_message(self) -> None:
        msg = make_request(1, "initialize", {"rootUri": "file:///tmp"})
        assert msg.is_request()
        assert not msg.is_notification()
        assert not msg.is_response()
        assert msg.id == 1
        assert msg.method == "initialize"
        assert msg.params == {"rootUri": "file:///tmp"}

    def test_notification_message(self) -> None:
        msg = make_notification("textDocument/didOpen", {"textDocument": {}})
        assert msg.is_notification()
        assert not msg.is_request()
        assert msg.id is None
        assert msg.method == "textDocument/didOpen"

    def test_response_message(self) -> None:
        msg = make_response(1, {"capabilities": {}})
        assert msg.is_response()
        assert msg.id == 1
        assert msg.result == {"capabilities": {}}

    def test_error_response(self) -> None:
        msg = make_error_response(1, -32601, "Method not found")
        assert msg.is_response()
        assert msg.error == {"code": -32601, "message": "Method not found"}
        assert msg.result is None

    def test_to_dict_roundtrip(self) -> None:
        original = make_request(5, "textDocument/completion", {"line": 1})
        d = original.to_dict()
        restored = LSPMessage.from_dict(d)
        assert restored.id == 5
        assert restored.method == "textDocument/completion"
        assert restored.params == {"line": 1}


class TestMessageCodec:
    """消息帧编解码测试"""

    def test_encode_message_format(self) -> None:
        """编码后的消息包含 Content-Length header + JSON body"""
        msg = make_request(1, "initialize", {})
        data = encode_message(msg)
        assert data.startswith(CONTENT_LENGTH_HEADER)
        assert b"\r\n\r\n" in data
        # body 是合法 JSON
        body = data.split(b"\r\n\r\n", 1)[1]
        parsed = json.loads(body)
        assert parsed["method"] == "initialize"

    def test_encode_decode_roundtrip(self) -> None:
        """编码后解码应得到等价消息"""
        original = make_request(42, "textDocument/hover", {"line": 10, "character": 5})
        encoded = encode_message(original)

        async def _decode() -> LSPMessage:
            reader = asyncio.StreamReader()
            reader.feed_data(encoded)
            reader.feed_eof()
            return await decode_message(reader)

        restored = asyncio.run(_decode())
        assert restored.id == 42
        assert restored.method == "textDocument/hover"
        assert restored.params == {"line": 10, "character": 5}

    def test_decode_empty_stream(self) -> None:
        """空流应返回 None"""

        async def _decode() -> LSPMessage | None:
            reader = asyncio.StreamReader()
            reader.feed_eof()
            return await decode_message(reader)

        result = asyncio.run(_decode())
        assert result is None

    def test_encode_notification_no_id(self) -> None:
        """通知消息编码后无 id 字段"""
        msg = make_notification("initialized", {})
        d = msg.to_dict()
        assert "id" not in d
        assert d["method"] == "initialized"


# ════════════════════════════════════════════════════════
# 客户端数据类测试
# ════════════════════════════════════════════════════════


class TestCompletionItem:
    """补全项数据类测试"""

    def test_default_values(self) -> None:
        item = CompletionItem()
        assert item.label == ""
        assert item.kind == 0

    def test_to_dict(self) -> None:
        item = CompletionItem(label="print", kind=3, detail="builtin", insert_text="print(")
        d = item.to_dict()
        assert d["label"] == "print"
        assert d["kind"] == 3
        assert d["insertText"] == "print("


class TestLocation:
    """位置数据类测试"""

    def test_default_values(self) -> None:
        loc = Location()
        assert loc.uri == ""
        assert loc.line == 0

    def test_to_dict(self) -> None:
        loc = Location(uri="file:///tmp/test.py", line=10, character=5, end_line=10, end_character=10)
        d = loc.to_dict()
        assert d["uri"] == "file:///tmp/test.py"
        assert d["range"]["start"]["line"] == 10
        assert d["range"]["end"]["character"] == 10


class TestHover:
    """悬停提示数据类测试"""

    def test_default_values(self) -> None:
        h = Hover()
        assert h.contents == ""

    def test_to_dict(self) -> None:
        h = Hover(contents="def foo(): ...", line=5, character=0)
        d = h.to_dict()
        assert d["contents"] == "def foo(): ..."
        assert d["range"]["start"]["line"] == 5


class TestDocumentSymbol:
    """文档符号数据类测试"""

    def test_default_values(self) -> None:
        s = DocumentSymbol()
        assert s.name == ""
        assert s.children == []

    def test_nested_children(self) -> None:
        child = DocumentSymbol(name="method", kind=6, line=5)
        parent = DocumentSymbol(name="MyClass", kind=5, line=1, children=[child])
        d = parent.to_dict()
        assert d["name"] == "MyClass"
        assert len(d["children"]) == 1
        assert d["children"][0]["name"] == "method"

    def test_parse_symbol_recursive(self) -> None:
        """测试 _parse_symbol 递归解析"""
        raw = {
            "name": "outer",
            "kind": 5,
            "range": {"start": {"line": 1, "character": 0}, "end": {"line": 10, "character": 0}},
            "detail": "class",
            "children": [
                {
                    "name": "inner",
                    "kind": 6,
                    "range": {"start": {"line": 2, "character": 4}, "end": {"line": 3, "character": 4}},
                    "detail": "",
                    "children": [],
                }
            ],
        }
        symbol = LSPClient._parse_symbol(raw)
        assert symbol.name == "outer"
        assert symbol.line == 1
        assert len(symbol.children) == 1
        assert symbol.children[0].name == "inner"


# ════════════════════════════════════════════════════════
# 客户端配置与状态测试
# ════════════════════════════════════════════════════════


class TestLSPClientConfig:
    """LSP 客户端配置测试"""

    def test_default_config(self) -> None:
        cfg = LSPClientConfig()
        assert cfg.command == ["pyright-langserver", "--stdio"]
        assert cfg.language_id == "python"
        assert cfg.initialization_timeout == 30.0

    def test_custom_config(self) -> None:
        cfg = LSPClientConfig(
            command=["pylsp"],
            workspace="/tmp/project",
            language_id="python",
        )
        assert cfg.command == ["pylsp"]
        assert cfg.workspace == "/tmp/project"


class TestLSPClientState:
    """LSP 客户端状态管理测试 (不启动真实进程)"""

    def test_initial_state(self) -> None:
        client = LSPClient()
        assert client.is_running is False
        assert client.is_initialized is False
        assert client.server_capabilities == {}

    def test_path_to_uri(self) -> None:
        """文件路径转 URI"""
        uri = LSPClient._path_to_uri("test.py")
        assert uri.startswith("file://")
        assert uri.endswith("test.py")

    def test_parse_completion_item(self) -> None:
        """解析补全项 (含 markdown 文档)"""
        raw = {
            "label": "print",
            "kind": 3,
            "detail": "builtin function",
            "documentation": {"value": "Print to stdout", "kind": "markdown"},
            "insertText": "print(",
        }
        item = LSPClient._parse_completion_item(raw)
        assert item.label == "print"
        assert item.detail == "builtin function"
        assert item.documentation == "Print to stdout"

    def test_parse_completion_item_plain_doc(self) -> None:
        """解析补全项 (纯文本文档)"""
        raw = {"label": "len", "documentation": "Return length"}
        item = LSPClient._parse_completion_item(raw)
        assert item.documentation == "Return length"

    def test_parse_locations_single(self) -> None:
        """解析单个 Location"""
        raw = {
            "uri": "file:///tmp/test.py",
            "range": {
                "start": {"line": 10, "character": 5},
                "end": {"line": 10, "character": 15},
            },
        }
        locs = LSPClient._parse_locations(raw)
        assert len(locs) == 1
        assert locs[0].uri == "file:///tmp/test.py"
        assert locs[0].line == 10

    def test_parse_locations_list(self) -> None:
        """解析 Location 列表"""
        raw = [
            {"uri": "file:///a.py", "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 5}}},
            {"uri": "file:///b.py", "range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 5}}},
        ]
        locs = LSPClient._parse_locations(raw)
        assert len(locs) == 2
        assert locs[0].uri == "file:///a.py"
        assert locs[1].uri == "file:///b.py"

    def test_parse_locations_none(self) -> None:
        """None 输入返回空列表"""
        assert LSPClient._parse_locations(None) == []

    def test_parse_hover_markdown(self) -> None:
        """解析 Hover (markdown contents)"""
        raw = {
            "contents": {"value": "**bold** text", "kind": "markdown"},
            "range": {"start": {"line": 5, "character": 0}, "end": {"line": 5, "character": 10}},
        }
        hover = LSPClient._parse_hover(raw)
        assert hover.contents == "**bold** text"
        assert hover.line == 5

    def test_parse_hover_list_contents(self) -> None:
        """解析 Hover (列表 contents)"""
        raw = {
            "contents": [{"value": "doc1"}, "plain text"],
        }
        hover = LSPClient._parse_hover(raw)
        assert "doc1" in hover.contents
        assert "plain text" in hover.contents

    def test_text_document_position(self) -> None:
        """构造 TextDocumentPositionParams"""
        client = LSPClient()
        params = client._text_document_position("test.py", 10, 5)
        assert params["position"] == {"line": 10, "character": 5}
        assert "uri" in params["textDocument"]
