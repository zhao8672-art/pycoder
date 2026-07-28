"""关键决策点快照 — 长对话回顾能力

功能:
  1. 每次重大修改后自动记录变更摘要 (文件、修改内容、原因)
  2. 支持上下文回顾，生成摘要文本
  3. 追踪受影响的文件列表

使用场景:
    mgr = DecisionSnapshotManager()
    mgr.record("src/app.py", "modify", "修复超时问题", "用户反馈请求超时")
    summary = mgr.get_context_summary()  # 生成上下文摘要
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DecisionSnapshot:
    """决策快照"""

    timestamp: float = 0.0
    file_path: str = ""
    change_type: str = ""  # create | modify | delete | refactor
    description: str = ""
    reason: str = ""
    diff_stats: dict[str, int] = field(default_factory=dict)  # {added, removed, modified}

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "time_str": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "file_path": self.file_path,
            "change_type": self.change_type,
            "description": self.description,
            "reason": self.reason,
            "diff_stats": self.diff_stats,
        }


class DecisionSnapshotManager:
    """决策快照管理器"""

    MAX_SNAPSHOTS = 100  # 最大快照数量
    SUMMARY_THRESHOLD = 10  # 超过此轮次时生成摘要

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id
        self._snapshots: list[DecisionSnapshot] = []
        self._turn_count = 0

    def record(
        self,
        file_path: str,
        change_type: str,
        description: str,
        reason: str = "",
        diff_stats: dict[str, int] | None = None,
    ) -> DecisionSnapshot:
        """记录决策快照

        Args:
            file_path: 修改的文件路径
            change_type: 修改类型 (create/modify/delete/refactor)
            description: 简短描述
            reason: 修改原因
            diff_stats: 差异统计 {added, removed, modified}

        Returns:
            创建的 DecisionSnapshot
        """
        snapshot = DecisionSnapshot(
            timestamp=time.time(),
            file_path=file_path,
            change_type=change_type,
            description=description,
            reason=reason,
            diff_stats=diff_stats or {},
        )
        self._snapshots.append(snapshot)

        # 限制快照数量
        if len(self._snapshots) > self.MAX_SNAPSHOTS:
            self._snapshots = self._snapshots[-self.MAX_SNAPSHOTS:]

        return snapshot

    def increment_turn(self) -> None:
        """增加对话轮次"""
        self._turn_count += 1

    def get_recent(self, n: int = 5) -> list[DecisionSnapshot]:
        """获取最近的 N 条快照"""
        return self._snapshots[-n:] if self._snapshots else []

    def get_context_summary(self) -> str:
        """生成上下文摘要文本

        当对话超过阈值轮次时，生成摘要供用户确认

        Returns:
            摘要文本 (如果不需要摘要则返回空字符串)
        """
        if self._turn_count < self.SUMMARY_THRESHOLD or not self._snapshots:
            return ""

        recent = self.get_recent(10)
        lines = [
            f"📋 **当前上下文摘要** (共 {self._turn_count} 轮对话, {len(self._snapshots)} 个变更):",
            "",
        ]

        # 按文件分组
        file_changes: dict[str, list[DecisionSnapshot]] = {}
        for snap in recent:
            file_changes.setdefault(snap.file_path, []).append(snap)

        for file_path, snaps in file_changes.items():
            changes = ", ".join(f"{s.change_type}: {s.description}" for s in snaps)
            lines.append(f"  • `{file_path}` — {changes}")

        # 受影响文件列表
        affected = self.get_affected_files()
        if len(affected) > 5:
            lines.append(f"\n  共影响 {len(affected)} 个文件")

        return "\n".join(lines)

    def get_affected_files(self) -> set[str]:
        """获取所有受影响的文件"""
        return {s.file_path for s in self._snapshots if s.file_path}

    def get_by_file(self, file_path: str) -> list[DecisionSnapshot]:
        """获取指定文件的变更历史"""
        return [s for s in self._snapshots if s.file_path == file_path]

    def clear(self) -> None:
        """清空快照"""
        self._snapshots.clear()
        self._turn_count = 0

    def persist(self, session_id: str, storage_dir: str | Path | None = None) -> None:
        """持久化到 JSON 文件"""
        if not storage_dir:
            storage_dir = Path.home() / ".pycoder" / "snapshots"
        storage_dir = Path(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)

        filepath = storage_dir / f"snapshots_{session_id}.json"
        data = {
            "session_id": session_id,
            "turn_count": self._turn_count,
            "snapshots": [s.to_dict() for s in self._snapshots],
        }
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str, storage_dir: str | Path | None = None) -> None:
        """从 JSON 文件加载"""
        if not storage_dir:
            storage_dir = Path.home() / ".pycoder" / "snapshots"
        filepath = Path(storage_dir) / f"snapshots_{session_id}.json"

        if not filepath.exists():
            return

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            self._session_id = data.get("session_id", session_id)
            self._turn_count = data.get("turn_count", 0)
            self._snapshots = [
                DecisionSnapshot(
                    timestamp=s.get("timestamp", 0.0),
                    file_path=s.get("file_path", ""),
                    change_type=s.get("change_type", ""),
                    description=s.get("description", ""),
                    reason=s.get("reason", ""),
                    diff_stats=s.get("diff_stats", {}),
                )
                for s in data.get("snapshots", [])
            ]
        except (json.JSONDecodeError, KeyError):
            pass

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)
