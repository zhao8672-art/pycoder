"""
V2 WebSocket 处理器 — 将聊天流接入 V2 AI-Centric 引擎

相比 V1 ws_handler.py 的改进:
- 消息流经 V2 审计追踪 (AuditTrail)
- 工具调用通过 V2 能力总线 (CapabilityRegistry)
- Agent 状态通过 V2 意识引擎 (ConsciousnessEngine)
- V2 事件通过 CapabilityEvent 协议发送到前端

前端兼容: 保持与 V1 相同的事件格式 (type/token/reasoning/done 等)
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from pycoder import __version__
from pycoder.server.chat_handler import (
    _get_api_key_for_model,
    _get_effective_model,
)
from pycoder.server.hermes_engine import _execute_hermes_write
from pycoder.server.log import log
from pycoder.server.session_share import get_session_share_manager
from pycoder.server.session_store import get_session_store


async def websocket_chat_v2(ws: WebSocket):
    """V2 WebSocket 处理器 — AI-Centric 架构入口

    与 V1 ws_handler 完全兼容的前端事件格式，
    但内部接入 V2 引擎的能力总线、审计追踪和意识引擎。
    """
    from pycoder.server.app import get_v2_engine
    from pycoder.server.project_helpers import _get_diff_preview, _get_git_status, _get_project_tree

    await ws.accept()
    share_mgr = get_session_share_manager()
    store = get_session_store()

    # ── 获取 V2 引擎引用 ──
    v2 = get_v2_engine()

    # ── 会话恢复（复用 V1 逻辑）──
    last_session = store.get_last_session()
    if last_session:
        if last_session.message_count > 0:
            session_id = last_session.id
            current_model = last_session.model or "deepseek-chat"
        else:
            session_id = last_session.id
            current_model = "deepseek-chat"
    else:
        session_id = str(uuid.uuid4())
        store.create_session(session_id=session_id)
        current_model = "deepseek-chat"

    client_id = str(uuid.uuid4())[:8]
    has_hist = bool(last_session and last_session.message_count > 0)
    await ws.send_json(
        {
            "type": "connected",
            "session_id": session_id,
            "version": __version__,
            "has_history": has_hist,
            "engine": "v2",  # V2: 告知前端当前使用 V2 引擎
            "capabilities": v2.registry.count if v2 else 0,
            "trust_level": v2.permission.current_trust.name if v2 else "READ_ONLY",
        }
    )

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            # ── 会话管理（与 V1 相同）──
            if msg_type == "create_session":
                new_id = str(uuid.uuid4())
                store.create_session(session_id=new_id)
                session_id = new_id
                await ws.send_json({"type": "session_created", "session_id": new_id})
                continue

            if msg_type in ("session_share_join", "session_share_leave"):
                if msg_type == "session_share_join":
                    ssid = msg.get("share_session_id", "")
                    if ssid:
                        share_mgr.join(client_id, ssid, ws.send_text)
                        count = share_mgr.get_shared_sessions(ssid)
                        await ws.send_json({
                            "type": "session_share_status", "share_session_id": ssid,
                            "shared_count": count,
                        })
                else:
                    share_mgr.leave(client_id)
                    await ws.send_json({
                        "type": "session_share_status", "share_session_id": "", "shared_count": 0,
                    })
                continue

            if msg_type == "switch_session":
                new_id = msg.get("session_id", "")
                if new_id and store.get_session(new_id):
                    session_id = new_id
                    await ws.send_json({"type": "session_switched", "session_id": session_id})
                continue

            if msg_type == "list_sessions":
                sessions = store.list_sessions(limit=20)
                await ws.send_json({
                    "type": "session_list",
                    "sessions": [s.to_dict() for s in sessions],
                })
                continue

            if msg_type == "history":
                sid = msg.get("session_id", session_id)
                messages = store.get_messages(sid)
                await ws.send_json({
                    "type": "history", "session_id": sid,
                    "messages": [m.to_dict() for m in messages],
                })
                continue

            # ── V2 专用消息: 列出能力 ──
            if msg_type == "v2_capabilities":
                if v2:
                    caps = v2.registry.list_all()
                    await ws.send_json({
                        "type": "v2_capabilities",
                        "capabilities": [c.to_dict() for c in caps],
                        "total": len(caps),
                    })
                else:
                    await ws.send_json({
                        "type": "v2_capabilities", "capabilities": [], "total": 0,
                    })
                continue

            # ── V2 专用消息: 直接调用能力 ──
            if msg_type == "v2_call":
                cap_id = msg.get("capability_id", "")
                cap_params = msg.get("params", {})
                if not cap_id:
                    await ws.send_json({"type": "error", "message": "v2_call requires 'capability_id'"})
                    continue
                if v2:
                    try:
                        result = await v2.call(cap_id, cap_params)
                        await ws.send_json({
                            "type": "v2_call_result",
                            "capability_id": cap_id,
                            "success": result.success,
                            "data": result.data,
                            "error": result.error,
                        })
                    except Exception as e:
                        await ws.send_json({
                            "type": "v2_call_result", "capability_id": cap_id,
                            "success": False, "error": str(e),
                        })
                else:
                    await ws.send_json({
                        "type": "v2_call_result", "capability_id": cap_id,
                        "success": False, "error": "V2 engine not available",
                    })
                continue

            # ── execute_plan / agent 模式（委托给 V1 handler）──
            if msg_type in ("execute_plan", "agent_chunk"):
                if msg_type == "execute_plan":
                    plan_content = msg.get("plan", "")
                    model = msg.get("model", current_model)
                    if not plan_content:
                        await ws.send_json({"type": "error", "message": "execute_plan requires 'plan' field"})
                        continue
                    from pycoder.server.services.agent_orchestrator import (
                        agent_chat_stream as agent_stream,
                    )
                    async for event in agent_stream(plan_content, model=model):
                        await ws.send_json(event)
                        await asyncio.sleep(0)
                else:
                    chunk_data = msg.get("content", "")
                    await ws.send_json({"type": "agent_chunk", "content": chunk_data})
                continue

            # ── 文件 / 项目 / Git 操作（与 V1 相同）──
            if msg_type == "write_file":
                file_path = msg.get("path", "")
                file_content = msg.get("content", "")
                if not file_path:
                    await ws.send_json({"type": "error", "message": "write_file requires 'path' field"})
                    continue
                # V2: 通过能力总线执行写文件
                if v2:
                    result = await v2.call("editor.file.write", {"path": file_path, "content": file_content})
                    if result.success:
                        await ws.send_json({"type": "file_write_result", "success": True, "path": file_path})
                    else:
                        await ws.send_json({"type": "error", "message": result.error or "Write failed"})
                else:
                    result = await _execute_hermes_write(file_path, file_content)
                    await ws.send_json({"type": "file_write_result", **result})
                continue

            if msg_type in ("project_tree", "file_open", "diff_preview", "git_status"):
                await _handle_legacy_file_ops(msg_type, msg, ws, v2,
                                              _get_project_tree, _get_diff_preview, _get_git_status)
                continue

            # ── MCP 工具调用（V2: 通过能力总线）──
            if msg_type in ("mcp_list", "mcp_call", "mcp_connect", "mcp_disconnect"):
                await _handle_mcp_v2(msg_type, msg, ws, v2)
                continue

            # ── 内联编辑（与 V1 相同）──
            if msg_type == "inline_edit":
                await _handle_inline_edit(msg, ws)
                continue

            # ═══════════════════════════════════════════════
            # 核心聊天流（接入 V2 审计 + 上下文感知）
            # ═══════════════════════════════════════════════
            await _handle_chat_v2(msg, ws, session_id, current_model, store, v2)

    except WebSocketDisconnect:
        log.info("ws_v2_disconnect", extra={"session_id": session_id})
    except Exception as e:
        log.error("ws_v2_error", extra={"session_id": session_id, "error": str(e)})


async def _handle_chat_v2(msg: dict, ws: WebSocket, session_id: str, current_model: str, store, v2):
    """V2 统一入口聊天处理器 — 通过 UnifiedEntryAgent 自动路由三种模式

    改动: 不再需要前端传 hermes 参数，UnifiedEntryAgent 自动根据意图分类路由。
    """
    message = msg.get("message", "")
    files = msg.get("files")

    if not message and not files:
        log.warning(
            "ws_v2_empty_message",
            extra={
                "session_id": session_id,
                "msg_keys": list(msg.keys()),
                "raw_msg_type": msg.get("type", "unknown"),
            },
        )
        await ws.send_json({"type": "error", "message": "Empty message"})
        return

    model = msg.get("model", current_model)
    effective_model = _get_effective_model(model)

    # 获取 API Key
    api_key = _get_api_key_for_model(effective_model)
    if not api_key:
        await ws.send_json({"type": "error", "message": "No API Key configured"})
        return

    # V2: 记录审计事件
    if v2:
        try:
            from pycoder.safety.audit import AuditRecord
            v2.audit.log(AuditRecord(
                trace_id=str(uuid.uuid4()),
                capability_id="chat.send_message",
                params_summary=message[:200],
                permission_level=0,
                decision="auto_allow",
                user_confirmed=False,
                success=True,
                session_id=session_id,
                caller="user",
            ))
        except (ImportError, AttributeError, TypeError, ValueError):
            pass

    # ── 统一入口: 所有消息走 UnifiedEntryAgent 自动路由 ──
    from pycoder.server.services.unified_entry import UnifiedEntryAgent

    entry = UnifiedEntryAgent(model=effective_model, api_key=api_key)

    final_content = ""
    async for event in entry.process_stream(message, session_id=session_id):
        await ws.send_json(event)
        if event.get("type") == "done":
            final_content = event.get("content", "")
        await asyncio.sleep(0)

    # 消息持久化
    if final_content:
        try:
            store.add_message(session_id, "user", message)
            store.add_message(session_id, "assistant", final_content)
        except (OSError, ValueError, RuntimeError) as e:
            import logging
            logging.getLogger(__name__).warning(
                "save_message_failed",
                extra={"session_id": session_id, "error": str(e)},
            )


async def _handle_mcp_v2(msg_type: str, msg: dict, ws: WebSocket, v2):
    """V2 MCP 工具处理 — 通过能力总线调用"""

    if msg_type == "mcp_list":
        from pycoder.server.mcp_tools import get_mcp_client_manager, list_builtin_tools

        builtin = list_builtin_tools()
        mgr = get_mcp_client_manager()
        remote_tools = []
        for server_name in mgr.connected_servers:
            tools = await mgr.list_remote_tools(server_name)
            remote_tools.extend(tools)

        await ws.send_json({
            "type": "mcp_tools",
            "builtin": builtin,
            "remote": remote_tools,
            "connected_servers": mgr.connected_servers,
            "total": len(builtin) + len(remote_tools),
            # V2: 额外返回 V2 总线中的能力数
            "v2_capabilities": v2.registry.count if v2 else 0,
        })
        return

    if msg_type == "mcp_call":
        tool_name = msg.get("tool", "")
        tool_args = msg.get("args", {})
        if not tool_name:
            await ws.send_json({"type": "error", "message": "mcp_call requires 'tool' field"})
            return

        # V2: 优先通过能力总线调用
        if v2:
            # 尝试 v1.<tool_name> 格式
            v2_id = f"v1.{tool_name}" if not tool_name.startswith("v1.") else tool_name
            try:
                result = await v2.call(v2_id, tool_args)
                await ws.send_json({
                    "type": "mcp_result", "tool": tool_name,
                    "success": result.success,
                    "output": result.data,
                    "error": result.error,
                    "via": "v2_bus",
                })
                return
            except (AttributeError, TypeError, ValueError):
                pass  # 回退到 V1 路径

        # V1 回退路径
        from pycoder.server.mcp_tools import call_builtin_tool, get_mcp_client_manager

        if tool_name.startswith("mcp:"):
            parts = tool_name[4:].split("/", 1)
            if len(parts) == 2:
                server_name, remote_tool = parts
                mgr = get_mcp_client_manager()
                result = await mgr.call_remote_tool(server_name, remote_tool, tool_args)
                await ws.send_json({
                    "type": "mcp_result", "tool": tool_name,
                    "success": result.success, "output": result.output, "error": result.error,
                })
            else:
                await ws.send_json({"type": "error", "message": f"无效的外部工具引用: {tool_name}"})
        else:
            result = await call_builtin_tool(tool_name, tool_args)
            await ws.send_json({
                "type": "mcp_result", "tool": tool_name,
                "success": result.success, "output": result.output, "error": result.error,
            })
        return

    # mcp_connect / mcp_disconnect
    if msg_type == "mcp_connect":
        server_name = msg.get("name", "")
        command = msg.get("command", "")
        cmd_args = msg.get("args", [])
        if not server_name or not command:
            await ws.send_json({"type": "error", "message": "mcp_connect requires 'name' and 'command'"})
            return
        from pycoder.server.mcp_tools import get_mcp_client_manager
        mgr = get_mcp_client_manager()
        ok = await mgr.connect_stdio(server_name, command, *cmd_args)
        await ws.send_json({"type": "mcp_connect_result", "name": server_name, "success": ok})
        return

    if msg_type == "mcp_disconnect":
        server_name = msg.get("name", "")
        if not server_name:
            await ws.send_json({"type": "error", "message": "mcp_disconnect requires 'name'"})
            return
        from pycoder.server.mcp_tools import get_mcp_client_manager
        mgr = get_mcp_client_manager()
        await mgr.disconnect(server_name)
        await ws.send_json({"type": "mcp_disconnect_result", "name": server_name, "success": True})


async def _handle_legacy_file_ops(msg_type, msg, ws, v2,
                                   _get_project_tree, _get_diff_preview, _get_git_status):
    """V2 文件操作 — 委托给能力总线或回退 V1"""
    try:
        if msg_type == "project_tree":
            tree = await _get_project_tree(msg.get("path"), msg.get("max_depth", 3))
            await ws.send_json({"type": "project_tree", **tree})
        elif msg_type == "file_open":
            from pycoder.server.routers.files import _safe_path

            file_path = msg.get("path", "")
            if not file_path:
                await ws.send_json({"type": "error", "message": "file_open requires 'path'"})
                return
            target = _safe_path(file_path)
            if not target.exists():
                await ws.send_json({"type": "error", "message": f"Not found: {file_path}"})
                return
            content = target.read_text(encoding="utf-8")
            stat = target.stat()
            await ws.send_json({
                "type": "file_open", "path": str(target), "name": target.name,
                "content": content, "size": stat.st_size, "modified_at": stat.st_mtime,
            })
        elif msg_type == "diff_preview":
            diff_data = await _get_diff_preview(msg.get("file"), msg.get("staged", False))
            await ws.send_json({"type": "diff_preview", **diff_data})
        elif msg_type == "git_status":
            status = await _get_git_status(msg.get("path"))
            await ws.send_json({"type": "git_status", **status})
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})


async def _handle_inline_edit(msg: dict, ws: WebSocket):
    """内联编辑处理器"""
    code_snippet = msg.get("code", "")
    instruction = msg.get("instruction", "")
    language = msg.get("language", "python")
    request_id = msg.get("request_id", "")

    if not code_snippet or not instruction:
        await ws.send_json({
            "type": "error",
            "message": "inline_edit requires 'code' and 'instruction'",
        })
        return

    prompt = (
        f"你是一个代码内联编辑助手。根据用户的指令修改下面的代码片段。\n"
        f"只返回修改后的代码，不要添加任何解释、注释标记或 markdown 代码块。\n\n"
        f"## 当前代码\n```{language}\n{code_snippet}\n```\n\n"
        f"## 编辑指令\n{instruction}"
    )

    from pycoder.server.chat_bridge import ChatBridge
    from pycoder.server.chat_handler import _get_api_key_for_model

    api_key = _get_api_key_for_model("deepseek-chat")
    if not api_key:
        await ws.send_json({"type": "error", "message": "No API Key configured"})
        return

    bridge = ChatBridge()
    bridge.configure(model="deepseek-chat", api_key=api_key)
    bridge.config.system_prompt = "你是一个代码编辑助手。直接返回修改后的代码。"
    bridge.config.max_tokens = 4096

    result = ""
    async for event in bridge.chat_stream(prompt):
        if event.event_type == "token":
            result += event.content
        elif event.event_type == "done":
            result = event.content or result

    await ws.send_json({
        "type": "inline_edit_result",
        "code": result.strip(),
        "request_id": request_id,
    })
