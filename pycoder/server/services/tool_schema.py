"""P1-2: 工具调用 JSON Schema 定义与校验

替代旧 parse_tool_calls 中的 XML 解析路径，提供结构化的 JSON Schema 校验。

Schema 定义：
    单个工具调用：{"name": str, "params": dict}
    LLM 响应：{"tool_calls": [...], "thought": str?}
"""

from __future__ import annotations

import logging
from typing import Any

from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)


# 单个工具调用的 Schema
TOOL_CALL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "params": {"type": "object"},
    },
    "required": ["name", "params"],
    "additionalProperties": False,
}

# 完整响应的 Schema（LLM 应输出此格式）
TOOL_CALLS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_calls": {
            "type": "array",
            "items": TOOL_CALL_SCHEMA,
        },
        "thought": {"type": "string"},  # 可选：LLM 的思考过程
    },
    "required": ["tool_calls"],
    "additionalProperties": False,
}


def validate_tool_calls(data: dict) -> list[dict]:
    """校验工具调用响应，返回标准化的 tool_calls 列表

    Args:
        data: 已解析的 dict（应包含 tool_calls 字段）

    Returns:
        标准化的 tool_calls 列表

    Raises:
        ValueError: 校验失败时
    """
    try:
        validate(instance=data, schema=TOOL_CALLS_RESPONSE_SCHEMA)
    except ValidationError as e:
        raise ValueError(f"工具调用格式校验失败: {e.message}") from e

    calls = data["tool_calls"]
    # 逐个校验（虽然 items schema 已校验，但此处明确单独校验以便定位错误）
    for call in calls:
        try:
            validate(instance=call, schema=TOOL_CALL_SCHEMA)
        except ValidationError as e:
            tool_name = call.get("name", "?") if isinstance(call, dict) else "?"
            raise ValueError(f"工具调用 {tool_name} 格式无效: {e.message}") from e

    return calls


def build_tool_calls_json(name: str, params: dict) -> dict:
    """构建单个工具调用 JSON

    用于测试或生成示例 LLM 输出
    """
    return {"name": name, "params": params}


def build_tool_calls_response(
    calls: list[dict],
    thought: str = "",
) -> dict:
    """构建完整的工具调用响应 JSON"""
    return {"thought": thought, "tool_calls": calls}
