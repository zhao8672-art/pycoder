"""ChatBridge 子模块 — 流式响应解析

从 chat_bridge.py 拆分而来，负责：
- SSE (Server-Sent Events) 行解析
- delta 提取（content / reasoning_content / tool_calls）
- 请求负载构建
- Provider 401 降级处理
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_sse_line(line: str) -> dict | None:
    """解析单行 SSE 数据

    Args:
        line: 一行 SSE 数据，形如 "data: {...}" 或 "data: [DONE]"

    Returns:
        解析后的 JSON dict，或 None（空行/非数据行/[DONE]）
    """
    if not line.startswith("data: "):
        return None
    data_str = line[6:].strip()
    if data_str == "[DONE]":
        return None
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None


def extract_stream_delta(
    data: dict,
    *,
    existing_tool_calls: list[dict] | None = None,
) -> tuple[str, str, list[dict], bool]:
    """从 SSE 数据中提取 delta 信息

    Args:
        data: SSE 解析后的 dict
        existing_tool_calls: 之前已累积的工具调用列表（用于流式累积）。
            若传入则在其基础上追加；None 表示创建新列表。

    Returns:
        (content, reasoning_content, tool_calls, finish_reason_is_tool_calls)
        - content: 文本内容（可能为空）
        - reasoning_content: 推理内容（可能为空）
        - tool_calls: 累积后的工具调用列表（已合并 existing_tool_calls）
        - finish_reason_is_tool_calls: 是否因 tool_calls 结束
    """
    content = ""
    reasoning_content = ""
    # 在已有列表基础上累积（流式增量合并）
    tool_calls: list[dict] = list(existing_tool_calls) if existing_tool_calls else []
    finish_is_tool = False

    choice = (data.get("choices") or [None])[0]
    if not choice:
        return content, reasoning_content, tool_calls, finish_is_tool

    delta = choice.get("delta") or {}
    if delta.get("reasoning_content"):
        reasoning_content = delta["reasoning_content"]
        # Agnes/纯推理模型的内容在 reasoning_content 中
        if not delta.get("content"):
            content = delta["reasoning_content"]
    if delta.get("content"):
        content = delta["content"]
    if delta.get("tool_calls"):
        for tc in delta["tool_calls"]:
            idx = tc.get("index", 0)
            while len(tool_calls) <= idx:
                tool_calls.append(
                    {"id": "", "function": {"name": "", "arguments": ""}}
                )
            if tc.get("id"):
                tool_calls[idx]["id"] += tc["id"]
            if tc.get("function"):
                if tc["function"].get("name"):
                    tool_calls[idx]["function"]["name"] += tc["function"]["name"]
                if tc["function"].get("arguments"):
                    tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]
    if choice.get("finish_reason") == "tool_calls":
        finish_is_tool = True

    return content, reasoning_content, tool_calls, finish_is_tool


def build_request_payload(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    tools_payload: list[dict],
    is_deepseek: bool,
    reasoning_effort: str,
    enable_thinking: bool,
    enable_cache: bool,
    stream: bool = True,
) -> dict[str, Any]:
    """构建 chat completions 请求负载

    Args:
        model: 模型名称
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大 token 数
        tools_payload: 工具负载（可为空）
        is_deepseek: 是否为 DeepSeek 模型（启用特殊参数）
        reasoning_effort: 推理强度 ("max"|"medium"|"low")
        enable_thinking: 是否启用深度思考链
        enable_cache: 是否启用 KV Cache
        stream: 是否流式

    Returns:
        OpenAI 兼容的请求负载 dict
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if is_deepseek and enable_thinking:
        payload["reasoning_effort"] = reasoning_effort
    if is_deepseek and enable_cache:
        payload["enable_cache"] = True
    if tools_payload:
        payload["tools"] = tools_payload
        payload["tool_choice"] = "auto"
    return payload


def rebuild_payload_for_fallback(
    payload: dict,
    *,
    new_model: str,
    new_api_key: str,
    is_deepseek: bool,
    reasoning_effort: str,
    enable_thinking: bool,
    enable_cache: bool,
) -> tuple[dict, dict]:
    """Provider 401 降级时重建 payload 和 headers

    Args:
        payload: 原始 payload
        new_model: 新模型名
        new_api_key: 新 API Key
        is_deepseek: 新模型是否为 DeepSeek
        reasoning_effort: 推理强度
        enable_thinking: 是否启用思考链
        enable_cache: 是否启用缓存

    Returns:
        (新 payload, 新 headers)
    """
    new_payload = dict(payload)
    new_payload["model"] = new_model
    # 重建 DeepSeek 特有选项
    if is_deepseek and enable_thinking:
        new_payload["reasoning_effort"] = reasoning_effort
    elif "reasoning_effort" in new_payload:
        del new_payload["reasoning_effort"]
    if is_deepseek and enable_cache:
        new_payload["enable_cache"] = True
    elif "enable_cache" in new_payload:
        del new_payload["enable_cache"]

    new_headers = {
        "Authorization": f"Bearer {new_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    return new_payload, new_headers


__all__ = [
    "parse_sse_line",
    "extract_stream_delta",
    "build_request_payload",
    "rebuild_payload_for_fallback",
]
