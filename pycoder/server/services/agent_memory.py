"""Agent 记忆系统 — 摘要压缩 + 关键事实提取

解决长对话的上下文膨胀问题：
  - 滑窗截断会丢失早期重要信息（文件路径、决策、错误模式）
  - 全量保留导致 prompt 膨胀、token 成本上升、注意力分散

策略（基于规则，不调用 LLM，零延迟零成本）：
  1. MessageSummarizer — 旧消息压缩为结构化摘要
  2. FactExtractor — 提取代码引用、决策点、错误模式
  3. MemoryStore — 持久化关键事实到 SQLite（按会话隔离）

集成点:
  - ChatBridge._get_effective_messages() — 超阈值时压缩旧消息
  - ReActLoop._build_prompt() — 注入关键事实到初始上下文
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class Fact:
    """关键事实"""

    type: str  # file_ref | decision | error_pattern | user_intent
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class Summary:
    """消息摘要"""

    text: str
    original_count: int
    summarized_count: int
    created_at: float = field(default_factory=time.time)


# ══════════════════════════════════════════════════════════
# 关键事实提取
# ══════════════════════════════════════════════════════════

# 文件路径：匹配 `path/to/file.ext` 或 "src/module.py" 等
_FILE_PATH_PATTERN = re.compile(
    r"[a-zA-Z0-9_\-./\\]+\.(?:py|js|ts|tsx|jsx|java|go|rs|c|cpp|h|hpp|cs|rb|php|swift|kt|md|json|yaml|yml|toml|cfg|ini|sh|bat|sql)",
    re.IGNORECASE,
)

# 代码块：```lang ... ```
_CODE_BLOCK_PATTERN = re.compile(r"```[\w]*\n(.*?)```", re.DOTALL)

# 决策关键词
_DECISION_KEYWORDS = [
    "决定",
    "选择",
    "采用",
    "方案",
    "策略",
    "重构",
    "迁移",
    "修复",
    "实现",
    "删除",
    "添加",
    "改为",
    "替换",
]

# 错误关键词
_ERROR_KEYWORDS = [
    "错误",
    "失败",
    "异常",
    "崩溃",
    "报错",
    "问题",
    "Error:",
    "Failed:",
    "Exception:",
    "Traceback",
]


class FactExtractor:
    """从消息中提取关键事实（基于规则，零延迟）"""

    def extract(self, messages: list[dict]) -> list[Fact]:
        """从消息列表提取关键事实"""
        facts: list[Fact] = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                continue
            role = msg.get("role", "")
            facts.extend(self._extract_file_refs(content, role))
            facts.extend(self._extract_decisions(content, role))
            facts.extend(self._extract_errors(content, role))
        return self._dedup(facts)

    def _extract_file_refs(self, content: str, role: str) -> list[Fact]:
        """提取文件路径引用"""
        facts: list[Fact] = []
        seen: set[str] = set()
        for m in _FILE_PATH_PATTERN.finditer(content):
            path = m.group(0).strip(".\"'` ")
            if len(path) < 3 or path in seen:
                continue
            # 过滤误匹配（如 "0.5" "v1.0"）
            if not re.search(r"[\\/]", path) and "." not in path:
                continue
            seen.add(path)
            facts.append(
                Fact(
                    type="file_ref",
                    content=path,
                    metadata={"role": role},
                )
            )
        return facts

    def _extract_decisions(self, content: str, role: str) -> list[Fact]:
        """提取决策点（基于关键词的句子级匹配）"""
        facts: list[Fact] = []
        # 按句切分
        sentences = re.split(r"[。.!！?\n]", content)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 5 or len(sentence) > 200:
                continue
            if any(kw in sentence for kw in _DECISION_KEYWORDS):
                facts.append(
                    Fact(
                        type="decision",
                        content=sentence,
                        metadata={"role": role},
                    )
                )
        return facts

    def _extract_errors(self, content: str, role: str) -> list[Fact]:
        """提取错误模式"""
        facts: list[Fact] = []
        sentences = re.split(r"[。.!！?\n]", content)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 5 or len(sentence) > 300:
                continue
            if any(kw in sentence for kw in _ERROR_KEYWORDS):
                facts.append(
                    Fact(
                        type="error_pattern",
                        content=sentence,
                        metadata={"role": role},
                    )
                )
        return facts

    def _dedup(self, facts: list[Fact]) -> list[Fact]:
        """去重（保留首次出现）"""
        seen: set[tuple[str, str]] = set()
        unique: list[Fact] = []
        for f in facts:
            key = (f.type, f.content[:100])
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique


# ══════════════════════════════════════════════════════════
# 消息摘要器
# ══════════════════════════════════════════════════════════

# 每条消息摘要的最大长度
_PER_MESSAGE_SUMMARY_LEN = 100
# 摘要总长度上限
_SUMMARY_MAX_LEN = 1500


class MessageSummarizer:
    """将旧消息列表压缩为结构化摘要（基于规则）"""

    def __init__(self, fact_extractor: FactExtractor | None = None):
        self._fact_extractor = fact_extractor or FactExtractor()

    def summarize(self, messages: list[dict]) -> Summary:
        """生成摘要

        策略:
        - 提取关键事实（文件引用、决策、错误）
        - 每条消息取首句作为简要描述
        - 按角色分组呈现
        """
        if not messages:
            return Summary(text="", original_count=0, summarized_count=0)

        # 提取关键事实
        facts = self._fact_extractor.extract(messages)

        lines: list[str] = []
        # 1. 关键事实部分
        if facts:
            lines.append("## 关键事实")
            file_refs = [f.content for f in facts if f.type == "file_ref"]
            decisions = [f.content for f in facts if f.type == "decision"]
            errors = [f.content for f in facts if f.type == "error_pattern"]

            if file_refs:
                unique_files = list(dict.fromkeys(file_refs))[:10]
                lines.append(f"- 涉及文件: {', '.join(unique_files)}")
            if decisions:
                lines.append("- 关键决策:")
                for d in decisions[:5]:
                    lines.append(f"  · {self._truncate(d, _PER_MESSAGE_SUMMARY_LEN)}")
            if errors:
                lines.append("- 错误模式:")
                for e in errors[:3]:
                    lines.append(f"  · {self._truncate(e, _PER_MESSAGE_SUMMARY_LEN)}")

        # 2. 消息摘要部分（按角色分组）
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        if user_msgs and len(messages) > 4:
            lines.append("\n## 用户消息摘要")
            for m in user_msgs[-3:]:  # 最后 3 条
                content = m.get("content", "")
                lines.append(f"- {self._truncate(content, _PER_MESSAGE_SUMMARY_LEN)}")

        if assistant_msgs and len(messages) > 4:
            lines.append("\n## 助手消息摘要")
            for m in assistant_msgs[-3:]:  # 最后 3 条
                content = m.get("content", "")
                lines.append(f"- {self._truncate(content, _PER_MESSAGE_SUMMARY_LEN)}")

        text = "\n".join(lines)
        # 全局截断
        if len(text) > _SUMMARY_MAX_LEN:
            text = text[:_SUMMARY_MAX_LEN] + "...[截断]"

        return Summary(
            text=text,
            original_count=len(messages),
            summarized_count=min(
                len([f for f in facts if f.type == "file_ref"])
                + len(user_msgs[-3:])
                + len(assistant_msgs[-3:]),
                len(messages),
            ),
        )

    def _truncate(self, text: str, max_len: int) -> str:
        """截断文本到指定长度"""
        text = text.strip().replace("\n", " ")
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."


# ══════════════════════════════════════════════════════════
# 记忆存储（SQLite 持久化）
# ══════════════════════════════════════════════════════════

# 复用 session_store 的 SQLite 数据库
_MEMORY_DB_PATH = Path.home() / ".pycoder" / "memory.db"

# 单会话最大持久化事实数
_MAX_FACTS_PER_SESSION = 50


class MemoryStore:
    """会话级记忆持久化"""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _MEMORY_DB_PATH
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    UNIQUE(session_id, fact_type, content)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_session
                ON session_memories(session_id, created_at)
            """)

    def save_facts(self, session_id: str, facts: list[Fact]) -> int:
        """保存关键事实到会话"""
        if not facts:
            return 0
        saved = 0
        with sqlite3.connect(str(self._db_path)) as conn:
            for f in facts:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO session_memories "
                        "(session_id, fact_type, content, metadata, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            session_id,
                            f.type,
                            f.content,
                            json.dumps(f.metadata, ensure_ascii=False),
                            f.timestamp,
                        ),
                    )
                    saved += conn.total_changes - saved
                except (sqlite3.Error, TypeError, ValueError) as e:
                    logger.debug("memory_save_failed type=%s error=%s", f.type, e)
        # 清理过期事实（保留最新 N 条）
        self._enforce_limit(session_id)
        return saved

    def load_facts(
        self,
        session_id: str,
        fact_type: str | None = None,
    ) -> list[Fact]:
        """加载会话的关键事实"""
        query = (
            "SELECT fact_type, content, metadata, created_at "
            "FROM session_memories WHERE session_id = ?"
        )
        params: list[Any] = [session_id]
        if fact_type:
            query += " AND fact_type = ?"
            params.append(fact_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(_MAX_FACTS_PER_SESSION)

        facts: list[Fact] = []
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                rows = conn.execute(query, params).fetchall()
            for row in rows:
                metadata = {}
                if row[2]:
                    try:
                        metadata = json.loads(row[2])
                    except (json.JSONDecodeError, TypeError):
                        pass
                facts.append(
                    Fact(
                        type=row[0],
                        content=row[1],
                        timestamp=row[3],
                        metadata=metadata,
                    )
                )
        except (sqlite3.Error, OSError) as e:
            logger.warning("memory_load_failed session=%s error=%s", session_id, e)
        return facts

    def clear_session(self, session_id: str) -> int:
        """清除会话的所有记忆"""
        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM session_memories WHERE session_id = ?",
                (session_id,),
            )
            return cursor.rowcount

    def _enforce_limit(self, session_id: str):
        """限制单会话事实数（保留最新 N 条）"""
        with sqlite3.connect(str(self._db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM session_memories WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            if count > _MAX_FACTS_PER_SESSION:
                excess = count - _MAX_FACTS_PER_SESSION
                conn.execute(
                    "DELETE FROM session_memories WHERE id IN ("
                    "  SELECT id FROM session_memories WHERE session_id = ? "
                    "  ORDER BY created_at ASC LIMIT ?"
                    ")",
                    (session_id, excess),
                )


# ══════════════════════════════════════════════════════════
# 统一记忆管理器
# ══════════════════════════════════════════════════════════

# 触发摘要的消息数阈值
_SUMMARY_THRESHOLD = 10


class AgentMemoryManager:
    """统一记忆管理 — 协调摘要、事实提取、持久化

    使用方式:
        manager = AgentMemoryManager()
        # 压缩旧消息
        summary = manager.compress_history(old_messages)
        # 提取并持久化事实
        manager.persist_facts(session_id, messages)
        # 加载历史事实构建上下文
        context = manager.build_fact_context(session_id)
    """

    def __init__(
        self,
        summarizer: MessageSummarizer | None = None,
        fact_extractor: FactExtractor | None = None,
        store: MemoryStore | None = None,
    ):
        self.summarizer = summarizer or MessageSummarizer()
        self.fact_extractor = fact_extractor or FactExtractor()
        self.store = store or MemoryStore()
        # 缓存：session_id -> 摘要文本（避免重复压缩）
        self._summary_cache: dict[str, str] = {}

    def compress_history(self, messages: list[dict]) -> str:
        """压缩历史消息为摘要文本

        当消息数超过阈值时触发压缩；否则返回空串。
        """
        if len(messages) < _SUMMARY_THRESHOLD:
            return ""
        summary = self.summarizer.summarize(messages)
        if not summary.text:
            return ""
        return f"[历史摘要]\n{summary.text}\n[/历史摘要]"

    def persist_facts(self, session_id: str, messages: list[dict]) -> int:
        """从消息中提取并持久化关键事实"""
        if not session_id or not messages:
            return 0
        facts = self.fact_extractor.extract(messages)
        if not facts:
            return 0
        return self.store.save_facts(session_id, facts)

    def build_fact_context(self, session_id: str) -> str:
        """构建关键事实上下文（注入到 system prompt 或初始上下文）"""
        if not session_id:
            return ""
        # 缓存命中
        if session_id in self._summary_cache:
            return self._summary_cache[session_id]

        facts = self.store.load_facts(session_id)
        if not facts:
            return ""

        lines: list[str] = ["[关键事实]"]
        file_refs = [f.content for f in facts if f.type == "file_ref"]
        decisions = [f.content for f in facts if f.type == "decision"]
        errors = [f.content for f in facts if f.type == "error_pattern"]

        if file_refs:
            unique_files = list(dict.fromkeys(file_refs))[:8]
            lines.append(f"涉及文件: {', '.join(unique_files)}")
        if decisions:
            lines.append("历史决策:")
            for d in decisions[:3]:
                lines.append(f"  · {d[:100]}")
        if errors:
            lines.append("已知问题:")
            for e in errors[:2]:
                lines.append(f"  · {e[:100]}")

        if len(lines) == 1:
            return ""

        context = "\n".join(lines) + "\n[/关键事实]"
        # 缓存（5 分钟有效期由调用方控制重建）
        self._summary_cache[session_id] = context
        return context

    def invalidate_cache(self, session_id: str | None = None):
        """清除缓存（会话切换或新消息到达时调用）"""
        if session_id:
            self._summary_cache.pop(session_id, None)
        else:
            self._summary_cache.clear()


# 模块级单例（按需懒加载）
_manager_instance: AgentMemoryManager | None = None


def get_memory_manager() -> AgentMemoryManager:
    """获取全局 AgentMemoryManager 单例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AgentMemoryManager()
    return _manager_instance


__all__ = [
    "Fact",
    "Summary",
    "FactExtractor",
    "MessageSummarizer",
    "MemoryStore",
    "AgentMemoryManager",
    "get_memory_manager",
]
