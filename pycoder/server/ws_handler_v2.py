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
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from pycoder import __version__

_logger = logging.getLogger("pycoder.server.ws_handler_v2")
from pycoder.core.services.log import log
from pycoder.observability.tracing import traced
from pycoder.server.chat_handler import (
    _get_api_key_for_model,
    _get_effective_model,
)
from pycoder.server.hermes_engine import _execute_hermes_write
from pycoder.server.session_share import get_session_share_manager
from pycoder.server.session_store import get_session_store

# ── 取消事件表：session_id → asyncio.Event ──
# 前端发送 {type: "stop"} 时，设置对应事件通知正在运行的流停止
_cancel_events: dict[str, asyncio.Event] = {}


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

            # ── 停止当前 AI 执行 ──
            if msg_type == "stop":
                # 1. 精确取消：设置对应 session 的 cancel_event
                cancel_event = _cancel_events.get(session_id)
                if cancel_event:
                    cancel_event.set()
                # 2. 精确取消：取消对应 session 的后台任务
                stream_task = _cancel_events.get(session_id + ":task")
                if stream_task and not stream_task.done():
                    stream_task.cancel()
                # 兼容旧键名
                old_task = _cancel_events.get(session_id + "_task")
                if old_task and not old_task.done():
                    old_task.cancel()
                _cancel_events.pop(session_id + "_task", None)
                # 3. 全局兜底：取消所有活跃的后台任务（防止 key 匹配失败）
                global_cancelled = 0
                for key in list(_cancel_events.keys()):
                    if key.endswith(":task") or key.endswith("_task"):
                        t = _cancel_events.get(key)
                        if t and hasattr(t, "done") and not t.done():
                            t.cancel()
                            _cancel_events.pop(key, None)
                            global_cancelled += 1
                # 也设置所有 cancel_event
                for key in list(_cancel_events.keys()):
                    if not (key.endswith(":task") or key.endswith("_task")):
                        ev = _cancel_events.get(key)
                        if ev and hasattr(ev, "set"):
                            ev.set()
                done_flag = (
                    stream_task.done() if stream_task else f"global_cancelled={global_cancelled}"
                )
                log.info("ws_v2_stop_requested done=%s", done_flag)
                await ws.send_json({"type": "stopped", "session_id": session_id})
                continue

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
                        await ws.send_json(
                            {
                                "type": "session_share_status",
                                "share_session_id": ssid,
                                "shared_count": count,
                            }
                        )
                else:
                    share_mgr.leave(client_id)
                    await ws.send_json(
                        {
                            "type": "session_share_status",
                            "share_session_id": "",
                            "shared_count": 0,
                        }
                    )
                continue

            if msg_type == "switch_session":
                new_id = msg.get("session_id", "")
                if new_id and store.get_session(new_id):
                    session_id = new_id
                    await ws.send_json({"type": "session_switched", "session_id": session_id})
                continue

            if msg_type == "list_sessions":
                sessions = store.list_sessions(limit=20)
                await ws.send_json(
                    {
                        "type": "session_list",
                        "sessions": [s.to_dict() for s in sessions],
                    }
                )
                continue

            if msg_type == "history":
                sid = msg.get("session_id", session_id)
                messages = store.get_messages(sid)
                await ws.send_json(
                    {
                        "type": "history",
                        "session_id": sid,
                        "messages": [m.to_dict() for m in messages],
                    }
                )
                continue

            # ── V2 专用消息: 列出能力 ──
            if msg_type == "v2_capabilities":
                if v2:
                    caps = v2.registry.list_all()
                    await ws.send_json(
                        {
                            "type": "v2_capabilities",
                            "capabilities": [c.to_dict() for c in caps],
                            "total": len(caps),
                        }
                    )
                else:
                    await ws.send_json(
                        {
                            "type": "v2_capabilities",
                            "capabilities": [],
                            "total": 0,
                        }
                    )
                continue

            # ── V2 专用消息: 直接调用能力 ──
            if msg_type == "v2_call":
                cap_id = msg.get("capability_id", "")
                cap_params = msg.get("params", {})
                if not cap_id:
                    await ws.send_json(
                        {"type": "error", "message": "v2_call requires 'capability_id'"}
                    )
                    continue
                if v2:
                    try:
                        result = await v2.call(cap_id, cap_params)
                        # 如果能力未找到，自动尝试 v1. 前缀
                        if not getattr(result, "success", True) and not cap_id.startswith("v1."):
                            try:
                                alt = await v2.call(f"v1.{cap_id}", cap_params)
                                if getattr(alt, "success", False):
                                    result = alt
                            except Exception:
                                _logger.warning("silently_swallowed: {err}", exc_info=False)
                                pass
                        await ws.send_json(
                            {
                                "type": "v2_call_result",
                                "capability_id": cap_id,
                                "success": getattr(result, "success", False),
                                "data": getattr(result, "data", None),
                                "error": getattr(result, "error", ""),
                            }
                        )
                    except Exception as e:
                        await ws.send_json(
                            {
                                "type": "v2_call_result",
                                "capability_id": cap_id,
                                "success": False,
                                "error": str(e),
                            }
                        )
                else:
                    await ws.send_json(
                        {
                            "type": "v2_call_result",
                            "capability_id": cap_id,
                            "success": False,
                            "error": "V2 engine not available",
                        }
                    )
                continue

            # ── chat 消息（委托给 V1 chat_handler）──
            if msg_type == "chat":
                user_message = msg.get("message", "")
                if not user_message:
                    await ws.send_json(
                        {"type": "error", "message": "chat requires 'message' field"}
                    )
                    continue
                requested_model = msg.get("model", "") or current_model
                try:
                    from pycoder.server.chat_handler import _run_chat_stream as chat_stream_fn

                    async for event in chat_stream_fn(
                        session_id,
                        user_message,
                        requested_model,
                        msg.get("system_prompt"),
                        hermes=msg.get("hermes", False),
                        reasoning_effort=msg.get("reasoning_effort", "medium"),
                        enable_cache=msg.get("enable_cache", True),
                    ):
                        await ws.send_json(event)
                        await asyncio.sleep(0)
                except Exception as e:
                    log.error("ws_v2_chat_failed", error=str(e))
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": f"chat: {str(e)[:200]}",
                        }
                    )
                continue

            # ── execute_plan / agent 模式（委托给 V1 handler）──
            if msg_type in ("execute_plan", "agent_chunk"):
                if msg_type == "execute_plan":
                    plan_content = msg.get("plan", "")
                    model = msg.get("model", current_model)
                    if not plan_content:
                        await ws.send_json(
                            {"type": "error", "message": "execute_plan requires 'plan' field"}
                        )
                        continue
                    from pycoder.server.services.agent_orchestrator import (
                        agent_chat_stream as agent_stream,
                    )

                    cancel_event = asyncio.Event()
                    _cancel_events[session_id] = cancel_event
                    async for event in agent_stream(
                        plan_content, model=model, cancel_event=cancel_event
                    ):
                        if cancel_event.is_set():
                            await ws.send_json({"type": "done", "content": "", "stopped": True})
                            break
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
                    await ws.send_json(
                        {"type": "error", "message": "write_file requires 'path' field"}
                    )
                    continue
                # V2: 通过能力总线执行写文件
                if v2:
                    result = await v2.call(
                        "editor.file.write", {"path": file_path, "content": file_content}
                    )
                    if result.success:
                        await ws.send_json(
                            {"type": "file_write_result", "success": True, "path": file_path}
                        )
                    else:
                        await ws.send_json(
                            {"type": "error", "message": result.error or "Write failed"}
                        )
                else:
                    result = await _execute_hermes_write(file_path, file_content)
                    await ws.send_json({"type": "file_write_result", **result})
                continue

            if msg_type in ("project_tree", "file_open", "diff_preview", "git_status"):
                await _handle_legacy_file_ops(
                    msg_type, msg, ws, v2, _get_project_tree, _get_diff_preview, _get_git_status
                )
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
    finally:
        # 清理取消事件
        _cancel_events.pop(session_id, None)


