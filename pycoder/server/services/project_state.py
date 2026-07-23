"""
ProjectState — 项目状态追踪器

追踪 AI 执行过程中的文件变更、待办事项、阶段进度。
解决"AI 创建了文件但不知道刚才做了什么"的核心问题。

用法:
    from pycoder.server.services.project_state import ProjectState
    ps = ProjectState()
    ps.record_file_created("app/main.py")
    ps.record_file_modified("README.md")
    prompt = ps.inject_to_prompt()  # → 注入到 System Prompt
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ProjectPhase:
    """项目阶段"""
    name: str = ""
    files: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | in_progress | done
    started_at: float = 0
    completed_at: float = 0


class ProjectState:
    """追踪单次会话中的项目状态"""

    def __init__(self):
        self.created_files: list[str] = []
        self.modified_files: list[str] = []
        self.todo_items: list[dict] = []  # [{task, status}]
        self.current_phase: str = "初始化"
        self.phase_progress: float = 0.0
        self.phases: list[ProjectPhase] = []
        self._start_time = time.time()
        self._errors: list[str] = []
        self._fix_attempts: dict[str, int] = {}  # file → attempts

    def record_file_created(self, path: str):
        if path not in self.created_files:
            self.created_files.append(path)

    def record_file_modified(self, path: str):
        if path not in self.modified_files:
            self.modified_files.append(path)

    def add_todo(self, task: str, status: str = "pending"):
        self.todo_items.append({"task": task, "status": status})

    def mark_todo_done(self, task: str):
        for item in self.todo_items:
            if item["task"] == task:
                item["status"] = "done"

    def set_phase(self, name: str, progress: float = 0.0):
        self.current_phase = name
        self.phase_progress = progress

    def record_error(self, error: str):
        self._errors.append(error)

    def record_fix_attempt(self, file_path: str):
        self._fix_attempts[file_path] = self._fix_attempts.get(file_path, 0) + 1

    def inject_to_prompt(self) -> str:
        """生成项目上下文注入块"""
        lines = ["📊 **项目进度**"]

        # 阶段
        lines.append(f"├─ 阶段: {self.current_phase} "
                     f"({self.phase_progress:.0f}%)")

        # 文件清单
        if self.created_files:
            lines.append(
                f"├─ 已创建: {', '.join(self.created_files[-5:])}"
            )
        if self.modified_files:
            lines.append(
                f"├─ 已修改: {', '.join(self.modified_files[-5:])}"
            )

        # 待办
        if self.todo_items:
            pending = [t for t in self.todo_items if t["status"] == "pending"]
            done = [t for t in self.todo_items if t["status"] == "done"]
            if pending:
                items = ", ".join(t["task"] for t in pending[:5])
                lines.append(f"├─ 待完成: {items}")
            if done:
                items = ", ".join(t["task"] for t in done[:5])
                lines.append(f"├─ 已完成: {items}")

        # 错误
        if self._errors:
            errs = self._errors[-3:]
            lines.append(f"├─ 最近错误: {'; '.join(errs)}")

        # 修复重试
        if self._fix_attempts:
            lines.append(
                f"└─ 修复尝试: "
                f"{sum(self._fix_attempts.values())} 次"
            )
        else:
            lines[-1] = lines[-1].replace("├", "└")

        return "\n".join(lines)

    def get_summary(self) -> dict:
        """获取项目摘要数据"""
        return {
            "phase": self.current_phase,
            "progress": self.phase_progress,
            "files_created": len(self.created_files),
            "files_modified": len(self.modified_files),
            "todos_done": sum(
                1 for t in self.todo_items if t["status"] == "done"
            ),
            "todos_pending": sum(
                1 for t in self.todo_items if t["status"] == "pending"
            ),
            "errors": len(self._errors),
            "fix_attempts": sum(self._fix_attempts.values()),
            "elapsed_s": time.time() - self._start_time,
        }


# 会话级全局单例（每次对话新建）
_session_state: dict[str, ProjectState] = {}


def get_project_state(session_id: str = "default") -> ProjectState:
    if session_id not in _session_state:
        _session_state[session_id] = ProjectState()
    return _session_state[session_id]


def clear_project_state(session_id: str = "default"):
    _session_state.pop(session_id, None)
