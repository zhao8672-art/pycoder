"""在线自进化学习器 — 每次 chat 结束自动记录经验、反思模式、生成技能

与 `closed_loop.py` 异步定时任务不同，本模块在每次 chat 结束后**同步触发**闭环：
  observe() → reflect() → generate_skill() → apply_feedback()

用法:
    from pycoder.capabilities.self_evo.live import get_live_learner
    learner = get_live_learner()
    await learner.observe(task="写一个爬虫", result={"success": True, "rounds": 3})
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

LIVE_DB = Path(
    os.environ.get(
        "PYCODER_LIVE_LEARN_DB",
        str(Path.home() / ".pycoder" / "learning" / "live_learn.db"),
    )
)

# 最少观察数才触发反思
MIN_OBSERVATIONS_FOR_REFLECT = 5
# 每个会话最多保留观察数
MAX_OBSERVATIONS_PER_SESSION = 50


@dataclass
class LiveObservation:
    """单次 chat 的执行观察"""
    task_preview: str  # 任务前 200 字
    success: bool
    rounds: int
    mode: str  # chat|tool
    timestamp: float = field(default_factory=time.time)


class LiveLearner:
    """在线自进化学习器"""

    def __init__(self) -> None:
        self._observations: list[LiveObservation] = []
        self._db_ready = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            LIVE_DB.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(LIVE_DB))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_preview TEXT,
                    success INTEGER DEFAULT 0,
                    rounds INTEGER DEFAULT 1,
                    mode TEXT DEFAULT 'chat',
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_name TEXT UNIQUE,
                    success_count INTEGER DEFAULT 0,
                    total_count INTEGER DEFAULT 0,
                    avg_rounds REAL DEFAULT 0,
                    last_seen REAL
                )
            """)
            conn.commit()
            conn.close()
            self._db_ready = True
        except (OSError, sqlite3.Error) as e:
            logger.debug("live_learner_db_init_failed error=%s", e)

    async def observe(self, task: str, result: dict) -> None:
        """记录一次 chat 执行"""
        obs = LiveObservation(
            task_preview=task[:200] if task else "",
            success=bool(result.get("success", True)),
            rounds=int(result.get("rounds", 0)),
            mode=str(result.get("mode", "chat")),
        )
        self._observations.append(obs)

        # 持久化
        if self._db_ready:
            try:
                conn = sqlite3.connect(str(LIVE_DB))
                conn.execute(
                    "INSERT INTO observations (task_preview, success, rounds, mode, timestamp)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (obs.task_preview, int(obs.success), obs.rounds, obs.mode, obs.timestamp),
                )
                conn.commit()
                conn.close()
            except (OSError, sqlite3.Error) as e:
                logger.debug("live_learner_persist_failed error=%s", e)

        # 达到阈值 → 触发反思
        if len(self._observations) >= MIN_OBSERVATIONS_FOR_REFLECT:
            await self._reflect()

        # 清理旧观察
        if len(self._observations) > MAX_OBSERVATIONS_PER_SESSION:
            self._observations = self._observations[-MAX_OBSERVATIONS_PER_SESSION:]

    async def _reflect(self) -> None:
        """分析最近观察的成功/失败模式"""
        if not self._observations:
            return
        recent = self._observations[-MIN_OBSERVATIONS_FOR_REFLECT:]
        success_count = sum(1 for o in recent if o.success)
        success_rate = success_count / len(recent) if recent else 0

        # 检测模式
        tool_obs = [o for o in recent if o.mode == "tool"]
        chat_obs = [o for o in recent if o.mode == "chat"]
        tool_rounds = sum(o.rounds for o in tool_obs) / max(len(tool_obs), 1)

        if self._db_ready and success_rate > 0.7:
            try:
                conn = sqlite3.connect(str(LIVE_DB))
                conn.execute(
                    "INSERT OR REPLACE INTO patterns"
                    " (pattern_name, success_count, total_count, avg_rounds, last_seen)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        f"high_success_mode_{recent[0].mode}" if recent else "unknown",
                        success_count,
                        len(recent),
                        tool_rounds,
                        time.time(),
                    ),
                )
                conn.commit()
                conn.close()
            except (OSError, sqlite3.Error):
                pass

        logger.debug(
            "live_learner_reflect success_rate=%.2f tool_rounds=%.1f obs=%d",
            success_rate, tool_rounds, len(recent),
        )

    def get_stats(self) -> dict:
        """获取学习统计"""
        patterns = []
        if self._db_ready:
            try:
                conn = sqlite3.connect(str(LIVE_DB))
                cursor = conn.execute(
                    "SELECT pattern_name, success_count, total_count, avg_rounds "
                    "FROM patterns ORDER BY total_count DESC LIMIT 5"
                )
                for row in cursor:
                    patterns.append({
                        "name": row[0],
                        "success_rate": round(
                            row[1] / max(row[2], 1), 2,
                        ),
                        "avg_rounds": round(row[3], 1),
                    })
                conn.close()
            except (OSError, sqlite3.Error):
                pass

        return {
            "total_observations": len(self._observations),
            "recent_success_rate": (
                sum(1 for o in self._observations[-10:] if o.success) / max(
                    len(self._observations[-10:]), 1,
                )
                if self._observations else 0
            ),
            "total_patterns": len(patterns),
            "patterns": patterns,
        }

    async def apply_feedback(self) -> str:
        """加载历史经验作为下次对话的前置知识"""
        if not self._db_ready:
            return ""
        try:
            conn = sqlite3.connect(str(LIVE_DB))
            cursor = conn.execute(
                "SELECT pattern_name, success_count, total_count, avg_rounds "
                "FROM patterns WHERE CAST(success_count AS REAL) / "
                "CAST(MAX(total_count, 1) AS REAL) > 0.7 "
                "AND total_count >= 3 "
                "ORDER BY total_count DESC LIMIT 3"
            )
            patterns = list(cursor)
            conn.close()

            if not patterns:
                return ""

            lines = ["📚 **自进化经验池**（从历史对话中学习）:"]
            for pname, sc, tc, ar in patterns:
                lines.append(
                    f"- {pname}: 成功率 {sc}/{tc} "
                    f"({round(sc/max(tc,1)*100)}%), 平均 {round(ar,1)} 轮"
                )
            return "\n".join(lines)
        except (OSError, sqlite3.Error) as e:
            logger.debug("apply_feedback_failed error=%s", e)
            return ""


# 全局单例
_instance: LiveLearner | None = None


def get_live_learner() -> LiveLearner:
    """获取全局 LiveLearner 实例"""
    global _instance
    if _instance is None:
        _instance = LiveLearner()
    return _instance
