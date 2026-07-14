"""
ws_handler.py 模块单元测试 — 覆盖率目标 ≥70%

覆盖内容:
  - websocket_chat 主入口的各类消息分支
  - _strip_code_fence 工具函数

测试策略:
  - 自定义 FakeWebSocket 类模拟 ws.accept/send_json/send_text/receive_text
  - 通过 monkeypatch 替换所有外部依赖: session_store, chat_handler,
    hermes_engine, session_share, project_helpers, mcp_tools 等
  - 每个测试发送一组消息序列, 最后断开连接, 收集发出的消息进行断言
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

from pycoder.server.ws_handler import _strip_code_fence, websocket_chat


# ── FakeWebSocket ──

class FakeWebSocket:
    """模拟 WebSocket, 通过队列控制 receive_text 返回值"""

    def __init__(self, messages: list[str] | None = None):
        # messages 是要接收的 JSON 字符串列表
        self._incoming = list(messages or [])
        self.sent: list[dict] = []
        self.sent_text: list[str] = []
        self.accepted = False
        self._idx = 0

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        self.sent.append(data)

    async def send_text(self, text: str):
        self.sent_text.append(text)

    async def receive_text(self) -> str:
        if self._idx >= len(self._incoming):
            # 模拟客户端断开连接
            raise WebSocketDisconnect()
        msg = self._incoming[self._idx]
        self._idx += 1
        return msg


# ── Mock 依赖 Fixture ──

@pytest.fixture
def setup_mocks(monkeypatch, tmp_path):
    """统一 mock 所有 ws_handler 的外部依赖"""
    # 1. session_store (在 ws_handler 中是别名导入, 需在 ws_handler 模块 patch)
    fake_store = MagicMock()
    fake_session = MagicMock()
    fake_session.id = "sess-123"
    fake_session.message_count = 0
    fake_session.model = None
    fake_store.get_last_session.return_value = None  # 默认无历史
    fake_store.create_session.return_value = MagicMock(id="new-sess")
    fake_store.get_session.return_value = MagicMock(id="sess-456")
    fake_store.list_sessions.return_value = []
    fake_store.get_messages.return_value = []
    fake_store.update_session.return_value = None
    fake_store.add_message.return_value = None
    monkeypatch.setattr(
        "pycoder.server.ws_handler.get_session_store",
        lambda: fake_store,
    )

    # 2. session_share manager (在 ws_handler 中是别名导入, 但来自 session_share 模块)
    fake_share = MagicMock()
    fake_share.join.return_value = None
    fake_share.leave.return_value = None
    fake_share.get_shared_sessions.return_value = 1
    fake_share.broadcast = AsyncMock()
    monkeypatch.setattr(
        "pycoder.server.ws_handler.get_session_share_manager",
        lambda: fake_share,
    )

    # 3. chat_handler (在 ws_handler 中是别名 chat_stream_fn / _get_effective_model)
    monkeypatch.setattr(
        "pycoder.server.ws_handler._get_effective_model",
        lambda m: m or "deepseek-chat",
    )
    # 默认空异步生成器
    async def empty_async_gen(*a, **k):
        if False:
            yield {}
    monkeypatch.setattr(
        "pycoder.server.ws_handler.chat_stream_fn",
        empty_async_gen,
    )

    # 4. hermes_engine (在 ws_handler 中直接导入 _execute_hermes_write)
    fake_hermes = AsyncMock(return_value={"success": True, "path": "x"})
    monkeypatch.setattr(
        "pycoder.server.ws_handler._execute_hermes_write",
        fake_hermes,
    )

    # 5. project_helpers (函数内 lazy import, 在源模块 patch)
    monkeypatch.setattr(
        "pycoder.server.project_helpers._get_project_tree",
        AsyncMock(return_value={"tree": "files"}),
    )
    monkeypatch.setattr(
        "pycoder.server.project_helpers._get_git_status",
        AsyncMock(return_value={"dirty": False}),
    )
    monkeypatch.setattr(
        "pycoder.server.project_helpers._get_diff_preview",
        AsyncMock(return_value={"diff": "diff content"}),
    )

    # 6. cloud_service: 注入 MagicMock 防止真实导入失败
    import sys as _sys
    fake_cs_mod = MagicMock()
    fake_cs = MagicMock()
    fake_cs_mod.get_cloud_service = lambda: fake_cs
    monkeypatch.setitem(_sys.modules, "pycoder.server.services.cloud_service", fake_cs_mod)

    return {
        "store": fake_store,
        "share": fake_share,
        "hermes": fake_hermes,
        "cloud_service": fake_cs,
    }


# ── _strip_code_fence ──

def test_strip_code_fence_with_language():
    """剥离 ```lang ... ``` 包裹"""
    text = "```python\nprint('hi')\n```"
    assert _strip_code_fence(text, "python") == "print('hi')"


def test_strip_code_fence_without_language():
    """剥离 ``` ... ``` 包裹"""
    text = "```\ncode\n```"
    assert _strip_code_fence(text) == "code"


def test_strip_code_fence_plain_text():
    """无 ``` 包裹的文本保持不变"""
    assert _strip_code_fence("plain code") == "plain code"


def test_strip_code_fence_empty():
    """空字符串处理"""
    assert _strip_code_fence("") == ""
    assert _strip_code_fence("   ") == ""


def test_strip_code_fence_only_opening_fence():
    """只有开头 ```"""
    assert _strip_code_fence("```python\ncode") == "code"


def test_strip_code_fence_only_closing_fence():
    """只有结尾 ```"""
    assert _strip_code_fence("code\n```") == "code"


