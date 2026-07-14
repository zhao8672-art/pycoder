"""
指标追踪器 — 持久化进化统计、质量趋势、成功率时间线

持久化所有 EvolutionStats，支持:
  - 按时间窗口查询趋势
  - 代码质量评分变化曲线
  - 各类操作成功率对比
  - 生成学习报告

用法:
  from .metrics_tracker import MetricsTracker
  mt = MetricsTracker()
  mt.record_evolution(outcome="success", lines_changed=12, bugs_fixed=2)
  trends = mt.get_quality_trends(days=7)
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field

from pycoder.server.unified_db import get_db_path

DB_DIR = get_db_path().parent
METRICS_DB = get_db_path()


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class EvolutionRecord:
    """进化记录"""

    id: int = 0
    task_id: str = ""
    operation: str = ""  # scan | fix | test | rollback | upgrade
    outcome: str = ""  # success | failure | partial
    lines_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    bugs_found: int = 0
    bugs_fixed: int = 0
    test_passed: bool = False
    test_failures: int = 0
    quality_score: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    rollback_count: int = 0
    tags: str = ""  # JSON 数组
    timestamp: float = field(default_factory=time.time)


@dataclass
class QualitySnapshot:
    """质量快照"""

    timestamp: float = 0.0
    lint_score: float = 100.0
    security_score: float = 100.0
    complexity_score: float = 100.0
    test_coverage: float = 0.0
    total_score: float = 100.0
    file_count: int = 0
    issue_count: int = 0


SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT DEFAULT '',
    operation TEXT DEFAULT '',
    outcome TEXT DEFAULT '',
    lines_changed INTEGER DEFAULT 0,
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    bugs_found INTEGER DEFAULT 0,
    bugs_fixed INTEGER DEFAULT 0,
    test_passed INTEGER DEFAULT 0,
    test_failures INTEGER DEFAULT 0,
    quality_score REAL DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    rollback_count INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    timestamp REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quality_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL DEFAULT 0,
    lint_score REAL DEFAULT 100,
    security_score REAL DEFAULT 100,
    complexity_score REAL DEFAULT 100,
    test_coverage REAL DEFAULT 0,
    total_score REAL DEFAULT 100,
    file_count INTEGER DEFAULT 0,
    issue_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT DEFAULT '',
    description TEXT DEFAULT '',
    data TEXT DEFAULT '{}',
    timestamp REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_evo_timestamp ON evolution_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_evo_outcome ON evolution_records(outcome);
CREATE INDEX IF NOT EXISTS idx_quality_timestamp ON quality_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_learning_timestamp ON learning_events(timestamp);
"""


