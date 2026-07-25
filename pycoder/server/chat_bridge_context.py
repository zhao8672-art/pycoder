"""ChatBridge 子模块 — 上下文构建与历史压缩

从 chat_bridge.py 拆分而来，负责：
- 上下文锚点注入（任务目标 + 进度 + 偏离提醒）
- 旧消息压缩为摘要
- Token 预算检查
"""

from __future__ import annotations

import json
import logging

from .chat_bridge_tokens import TokenCounter

logger = logging.getLogger(__name__)


def _get_context_anchor() -> str:
    """获取当前会话的上下文锚点（任务目标 + 进度 + 偏离提醒）

    由 ContextOrchestrator 管理，在每次 LLM 调用前注入到 system prompt 前缀。
    获取失败时静默返回空串，不阻塞主流程。
    """
    try:
        from pycoder.server.services.context_orchestrator import (
            get_orchestrator,
        )

        orch = get_orchestrator()
        if orch and orch.tracker.is_active:
            return orch.get_anchor()
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    return ""


def _compress_old_messages(old_messages: list[dict]) -> str:
    """压缩旧消息为摘要文本（零延迟规则提取，不调用 LLM）

    失败时降级为空串，不影响主流程。
    """
    if not old_messages:
        return ""
    try:
        from pycoder.server.services.agent_memory import get_memory_manager

        manager = get_memory_manager()
        return manager.compress_history(old_messages)
    except (ImportError, RuntimeError, OSError, ValueError) as e:
        logger.debug("memory_compress_failed error=%s", e)
        return ""


def _check_token_budget(messages: list[dict]) -> int:
    """精确计算消息列表的 token 数，超出阈值时预警

    Args:
        messages: 消息列表

    Returns:
        估算的 token 数
    """
    msg_str = json.dumps(
        [{"role": m.get("role", ""), "content": m.get("content", "")} for m in messages]
    )
    estimated = TokenCounter.count(msg_str)
    if estimated > 60000:
        logger.warning(
            "context_near_limit estimated=%d limit=64000",
            estimated,
        )
    return estimated


def _apply_context_anchor(messages: list[dict]) -> list[dict]:
    """将上下文锚点注入到消息列表开头

    如果首条消息是 system，则追加到其后；否则插入新 system 消息。

    Args:
        messages: 原始消息列表

    Returns:
        注入锚点后的新消息列表（不修改原列表）
    """
    anchor = _get_context_anchor()
    if not anchor or not messages:
        return list(messages)

    new_messages = list(messages)
    if new_messages[0].get("role") == "system":
        new_messages[0] = {
            **new_messages[0],
            "content": anchor + "\n\n---\n" + str(new_messages[0]["content"]),
        }
    else:
        new_messages.insert(0, {"role": "system", "content": anchor})
    return new_messages


def _apply_history_sliding_window(
    messages: list[dict],
    max_history: int,
) -> tuple[list[dict], int, int]:
    """应用历史消息滑窗截断

    Args:
        messages: 原始消息列表
        max_history: 最大保留消息数（0 表示不截断）

    Returns:
        (截断后消息列表, dropped 数量, compressed 摘要长度)
        若未触发截断，dropped=0, compressed_len=0
    """
    if max_history <= 0 or len(messages) <= max_history:
        return list(messages), 0, 0

    dropped_messages = messages[:-max_history]
    kept_messages = messages[-max_history:]
    compressed = _compress_old_messages(dropped_messages)
    new_messages = list(kept_messages)
    if compressed:
        new_messages.insert(0, {"role": "system", "content": compressed})

    logger.debug(
        "chat_history_compressed dropped=%d kept=%d summary_len=%d",
        len(dropped_messages),
        max_history,
        len(compressed),
    )
    return new_messages, len(dropped_messages), len(compressed)


__all__ = [
    "_get_context_anchor",
    "_compress_old_messages",
    "_check_token_budget",
    "_apply_context_anchor",
    "_apply_history_sliding_window",
]