# ── websocket_chat 连接初始化 ──

async def test_websocket_chat_connect_no_history(setup_mocks):
    """初次连接, 无历史会话, 创建新会话"""
    ws = FakeWebSocket(messages=[])  # 立即断开
    await websocket_chat(ws)
    assert ws.accepted is True
    # 第一条消息应是 connected
    assert ws.sent[0]["type"] == "connected"
    assert ws.sent[0]["session_id"]  # UUID 格式
    assert ws.sent[0]["has_history"] is False
    # store.create_session 应被调用
    setup_mocks["store"].create_session.assert_called_once()


async def test_websocket_chat_connect_with_history(setup_mocks):
    """有历史会话时恢复, has_history=True"""
    last_session = MagicMock()
    last_session.id = "existing-sess"
    last_session.message_count = 5
    last_session.model = "deepseek-coder"
    setup_mocks["store"].get_last_session.return_value = last_session
    ws = FakeWebSocket(messages=[])
    await websocket_chat(ws)
    assert ws.sent[0]["type"] == "connected"
    assert ws.sent[0]["session_id"] == "existing-sess"
    assert ws.sent[0]["has_history"] is True
    # 不应调用 create_session
    setup_mocks["store"].create_session.assert_not_called()


async def test_websocket_chat_connect_empty_session_reuse(setup_mocks):
    """空会话(0消息)被复用, has_history=False"""
    last_session = MagicMock()
    last_session.id = "empty-sess"
    last_session.message_count = 0
    last_session.model = None
    setup_mocks["store"].get_last_session.return_value = last_session
    ws = FakeWebSocket(messages=[])
    await websocket_chat(ws)
    assert ws.sent[0]["session_id"] == "empty-sess"
    assert ws.sent[0]["has_history"] is False


# ── 消息类型: create_session ──

async def test_msg_create_session(setup_mocks):
    """create_session 消息创建新会话"""
    setup_mocks["store"].get_session.return_value = MagicMock(id="new-id")
    ws = FakeWebSocket(messages=[json.dumps({"type": "create_session"})])
    await websocket_chat(ws)
    # 找到 session_created 消息
    created_msgs = [m for m in ws.sent if m.get("type") == "session_created"]
    assert len(created_msgs) == 1
    assert "session_id" in created_msgs[0]


# ── 会话共享 ──

async def test_msg_session_share_join(setup_mocks):
    """session_share_join 加入共享会话"""
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "session_share_join", "share_session_id": "shared-1"}),
    ])
    await websocket_chat(ws)
    setup_mocks["share"].join.assert_called_once()
    status_msgs = [m for m in ws.sent if m.get("type") == "session_share_status"]
    assert len(status_msgs) == 1
    assert status_msgs[0]["share_session_id"] == "shared-1"
    assert status_msgs[0]["shared_count"] == 1


async def test_msg_session_share_leave(setup_mocks):
    """session_share_leave 离开共享会话"""
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "session_share_leave"}),
    ])
    await websocket_chat(ws)
    setup_mocks["share"].leave.assert_called()
    status_msgs = [m for m in ws.sent if m.get("type") == "session_share_status"]
    assert status_msgs[-1]["shared_count"] == 0


# ── 会话切换 ──

async def test_msg_switch_session_existing(setup_mocks):
    """switch_session 切换到存在的会话"""
    setup_mocks["store"].get_session.return_value = MagicMock(id="target-sess")
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "switch_session", "session_id": "target-sess"}),
    ])
    await websocket_chat(ws)
    switched = [m for m in ws.sent if m.get("type") == "session_switched"]
    assert len(switched) == 1


async def test_msg_switch_session_nonexistent(setup_mocks):
    """switch_session 切换到不存在的会话: 不发 switched 消息"""
    setup_mocks["store"].get_session.return_value = None
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "switch_session", "session_id": "no-such"}),
    ])
    await websocket_chat(ws)
    switched = [m for m in ws.sent if m.get("type") == "session_switched"]
    assert len(switched) == 0


async def test_msg_list_sessions(setup_mocks):
    """list_sessions 返回会话列表"""
    fake_session = MagicMock()
    fake_session.to_dict.return_value = {"id": "s1"}
    setup_mocks["store"].list_sessions.return_value = [fake_session]
    ws = FakeWebSocket(messages=[json.dumps({"type": "list_sessions"})])
    await websocket_chat(ws)
    list_msgs = [m for m in ws.sent if m.get("type") == "session_list"]
    assert len(list_msgs) == 1
    assert list_msgs[0]["sessions"] == [{"id": "s1"}]


