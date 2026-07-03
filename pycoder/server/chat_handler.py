"""Chat handler: request/response models, model routing, streaming chat."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional
from pydantic import BaseModel, Field

from pycoder.server.session_store import get_session_store
from pycoder.providers.auth import get_model_manager
from pycoder.server.chat_bridge import ChatBridge
from pycoder.providers.setup_wizard import get_api_key
from pycoder.server.hermes_engine import (
    _extract_field,
    _execute_hermes_write,
)

class ChatRequest(BaseModel):
    message: str = Field(..., description="User message", min_length=1)
    session_id: Optional[str] = Field(None)
    model: str = Field("auto")
    stream: bool = Field(False)
    files: list[str] = Field(default_factory=list)
    system_prompt: Optional[str] = Field(None)
    hermes: bool = Field(False, description="Enable Hermes structured task mode")
    agent_mode: bool = Field(False, description="Enable Agent team orchestration mode")

class ChatResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    role: str = "assistant"
    content: str
    model: str
    usage: dict = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)



def _resolve_model(requested: str) -> str:
    """Resolve model name from user input."""
    if requested and requested != "auto":
        return requested
    return _get_effective_model(requested)


def _get_effective_model(requested: str | None = None) -> str:
    """Get the effective model to use."""
    if requested and requested != "auto":
        return requested
    try:
        mgr = get_model_manager()
        try:
            model, _ = mgr.recommend(task_type="coding")
        except TypeError:
            model, _ = mgr.recommend()
        return model or "deepseek-chat"
    except Exception:
        return "deepseek-chat"


def _get_api_key_for_model(model: str) -> str:
    """Get the API key for the given model."""
    try:
        mgr = get_model_manager()
        provider = "deepseek"
        if model.startswith("qwen"):
            provider = "qwen"
        elif model.startswith("glm"):
            provider = "glm"
        elif model.startswith("gpt"):
            provider = "openai"
        elif model.startswith("claude"):
            provider = "anthropic"
        elif model.startswith("gemini"):
            provider = "google"
        return mgr.get_key(provider) or get_api_key(provider) or os.environ.get("DEEPSEEK_API_KEY", "")
    except Exception:
        if model.startswith("deepseek"):
            return get_api_key("deepseek") or os.environ.get("DEEPSEEK_API_KEY", "")
        return ""


async def _run_chat_stream(
    session_id, message, model, system_prompt=None, files=None, hermes=False, ws=None
):
    """Streaming chat via ChatBridge, with optional Hermes structured mode."""
    api_key = _get_api_key_for_model(model)
    if not api_key:
        yield {"type": "error", "message": "No API Key configured"}
        return

    bridge = ChatBridge()
    bridge.configure(model=model, api_key=api_key)
    if system_prompt:
        bridge.config.system_prompt = system_prompt

    store = get_session_store()
    if session_id and store.get_session(session_id):
        try:
            for msg in store.get_messages(session_id, limit=100):
                bridge.add_message(msg.role, msg.content)
        except Exception:
            pass

    # Agent mode: delegate to AgentOrchestrator via Gateway
    if hermes:
        yield {"type": "agent_status", "message": "Agent mode activated"}
        from pycoder.server.services.agent_orchestrator import agent_chat_stream as agent_stream
        async for event in agent_stream(message, model=model):
            yield event
        return

    # Normal chat mode (streaming chunks)
    chunk_index = 0
    final_content = ""
    try:
        async for event in bridge.chat_stream(message):
            if event.event_type == "token":
                chunk_index += 1
                final_content += event.content
                yield {"type": "token", "data": event.content, "content": event.content, "index": chunk_index}
            elif event.event_type == "done":
                yield {"type": "done", "content": event.content or final_content, "usage": event.usage}
            elif event.event_type == "error":
                yield {"type": "error", "message": event.content}
                return
    finally:
        await bridge.close()
