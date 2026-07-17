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
    """FIM 增强内联补全 — FIM引擎 → ChatBridge → 空 三层降级"""
    try:
        body = await req.json()
        prefix = str(body.get("prefix", ""))[-500:]
        suffix = str(body.get("suffix", ""))[:200]
        language = str(body.get("language", "python"))
        max_tokens = min(int(body.get("maxTokens", 64)), 128)
        # Layer 1: FIM 引擎（零 token）
        try:
            from pycoder.ai.completion.fim_engine import FIMCodeCompleter
            fim = FIMCodeCompleter()
            result = await fim.complete(prefix, suffix, language)
            if result and len(result) > 3:
                return {"completion": result[:max_tokens]}
        except (ImportError, RuntimeError, ValueError, TypeError):
            pass
        # Layer 2: ChatBridge 降级
        from pycoder.server.chat_bridge import ChatBridge
        bridge = ChatBridge()
        bridge.config.max_tokens = max_tokens
        bridge.config.temperature = 0.2
        bridge.config.enable_thinking = False
        prompt = f"Complete {language} code:\n{prefix}"
        result = await bridge.chat(prompt, max_tokens=max_tokens)
        await bridge.close()
        return {"completion": (result or "").strip()[:max_tokens]}
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