async def test_msg_history(setup_mocks):
    """history 消息返回历史消息"""
    fake_msg = MagicMock()
    fake_msg.to_dict.return_value = {"role": "user", "content": "hi"}
    setup_mocks["store"].get_messages.return_value = [fake_msg]
    ws = FakeWebSocket(messages=[json.dumps({"type": "history", "session_id": "s1"})])
    await websocket_chat(ws)
    history_msgs = [m for m in ws.sent if m.get("type") == "history"]
    assert len(history_msgs) == 1
    assert history_msgs[0]["session_id"] == "s1"


# ── execute_plan ──

async def test_msg_execute_plan_missing_plan(setup_mocks):
    """execute_plan 缺少 plan 字段返回错误"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "execute_plan"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "execute_plan requires 'plan'" in errors[0]["message"]


async def test_msg_execute_plan_success(setup_mocks, monkeypatch):
    """execute_plan 成功调用 agent_chat_stream"""
    async def fake_agent_stream(plan, model=None):
        yield {"type": "chunk", "content": "step1"}
        yield {"type": "done", "content": "final"}
    monkeypatch.setattr(
        "pycoder.server.services.agent_orchestrator.agent_chat_stream",
        fake_agent_stream,
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "execute_plan", "plan": "do x", "model": "gpt"})])
    await websocket_chat(ws)
    # 应收到 chunk 和 done 事件
    chunk_msgs = [m for m in ws.sent if m.get("type") == "chunk"]
    done_msgs = [m for m in ws.sent if m.get("type") == "done"]
    assert len(chunk_msgs) == 1
    assert len(done_msgs) == 1


async def test_msg_agent_chunk_triggers_exception_path(setup_mocks):
    """agent_chunk 消息触发源代码 bug (data.get on string),
    异常被外层 except 捕获, share_mgr.leave 被调用 (覆盖 line 116-118)"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "agent_chunk", "content": "x"})])
    await websocket_chat(ws)
    # 异常应被外层 except 捕获, share_mgr.leave 被调用清理
    setup_mocks["share"].leave.assert_called()
    assert ws.accepted is True


# ── write_file ──

async def test_msg_write_file_missing_path(setup_mocks):
    """write_file 缺少 path 返回错误"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "write_file"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "write_file requires 'path'" in errors[0]["message"]


async def test_msg_write_file_success(setup_mocks):
    """write_file 成功调用 hermes_engine"""
    setup_mocks["hermes"].return_value = {"success": True, "path": "/x.py"}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "write_file", "path": "/x.py", "content": "code"}),
    ])
    await websocket_chat(ws)
    setup_mocks["hermes"].assert_awaited_once_with("/x.py", "code")
    result_msgs = [m for m in ws.sent if m.get("type") == "file_write_result"]
    assert len(result_msgs) == 1
    assert result_msgs[0]["success"] is True


# ── project_tree ──

async def test_msg_project_tree_success(setup_mocks):
    """project_tree 成功返回"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "project_tree", "path": "/x", "max_depth": 2})])
    await websocket_chat(ws)
    tree_msgs = [m for m in ws.sent if m.get("type") == "project_tree"]
    assert len(tree_msgs) == 1
    assert "tree" in tree_msgs[0]


