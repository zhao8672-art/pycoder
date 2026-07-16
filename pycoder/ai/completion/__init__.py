"""Fill-in-the-Middle 代码补全引擎 — 弥补与 Codex -6.5 的差距

支持两种模式:
  1. DeepSeek FIM API (专用补全端点)
  2. Chat-based FIM (通过 LLM 聊天接口)

特性:
  - 光标位置感知
  - 多语言支持
  - 异步流式补全
"""

from __future__ import annotations

from pycoder.ai.completion.fim_engine import FIMCodeCompleter, get_completer

__all__ = ["FIMCodeCompleter", "get_completer"]
