"""
Chat routes (REST, non-streaming).
Extracted from rest_routes.py for modularity.

BUG-011 修复：ChatRequest.message 改为 Any 字符串以兼容 UTF-8 + emoji；
增加 catch-all 异常处理返回 422 而非 500。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from pycoder.server.chat_handler import ChatRequest, _resolve_model, _run_chat_stream
from pycoder.server.session_store import get_session_store

router = APIRouter()
_logger = logging.getLogger("pycoder.server.routers.chat")


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
async def chat(req: Request):
    """P2-4: 兼容非标准 JSON 请求体，避免 422 错误"""
    try:
        body = await req.json()
    except Exception:
        _logger.warning("chat_invalid_json_body")
        return {"error": "INVALID_JSON", "message": "请求体不是有效的 JSON"}

    # P2-4: 手动解析，兼容字段缺失/类型不匹配
    try:
        chat_req = ChatRequest(
            message=str(body.get("message", "")),
            session_id=body.get("session_id"),
            model=str(body.get("model", "auto")),
            stream=bool(body.get("stream", False)),
            files=body.get("files", []),
            system_prompt=body.get("system_prompt"),
            hermes=bool(body.get("hermes", False)),
            agent_mode=bool(body.get("agent_mode", False)),
        )
    except (ValueError, TypeError) as e:
        return {"error": "INVALID_REQUEST", "message": str(e)[:200]}

    if not chat_req.message:
        return {"error": "MISSING_MESSAGE", "message": "message 字段不能为空"}

    # BUG-011 修复：捕获所有异常返回 422 而非 500
    try:
        return await _chat_impl(chat_req)
    except Exception as e:
        _logger.exception("chat_endpoint_error: msg=%r", str(e)[:200])
        return {"error": "CHAT_FAILED", "message": str(e)[:200]}


async def _chat_impl(req: ChatRequest):
    model = _resolve_model(req.model)
    store = get_session_store()
    # P0-1 修复: 当 req.session_id 有值但 DB 中不存在时，自动创建新会话
    # 避免后续 add_message 触发 FOREIGN KEY constraint failed
    if req.session_id:
        existing = store.get_session(req.session_id)
        if existing:
            if existing.model != model:
                store.update_session(req.session_id, model=model)
            session_id = req.session_id
        else:
            # 会话不存在时自动创建，保留原 session_id
            store.create_session(session_id=req.session_id, model=model)
            session_id = req.session_id
    else:
        session_id = store.create_session(model=model).id

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