async def test_msg_project_tree_exception(setup_mocks, monkeypatch):
    """project_tree 抛异常时返回 error"""
    monkeypatch.setattr(
        "pycoder.server.project_helpers._get_project_tree",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "project_tree"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "Failed" in errors[0]["message"]


# ── file_open ──

async def test_msg_file_open_missing_path(setup_mocks):
    """file_open 缺少 path 返回错误"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "file_open"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "file_open requires 'path'" in errors[0]["message"]


async def test_msg_file_open_not_found(setup_mocks, monkeypatch, tmp_path):
    """file_open 文件不存在"""
    fake_target = MagicMock()
    fake_target.exists.return_value = False
    monkeypatch.setattr(
        "pycoder.server.routers.files._safe_path",
        lambda p: fake_target,
    )
    monkeypatch.setattr(
        "pycoder.server.routers.files.HTTPException",
        type("FakeHTTPException", (Exception,), {"__init__": lambda self, **kw: setattr(self, "detail", kw.get("detail", ""))}),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "file_open", "path": "/no.py"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "Not found" in errors[0]["message"]


async def test_msg_file_open_success(setup_mocks, monkeypatch, tmp_path):
    """file_open 成功读取文件"""
    real_file = tmp_path / "test.py"
    real_file.write_text("print('hi')", encoding="utf-8")
    monkeypatch.setattr(
        "pycoder.server.routers.files._safe_path",
        lambda p: real_file,
    )
    monkeypatch.setattr(
        "pycoder.server.routers.files.HTTPException",
        type("FakeHTTPException", (Exception,), {"__init__": lambda self, **kw: setattr(self, "detail", kw.get("detail", ""))}),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "file_open", "path": "test.py"})])
    await websocket_chat(ws)
    open_msgs = [m for m in ws.sent if m.get("type") == "file_open" and "content" in m]
    assert len(open_msgs) == 1
    assert open_msgs[0]["content"] == "print('hi')"
    assert open_msgs[0]["name"] == "test.py"


async def test_msg_file_open_http_exception(setup_mocks, monkeypatch):
    """file_open 触发 HTTPException"""
    class FakeHTTPException(Exception):
        def __init__(self, **kw):
            self.detail = kw.get("detail", "")
    monkeypatch.setattr(
        "pycoder.server.routers.files.HTTPException",
        FakeHTTPException,
    )
    def raise_http(p):
        raise FakeHTTPException(detail="forbidden")
    monkeypatch.setattr("pycoder.server.routers.files._safe_path", raise_http)
    ws = FakeWebSocket(messages=[json.dumps({"type": "file_open", "path": "/x"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "forbidden" in errors[0]["message"]


async def test_msg_file_open_generic_exception(setup_mocks, monkeypatch):
    """file_open 触发非 HTTPException 的异常 (覆盖 line 164-165)"""
    monkeypatch.setattr(
        "pycoder.server.routers.files.HTTPException",
        type("FakeHTTPException", (Exception,), {"__init__": lambda self, **kw: setattr(self, "detail", kw.get("detail", ""))}),
    )
    def raise_runtime(p):
        raise RuntimeError("disk error")
    monkeypatch.setattr("pycoder.server.routers.files._safe_path", raise_runtime)
    ws = FakeWebSocket(messages=[json.dumps({"type": "file_open", "path": "/x"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "Error reading" in errors[0]["message"]


# ── diff_preview / git_status ──

async def test_msg_diff_preview_success(setup_mocks):
    ws = FakeWebSocket(messages=[json.dumps({"type": "diff_preview", "file": "x.py", "staged": True})])
    await websocket_chat(ws)
    diff_msgs = [m for m in ws.sent if m.get("type") == "diff_preview"]
    assert len(diff_msgs) == 1


async def test_msg_diff_preview_exception(setup_mocks, monkeypatch):
    monkeypatch.setattr(
        "pycoder.server.project_helpers._get_diff_preview",
        AsyncMock(side_effect=RuntimeError("git err")),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "diff_preview"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "Diff failed" in errors[0]["message"]


async def test_msg_git_status_success(setup_mocks):
    ws = FakeWebSocket(messages=[json.dumps({"type": "git_status", "path": "/x"})])
    await websocket_chat(ws)
    status_msgs = [m for m in ws.sent if m.get("type") == "git_status"]
    assert len(status_msgs) == 1


async def test_msg_git_status_exception(setup_mocks, monkeypatch):
    monkeypatch.setattr(
        "pycoder.server.project_helpers._get_git_status",
        AsyncMock(side_effect=RuntimeError("git err")),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "git_status"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "Git status failed" in errors[0]["message"]


# ── MCP 消息 ──

async def test_msg_mcp_list(setup_mocks, monkeypatch):
    """mcp_list 列出工具"""
    fake_mgr = MagicMock()
    fake_mgr.connected_servers = ["server1"]
    fake_mgr.list_remote_tools = AsyncMock(return_value=[{"name": "tool1"}])
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.list_builtin_tools",
        lambda: [{"name": "builtin1"}],
    )
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.get_mcp_client_manager",
        lambda: fake_mgr,
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "mcp_list"})])
    await websocket_chat(ws)
    mcp_msgs = [m for m in ws.sent if m.get("type") == "mcp_tools"]
    assert len(mcp_msgs) == 1
    assert mcp_msgs[0]["total"] == 2  # 1 builtin + 1 remote


async def test_msg_mcp_call_missing_tool(setup_mocks):
    """mcp_call 缺少 tool 字段返回错误"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "mcp_call"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "mcp_call requires 'tool'" in errors[0]["message"]


async def test_msg_mcp_call_builtin(setup_mocks, monkeypatch):
    """mcp_call 调用内置工具"""
    fake_result = MagicMock()
    fake_result.success = True
    fake_result.output = "result"
    fake_result.error = ""
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.call_builtin_tool",
        AsyncMock(return_value=fake_result),
    )
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.get_mcp_client_manager",
        lambda: MagicMock(connected_servers=[]),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "mcp_call", "tool": "builtin_tool", "args": {}})])
    await websocket_chat(ws)
    result_msgs = [m for m in ws.sent if m.get("type") == "mcp_result"]
    assert len(result_msgs) == 1
    assert result_msgs[0]["tool"] == "builtin_tool"
    assert result_msgs[0]["success"] is True


async def test_msg_mcp_call_external_valid(setup_mocks, monkeypatch):
    """mcp_call 调用外部 mcp:server/tool 工具"""
    fake_mgr = MagicMock()
    fake_result = MagicMock(success=True, output="x", error="")
    fake_mgr.call_remote_tool = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.get_mcp_client_manager",
        lambda: fake_mgr,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "mcp_call", "tool": "mcp:server1/tool1", "args": {}}),
    ])
    await websocket_chat(ws)
    result_msgs = [m for m in ws.sent if m.get("type") == "mcp_result"]
    assert len(result_msgs) == 1
    fake_mgr.call_remote_tool.assert_awaited_once_with("server1", "tool1", {})


