"""进度追踪器 — 任务进度监控与剩余时间预估

维护任务进度快照历史，基于近期速率预估剩余时间。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ProgressSnapshot:
    """进度快照"""

    progress: float
    message: str
    timestamp: float = field(default_factory=time.time)


class ProgressTracker:
    """进度追踪器

    用法:
        tracker = ProgressTracker()
        tracker.record("task_1", 0.0, "开始")
        tracker.record("task_1", 0.5, "已完成一半")
        eta = tracker.estimate_remaining("task_1")
    """

    def __init__(self):
        self._snapshots: dict[str, list[ProgressSnapshot]] = {}

    def record(self, task_id: str, progress: float, message: str = ""):
        """记录进度快照"""
        if task_id not in self._snapshots:
            self._snapshots[task_id] = []
        self._snapshots[task_id].append(
            ProgressSnapshot(
                progress=progress,
                message=message,
            )
        )

    def estimate_remaining(self, task_id: str) -> float | None:
        """预估剩余时间（秒）

        基于最近两个快照之间的进度速率计算。
        返回 None 表示无法预估（快照不足或进度为 0）。
        """
        snaps = self._snapshots.get(task_id, [])
        if len(snaps) < 2:
            return None

        # 使用最近两个有效快照
        recent = snaps[-2:]
        progress_delta = recent[1].progress - recent[0].progress
        time_delta = recent[1].timestamp - recent[0].timestamp

        if progress_delta <= 0 or time_delta <= 0:
            return None

        rate = progress_delta / time_delta
        remaining_progress = 1.0 - recent[1].progress
        if remaining_progress <= 0:
            return 0.0
        return remaining_progress / rate

    def get_history(self, task_id: str) -> list[dict]:
        """获取进度历史"""
        return [
            {"progress": s.progress, "message": s.message, "timestamp": s.timestamp}
            for s in self._snapshots.get(task_id, [])
        ]

    def get_current(self, task_id: str) -> dict | None:
        """获取当前进度"""
        snaps = self._snapshots.get(task_id, [])
        if not snaps:
            return None
        s = snaps[-1]
        return {"progress": s.progress, "message": s.message, "timestamp": s.timestamp}

    def clear(self, task_id: str):
        """清除某任务的进度记录"""
        self._snapshots.pop(task_id, None)