@traced("ws_v2.handle_chat")
async def _handle_chat_v2(msg: dict, ws: WebSocket, session_id: str, current_model: str, store, v2):
    """V2 统一入口聊天处理器 — 通过 UnifiedEntryAgent 自动路由三种模式

    改动: 不再需要前端传 hermes 参数，UnifiedEntryAgent 自动根据意图分类路由。

    P1-C: 集成并发控制
    - 背压: 限制单连接并发请求数（默认 10）
    - LLM 限流: 限制全局并发 LLM 调用数（默认 8）
    """
    # P1-C: 背压检查
    from pycoder.server.ws_concurrency import (
        get_backpressure_manager,
        get_llm_limiter,
    )

    bp = get_backpressure_manager()
    bp_conn_id = f"{session_id}:{id(ws)}"
    if not bp.try_acquire(bp_conn_id):
        log.warning(
            "ws_v2_backpressure_rejected",
            extra={"session_id": session_id, "connection_id": bp_conn_id},
        )
        await ws.send_json(
            {
                "type": "error",
                "message": "Too many in-flight requests, please wait",
            }
        )
        return

    try:
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

        # ── /setup 命令: 直接在聊天中配置 API Key ──────────
        if message.startswith("/setup"):
            await _handle_setup_command(message, ws, effective_model)
            return

        # V2: 记录审计事件
        if v2:
            try:
                from pycoder.safety.audit import AuditRecord

                v2.audit.log(
                    AuditRecord(
                        trace_id=str(uuid.uuid4()),
                        capability_id="chat.send_message",
                        params_summary=message[:200],
                        permission_level=0,
                        decision="auto_allow",
                        user_confirmed=False,
                        success=True,
                        session_id=session_id,
                        caller="user",
                    )
                )
            except (ImportError, AttributeError, TypeError, ValueError):
                pass

        # ── 统一入口: 所有消息走 UnifiedEntryAgent 自动路由 ──
        from pycoder.server.services.unified_entry import UnifiedEntryAgent

        entry = UnifiedEntryAgent(model=effective_model, api_key=api_key)

        # ── 取消事件：前端 stop 信号 ──
        cancel_event = asyncio.Event()
        _cancel_events[session_id] = cancel_event

        # P1-C: LLM 并发限流
        limiter = get_llm_limiter()
        final_content = ""

        async def _run_stream():
            """后台运行流，支持被 cancel_event 中断"""
            nonlocal final_content
            async with limiter.acquire():
                async for event in entry.process_stream(
                    message, session_id=session_id, cancel_event=cancel_event
                ):
                    if cancel_event.is_set():
                        await ws.send_json(
                            {"type": "done", "content": final_content, "stopped": True}
                        )
                        log.info("ws_v2_stream_cancelled", extra={"session_id": session_id})
                        return
                    await ws.send_json(event)
                    if event.get("type") == "done":
                        final_content = event.get("content", "")
                    await asyncio.sleep(0)

        stream_task = asyncio.create_task(_run_stream())
        _cancel_events[session_id + ":task"] = stream_task

        # ── 后台流完成后的清理 ──
        async def _on_stream_done():
            try:
                await stream_task
            except asyncio.CancelledError:
                await ws.send_json({"type": "done", "content": final_content, "stopped": True})
            finally:
                _cancel_events.pop(session_id, None)
                _cancel_events.pop(session_id + ":task", None)
                bp.release(bp_conn_id)
                if final_content:
                    try:
                        store.add_message(session_id, "user", message)
                        store.add_message(session_id, "assistant", final_content)
                    except (RuntimeError, ConnectionError, OSError, AttributeError, KeyError):
                        pass

        # 不阻塞主循环 — 后台流 + 清理任务
        asyncio.create_task(_on_stream_done())
        return

    except Exception:
        bp.release(bp_conn_id)
        raise


