"""
Chat routes (REST, non-streaming).
Extracted from rest_routes.py for modularity.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from pycoder.server.chat_handler import ChatRequest, _resolve_model, _run_chat_stream
from pycoder.server.session_store import get_session_store

router = APIRouter()


@router.post("/api/completion")
async def inline_completion(req: Request):
    """Lightweight inline completion endpoint (Phase 1 #10)"""
    try:
        import json as _json
        body = await req.json()
        prefix = str(body.get("prefix", ""))[-200:]
        max_tokens = min(int(body.get("maxTokens", 30)), 50)
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        bridge.config.max_tokens = max_tokens
        bridge.config.temperature = 0.2
        bridge.config.enable_thinking = False
        result = await bridge.chat(prefix, max_tokens=max_tokens)
        await bridge.close()
        return {"completion": result.strip()[:200]}
    except Exception as e:
        return {"completion": "", "error": str(e)[:100]}


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
        async for event in _run_chat_stream(
            session_id, req.message, model, req.system_prompt, req.files, hermes=True
        ):
            if event.get("type") == "error":
                return {"error": event.get("message")}
        return {"status": "ok", "hermes_complete": True}
    else:
        collected_content = ""
        usage_info = {}
        try:
            async for event in _run_chat_stream(
                session_id, req.message, model, req.system_prompt, req.files, hermes=False
            ):
                if event.get("type") == "token":
                    collected_content += event.get("data") or event.get("content", "")
                elif event.get("type") == "done":
                    usage_info = event.get("usage", {})
                elif event.get("type") == "error":
                    return {"error": event.get("message")}
        finally:
            pass

        return {
            "reply": collected_content,
            "session_id": session_id,
            "model": model,
            "usage": usage_info,
        }
