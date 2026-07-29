"""ChatBridge 子模块 — Token 计数与估算

从 chat_bridge.py 拆分而来，负责：
- 精确 Token 计数（tiktoken）
- 文本截断
- 粗略 Token 估算（降级方案）
"""

from __future__ import annotations


class TokenCounter:
    """精确 Token 计数器 — 使用 tiktoken (兼容 cl100k_base)

    当 tiktoken 不可用时自动降级为 len//3 估算。
    """

    _encoders: dict[str, object] = {}

    @classmethod
    def count(cls, text: str, model: str = "deepseek-chat") -> int:
        """精确计算 token 数"""
        try:
            encoding = cls._get_encoding(model)
            return len(encoding.encode(text))
        except (ImportError, KeyError, ValueError):
            return len(text) // 3  # 降级估算

    @classmethod
    def truncate(cls, text: str, max_tokens: int, model: str = "deepseek-chat") -> str:
        """精确截断到指定 token 数"""
        try:
            encoding = cls._get_encoding(model)
            tokens = encoding.encode(text)
            return encoding.decode(tokens[:max_tokens])
        except (ImportError, KeyError):
            return text[: max_tokens * 3]  # 降级截断

    @classmethod
    def _get_encoding(cls, model: str):
        """获取编码器（带缓存）"""
        if model not in cls._encoders:
            import tiktoken

            # DeepSeek/Qwen/GLM 兼容 cl100k_base
            cls._encoders[model] = tiktoken.get_encoding("cl100k_base")
        return cls._encoders[model]


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量 (~每中文字符1token，每英文词1.3token)"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.2 + other_chars / 2.5) + 4


__all__ = ["TokenCounter", "estimate_tokens"]
