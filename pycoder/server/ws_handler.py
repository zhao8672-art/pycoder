"""WebSocket chat handler: streaming AI chat via WebSocket."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from pycoder import __version__
from pycoder.core.services.log import log
from pycoder.server.chat_handler import (
    _get_effective_model,
)
from pycoder.server.chat_handler import _run_chat_stream as chat_stream_fn
from pycoder.server.hermes_engine import _execute_hermes_write
from pycoder.server.session_share import get_session_share_manager
from pycoder.server.session_store import get_session_store


async def _run_cancellable_stream(
    gen_or_coro,
    ws: WebSocket,
    runtime: dict,
    task_key: str,
):
    """运行 async generator 或 coroutine，支持通过前端 stop 消息取消。

    FIX(任务终止): 前端 AIPanel.tsx 已实现停止按钮发送 {type:"stop"}，
    但原代码 `async for event in chat_stream_fn(...)` 阻塞在 generator 内部，
    主循环无法接收 stop 消息导致按钮无效。

    本函数:
      1. 用 asyncio.create_task 包装 stream 消费循环
      2. 并发启动 _stop_watcher 监听 stop 消息
      3. 收到 stop 时 task.cancel()，CancelledError 在 async generator 中传播
      4. agent_loop 已在迭代开头加入取消检查点，能及时退出

    Args:
        gen_or_coro: AsyncIterator（chat_stream_fn 返回）或 Awaitable（loop.execute 返回）
        ws: WebSocket 连接
        runtime: 维护任务句柄的 dict
        task_key: runtime 的 key（"chat_task" / "fix_task"）

    Returns:
        对于 coroutine：返回其结果；对于 generator：返回 None
    """
    is_gen = hasattr(gen_or_coro, "__aiter__")
    result_holder: list = []

    async def _consume():
        if is_gen:
            async for event in gen_or_coro:
                await ws.send_json(event)
                await asyncio.sleep(0)  # 让出控制权，让 cancel 能及时传播
        else:
            # coroutine 模式：直接 await
            r = await gen_or_coro
            result_holder.append(r)
            return r

    runtime[task_key] = asyncio.create_task(_consume())

    # 后台监听 stop 消息（仅在主任务运行期间占用 ws.receive_text）
    async def _stop_watcher():
        while not runtime[task_key].done():
            try:
                data = await ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                return None
            except Exception:
                return None
            try:
                msg = json.loads(data)
            except (ValueError, TypeError):
                continue
            if msg.get("type") == "stop":
                # 关键：主动取消主任务，让 CancelledError 在 async generator 中传播
                t = runtime.get(task_key)
                if t is not None and not t.done():
                    t.cancel()
                return data
            # 其他消息：在 AI 响应期间忽略（用户应等回复完再发新消息）
        return None

    watcher = asyncio.create_task(_stop_watcher())

    try:
        await runtime[task_key]
    except asyncio.CancelledError:
        # 被 stop_watcher 通过 task.cancel() 触发
        try:
            await ws.send_json({"type": "stopped", "message": "任务已停止"})
        except Exception:
            pass
    else:
        # 主任务正常完成，返回结果
        if result_holder:
            return result_holder[0]
    finally:
        # 清理 watcher
        if not watcher.done():
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass
        runtime[task_key] = None

    return None


async def websocket_chat(ws: WebSocket):
    """Main WebSocket handler for real-time AI chat."""
    from pycoder.server.project_helpers import _get_diff_preview, _get_git_status, _get_project_tree

    await ws.accept()
    share_mgr = get_session_share_manager()
    store = get_session_store()

    # FIX(任务终止): 维护本连接当前正在执行的 chat/agent 任务句柄，
    # 收到 type:"stop" 消息时调用 task.cancel() 即可让 async generator
    # 抛出 CancelledError 并自然退出（agent_loop 已加取消检查点）。
    # 同时支持 run_fix / execute_plan / dep_agent 等长任务。
    runtime: dict[str, asyncio.Task | None] = {
        "chat_task": None,  # 主对话流（chat_stream_fn / agent_stream）
        "fix_task": None,  # run_fix 循环
    }

    async def _cancel_running_tasks() -> None:
        """取消本连接所有正在运行的任务，已完成的任务忽略"""
        for key in list(runtime.keys()):
            t = runtime.get(key)
            if t is not None and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            runtime[key] = None

    # FIX #1: 优先恢复上次会话，空会话复用不新建
    last_session = store.get_last_session()
    if last_session:
        # 有消息的会话直接恢复
        if last_session.message_count > 0:
            session_id = last_session.id
            current_model = last_session.model or "deepseek-chat"
        else:
            # 空会话复用而不是新建
            session_id = last_session.id
            current_model = "deepseek-chat"
    else:
        session_id = str(uuid.uuid4())
        store.create_session(session_id=session_id)
        current_model = "deepseek-chat"

    client_id = str(uuid.uuid4())[:8]
    shared_session_id = ""
    has_hist = bool(last_session and last_session.message_count > 0)
    await ws.send_json(
        {
            "type": "connected",
            "session_id": session_id,
            "version": __version__,
            "has_history": has_hist,
        }
    )
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            # ═══════════════════════════════════════════════
            # FIX(任务终止): 处理前端的"停止"按钮 — 取消正在运行的 chat/agent/run_fix 任务
            # 前端 AIPanel.tsx 已实现按钮发送 {type:"stop"}，
            # 之前后端没有处理导致按钮无效。
            # ═══════════════════════════════════════════════
            if msg_type == "stop":
                await _cancel_running_tasks()
                await ws.send_json({
                    "type": "stopped",
                    "message": "任务已停止",
                })
                continue

            if msg_type == "create_session":
                new_id = str(uuid.uuid4())
                store.create_session(session_id=new_id)
                session_id = new_id
                await ws.send_json({"type": "session_created", "session_id": new_id})
                continue

            # ── 会话共享 ──
            if msg_type == "session_share_join":
                shared_session_id = msg.get("share_session_id", "")
                if shared_session_id:
                    share_mgr.join(client_id, shared_session_id, ws.send_text)
                    count = share_mgr.get_shared_sessions(shared_session_id)
                    await ws.send_json(
                        {
                            "type": "session_share_status",
                            "share_session_id": shared_session_id,
                            "shared_count": count,
                        }
                    )
                continue

            if msg_type == "session_share_leave":
                share_mgr.leave(client_id)
                shared_session_id = ""
                await ws.send_json(
                    {"type": "session_share_status", "share_session_id": "", "shared_count": 0}
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
                    {"type": "session_list", "sessions": [s.to_dict() for s in sessions]}
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

                # FIX(任务终止): 用 _run_cancellable_stream 包装，支持 stop 消息取消
                await _run_cancellable_stream(
                    agent_stream(plan_content, model=model),
                    ws,
                    runtime,
                    "chat_task",
                )
                continue
            elif msg_type in ("agent_chunk",):
                # Agent 流式块处理
                chunk_data = msg.get("content", "")
                await ws.send_json({"type": "agent_chunk", "content": chunk_data})
                continue

            if msg_type == "write_file":
                file_path = msg.get("path", "")
                file_content = msg.get("content", "")
                if not file_path:
                    await ws.send_json(
                        {"type": "error", "message": "write_file requires 'path' field"}
                    )
                    continue
                result = await _execute_hermes_write(file_path, file_content)
                await ws.send_json({"type": "file_write_result", **result})
                continue

            if msg_type == "project_tree":
                tree_path = msg.get("path", None)
                max_depth = msg.get("max_depth", 3)
                try:
                    tree = await _get_project_tree(tree_path, max_depth)
                    await ws.send_json({"type": "project_tree", **tree})
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"Failed: {str(e)}"})
                continue

            if msg_type == "file_open":
                file_path = msg.get("path", "")
                if not file_path:
                    await ws.send_json({"type": "error", "message": "file_open requires 'path'"})
                    continue
                try:
                    # 使用安全路径校验，防止路径穿越
                    from pycoder.server.routers.files import HTTPException as FileHTTPException
                    from pycoder.server.routers.files import _safe_path

                    target = _safe_path(file_path)
                    if not target.exists():
                        await ws.send_json({"type": "error", "message": f"Not found: {file_path}"})
                        continue
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
                except FileHTTPException as e:
                    await ws.send_json({"type": "error", "message": str(e.detail)})
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"Error reading: {str(e)}"})
                continue

            if msg_type == "diff_preview":
                diff_file = msg.get("file", None)
                staged = msg.get("staged", False)
                try:
                    diff_data = await _get_diff_preview(diff_file, staged)
                    await ws.send_json({"type": "diff_preview", **diff_data})
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"Diff failed: {str(e)}"})
                continue

            if msg_type == "git_status":
                git_path = msg.get("path", None)
                try:
                    status = await _get_git_status(git_path)
                    await ws.send_json({"type": "git_status", **status})
                except Exception as e:
                    await ws.send_json({"type": "error", "message": f"Git status failed: {str(e)}"})
                continue

            # ═══════════════════════════════════════════════
            # MCP (Model Context Protocol) 消息类型
            # ═══════════════════════════════════════════════

            if msg_type == "mcp_list":
                """列出所有可用 MCP Tool（内置 + 外部）"""
                from pycoder.server.mcp_tools import get_mcp_client_manager, list_builtin_tools

                builtin = list_builtin_tools()
                # 收集外部 Server 的工具
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
                    }
                )
                continue

            if msg_type == "mcp_call":
                """调用一个 MCP Tool"""
                tool_name = msg.get("tool", "")
                tool_args = msg.get("args", {})
                if not tool_name:
                    err_msg = "mcp_call requires 'tool' field"
                    await ws.send_json({"type": "error", "message": err_msg})
                    continue
                from pycoder.server.mcp_tools import call_builtin_tool, get_mcp_client_manager

                # 先查内置 Tool
                if tool_name.startswith("mcp:"):
                    # 外部 Server 工具: mcp:server_name/tool_name
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
                        await ws.send_json(
                            {"type": "error", "message": f"无效的外部工具引用: {tool_name}"}
                        )
                else:
                    # 内置 Tool
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
                continue

            if msg_type == "mcp_connect":
                """连接外部 MCP Server"""
                server_name = msg.get("name", "")
                command = msg.get("command", "")
                cmd_args = msg.get("args", [])
                if not server_name or not command:
                    err_msg = "mcp_connect requires 'name' and 'command'"
                    await ws.send_json({"type": "error", "message": err_msg})
                    continue
                from pycoder.server.mcp_tools import get_mcp_client_manager

                mgr = get_mcp_client_manager()
                ok = await mgr.connect_stdio(server_name, command, *cmd_args)
                await ws.send_json(
                    {
                        "type": "mcp_connect_result",
                        "name": server_name,
                        "success": ok,
                    }
                )
                continue

            if msg_type == "mcp_disconnect":
                """断开外部 MCP Server"""
                server_name = msg.get("name", "")
                if not server_name:
                    err_msg = "mcp_disconnect requires 'name'"
                    await ws.send_json({"type": "error", "message": err_msg})
                    continue
                from pycoder.server.mcp_tools import get_mcp_client_manager

                mgr = get_mcp_client_manager()
                await mgr.disconnect(server_name)
                await ws.send_json(
                    {
                        "type": "mcp_disconnect_result",
                        "name": server_name,
                        "success": True,
                    }
                )
                continue

            # ═══════════════════════════════════════════════
            # 内联编辑 (Cmd+K)
            # ═══════════════════════════════════════════════

            if msg_type == "inline_edit":
                """内联编辑: 选中代码 → AI 修改 → 直接替换选区"""
                code_snippet = msg.get("code", "")
                instruction = msg.get("instruction", "")
                file_path = msg.get("file_path", "")
                language = msg.get("language", "python")
                request_id = msg.get("request_id", "")

                if not code_snippet or not instruction:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "inline_edit requires 'code' and 'instruction'",
                        }
                    )
                    continue

                # 构造内联编辑 prompt
                prompt = f"""你是一个代码内联编辑助手。根据用户的指令修改下面的代码片段。
