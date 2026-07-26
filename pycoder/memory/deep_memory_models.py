"""深度记忆数据模型 — 四级记忆系统的基础数据结构"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ── ChromaDB 可选导入 ──────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    _CHROMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]
    ChromaSettings = None  # type: ignore[assignment]
    _CHROMA_AVAILABLE = False


@dataclass
class MemoryEntry:
    """单条记忆条目"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    level: int = 0  # 1-4 记忆层级
    key: str = ""  # 记忆键名
    content: str = ""  # 记忆内容
    embedding: list[float] | None = None  # 向量嵌入（可选）
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl: float | None = None  # 过期时间（秒），None 表示永不过期

    def is_expired(self) -> bool:
        """检查记忆是否已过期"""
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl


@dataclass
class MemoryContext:
    """多级检索结果上下文"""

    entries: list[MemoryEntry] = field(default_factory=list)
    source_levels: list[int] = field(default_factory=list)  # 来源层级
    total_tokens: int = 0  # 估算总 Token 数
    query: str = ""
    retrieval_time_ms: float = 0.0


@dataclass
class MemoryStats:
    """记忆统计信息"""

    level_stats: dict[int, dict[str, int]] = field(default_factory=dict)
    total_entries: int = 0
    total_size_bytes: int = 0
    last_cleanup: str = ""
    chroma_available: bool = _CHROMA_AVAILABLE


def _estimate_tokens(text: str) -> int:
    """粗略估算文本的 Token 数量（按字符数 / 4 估算）"""
    return max(1, math.ceil(len(text) / 4))


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串"""
    return datetime.now(UTC).isoformat()
