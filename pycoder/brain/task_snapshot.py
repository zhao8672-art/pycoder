"""
任务快照与断点续跑 — 借鉴生产级 Agent 团队方案

任务状态持久化，支持系统重启后从断点恢复，不重复执行、不丢失进度。

用法:
  from pycoder.brain.task_snapshot import TaskSnapshot, TaskState

  snapshot = TaskSnapshot(workspace=Path("."))
  state = snapshot.load(task_id)  # 恢复任务
  snapshot.save(state)            # 保存快照
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    """任务状态"""
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 执行中
    SUCCESS = "success"       # 完成
    FAILED = "failed"         # 失败
    BLOCKED = "blocked"       # 阻塞（依赖未满足）
    PAUSED = "paused"         # 暂停
    CANCELLED = "cancelled"   # 取消


@dataclass
class SubTask:
    """原子子任务"""
    task_id: str
    task_name: str
    task_type: str = "dev"  # design/dev/test/env/review
    status: str = "pending"
    depend_task_ids: list[str] = field(default_factory=list)
    accept_std: str = ""
    result: str = ""
    error_msg: str = ""
    assigned_agent: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_type": self.task_type,
            "status": self.status,
            "depend_task_ids": self.depend_task_ids,
            "accept_std": self.accept_std,
            "result": self.result,
            "error_msg": self.error_msg,
            "assigned_agent": self.assigned_agent,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubTask:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TaskState:
    """全局任务状态 — 支撑断点续跑的核心数据结构"""
    global_task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_title: str = ""
    task_level: str = "A"  # S/A/B
    status: str = "pending"

    # 流程数据
    requirement_content: str = ""
    tech_solution: str = ""
    sub_tasks: dict[str, SubTask] = field(default_factory=dict)

    # 阶段结果
    code_commit_log: list[str] = field(default_factory=list)
    bug_list: list[dict] = field(default_factory=list)
    test_report: str = ""
    deploy_result: str = ""
    review_report: str = ""

    # 断点标记
    last_run_node: str = "start"
    current_phase: str = "init"
    is_finish: bool = False

    # 时间戳
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    # 统计
    total_subtasks: int = 0
    completed_subtasks: int = 0
    failed_subtasks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_task_id": self.global_task_id,
            "task_title": self.task_title,
            "task_level": self.task_level,
            "status": self.status,
            "requirement_content": self.requirement_content,
            "tech_solution": self.tech_solution,
            "sub_tasks": {k: v.to_dict() for k, v in self.sub_tasks.items()},
            "code_commit_log": self.code_commit_log,
            "bug_list": self.bug_list,
            "test_report": self.test_report,
            "deploy_result": self.deploy_result,
            "review_report": self.review_report,
            "last_run_node": self.last_run_node,
            "current_phase": self.current_phase,
            "is_finish": self.is_finish,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "total_subtasks": self.total_subtasks,
            "completed_subtasks": self.completed_subtasks,
            "failed_subtasks": self.failed_subtasks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        state = cls()
        for k, v in data.items():
            if k == "sub_tasks":
                state.sub_tasks = {k2: SubTask.from_dict(v2) for k2, v2 in v.items()}
            elif hasattr(state, k):
                setattr(state, k, v)
        return state

    @property
    def progress_percent(self) -> float:
        """计算进度百分比"""
        if self.total_subtasks == 0:
            return 0.0
        return round(self.completed_subtasks / self.total_subtasks * 100, 1)

    @property
    def has_dependency_cycle(self) -> bool:
        """检测是否存在依赖环"""
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def _dfs(nid: str) -> bool:
            visited.add(nid)
            rec_stack.add(nid)
            task = self.sub_tasks.get(nid)
            if task:
                for dep in task.depend_task_ids:
                    if dep not in visited:
                        if _dfs(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            rec_stack.discard(nid)
            return False

        for nid in self.sub_tasks:
            if nid not in visited:
                if _dfs(nid):
                    return True
        return False


class TaskSnapshot:
    """任务快照管理器 — 持久化 + 恢复

    特性:
      - JSON 文件持久化
      - 自动保存时间戳
      - 支持快照列表查询
      - 支持清理过期快照
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path.home() / ".pycoder"
        self._snap_dir = self._workspace / "task_snapshots"
        self._snap_dir.mkdir(parents=True, exist_ok=True)

    def _snap_path(self, task_id: str) -> Path:
        return self._snap_dir / f"{task_id}.json"

    def save(self, state: TaskState) -> Path:
        """保存任务快照"""
        state.updated_at = time.time()
        path = self._snap_path(state.global_task_id)
        path.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("task_snapshot_saved: task_id=%s path=%s", state.global_task_id, path)
        return path

    def load(self, task_id: str) -> TaskState | None:
        """加载任务快照，恢复进度"""
        path = self._snap_path(task_id)
        if not path.exists():
            logger.warning("task_snapshot_not_found: task_id=%s", task_id)
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = TaskState.from_dict(data)
            logger.info(
                "task_snapshot_loaded: task_id=%s phase=%s subtasks=%d/%d",
                task_id, state.current_phase,
                state.completed_subtasks, state.total_subtasks,
            )
            return state
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("task_snapshot_load_error: task_id=%s error=%s", task_id, e)
            return None

    def delete(self, task_id: str) -> bool:
        """删除任务快照"""
        path = self._snap_path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出所有快照"""
        snapshots: list[dict[str, Any]] = []
        for f in sorted(self._snap_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                snapshots.append({
                    "task_id": data.get("global_task_id", f.stem),
                    "title": data.get("task_title", ""),
                    "status": data.get("status", "unknown"),
                    "phase": data.get("current_phase", "?"),
                    "progress": f"{data.get('completed_subtasks', 0)}/{data.get('total_subtasks', 0)}",
                    "updated_at": data.get("updated_at", 0),
                    "file_size": f.stat().st_size,
                })
            except (json.JSONDecodeError, OSError):
                continue
            if len(snapshots) >= limit:
                break
        return snapshots

    def cleanup_expired(self, max_age_days: int = 30) -> int:
        """清理过期快照"""
        cutoff = time.time() - max_age_days * 86400
        cleaned = 0
        for f in self._snap_dir.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    cleaned += 1
                except OSError:
                    pass
        if cleaned:
            logger.info("task_snapshot_cleanup: cleaned=%d", cleaned)
        return cleaned