async def test_msg_mcp_call_external_invalid_format(setup_mocks, monkeypatch):
    """mcp_call 外部工具引用格式错误"""
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.get_mcp_client_manager",
        lambda: MagicMock(connected_servers=[]),
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "mcp_call", "tool": "mcp:noslash", "args": {}}),
    ])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "无效的外部工具引用" in errors[0]["message"]


async def test_msg_mcp_connect_missing_args(setup_mocks):
    """mcp_connect 缺少 name 或 command"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "mcp_connect", "name": "x"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "mcp_connect requires" in errors[0]["message"]


async def test_msg_mcp_connect_success(setup_mocks, monkeypatch):
    """mcp_connect 成功连接"""
    fake_mgr = MagicMock()
    fake_mgr.connect_stdio = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.get_mcp_client_manager",
        lambda: fake_mgr,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "mcp_connect", "name": "x", "command": "cmd", "args": []}),
    ])
    await websocket_chat(ws)
    connect_msgs = [m for m in ws.sent if m.get("type") == "mcp_connect_result"]
    assert len(connect_msgs) == 1
    assert connect_msgs[0]["success"] is True


async def test_msg_mcp_disconnect_missing_name(setup_mocks):
    """mcp_disconnect 缺少 name 返回错误"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "mcp_disconnect"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "mcp_disconnect requires" in errors[0]["message"]


async def test_msg_mcp_disconnect_success(setup_mocks, monkeypatch):
    """mcp_disconnect 成功"""
    fake_mgr = MagicMock()
    fake_mgr.disconnect = AsyncMock()
    monkeypatch.setattr(
        "pycoder.server.mcp_tools.get_mcp_client_manager",
        lambda: fake_mgr,
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "mcp_disconnect", "name": "x"})])
    await websocket_chat(ws)
    dis_msgs = [m for m in ws.sent if m.get("type") == "mcp_disconnect_result"]
    assert len(dis_msgs) == 1
    assert dis_msgs[0]["success"] is True


# ── inline_edit ──

async def test_msg_inline_edit_missing_args(setup_mocks):
    """inline_edit 缺少 code 或 instruction"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "inline_edit", "code": "x"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "inline_edit requires" in errors[0]["message"]


async def test_msg_inline_edit_success(setup_mocks, monkeypatch):
    """inline_edit 成功调用 chat_stream 并返回结果"""
    async def fake_stream(*args, **kwargs):
        yield {"type": "chunk", "content": "part"}
        yield {"type": "done", "content": "```python\nfinal code\n```"}
    monkeypatch.setattr(
        "pycoder.server.ws_handler.chat_stream_fn",
        fake_stream,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "inline_edit", "code": "x", "instruction": "fix",
            "language": "python", "request_id": "r1",
        }),
    ])
    await websocket_chat(ws)
    done_msgs = [m for m in ws.sent if m.get("type") == "inline_edit_done"]
    assert len(done_msgs) == 1
    assert done_msgs[0]["request_id"] == "r1"
    # 应剥离 ```python ... ``` 包裹
    assert done_msgs[0]["code"] == "final code"


# ── run_fix ──

async def test_msg_run_fix_missing_task(setup_mocks):
    """run_fix 缺少 task"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "run_fix"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "run_fix requires 'task'" in errors[0]["message"]


async def test_msg_run_fix_success(setup_mocks, monkeypatch):
    """run_fix 成功执行"""
    from pycoder.server.services.run_fix_loop import RunFixLoop
    fake_loop = MagicMock()
    fake_loop.execute = AsyncMock(return_value=MagicMock(
        success=True, total_retries=2, final_code="code",
        exec_output="output", duration_ms=100.0,
        steps=[],
    ))
    monkeypatch.setattr(RunFixLoop, "execute", fake_loop.execute)
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "run_fix", "task": "do x", "target_file": "sol.py"}),
    ])
    await websocket_chat(ws)
    done_msgs = [m for m in ws.sent if m.get("type") == "run_fix_done"]
    assert len(done_msgs) == 1
    assert done_msgs[0]["success"] is True


# ── dep_agent ──

async def test_msg_dep_agent_missing_code(setup_mocks):
    """dep_agent 缺少 code"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "dep_agent"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "dep_agent requires 'code'" in errors[0]["message"]


async def test_msg_dep_agent_success(setup_mocks, monkeypatch):
    """dep_agent 成功"""
    monkeypatch.setattr(
        "pycoder.python.project_tools.auto_dep_agent",
        AsyncMock(return_value={"installed": ["pkg1"]}),
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "dep_agent", "code": "import pkg1"})])
    await websocket_chat(ws)
    done_msgs = [m for m in ws.sent if m.get("type") == "dep_agent_done"]
    assert len(done_msgs) == 1
    assert done_msgs[0]["installed"] == ["pkg1"]


# ── quality_check ──

async def test_msg_quality_check_missing_file(setup_mocks):
    """quality_check 缺少 file_path"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "quality_check"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "quality_check requires" in errors[0]["message"]