async def _handle_setup_command(message: str, ws: WebSocket, effective_model: str) -> None:
    """处理 /setup 命令 — 从 _handle_chat_v2 拆出，便于维护

    P2-B chat_bridge 拆分后此函数可移到独立模块。
    """
    parts = message.split(maxsplit=2)
    if len(parts) == 1:
        # 显示引导
        from pycoder.providers.auth import get_model_manager

        mgr = get_model_manager()
        guide = mgr.format_setup_guide()
        await ws.send_json(
            {
                "type": "content",
                "content": f"```\n{guide}\n```\n\n**快捷配置:** 发送 `/setup deepseek YOUR_API_KEY`",
            }
        )
        await ws.send_json({"type": "done", "content": ""})
        return
    provider = parts[1].lower()
    if provider == "guide":
        from pycoder.providers.auth import get_model_manager

        mgr = get_model_manager()
        guide = mgr.format_setup_guide()
        await ws.send_json({"type": "content", "content": f"```\n{guide}\n```"})
        await ws.send_json({"type": "done", "content": ""})
        return
    if len(parts) < 3:
        await ws.send_json(
            {
                "type": "content",
                "content": (
                    f"用法: `/setup {provider} YOUR_API_KEY`\n"
                    f"示例: `/setup deepseek sk-abc123`\n\n"
                    "查看所有提供商: `/setup guide`"
                ),
            }
        )
        await ws.send_json({"type": "done", "content": ""})
        return
    api_key_value = parts[2]
    from pycoder.providers.setup_wizard import set_api_key

    result = set_api_key(provider, api_key_value)
    if result.get("success"):
        await ws.send_json(
            {
                "type": "content",
                "content": f"✅ **{provider} API Key 已配置成功!**\n现在可以正常使用 AI 功能了 🚀",
            }
        )
    else:
        await ws.send_json(
            {
                "type": "content",
                "content": (
                    f"❌ 配置失败: {result.get('error', '未知错误')}\n"
                    "支持提供商: deepseek, qwen, glm, openai, openrouter, nvidia"
                ),
            }
        )
    await ws.send_json({"type": "done", "content": ""})


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

        await ws.send_json(
            {
                "type": "mcp_tools",
                "builtin": builtin,
                "remote": remote_tools,
                "connected_servers": mgr.connected_servers,
                "total": len(builtin) + len(remote_tools),
                # V2: 额外返回 V2 总线中的能力数
                "v2_capabilities": v2.registry.count if v2 else 0,
            }
        )
        return

    if msg_type == "mcp_call":
        tool_name = msg.get("tool", "")
        tool_args = msg.get("args", {})
        if not tool_name:
            await ws.send_json({"type": "error", "message": "mcp_call requires 'tool' field"})
            return

        # P1-3 修复: 先做工具名重定向 (head/body(path=...) → tools.file.read)
        # 必须在 V2 调用之前执行，因为 V2 不会回退到 V1 路径
        try:
            from pycoder.server.mcp_tools import _maybe_redirect_common_aliases

            tool_name, tool_args = _maybe_redirect_common_aliases(tool_name, tool_args)
        except (ImportError, AttributeError) as e:
            import logging as _lg

            _lg.getLogger(__name__).debug("alias_redirect_unavailable: %s", e)

        # V2: 优先通过能力总线调用
        v2_succeeded = False
        if v2:
            # 尝试 v1.<tool_name> 格式
            v2_id = f"v1.{tool_name}" if not tool_name.startswith("v1.") else tool_name
            try:
                result = await v2.call(v2_id, tool_args)
                if result and getattr(result, "success", False):
                    await ws.send_json(
                        {
                            "type": "mcp_result",
                            "tool": tool_name,
                            "success": True,
                            "output": result.data,
                            "error": result.error,
                            "via": "v2_bus",
                        }
                    )
                    v2_succeeded = True
                else:
                    # V2 找到能力但执行失败（或路由未找到），
                    # 不直接返回错误 — 回退到 V1 路径（含重定向）再尝试
                    import logging as _lg

                    _lg.getLogger(__name__).info(
                        "v2_call_failed tool=%s error=%s, falling back to v1",
                        tool_name,
                        getattr(result, "error", "unknown"),
                    )
            except (AttributeError, TypeError, ValueError):
                pass  # 回退到 V1 路径
            except Exception as e:
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "v2_call_exception tool=%s error=%s, falling back to v1",
                    tool_name,
                    e,
                )

        if v2_succeeded:
            return

        # V1 回退路径
        from pycoder.server.mcp_tools import call_builtin_tool, get_mcp_client_manager

        if tool_name.startswith("mcp:"):
            parts = tool_name[4:].split("/", 1)
            if len(parts) == 2:
                server_name, remote_tool = parts
                mgr = get_mcp_client_manager()
                result = await mgr.call_remote_tool(server_name, remote_tool, tool_args)
                await ws.send_json(
                    {
                        "type": "mcp_result",
                        "tool": tool_name,
                        "success": result.success,
                        "output": result.output,
                        "error": result.error,
                    }
                )
            else:
                await ws.send_json({"type": "error", "message": f"无效的外部工具引用: {tool_name}"})
        else:
            result = await call_builtin_tool(tool_name, tool_args)
            await ws.send_json(
                {
                    "type": "mcp_result",
                    "tool": tool_name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                }
            )
        return

    # mcp_connect / mcp_disconnect
    if msg_type == "mcp_connect":
        server_name = msg.get("name", "")
        command = msg.get("command", "")
        cmd_args = msg.get("args", [])
        if not server_name or not command:
            await ws.send_json(
                {"type": "error", "message": "mcp_connect requires 'name' and 'command'"}
            )
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


async def _handle_legacy_file_ops(
    msg_type, msg, ws, v2, _get_project_tree, _get_diff_preview, _get_git_status
):
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
            await ws.send_json(
                {
                    "type": "file_open",
                    "path": str(target),
                    "name": target.name,
                    "content": content,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
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
        await ws.send_json(
            {
                "type": "error",
                "message": "inline_edit requires 'code' and 'instruction'",
            }
        )
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

    await ws.send_json(
        {
            "type": "inline_edit_result",
            "code": result.strip(),
            "request_id": request_id,
        }
    )
