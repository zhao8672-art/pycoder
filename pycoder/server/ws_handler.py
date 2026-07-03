"""WebSocket chat handler: streaming AI chat via WebSocket."""

from __future__ import annotations

import asyncio
import json
import os
import traceback
import uuid
from pathlib import Path
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from pycoder import __version__
from pycoder.server.log import log
from pycoder.server.session_store import get_session_store
from pycoder.server.chat_handler import (
    ChatRequest,
    _get_effective_model,
    _run_chat_stream as chat_stream_fn,
)
from pycoder.server.hermes_engine import _execute_hermes_write


async def websocket_chat(ws: WebSocket):
    """Main WebSocket handler for real-time AI chat."""
    from pycoder.server.project_helpers import _get_project_tree
    from pycoder.server.project_helpers import _get_git_status
    from pycoder.server.project_helpers import _get_diff_preview

    await ws.accept()
    store = get_session_store()
    session_id = str(uuid.uuid4())
    store.create_session(session_id=session_id)
    current_model = "deepseek-chat"
    await ws.send_json({"type": "connected", "session_id": session_id, "version": __version__})
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")
            if msg_type == "switch_session":
                new_id = msg.get("session_id", "")
                if new_id and store.get_session(new_id):
                    session_id = new_id
                    await ws.send_json({"type": "session_switched", "session_id": session_id})
                continue
            if msg_type == "list_sessions":
                sessions = store.list_sessions(limit=20)
                await ws.send_json({"type": "session_list", "sessions": [s.to_dict() for s in sessions]})
                continue
            if msg_type == "history":
                sid = msg.get("session_id", session_id)
                messages = store.get_messages(sid)
                await ws.send_json({"type": "history", "session_id": sid, "messages": [m.to_dict() for m in messages]})
                continue
            if msg_type == "execute_plan":
                plan_content = msg.get("plan", "")
                if not plan_content:
                    await ws.send_json({"type": "error", "message": "execute_plan requires 'plan' field"})
                    continue
                async for event in _run_hermes_execute(session_id, plan_content, current_model):
                    await ws.send_json(event)
                    await asyncio.sleep(0)
                continue
            if msg_type == "write_file":
                file_path = msg.get("path", "")
                file_content = msg.get("content", "")
                if not file_path:
                    await ws.send_json({"type": "error", "message": "write_file requires 'path' field"})
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
                    target = Path(file_path)
                    if not target.is_absolute():
                        target = Path(os.getcwd()) / target
                    if not target.exists():
                        await ws.send_json({"type": "error", "message": f"Not found: {file_path}"})
                        continue
                    content = target.read_text(encoding="utf-8")
                    stat = target.stat()
                    await ws.send_json({
                        "type": "file_open",
                        "path": str(target),
                        "name": target.name,
                        "content": content,
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                    })
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

            user_message = msg.get("message", "")
            if not user_message:
                continue
            requested_model = msg.get("model", "")
            effective_model = _get_effective_model(requested_model or current_model)
            if effective_model != current_model:
                current_model = effective_model
                store.update_session(session_id, model=current_model)

            hermes_mode = msg.get("hermes", False)
            async for event in chat_stream_fn(session_id, user_message, current_model, msg.get("system_prompt"), hermes=hermes_mode):
                await ws.send_json(event)
                await asyncio.sleep(0)
    except WebSocketDisconnect:
        log.info("ws_disconnect")
    except Exception as e:
        log.error("ws_error", error=str(e))
