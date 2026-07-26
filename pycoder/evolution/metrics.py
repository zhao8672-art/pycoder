"""
进化指标 — 进化效果评估与趋势分析

指标:
  - 成功率: 进化修复的成功率
  - 覆盖率: 被进化处理的代码比例
  - 回归率: 修复引入新问题的比例
  - 效率: 平均每次进化的耗时
  - 成本: Token 消耗和 API 费用
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from pycoder.evolution.models import EvolutionTask

logger = logging.getLogger(__name__)

# 进化数据库目录
EVOLUTION_DB_DIR = Path.home() / ".pycoder" / "evolution"


class EvolutionMetrics:
    """进化效果评估器 — 跟踪和评估进化效果

    指标:
      - 成功率: 进化修复的成功率
      - 覆盖率: 被进化处理的代码比例
      - 回归率: 修复引入新问题的比例
      - 效率: 平均每次进化的耗时
      - 成本: Token 消耗和 API 费用
    """

    def __init__(self):
        self._data: list[dict[str, Any]] = []
        self._load_data()

    def record(self, task: EvolutionTask) -> None:
        """记录一次进化指标"""
        entry = {
            "task_id": task.id,
            "task_type": task.task_type,
            "timestamp": task.completed_at,
            "duration_ms": task.duration_ms,
            "errors_collected": len(task.errors_collected),
            "applied": task.applied,
            "test_passed": task.test_passed,
            "grade": task.grade,
            "rollback": task.rollback_performed,
        }
        self._data.append(entry)
        if len(self._data) > 500:
            self._data = self._data[-500:]
        self._save_data()

    def get_summary(self) -> dict[str, Any]:
        """获取进化指标摘要"""
        if not self._data:
            return self._empty_summary()

        total = len(self._data)
        success = sum(1 for d in self._data if d["test_passed"])
        applied = sum(1 for d in self._data if d["applied"])
        rolled = sum(1 for d in self._data if d["rollback"])
        avg_grade = sum(d["grade"] for d in self._data) / total
        avg_duration = sum(d["duration_ms"] for d in self._data) / total

        # 最近 10 次趋势
        recent = self._data[-10:]
        recent_success = sum(1 for d in recent if d["test_passed"]) / max(len(recent), 1)

        return {
            "total_evolutions": total,
            "success_rate": round(success / total * 100, 1),
            "apply_rate": round(applied / total * 100, 1),
            "rollback_rate": round(rolled / total * 100, 1),
            "avg_grade": round(avg_grade, 1),
            "avg_duration_ms": round(avg_duration, 0),
            "recent_success_rate": round(recent_success * 100, 1),
            "trend": "improving" if recent_success > (success / total) else "declining",
        }

    def get_trend_data(self, days: int = 7) -> list[dict[str, Any]]:
        """获取按天聚合的趋势数据"""
        from collections import defaultdict

        now = time.time()
        day_data: dict[str, list[dict]] = defaultdict(list)

        for d in self._data:
            if now - d["timestamp"] > days * 86400:
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(d["timestamp"]))
            day_data[day].append(d)

        return [
            {
                "date": day,
                "count": len(entries),
                "success_rate": round(
                    sum(1 for e in entries if e["test_passed"]) / len(entries) * 100, 1
                ),
                "avg_grade": round(sum(e["grade"] for e in entries) / len(entries), 1),
            }
            for day, entries in sorted(day_data.items())
        ]

    def _empty_summary(self) -> dict[str, Any]:
        return {
            "total_evolutions": 0,
            "success_rate": 0.0,
            "apply_rate": 0.0,
            "rollback_rate": 0.0,
            "avg_grade": 0.0,
            "avg_duration_ms": 0.0,
            "recent_success_rate": 0.0,
            "trend": "no-data",
        }

    def _load_data(self) -> None:
        metrics_file = EVOLUTION_DB_DIR / "metrics.json"
        try:
            if metrics_file.exists():
                self._data = json.loads(metrics_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    def _save_data(self) -> None:
        EVOLUTION_DB_DIR.mkdir(parents=True, exist_ok=True)
        metrics_file = EVOLUTION_DB_DIR / "metrics.json"
        metrics_file.write_text(
            json.dumps(self._data[-500:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


__all__ = ["EvolutionMetrics"]