class MetricsTracker:
    """指标追踪器 — SQLite 持久化"""

    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(METRICS_DB)) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(METRICS_DB))
        conn.row_factory = sqlite3.Row
        return conn

    # ─── 进化记录 ───

    def record_evolution(
        self,
        task_id: str = "",
        operation: str = "fix",
        outcome: str = "success",
        lines_changed: int = 0,
        lines_added: int = 0,
        lines_removed: int = 0,
        bugs_found: int = 0,
        bugs_fixed: int = 0,
        test_passed: bool = False,
        test_failures: int = 0,
        quality_score: float = 0.0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
        rollback_count: int = 0,
        tags: list[str] | None = None,
    ) -> int:
        """记录一次进化操作"""
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO evolution_records
                   (task_id, operation, outcome, lines_changed, lines_added,
                    lines_removed, bugs_found, bugs_fixed, test_passed,
                    test_failures, quality_score, tokens_used, cost_usd,
                    duration_seconds, rollback_count, tags, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    operation,
                    outcome,
                    lines_changed,
                    lines_added,
                    lines_removed,
                    bugs_found,
                    bugs_fixed,
                    1 if test_passed else 0,
                    test_failures,
                    quality_score,
                    tokens_used,
                    cost_usd,
                    duration_seconds,
                    rollback_count,
                    json.dumps(tags or []),
                    time.time(),
                ),
            )
            conn.commit()
            return cur.lastrowid or 0

    def record_quality_snapshot(
        self,
        lint_score: float = 100,
        security_score: float = 100,
        complexity_score: float = 100,
        test_coverage: float = 0,
        total_score: float = 100,
        file_count: int = 0,
        issue_count: int = 0,
    ) -> None:
        """记录质量快照"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO quality_snapshots
                   (timestamp, lint_score, security_score, complexity_score,
                    test_coverage, total_score, file_count, issue_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    lint_score,
                    security_score,
                    complexity_score,
                    test_coverage,
                    total_score,
                    file_count,
                    issue_count,
                ),
            )
            conn.commit()

    def record_learning_event(
        self,
        event_type: str,
        description: str = "",
        data: dict | None = None,
    ) -> None:
        """记录学习事件（模式发现、知识更新等）"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO learning_events
                   (event_type, description, data, timestamp)
                   VALUES (?,?,?,?)""",
                (event_type, description, json.dumps(data or {}), time.time()),
            )
            conn.commit()

    # ─── 查询趋势 ───

    def get_evolution_stats(self, days: int = 30) -> dict:
        """获取进化统计"""
        cutoff = time.time() - days * 86400
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM evolution_records WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM evolution_records WHERE timestamp > ? AND outcome='success'",
                (cutoff,),
            ).fetchone()[0]
            lines = conn.execute(
                "SELECT COALESCE(SUM(lines_changed), 0) FROM evolution_records WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            bugs = conn.execute(
                "SELECT COALESCE(SUM(bugs_fixed), 0) FROM evolution_records WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            tokens = conn.execute(
                "SELECT COALESCE(SUM(tokens_used), 0) FROM evolution_records WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            cost = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM evolution_records WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            rollbacks = conn.execute(
                """SELECT COUNT(*) FROM evolution_records
                   WHERE timestamp > ? AND operation='rollback'""",
                (cutoff,),
            ).fetchone()[0]

        return {
            "total_evolutions": total,
            "successful": success,
            "success_rate": success / total if total > 0 else 0,
            "total_lines_changed": lines,
            "total_bugs_fixed": bugs,
            "total_tokens": tokens,
            "total_cost_usd": round(cost, 4),
            "rollbacks": rollbacks,
            "days": days,
        }

    def get_quality_trends(self, days: int = 14) -> list[dict]:
        """获取质量趋势（按天聚合）"""
        cutoff = time.time() - days * 86400
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT
                     DATE(timestamp, 'unixepoch', 'localtime') AS day,
                     AVG(total_score) AS avg_score,
                     AVG(test_coverage) AS avg_coverage,
                     COUNT(*) AS snapshots,
                     SUM(issue_count) AS total_issues
                   FROM quality_snapshots
                   WHERE timestamp > ?
                   GROUP BY day
                   ORDER BY day""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_operation_breakdown(self) -> dict:
        """获取各类操作的成功率分布"""
        with self._get_conn() as conn:
            rows = conn.execute("""SELECT operation, outcome, COUNT(*) AS cnt
                   FROM evolution_records
                   GROUP BY operation, outcome""").fetchall()

        breakdown: dict[str, dict] = {}
        for r in rows:
            op = r["operation"]
            if op not in breakdown:
                breakdown[op] = {"total": 0, "success": 0, "failure": 0}
            breakdown[op]["total"] += r["cnt"]
            if r["outcome"] == "success":
                breakdown[op]["success"] += r["cnt"]
            else:
                breakdown[op]["failure"] += r["cnt"]

        for op in breakdown:
            t = breakdown[op]["total"]
            breakdown[op]["rate"] = breakdown[op]["success"] / t if t > 0 else 0

        return breakdown

    def get_daily_summary(self, days: int = 7) -> list[dict]:
        """每日汇总"""
        cutoff = time.time() - days * 86400
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT
                     DATE(timestamp, 'unixepoch', 'localtime') AS day,
                     COUNT(*) AS evolutions,
                     SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successes,
                     COALESCE(SUM(lines_changed), 0) AS lines,
                     COALESCE(SUM(tokens_used), 0) AS tokens,
                     COALESCE(SUM(cost_usd), 0) AS cost
                   FROM evolution_records
                   WHERE timestamp > ?
                   GROUP BY day
                   ORDER BY day""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_learning_events(self, limit: int = 50) -> list[dict]:
        """获取最近的学习事件"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM learning_events
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# 全局单例
_tracker: MetricsTracker | None = None


def get_metrics_tracker() -> MetricsTracker:
    global _tracker
    if _tracker is None:
        _tracker = MetricsTracker()
    return _tracker


__all__ = [
    "MetricsTracker",
    "EvolutionRecord",
    "QualitySnapshot",
    "get_metrics_tracker",
    "METRICS_DB",
    "DB_DIR",
]
