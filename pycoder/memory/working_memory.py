"""Level 1: WorkingMemory — 会话级滑动窗口"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from pycoder.memory.deep_memory_models import MemoryEntry, _estimate_tokens, _now_iso

logger = logging.getLogger(__name__)


class WorkingMemory:
    """工作记忆 — 会话级临时记忆（Level 1）

    特性:
    - 滑动窗口上下文管理，限制最大 Token 数
    - 超限自动摘要压缩
    - LRU 缓存高频访问项
    - 生命周期: 单次会话
    """

    DEFAULT_MAX_TOKENS = 4096
    LRU_CACHE_SIZE = 64

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        self._max_tokens = max_tokens
        self._store: dict[str, MemoryEntry] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._total_tokens = 0
        self._created_at = _now_iso()

    def store(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryEntry:
        """存储一条工作记忆"""
        entry = MemoryEntry(
            level=1,
            key=key,
            content=content,
            metadata=metadata or {},
            ttl=3600,
        )
        if key in self._store:
            old = self._store[key]
            self._total_tokens -= _estimate_tokens(old.content)
        self._store[key] = entry
        self._total_tokens += _estimate_tokens(content)
        self._touch_lru(key)
        if self._total_tokens > self._max_tokens:
            self._evict_lru()
        logger.debug(
            "working_memory_store key=%s tokens=%d/%d", key, self._total_tokens, self._max_tokens
        )
        return entry

    def retrieve(self, key: str) -> MemoryEntry | None:
        """检索一条工作记忆"""
        if key in self._store:
            entry = self._store[key]
            if entry.is_expired():
                self.delete(key)
                return None
            self._touch_lru(key)
            return entry
        return None

    def get_context(self) -> str:
        """获取当前工作上下文"""
        parts: list[str] = []
        for key in self._store:
            entry = self._store[key]
            if not entry.is_expired():
                parts.append(f"[{key}] {entry.content}")
        return "\n".join(parts)

    def get_all_entries(self) -> list[MemoryEntry]:
        """获取所有活跃记忆条目"""
        return [e for e in self._store.values() if not e.is_expired()]

    def delete(self, key: str) -> bool:
        """删除一条工作记忆"""
        if key in self._store:
            self._total_tokens -= _estimate_tokens(self._store[key].content)
            del self._store[key]
            self._lru.pop(key, None)
            return True
        return False

    def clear(self) -> None:
        """清空所有工作记忆"""
        self._store.clear()
        self._lru.clear()
        self._total_tokens = 0

    async def summarize(self, llm_provider=None) -> str:
        """压缩当前工作记忆为摘要"""
        entries = self.get_all_entries()
        if not entries:
            return ""
        pending_tasks = [e for e in entries if "task" in e.key.lower() or "todo" in e.key.lower()]
        open_files = [e for e in entries if "file" in e.key.lower()]
        current = [
            e for e in entries if "current" in e.key.lower() or "conversation" in e.key.lower()
        ]
        parts: list[str] = []
        if current:
            parts.append(f"当前对话: {'; '.join(e.content[:100] for e in current)}")
        if pending_tasks:
            parts.append(f"待办任务: {'; '.join(e.content[:100] for e in pending_tasks)}")
        if open_files:
            parts.append(f"打开文件: {'; '.join(e.content[:100] for e in open_files)}")
        if llm_provider:
            try:
                prompt = (
                    "请用 1-2 句话总结以下工作上下文:\n\n"
                    + "\n".join(f"[{e.key}] {e.content[:200]}" for e in entries)
                    + "\n\n摘要:"
                )
                resp = await llm_provider.generate(prompt, max_tokens=150)
                return resp.content.strip()
            except (OSError, RuntimeError, ValueError, AttributeError) as e:
                logger.debug("working_memory_summarize_failed: %s", e)
        return " | ".join(parts) if parts else "无活跃上下文"

    def _touch_lru(self, key: str) -> None:
        self._lru.pop(key, None)
        self._lru[key] = None

    def _evict_lru(self) -> None:
        while self._total_tokens > self._max_tokens and self._lru:
            oldest_key, _ = self._lru.popitem(last=False)
            if oldest_key in self._store:
                self._total_tokens -= _estimate_tokens(self._store[oldest_key].content)
                del self._store[oldest_key]
                logger.debug(
                    "working_memory_evict key=%s remaining_tokens=%d",
                    oldest_key,
                    self._total_tokens,
                )

    @property
    def token_count(self) -> int:
        return self._total_tokens

    @property
    def entry_count(self) -> int:
        return len(self._store)