只返回修改后的代码，不要添加任何解释、注释标记或 markdown 代码块。

## 当前代码
```{language}
{code_snippet}
```

## 修改指令
{instruction}

## 修改后的代码
```{language}
"""
                full_content = ""
                async for event in chat_stream_fn(
                    session_id,
                    prompt,
                    current_model,
                    system_prompt="你是一个精确的代码修改助手。只返回被修改的代码，不添加任何解释或额外内容。",
                    hermes=False,
                ):
                    await ws.send_json(
                        {
                            "type": "inline_edit_stream",
                            "request_id": request_id,
                            **event,
                        }
                    )
                    if event.get("type") == "done":
                        full_content = event.get("content", "")
                    await asyncio.sleep(0)

                # 剥离可能残留的 markdown 代码块标记
                cleaned = _strip_code_fence(full_content, language)
                await ws.send_json(
                    {
                        "type": "inline_edit_done",
                        "request_id": request_id,
                        "code": cleaned,
                    }
                )
                continue

            # ═══════════════════════════════════════════════
            # Run & Fix 自动循环
            # ═══════════════════════════════════════════════

            if msg_type == "run_fix":
                """Run & Fix: AI 写代码→运行→修复→重新运行"""
                task = msg.get("task", "")
                target = msg.get("target_file", "solution.py")

                if not task:
                    await ws.send_json({"type": "error", "message": "run_fix requires 'task'"})
                    continue

                from pycoder.server.services.run_fix_loop import RunFixLoop

                loop = RunFixLoop(
                    chat_stream_fn=chat_stream_fn,
                    ws_send_fn=ws.send_text,
                    model=current_model,
                )

                # FIX(任务终止): 用 _run_cancellable_stream 包装，支持 stop 消息取消
                result = await _run_cancellable_stream(
                    loop.execute(task, target),
                    ws,
                    runtime,
                    "fix_task",
                )
                if result is None:
                    # 任务被取消
                    continue
                await ws.send_json(
                    {
                        "type": "run_fix_done",
                        "success": result.success,
                        "total_retries": result.total_retries,
                        "final_code": result.final_code,
                        "exec_output": result.exec_output,
                        "duration_ms": result.duration_ms,
                        "steps": [
                            {
                                "step": s.step,
                                "action": s.action,
                                "status": s.status,
                                "error": s.error,
                                "fix_description": s.fix_description,
                            }
                            for s in result.steps
                        ],
                    }
                )
                continue

            # ═══════════════════════════════════════════════
            # 依赖智能体
            # ═══════════════════════════════════════════════

            if msg_type == "dep_agent":
                """依赖智能体: 分析代码 import → 自动安装缺失依赖"""
                code = msg.get("code", "")
                if not code:
                    await ws.send_json({"type": "error", "message": "dep_agent requires 'code'"})
                    continue

                from pycoder.python.project_tools import auto_dep_agent

                result = await auto_dep_agent(code, ws_send=ws.send_text)
                await ws.send_json(
                    {
                        "type": "dep_agent_done",
                        **result,
                    }
                )
                continue

            # ═══════════════════════════════════════════════
            # 代码质量守卫
            # ═══════════════════════════════════════════════

            if msg_type == "quality_check":
                """代码质量守卫: 对文件运行质量检查"""
                file_path = msg.get("file_path", "")
                if not file_path:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "quality_check requires 'file_path'",
                        }
                    )
                    continue

                from pycoder.server.services.quality_guard import QualityGuard

                guard = QualityGuard()
                report = await guard.check(file_path)
                await ws.send_json(
                    {
                        "type": "quality_report",
                        "success": report.success,
                        "score": report.score,
                        "lint_score": report.lint_score,
                        "security_score": report.security_score,
                        "complexity_score": report.complexity_score,
                        "format_ok": report.format_ok,
                        "summary": report.summary,
                        "issues": [
                            {
                                "line": i.line,
                                "column": i.column,
                                "severity": i.severity,
                                "message": i.message,
                                "category": i.category,
                            }
                            for i in report.issues[:30]
                        ],
                    }
                )
                continue

            # ═══════════════════════════════════════════════
            # 智能测试生成
            # ═══════════════════════════════════════════════

            if msg_type == "test_generator":
                """智能测试生成: 分析源文件 → 生成 pytest 测试 → 运行报告"""
                file_path = msg.get("file_path", "")
                if not file_path:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "test_generator requires 'file_path'",
                        }
                    )
                    continue

                from pycoder.server.services.test_generator import TestGenerator

                generator = TestGenerator()
                result = generator.generate(file_path)
                await ws.send_json(
                    {
                        "type": "test_generator_done",
                        "success": result.success,
                        "test_file": result.test_file,
                        "test_count": result.test_count,
                        "passed": result.passed,
                        "failed": result.failed,
                        "coverage_percent": result.coverage_percent,
                        "output": result.output[:2000],
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                    }
                )
                continue

            # ═══════════════════════════════════════════════
            # 团队协作工作区
            # ═══════════════════════════════════════════════

            if msg_type == "team_ws":
                """团队协作: 工作区管理 + 代码审查 + 活动 Feed"""
                subcmd = msg.get("subcommand", "")
                from pycoder.server.services.team_workspace import get_team_workspace_manager

                tw = get_team_workspace_manager()

                if subcmd == "create":
                    name = msg.get("name", "新工作区")
                    created_by = msg.get("created_by", "local")
                    result = tw.create_workspace(name, created_by)
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "list":
                    ws_list = tw.list_workspaces()
                    await ws.send_json(
                        {
                            "type": "team_ws_result",
                            "subcommand": subcmd,
                            "workspaces": ws_list,
                        }
                    )
                elif subcmd == "get":
                    ws_id = msg.get("workspace_id", "")
                    data = tw.get_workspace(ws_id)
                    await ws.send_json(
                        {
                            "type": "team_ws_result",
                            "subcommand": subcmd,
                            "workspace": data,
                        }
                    )
                elif subcmd == "delete":
                    ws_id = msg.get("workspace_id", "")
                    result = tw.delete_workspace(ws_id)
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "join":
                    ws_id = msg.get("workspace_id", "")
                    name = msg.get("display_name", "guest")
                    result = tw.join_workspace(ws_id, name)
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "leave":
                    member_id = msg.get("member_id", "")
                    result = tw.leave_workspace(member_id)
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "members":
                    ws_id = msg.get("workspace_id", "")
                    members = tw.list_members(ws_id)
                    await ws.send_json(
                        {
                            "type": "team_ws_result",
                            "subcommand": subcmd,
                            "members": members,
                        }
                    )
                elif subcmd == "review_create":
                    result = tw.create_review_request(
                        msg.get("workspace_id", ""),
                        msg.get("title", ""),
                        msg.get("requested_by", ""),
                        msg.get("file_path", ""),
                        msg.get("code_snippet", ""),
                        msg.get("description", ""),
                        msg.get("assigned_to"),
                    )
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "review_list":
                    reviews = tw.list_review_requests(
                        msg.get("workspace_id", ""),
                        msg.get("status", ""),
                    )
                    await ws.send_json(
                        {
                            "type": "team_ws_result",
                            "subcommand": subcmd,
                            "reviews": reviews,
                        }
                    )
                elif subcmd == "review_comment":
                    result = tw.add_review_comment(
                        msg.get("review_id", ""),
                        msg.get("user", ""),
                        msg.get("comment", ""),
                    )
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "review_status":
                    result = tw.update_review_status(
                        msg.get("review_id", ""),
                        msg.get("status", ""),
                    )
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                elif subcmd == "activity":
                    feed = tw.get_activity_feed(msg.get("workspace_id", ""), msg.get("limit", 30))
                    await ws.send_json(
                        {
                            "type": "team_ws_result",
                            "subcommand": subcmd,
                            "activities": feed,
                        }
                    )
                elif subcmd == "share_session":
                    result = tw.share_session(
                        msg.get("workspace_id", ""),
                        msg.get("session_id", ""),
                        msg.get("user_name", ""),
                    )
                    await ws.send_json({"type": "team_ws_result", "subcommand": subcmd, **result})
                else:
                    await ws.send_json(
                        {"type": "error", "message": f"未知 team_ws 子命令: {subcmd}"}
                    )
                continue

            # ═══════════════════════════════════════════════
            # PyCoder Cloud
            # ═══════════════════════════════════════════════

            if msg_type == "cloud":
                """PyCoder Cloud: register/login/check_quota/usage/upgrade"""
                subcmd = msg.get("subcommand", "")
                from pycoder.server.services.cloud_service import get_cloud_service

                cs = get_cloud_service()

                if subcmd == "register":
                    result = cs.register(
                        msg.get("username", ""),
                        msg.get("password", ""),
                        msg.get("email", ""),
                    )
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "login":
                    result = cs.login(
                        msg.get("username", ""),
                        msg.get("password", ""),
                    )
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "user_info":
                    result = cs.get_user_info(msg.get("token", ""))
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "check_quota":
                    result = cs.check_quota(msg.get("token", ""))
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "usage_history":
                    result = cs.get_usage_history(
                        msg.get("token", ""),
                        msg.get("days", 7),
                    )
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "track_usage":
                    result = cs.track_usage(
                        msg.get("token", ""),
                        msg.get("model", ""),
                        msg.get("tokens_in", 0),
                        msg.get("tokens_out", 0),
                    )
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "plans":
                    plans = cs.get_plan_upgrade_info()
                    await ws.send_json(
                        {
                            "type": "cloud_result",
                            "subcommand": subcmd,
                            "plans": plans,
                        }
                    )
                elif subcmd == "upgrade":
                    result = cs.upgrade_plan(
                        msg.get("token", ""),
                        msg.get("plan", ""),
                    )
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "add_key":
                    result = cs.add_api_key(
                        msg.get("provider", ""),
                        msg.get("api_key", ""),
                    )
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, **result})
                elif subcmd == "list_keys":
                    keys = cs.list_api_keys()
                    await ws.send_json({"type": "cloud_result", "subcommand": subcmd, "keys": keys})
                else:
                    await ws.send_json({"type": "error", "message": f"未知 cloud 子命令: {subcmd}"})
                continue

            user_message = msg.get("message", "")
            if not user_message:
                continue
            requested_model = msg.get("model", "")
            effective_model = _get_effective_model(requested_model or current_model)
            if effective_model != current_model:
                current_model = effective_model
                store.update_session(session_id, model=current_model)

            hermes_mode = msg.get("hermes", False)
            # DeepSeek 推理参数透传
            reasoning_effort = msg.get("reasoning_effort", "medium")
            enable_cache = msg.get("enable_cache", True)
            final_content = ""

            # FIX(任务终止): 用 _run_cancellable_stream 包装，
            # 收到 stop 消息时取消正在执行的 chat/agent 流。
            # 之前直接 `async for event in chat_stream_fn(...)` 阻塞在 generator 内部，
            # 主循环无法接收 stop 消息，前端的停止按钮实际无效。
            captured_events: list[dict] = []

            async def _chat_gen_factory():
                async for event in chat_stream_fn(
                    session_id,
                    user_message,
                    current_model,
                    msg.get("system_prompt"),
                    hermes=hermes_mode,
                    reasoning_effort=reasoning_effort,
                    enable_cache=enable_cache,
                ):
                    if event.get("type") == "done" or event.get("type") == "agent_result":
                        # 捕获最终内容供后续 shared session 广播使用
                        final_evt_content = event.get("content") or event.get("summary", "")
                        captured_events.append({"content": final_evt_content})
                    yield event

            await _run_cancellable_stream(
                _chat_gen_factory(),
                ws,
                runtime,
                "chat_task",
            )

            # 从捕获的事件中提取 final_content（用于 shared session 广播）
            if captured_events:
                final_content = captured_events[-1]["content"]

            # 消息持久化已由 _run_chat_stream 内部处理，此处不再重复保存

            # 多播给共享会话的其他成员
            if shared_session_id and final_content:
                await share_mgr.broadcast(
                    shared_session_id,
                    {"type": "share_message", "content": final_content, "role": "assistant"},
                    exclude=client_id,
                )
    except WebSocketDisconnect:
        log.info("ws_disconnect")
        share_mgr.leave(client_id)
    except Exception as e:
        log.error("ws_error", error=str(e))
        share_mgr.leave(client_id)


def _strip_code_fence(text: str, language: str = "") -> str:
    """剥离 AI 输出中可能残留的 ``` 代码块标记"""
    text = text.strip()
    # 去掉开头的 ```lang
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline > 0:
            text = text[first_newline + 1 :]
    # 去掉结尾的 ```
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
