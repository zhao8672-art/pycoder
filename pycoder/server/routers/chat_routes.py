"""
Chat routes (REST, non-streaming).
Extracted from rest_routes.py for modularity.
"""
from __future__ import annotations

import json

from fastapi import APIRouter
from starlette.responses import StreamingResponse
from pycoder.server.chat_handler import ChatRequest
from pycoder.server.chat_handler import _resolve_model
from pycoder.server.chat_handler import _run_chat_stream as chat_stream_fn
from pycoder.server.session_store import get_session_store

router = APIRouter()

@router.post("/api/chat")
async def chat(req: ChatRequest):
    model = _resolve_model(req.model)
    store = get_session_store()
    session_id = req.session_id or store.create_session(model=model).id
    if session_id:
        existing = store.get_session(session_id)
        if existing and existing.model != model:
            store.update_session(session_id, model=model)

    if req.hermes:
        hermes_events = []
        async for event in _run_chat_stream(session_id, req.message, model, req.system_prompt, req.files, hermes=True):
            hermes_events.append(event)
        result_event = {}
        for ev in hermes_events:
            if ev.get("type") == "hermes_result":
                result_event = ev
                break
        content = result_event.get("summary", "")
        result_type = result_event.get("result", "success")
        return {
            "success": True,
            "type": "hermes_result",
            "result": result_type,
            "content": content,
            "session_id": session_id,
            "model": model,
            "hermes_events": hermes_events,
        }

    # 普通聊天模式（非 Hermes）- 收集流式输出并返回
    collected_content = ""
    usage_info = {}
    try:
        async for event in _run_chat_stream(session_id, req.message, model, req.system_prompt, req.files, hermes=False):
            if event.get("type") == "chunk":
                collected_content += event.get("content", "")
            elif event.get("type") == "done":
                collected_content = event.get("content", "") or collected_content
                usage_info = event.get("usage", {})
            elif event.get("type") == "error":
                return {"success": False, "error": event.get("message", "Unknown error"), "session_id": session_id}
    except Exception as e:
        return {"success": False, "error": str(e), "session_id": session_id}

    return {
        "success": True,
        "content": collected_content,
        "session_id": session_id,
        "model": model,
        "usage": usage_info,
    }




@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming endpoint for /api/chat/stream"""
    model = _resolve_model(req.model)
    store = get_session_store()
    session_id = req.session_id or store.create_session(model=model).id
    if session_id:
        existing = store.get_session(session_id)
        if existing and existing.model != model:
            store.update_session(session_id, model=model)

    async def event_generator():
        if req.hermes:
            async for event in _run_chat_stream(session_id, req.message, model, req.system_prompt, req.files, hermes=True):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        else:
            async for event in _run_chat_stream(session_id, req.message, model, req.system_prompt, req.files, hermes=False):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