async def test_msg_quality_check_success(setup_mocks, monkeypatch):
    """quality_check 成功"""
    fake_report = MagicMock()
    fake_report.success = True
    fake_report.score = 85
    fake_report.lint_score = 90
    fake_report.security_score = 80
    fake_report.complexity_score = 85
    fake_report.format_ok = True
    fake_report.summary = "ok"
    fake_report.issues = []
    fake_guard = MagicMock()
    fake_guard.check = AsyncMock(return_value=fake_report)
    monkeypatch.setattr(
        "pycoder.server.services.quality_guard.QualityGuard",
        lambda: fake_guard,
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "quality_check", "file_path": "x.py"})])
    await websocket_chat(ws)
    report_msgs = [m for m in ws.sent if m.get("type") == "quality_report"]
    assert len(report_msgs) == 1
    assert report_msgs[0]["score"] == 85


# ── test_generator ──

async def test_msg_test_generator_missing_file(setup_mocks):
    """test_generator 缺少 file_path"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "test_generator"})])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "test_generator requires" in errors[0]["message"]


async def test_msg_test_generator_success(setup_mocks, monkeypatch):
    """test_generator 成功"""
    fake_gen = MagicMock()
    fake_gen.generate.return_value = MagicMock(
        success=True, test_file="t.py", test_count=3,
        passed=3, failed=0, coverage_percent=80.0,
        output="ok", error="", duration_ms=100.0,
    )
    monkeypatch.setattr(
        "pycoder.server.services.test_generator.TestGenerator",
        lambda: fake_gen,
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "test_generator", "file_path": "x.py"})])
    await websocket_chat(ws)
    done_msgs = [m for m in ws.sent if m.get("type") == "test_generator_done"]
    assert len(done_msgs) == 1
    assert done_msgs[0]["test_count"] == 3


# ── team_ws ──

async def test_msg_team_ws_create(setup_mocks, monkeypatch):
    """team_ws create 子命令"""
    fake_tw = MagicMock()
    fake_tw.create_workspace.return_value = {"success": True, "workspace_id": "w1"}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "create", "name": "W", "created_by": "alice"}),
    ])
    await websocket_chat(ws)
    fake_tw.create_workspace.assert_called_once_with("W", "alice")
    result_msgs = [m for m in ws.sent if m.get("type") == "team_ws_result"]
    assert len(result_msgs) == 1
    assert result_msgs[0]["subcommand"] == "create"


async def test_msg_team_ws_list(setup_mocks, monkeypatch):
    fake_tw = MagicMock()
    fake_tw.list_workspaces.return_value = [{"id": "w1"}]
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[json.dumps({"type": "team_ws", "subcommand": "list"})])
    await websocket_chat(ws)
    result_msgs = [m for m in ws.sent if m.get("type") == "team_ws_result"]
    assert result_msgs[0]["workspaces"] == [{"id": "w1"}]


async def test_msg_team_ws_unknown_subcmd(setup_mocks, monkeypatch):
    """未知 team_ws 子命令"""
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: MagicMock(),
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "unknown_cmd"}),
    ])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "未知 team_ws 子命令" in errors[0]["message"]


async def test_msg_team_ws_get(setup_mocks, monkeypatch):
    """team_ws get 子命令"""
    fake_tw = MagicMock()
    fake_tw.get_workspace.return_value = {"id": "w1", "name": "W"}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "get", "workspace_id": "w1"}),
    ])
    await websocket_chat(ws)
    fake_tw.get_workspace.assert_called_once_with("w1")
    result_msgs = [m for m in ws.sent if m.get("type") == "team_ws_result"]
    assert result_msgs[0]["workspace"] == {"id": "w1", "name": "W"}


async def test_msg_team_ws_delete(setup_mocks, monkeypatch):
    """team_ws delete 子命令"""
    fake_tw = MagicMock()
    fake_tw.delete_workspace.return_value = {"success": True}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "delete", "workspace_id": "w1"}),
    ])
    await websocket_chat(ws)
    fake_tw.delete_workspace.assert_called_once_with("w1")


async def test_msg_team_ws_join(setup_mocks, monkeypatch):
    """team_ws join 子命令"""
    fake_tw = MagicMock()
    fake_tw.join_workspace.return_value = {"success": True, "member_id": "m1"}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "join", "workspace_id": "w1", "display_name": "bob"}),
    ])
    await websocket_chat(ws)
    fake_tw.join_workspace.assert_called_once_with("w1", "bob")


async def test_msg_team_ws_leave(setup_mocks, monkeypatch):
    """team_ws leave 子命令"""
    fake_tw = MagicMock()
    fake_tw.leave_workspace.return_value = {"success": True}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "leave", "member_id": "m1"}),
    ])
    await websocket_chat(ws)
    fake_tw.leave_workspace.assert_called_once_with("m1")


async def test_msg_team_ws_members(setup_mocks, monkeypatch):
    """team_ws members 子命令"""
    fake_tw = MagicMock()
    fake_tw.list_members.return_value = [{"id": "m1"}]
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "team_ws", "subcommand": "members", "workspace_id": "w1"}),
    ])
    await websocket_chat(ws)
    result_msgs = [m for m in ws.sent if m.get("type") == "team_ws_result"]
    assert result_msgs[0]["members"] == [{"id": "m1"}]


async def test_msg_team_ws_review_create(setup_mocks, monkeypatch):
    """team_ws review_create 子命令"""
    fake_tw = MagicMock()
    fake_tw.create_review_request.return_value = {"success": True, "review_id": "r1"}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "team_ws", "subcommand": "review_create",
            "workspace_id": "w1", "title": "T", "requested_by": "alice",
            "file_path": "x.py", "code_snippet": "code", "description": "desc",
            "assigned_to": ["bob"],
        }),
    ])
    await websocket_chat(ws)
    fake_tw.create_review_request.assert_called_once_with(
        "w1", "T", "alice", "x.py", "code", "desc", ["bob"],
    )


async def test_msg_team_ws_review_list(setup_mocks, monkeypatch):
    """team_ws review_list 子命令"""
    fake_tw = MagicMock()
    fake_tw.list_review_requests.return_value = [{"id": "r1"}]
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "team_ws", "subcommand": "review_list",
            "workspace_id": "w1", "status": "open",
        }),
    ])
    await websocket_chat(ws)
    fake_tw.list_review_requests.assert_called_once_with("w1", "open")
    result_msgs = [m for m in ws.sent if m.get("type") == "team_ws_result"]
    assert result_msgs[0]["reviews"] == [{"id": "r1"}]


async def test_msg_team_ws_review_comment(setup_mocks, monkeypatch):
    """team_ws review_comment 子命令"""
    fake_tw = MagicMock()
    fake_tw.add_review_comment.return_value = {"success": True}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "team_ws", "subcommand": "review_comment",
            "review_id": "r1", "user": "alice", "comment": "ok",
        }),
    ])
    await websocket_chat(ws)
    fake_tw.add_review_comment.assert_called_once_with("r1", "alice", "ok")


async def test_msg_team_ws_review_status(setup_mocks, monkeypatch):
    """team_ws review_status 子命令"""
    fake_tw = MagicMock()
    fake_tw.update_review_status.return_value = {"success": True}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "team_ws", "subcommand": "review_status",
            "review_id": "r1", "status": "approved",
        }),
    ])
    await websocket_chat(ws)
    fake_tw.update_review_status.assert_called_once_with("r1", "approved")


async def test_msg_team_ws_activity(setup_mocks, monkeypatch):
    """team_ws activity 子命令"""
    fake_tw = MagicMock()
    fake_tw.get_activity_feed.return_value = [{"action": "chat"}]
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "team_ws", "subcommand": "activity",
            "workspace_id": "w1", "limit": 10,
        }),
    ])
    await websocket_chat(ws)
    fake_tw.get_activity_feed.assert_called_once_with("w1", 10)


async def test_msg_team_ws_share_session(setup_mocks, monkeypatch):
    """team_ws share_session 子命令"""
    fake_tw = MagicMock()
    fake_tw.share_session.return_value = {"success": True}
    monkeypatch.setattr(
        "pycoder.server.services.team_workspace.get_team_workspace_manager",
        lambda: fake_tw,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "team_ws", "subcommand": "share_session",
            "workspace_id": "w1", "session_id": "sess-1", "user_name": "alice",
        }),
    ])
    await websocket_chat(ws)
    fake_tw.share_session.assert_called_once_with("w1", "sess-1", "alice")


# ── cloud ──

async def test_msg_cloud_register(setup_mocks):
    """cloud register 子命令"""
    setup_mocks["cloud_service"].register.return_value = {"success": True, "token": "t1"}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "register", "username": "u", "password": "p"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].register.assert_called_once_with("u", "p", "")
    result_msgs = [m for m in ws.sent if m.get("type") == "cloud_result"]
    assert result_msgs[0]["subcommand"] == "register"


async def test_msg_cloud_unknown_subcmd(setup_mocks):
    """未知 cloud 子命令"""
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "unknown"}),
    ])
    await websocket_chat(ws)
    errors = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errors) == 1
    assert "未知 cloud 子命令" in errors[0]["message"]


async def test_msg_cloud_login(setup_mocks):
    """cloud login 子命令"""
    setup_mocks["cloud_service"].login.return_value = {"success": True, "token": "t"}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "login", "username": "u", "password": "p"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].login.assert_called_once_with("u", "p")


async def test_msg_cloud_user_info(setup_mocks):
    """cloud user_info 子命令"""
    setup_mocks["cloud_service"].get_user_info.return_value = {"username": "u"}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "user_info", "token": "t"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].get_user_info.assert_called_once_with("t")


async def test_msg_cloud_check_quota(setup_mocks):
    """cloud check_quota 子命令"""
    setup_mocks["cloud_service"].check_quota.return_value = {"quota": 100}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "check_quota", "token": "t"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].check_quota.assert_called_once_with("t")


async def test_msg_cloud_usage_history(setup_mocks):
    """cloud usage_history 子命令"""
    setup_mocks["cloud_service"].get_usage_history.return_value = {"days": 7}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "usage_history", "token": "t", "days": 7}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].get_usage_history.assert_called_once_with("t", 7)


async def test_msg_cloud_track_usage(setup_mocks):
    """cloud track_usage 子命令"""
    setup_mocks["cloud_service"].track_usage.return_value = {"ok": True}
    ws = FakeWebSocket(messages=[
        json.dumps({
            "type": "cloud", "subcommand": "track_usage",
            "token": "t", "model": "gpt", "tokens_in": 10, "tokens_out": 20,
        }),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].track_usage.assert_called_once_with("t", "gpt", 10, 20)


async def test_msg_cloud_plans(setup_mocks):
    """cloud plans 子命令"""
    setup_mocks["cloud_service"].get_plan_upgrade_info.return_value = [{"plan": "pro"}]
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "plans"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].get_plan_upgrade_info.assert_called_once()


async def test_msg_cloud_upgrade(setup_mocks):
    """cloud upgrade 子命令"""
    setup_mocks["cloud_service"].upgrade_plan.return_value = {"success": True}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "upgrade", "token": "t", "plan": "pro"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].upgrade_plan.assert_called_once_with("t", "pro")


async def test_msg_cloud_add_key(setup_mocks):
    """cloud add_key 子命令"""
    setup_mocks["cloud_service"].add_api_key.return_value = {"ok": True}
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "add_key", "provider": "openai", "api_key": "sk-xxx"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].add_api_key.assert_called_once_with("openai", "sk-xxx")


async def test_msg_cloud_list_keys(setup_mocks):
    """cloud list_keys 子命令"""
    setup_mocks["cloud_service"].list_api_keys.return_value = [{"provider": "openai"}]
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "cloud", "subcommand": "list_keys"}),
    ])
    await websocket_chat(ws)
    setup_mocks["cloud_service"].list_api_keys.assert_called_once()


async def test_msg_regular_chat_with_shared_session(setup_mocks, monkeypatch):
    """普通聊天 + 共享会话: 完成后调用 share_mgr.broadcast"""
    # 先加入共享会话
    setup_mocks["share"].get_shared_sessions.return_value = 1
    async def fake_stream(*args, **kwargs):
        yield {"type": "done", "content": "final answer"}
    monkeypatch.setattr(
        "pycoder.server.ws_handler.chat_stream_fn",
        fake_stream,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "session_share_join", "share_session_id": "shared-1"}),
        json.dumps({"type": "message", "message": "hi"}),
    ])
    await websocket_chat(ws)
    # broadcast 应被调用 (排除 client_id)
    setup_mocks["share"].broadcast.assert_awaited()
    call_args = setup_mocks["share"].broadcast.call_args
    assert call_args.args[0] == "shared-1"
    assert call_args.kwargs.get("exclude") is not None


# ── 默认消息路径 (普通聊天) ──

async def test_msg_empty_message_skipped(setup_mocks):
    """空消息被跳过"""
    ws = FakeWebSocket(messages=[json.dumps({"type": "message", "message": ""})])
    await websocket_chat(ws)
    # 不应有 chunk/done 等消息（除了 connected）
    chunk_msgs = [m for m in ws.sent if m.get("type") in ("chunk", "done")]
    assert len(chunk_msgs) == 0


async def test_msg_regular_chat(setup_mocks, monkeypatch):
    """普通聊天消息触发 chat_stream

    消息持久化已由 chat_stream_fn 内部处理（见 ws_handler.py L645 注释），
    因此不再断言 store.add_message 在 ws_handler 层被调用。
    """
    captured_calls = []

    async def fake_stream(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        yield {"type": "chunk", "content": "hello"}
        yield {"type": "done", "content": "hello world"}

    monkeypatch.setattr(
        "pycoder.server.ws_handler.chat_stream_fn",
        fake_stream,
    )
    ws = FakeWebSocket(messages=[
        json.dumps({"type": "message", "message": "hi", "model": "gpt-4"}),
    ])
    await websocket_chat(ws)
    chunk_msgs = [m for m in ws.sent if m.get("type") == "chunk"]
    done_msgs = [m for m in ws.sent if m.get("type") == "done"]
    assert len(chunk_msgs) == 1
    assert len(done_msgs) == 1
    # chat_stream_fn 应以连接时的 session_id 调用
    assert len(captured_calls) == 1
    assert captured_calls[0]["args"][0] == ws.sent[0]["session_id"]
    assert captured_calls[0]["args"][1] == "hi"


# ── WebSocketDisconnect 处理 ──

async def test_websocket_disconnect_handled(setup_mocks):
    """WebSocketDisconnect 异常被妥善处理, 不抛出"""
    ws = FakeWebSocket(messages=[])  # 立即断开
    # 不应抛出异常
    await websocket_chat(ws)
    assert ws.accepted is True


async def test_websocket_general_exception_handled(setup_mocks, monkeypatch):
    """普通异常被 outer except 捕获, share_mgr.leave 被调用

    异常发生在主循环内 (ws.receive_text 抛 RuntimeError, 非 WebSocketDisconnect)
    """
    class ErrorWebSocket(FakeWebSocket):
        async def receive_text(self):
            raise RuntimeError("boom")
    # 接受连接后立即抛 RuntimeError
    ws = ErrorWebSocket(messages=[])
    await websocket_chat(ws)
    assert ws.accepted is True
    setup_mocks["share"].leave.assert_called()
