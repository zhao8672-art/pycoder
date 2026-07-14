"""
持久化知识库 — 自学习系统的核心存储层

基于 SQLite 存储三类知识:
  1. 错误模式库 (error → fix 映射，含成功率统计)
  2. 修复历史 (每次修复的完整记录)
  3. 项目知识图谱 (模块依赖/API用法/常见模式)

集成点:
  - SelfEvolutionEngine._apply_fix() → 记录修复
  - SelfEvolutionEngine._run_tests() → 记录结果
  - AutonomousPipeline → 记录流水线产出

用法:
  from .knowledge_base import KnowledgeBase
  kb = KnowledgeBase()
  kb.record_fix(error_sig, fix_template, success=True)
  suggestions = kb.suggest_fix("NameError: name 'foo' is not defined")
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.unified_db import get_db_path

DB_DIR = get_db_path().parent
DB_PATH = get_db_path()


@dataclass
class ErrorPattern:
    """错误模式"""

    id: int = 0
    error_signature: str = ""  # 标准化错误签名
    error_type: str = ""  # 错误分类
    fix_template: str = ""  # 修复方案模板
    file_pattern: str = ""  # 涉及文件模式
    success_count: int = 0  # 成功次数
    fail_count: int = 0  # 失败次数
    last_seen: float = 0.0  # 最后出现时间
    created_at: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def confidence(self) -> float:
        """Wilson 置信区间下界 — 样本少时自动降权"""
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.0
        z = 1.96  # 95% 置信
        p = self.success_count / total
        numerator = (
            p + z * z / (2 * total) - z * ((p * (1 - p) + z * z / (4 * total)) / total) ** 0.5
        )
        return numerator / (1 + z * z / total)


@dataclass
class FixRecord:
    """修复记录"""

    id: int = 0
    task_id: str = ""
    error_signature: str = ""
    error_message: str = ""
    file_path: str = ""
    fix_content: str = ""
    outcome: str = ""  # success | failure | rolled_back
    test_result: str = ""
    quality_score: float = 0.0
    tokens_used: int = 0
    duration_ms: float = 0.0
    agent_role: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ProjectKnowledge:
    """项目结构知识"""

    entity: str  # 模块/类/函数路径
    entity_type: str  # module | class | function | api_endpoint
    dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    change_frequency: int = 0  # 被修改次数
    bug_frequency: int = 0  # 产生bug次数
    last_modified: float = 0.0
    metadata: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════
# SQL 表定义
# ══════════════════════════════════════════════════════════

SCHEMA = """
CREATE TABLE IF NOT EXISTS error_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_signature TEXT UNIQUE NOT NULL,
    error_type TEXT DEFAULT '',
    fix_template TEXT DEFAULT '',
    file_pattern TEXT DEFAULT '',
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    last_seen REAL DEFAULT 0,
    created_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fix_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT DEFAULT '',
    error_signature TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    fix_content TEXT DEFAULT '',
    outcome TEXT DEFAULT '',
    test_result TEXT DEFAULT '',
    quality_score REAL DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    duration_ms REAL DEFAULT 0,
    agent_role TEXT DEFAULT '',
    timestamp REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_knowledge (
    entity TEXT PRIMARY KEY,
    entity_type TEXT DEFAULT '',
    dependencies TEXT DEFAULT '[]',
    dependents TEXT DEFAULT '[]',
    change_frequency INTEGER DEFAULT 0,
    bug_frequency INTEGER DEFAULT 0,
    last_modified REAL DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_error_sig ON error_patterns(error_signature);
CREATE INDEX IF NOT EXISTS idx_error_type ON error_patterns(error_type);
CREATE INDEX IF NOT EXISTS idx_fix_outcome ON fix_history(outcome);
CREATE INDEX IF NOT EXISTS idx_fix_timestamp ON fix_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_fix_error_sig ON fix_history(error_signature);
"""


# ══════════════════════════════════════════════════════════
# 错误签名标准化
# ══════════════════════════════════════════════════════════


def normalize_error_signature(error_msg: str) -> str:
    """标准化错误消息为可比较的签名"""
    import re

    sig = error_msg.strip()
    # 先替换引号内的内容（最内层先执行）
    sig = re.sub(r"'[^']*'", "'<VALUE>'", sig)
    sig = re.sub(r'"[^"]*"', '"<VALUE>"', sig)
    # 再替换文件路径和行号
    sig = re.sub(r"File\s+<VALUE>,\s+line\s+<N>", "File <path>, line <N>", sig)
    sig = re.sub(r"\b0x[0-9a-fA-F]+\b", "<HEX>", sig)
    sig = re.sub(r"\b\d+\b", "<N>", sig)
    # 截断过长签名
    if len(sig) > 300:
        sig = sig[:300]
    return sig


def _first_exception_prefix(msg: str) -> str:
    """提取错误消息开头的标准异常类名"""
    import re

    m = re.match(r"(\w+(?:Error|Warning|Exception))\(?", msg)
    if m:
        return m.group(1)
    return ""


def classify_error(error_msg: str) -> str:
    """错误分类 - 优先匹配标准异常前缀，避免误判"""
    prefix = _first_exception_prefix(error_msg)
    if prefix:
        return prefix
    msg_lower = error_msg.lower()
    # 二次兜底匹配
    if "nameerror" in msg_lower or (
        "not defined" in msg_lower and "name" in error_msg[:80].lower()
    ):
        return "NameError"
    if "typeerror" in msg_lower:
        return "TypeError"
    if "attributeerror" in msg_lower or "has no attribute" in msg_lower:
        return "AttributeError"
    import_keys = ["importerror", "modulenotfound", "no module named"]
    if any(k in msg_lower for k in import_keys):
        return "ImportError"
    if "syntaxerror" in msg_lower or "indentationerror" in msg_lower:
        return "SyntaxError"
    if "keyerror" in msg_lower:
        return "KeyError"
    if "indexerror" in msg_lower or "list index" in msg_lower:
        return "IndexError"
    if "valueerror" in msg_lower:
        return "ValueError"
    if "filenotfound" in msg_lower or "no such file" in msg_lower:
        return "FileNotFoundError"
    if "connection" in msg_lower or "timeout" in msg_lower:
        return "ConnectionError"
    if "assertionerror" in msg_lower:
        return "AssertionError"
    if "permissionerror" in msg_lower:
        return "PermissionError"
    if "memoryerror" in msg_lower:
        return "MemoryError"
    return "Unknown"


# ══════════════════════════════════════════════════════════
# KnowledgeBase 核心类
# ══════════════════════════════════════════════════════════


class KnowledgeBase:
    """持久化知识库 — SQLite 存储 + 内存缓存"""

    def __init__(self, db_path: str | Path | None = None):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path or DB_PATH)
        self._init_db()
        # 内存缓存（热数据）
        self._error_cache: dict[str, ErrorPattern] = {}

    def _init_db(self) -> None:
        """初始化数据库"""
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── 错误模式管理 ───

    def record_error_pattern(
        self,
        error_msg: str,
        fix_template: str = "",
        file_path: str = "",
        success: bool = True,
    ) -> ErrorPattern:
        """记录或更新错误模式"""
        sig = normalize_error_signature(error_msg)
        err_type = classify_error(error_msg)
        now = time.time()

        sc_final = 1 if success else 0
        fc_final = 0 if success else 1
        fix_final = fix_template
        created_ts = now

        conn = self._get_conn()
        try:
            existing = conn.execute(
                "SELECT * FROM error_patterns WHERE error_signature = ?",
                (sig,),
            ).fetchone()

            if existing:
                sc = existing["success_count"]
                fc = existing["fail_count"]
                if success:
                    sc += 1
                else:
                    fc += 1
                # 使用最新成功的 fix_template
                old_fix = existing["fix_template"] or ""
                _use_new = success and fix_template and len(fix_template) > len(old_fix)
                chosen_fix = fix_template if _use_new else old_fix
                conn.execute(
                    """UPDATE error_patterns
                       SET error_type=?, fix_template=?, file_pattern=?,
                           success_count=?, fail_count=?, last_seen=?
                       WHERE error_signature=?""",
                    (err_type, chosen_fix, file_path, sc, fc, now, sig),
                )
                sc_final, fc_final = sc, fc
                fix_final = chosen_fix
                created_ts = existing["created_at"]
            else:
                conn.execute(
                    """INSERT INTO error_patterns
                       (error_signature, error_type, fix_template, file_pattern,
                        success_count, fail_count, last_seen, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sig, err_type, fix_template, file_path, sc_final, fc_final, now, now),
                )
            conn.commit()
        finally:
            conn.close()

        # 构建返回数据（不从已关闭连接读）
        pattern = ErrorPattern(
            error_signature=sig,
            error_type=err_type,
            fix_template=fix_final,
            file_pattern=file_path,
            success_count=sc_final,
            fail_count=fc_final,
            last_seen=now,
            created_at=created_ts,
        )
        self._error_cache[sig] = pattern
        return pattern

    def suggest_fix(self, error_msg: str, min_confidence: float = 0.3) -> ErrorPattern | None:
        """根据错误消息推荐修复方案"""
        sig = normalize_error_signature(error_msg)

        # 1. 精确匹配
        pattern = self._get_pattern(sig)
        if pattern and pattern.confidence >= min_confidence:
            return pattern

        # 2. 同类型错误中找相似
        err_type = classify_error(error_msg)
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM error_patterns
                   WHERE error_type = ? AND success_count > 0
                   ORDER BY success_count DESC LIMIT 5""",
                (err_type,),
            ).fetchall()
            for row in rows:
                p = self._row_to_pattern(row)
                if p.confidence >= min_confidence:
                    return p

        return None

    def get_top_errors(self, limit: int = 20) -> list[ErrorPattern]:
        """获取最常见错误"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM error_patterns
                   ORDER BY (success_count + fail_count) DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_pattern(r) for r in rows]

    def get_improving_errors(self) -> list[dict]:
        """获取成功率在提升的错误（最近5次比历史好）"""
        with self._get_conn() as conn:
            rows = conn.execute("""SELECT error_signature, error_type,
                          success_count, fail_count,
                          CAST(success_count AS REAL) /
                          (success_count + fail_count) AS rate
                   FROM error_patterns
                   WHERE success_count + fail_count >= 3
                   ORDER BY rate DESC LIMIT 10""").fetchall()
            return [dict(r) for r in rows]

    def _get_pattern(self, sig: str) -> ErrorPattern | None:
        """获取错误模式（先查缓存）"""
        if sig in self._error_cache:
            return self._error_cache[sig]
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM error_patterns WHERE error_signature = ?",
                (sig,),
            ).fetchone()
            if row:
                p = self._row_to_pattern(row)
                self._error_cache[sig] = p
                return p
        return None

    @staticmethod
    def _row_to_pattern(row) -> ErrorPattern:
        return ErrorPattern(
            id=row["id"],
            error_signature=row["error_signature"],
            error_type=row["error_type"],
            fix_template=row["fix_template"],
            file_pattern=row["file_pattern"],
            success_count=row["success_count"],
            fail_count=row["fail_count"],
            last_seen=row["last_seen"],
            created_at=row["created_at"],
        )

    # ─── 修复历史 ───

    def record_fix(
        self,
        task_id: str,
        error_msg: str,
        file_path: str,
        fix_content: str,
        outcome: str,
        test_result: str = "",
        quality_score: float = 0.0,
        tokens_used: int = 0,
        duration_ms: float = 0.0,
        agent_role: str = "",
    ) -> int:
        """记录一次修复"""
        sig = normalize_error_signature(error_msg)
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO fix_history
                   (task_id, error_signature, error_message, file_path,
                    fix_content, outcome, test_result, quality_score,
                    tokens_used, duration_ms, agent_role, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    sig,
                    error_msg[:500],
                    file_path,
                    fix_content[:2000],
                    outcome,
                    test_result[:500],
                    quality_score,
                    tokens_used,
                    duration_ms,
                    agent_role,
                    time.time(),
                ),
            )
            conn.commit()
            return cur.lastrowid or 0

    def get_fix_history(
        self,
        limit: int = 50,
        outcome: str = "",
    ) -> list[FixRecord]:
        """获取修复历史"""
        with self._get_conn() as conn:
            if outcome:
                rows = conn.execute(
                    """SELECT * FROM fix_history WHERE outcome = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (outcome, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM fix_history ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                FixRecord(
                    id=r["id"],
                    task_id=r["task_id"],
                    error_signature=r["error_signature"],
                    error_message=r["error_message"],
                    file_path=r["file_path"],
                    fix_content=r["fix_content"],
                    outcome=r["outcome"],
                    test_result=r["test_result"],
                    quality_score=r["quality_score"],
                    tokens_used=r["tokens_used"],
                    duration_ms=r["duration_ms"],
                    agent_role=r["agent_role"],
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    def get_success_rate(self, window_hours: int = 24) -> dict:
        """获取近期修复成功率"""
        cutoff = time.time() - window_hours * 3600
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM fix_history WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM fix_history WHERE timestamp > ? AND outcome = 'success'",
                (cutoff,),
            ).fetchone()[0]
        return {
            "total": total,
            "success": success,
            "rate": success / total if total > 0 else 0.0,
            "window_hours": window_hours,
        }

    # ─── 项目知识 ───

    def record_entity(
        self,
        entity: str,
        entity_type: str,
        deps: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """记录项目实体"""
        deps = deps or []
        meta = metadata or {}
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO project_knowledge
                   (entity, entity_type, dependencies, metadata, last_modified)
                   VALUES (?, ?, ?, ?, ?)""",
                (entity, entity_type, json.dumps(deps), json.dumps(meta), time.time()),
            )
            conn.commit()

    def increment_bug_count(self, entity: str) -> None:
        """增加实体的 bug 计数"""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE project_knowledge
                   SET bug_frequency = bug_frequency + 1,
                       change_frequency = change_frequency + 1
                   WHERE entity = ?""",
                (entity,),
            )
            conn.commit()

    def get_hotspots(self, limit: int = 10) -> list[dict]:
        """获取 bug 热点（高频出错模块）"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT entity, entity_type, bug_frequency, change_frequency
                   FROM project_knowledge
                   WHERE bug_frequency > 0
                   ORDER BY bug_frequency DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_entity_risk(self, entity: str) -> float:
        """计算实体风险评分 0-100"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT bug_frequency, change_frequency FROM project_knowledge WHERE entity = ?",
                (entity,),
            ).fetchone()
            if not row:
                return 0.0
            bug_ratio = row["bug_frequency"] / max(row["change_frequency"], 1)
            return min(100, bug_ratio * 100)

    # ─── TTL 清理（Bug #9） ───

    def cleanup_old_records(
        self,
        max_age_days: int = 90,
        max_records: int = 10000,
    ) -> dict:
        """清理过期记录，防无限膨胀"""
        cutoff = time.time() - max_age_days * 86400
        result: dict = {}
        with self._get_conn() as conn:
            deleted_fixes = conn.execute(
                "DELETE FROM fix_history WHERE timestamp < ?",
                (cutoff,),
            ).rowcount
            result["deleted_fixes"] = deleted_fixes
            total = conn.execute("SELECT COUNT(*) FROM fix_history").fetchone()[0]
            if total > max_records:
                delete_count = total - max_records
                conn.execute(
                    """DELETE FROM fix_history WHERE id IN (
                        SELECT id FROM fix_history
                        ORDER BY timestamp ASC LIMIT ?
                    )""",
                    (delete_count,),
                )
                result["capped_fixes"] = delete_count
            deleted_patterns = conn.execute(
                """DELETE FROM error_patterns
                   WHERE success_count + fail_count < 2
                   AND created_at < ?""",
                (cutoff,),
            ).rowcount
            result["deleted_patterns"] = deleted_patterns
            conn.commit()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("VACUUM")
                result["vacuumed"] = True
        except Exception:
            result["vacuumed"] = False
        return result

    # ─── 统计数据 ───

    def get_stats(self) -> dict:
        """获取知识库统计"""
        with self._get_conn() as conn:
            pattern_count = conn.execute("SELECT COUNT(*) FROM error_patterns").fetchone()[0]
            fix_count = conn.execute("SELECT COUNT(*) FROM fix_history").fetchone()[0]
            success_count = conn.execute(
                "SELECT COUNT(*) FROM fix_history WHERE outcome='success'"
            ).fetchone()[0]
            entity_count = conn.execute("SELECT COUNT(*) FROM project_knowledge").fetchone()[0]
            total_tokens = conn.execute(
                "SELECT COALESCE(SUM(tokens_used), 0) FROM fix_history"
            ).fetchone()[0]
            avg_quality = conn.execute(
                "SELECT COALESCE(AVG(quality_score), 0) FROM fix_history WHERE quality_score > 0"
            ).fetchone()[0]

        return {
            "error_patterns": pattern_count,
            "total_fixes": fix_count,
            "successful_fixes": success_count,
            "fix_success_rate": success_count / fix_count if fix_count > 0 else 0,
            "project_entities": entity_count,
            "total_tokens_spent": total_tokens,
            "avg_quality_score": round(avg_quality, 1),
        }


# 全局单例
_kb: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


__all__ = [
    "KnowledgeBase",
    "ErrorPattern",
    "FixRecord",
    "ProjectKnowledge",
    "normalize_error_signature",
    "classify_error",
    "get_knowledge_base",
    "DB_PATH",
    "DB_DIR",
]
