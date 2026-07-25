"""ChatBridge 子模块 — 对话历史管理

从 chat_bridge.py 拆分而来，负责：
- 维护会话消息列表
- 应用滑窗截断 + 记忆压缩
- 注入上下文锚点
- Token 预算检查
"""

from __future__ import annotations

import logging

from .chat_bridge_context import (
    _apply_context_anchor,
    _apply_history_sliding_window,
    _check_token_budget,
)

logger = logging.getLogger(__name__)


class HistoryManager:
    """对话历史管理器 — 维护消息列表 + 滑窗截断 + 上下文锚点注入"""

    def __init__(self, *, max_history_messages: int = 20):
        """
        Args:
            max_history_messages: 发给 LLM 的历史消息滑窗上限（0 表示不截断）
        """
        self._messages: list[dict] = []
        self._max_history = max_history_messages

    @property
    def messages(self) -> list[dict]:
        """完整历史消息列表（仅供审计/序列化，不应直接修改）"""
        return self._messages

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        self._messages = list(value)

    @property
    def max_history(self) -> int:
        return self._max_history

    @max_history.setter
    def max_history(self, value: int) -> None:
        self._max_history = max(0, int(value))

    def add_message(self, role: str, content: str) -> None:
        """添加上下文消息"""
        self._messages.append({"role": role, "content": content})

    def add_raw(self, message: dict) -> None:
        """添加完整的消息 dict（含 tool_calls/tool_call_id 等字段）"""
        self._messages.append(dict(message))

    def clear(self) -> None:
        """清空所有历史消息"""
        self._messages.clear()

    def get_effective_messages(self) -> list[dict]:
        """返回发给 LLM 的历史消息（应用滑窗截断 + 记忆压缩 + 上下文锚点）

        - 保留 _messages 完整历史供审计/序列化
        - 仅截断本次发给 LLM 的副本
        - max_history_messages=0 表示不截断
        """
        messages = list(self._messages)
        # 1) 滑窗截断 + 记忆压缩
        messages, _dropped, _compressed_len = _apply_history_sliding_window(
            messages, self._max_history,
        )
        # 2) 注入上下文锚点
        messages = _apply_context_anchor(messages)
        return messages

    def check_token_budget(self) -> int:
        """检查当前历史消息的 token 数，超出阈值时预警

        Returns:
            估算的 token 数
        """
        return _check_token_budget(self._messages)

    def to_list(self) -> list[dict]:
        """导出消息列表的副本"""
        return [dict(m) for m in self._messages]

    def extend(self, messages: list[dict]) -> None:
        """批量追加消息"""
        self._messages.extend(dict(m) for m in messages)

    def __len__(self) -> int:
        return len(self._messages)


__all__ = ["HistoryManager"]
