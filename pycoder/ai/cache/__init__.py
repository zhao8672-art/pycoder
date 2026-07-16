"""KV Cache 持久化 — LLM Prompt 前缀缓存

将 LLM 调用的前缀 prompt 计算结果缓存到 SQLite，
避免重复计算相同前缀。

原理:
  1. 每次 LLM 调用前计算 prompt 的 hash 前缀
  2. 在 cache 中查找 (prefix_hash, model, temperature) 的组合
  3. 命中 → 返回缓存的 prefix_output + 只发送新 tokens
  4. 未命中 → 完整调用 + 缓存结果

收益:
  - 重复前缀 (system_prompt + 工具定义) 可节省 30-50% Token
  - 首 Token 延迟降低 40-60%
"""

from __future__ import annotations

from pycoder.ai.cache.kv_cache import PromptCache, get_cache

__all__ = ["PromptCache", "get_cache"]
