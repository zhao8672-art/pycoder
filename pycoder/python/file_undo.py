"""
文件操作撤销引擎 — diff 预览 + 操作记录 + 逐级回滚
"""

from __future__ import annotations

import difflib
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileSnapshot:
    """文件快照"""

    file_path: str
    content: str
    timestamp: float = field(default_factory=time.time)
    operation: str = ""


class FileUndoManager:
    """文件操作记录与回滚管理器"""

    def __init__(self):
        self._history: dict[str, list[FileSnapshot]] = {}
        self._max_snapshots = 50
        self._storage = Path.home() / ".pycoder" / "file_snapshots.json"

    def preview_diff(self, file_path: str, new_content: str) -> dict:
        """预览文件变更 diff"""
        path = Path(file_path)
        if path.exists():
            old = path.read_text(encoding="utf-8", errors="replace")
        else:
            old = ""

        diff_lines = list(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=file_path,
                tofile=f"{file_path} (new)",
                lineterm="",
            )
        )

        return {
            "file": file_path,
            "added": sum(
                1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
            ),
            "removed": sum(
                1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
            ),
            "diff": "".join(diff_lines)[:5000],
            "truncated": sum(len(line) for line in diff_lines) > 5000,
        }

    def snapshot(self, file_path: str, operation: str = "save"):
        """创建文件快照"""
        path = Path(file_path)
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8", errors="replace")
        snap = FileSnapshot(
            file_path=file_path,
            content=content,
            operation=operation,
        )
        history = self._history.setdefault(file_path, [])
        history.append(snap)
        if len(history) > self._max_snapshots:
            history.pop(0)

    def undo(self, file_path: str, steps: int = 1) -> dict:
        """撤销最近的修改"""
        history = self._history.get(file_path, [])
        if len(history) < steps:
            return {"success": False, "error": f"只有 {len(history)} 个快照"}

        target = history[-steps]
        path = Path(file_path)
        path.write_text(target.content, encoding="utf-8")

        # 移除已回滚的快照
        for _ in range(steps):
            history.pop()

        return {
            "success": True,
            "file": file_path,
            "restored_to": target.operation,
            "remaining_snapshots": len(history),
        }

    def history(self, file_path: str) -> list[dict]:
        """获取文件变更历史"""
        history = self._history.get(file_path, [])
        return [{"operation": s.operation, "timestamp": s.timestamp} for s in history[-20:]]

    def diff_history(self, file_path: str, step: int = 1) -> dict:
        """查看历史版本与当前版本的 diff"""
        history = self._history.get(file_path, [])
        if not history or step > len(history):
            return {"diff": "", "file": file_path}

        old = history[-step].content
        path = Path(file_path)
        current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile=f"{file_path} (version -{step})",
                tofile=f"{file_path} (current)",
                lineterm="",
            )
        )[:5000]

        return {"file": file_path, "diff": diff}


_undo_manager: FileUndoManager | None = None


def get_undo_manager() -> FileUndoManager:
    global _undo_manager
    if _undo_manager is None:
        _undo_manager = FileUndoManager()
    return _undo_manager
