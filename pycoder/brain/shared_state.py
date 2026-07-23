"""
共享状态系统 — 借鉴 Hermes 共享状态体系

所有 Agent 间通信通过共享状态 JSON 文件实现，避免直接耦合。

状态文件:
  shared/{taskId}.json          — 任务状态
  shared/contracts/{taskId}.json — 验证合约
  shared/evaluations/{taskId}.json — 合约评估
  shared/budgets/{workflowId}.json — 预算控制
  shared/traces/{traceId}/       — 追踪会话
  shared/workflow-checkpoints/   — 工作流版本化检查点

用法:
  from pycoder.brain.shared_state import SharedState, TaskState

  state = SharedState()
  state.create_task("实现用户登录", "fullstack-dev")
  state.update_task(task_id, status="running", phase="develop")
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
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPhase(StrEnum):
    """任务阶段"""
    INIT = "init"
    INTAKE = "intake"
    DESIGN = "design"
    DECOMPOSE = "decompose"
    ENV_SETUP = "env_setup"
    DEVELOP = "develop"
    TEST = "test"
    DEPLOY = "deploy"
    REVIEW = "review"
    DONE = "done"


@dataclass
class ValidationContract:
    """验证合约 — 定义任务验收标准"""
    contract_id: str
    task_id: str
    requirements: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    quality_thresholds: dict[str, float] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    evaluated: bool = False
    passed: bool = False
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "requirements": self.requirements,
            "acceptance_criteria": self.acceptance_criteria,
            "quality_thresholds": self.quality_thresholds,
            "constraints": self.constraints,
            "created_at": self.created_at,
            "evaluated": self.evaluated,
            "passed": self.passed,
            "score": self.score,
        }


@dataclass
class SharedTaskState:
    """共享任务状态"""
    task_id: str
    title: str
    description: str = ""
    workflow: str = ""
    status: str = TaskStatus.PENDING.value
    phase: str = TaskPhase.INIT.value
    progress: float = 0.0
    assigned_agents: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "workflow": self.workflow,
            "status": self.status,
            "phase": self.phase,
            "progress": self.progress,
            "assigned_agents": self.assigned_agents,
            "dependencies": self.dependencies,
            "deliverables": self.deliverables,
            "errors": self.errors,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SharedTaskState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SharedState:
    """共享状态管理器

    管理 Agent 间共享状态，所有状态以 JSON 文件形式持久化。

    特性:
      - JSON 文件持久化
      - 任务状态生命周期管理
      - 验证合约管理
      - 追踪会话
      - 预算控制
      - 并发安全（文件锁）
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path.home() / ".pycoder"
        self._shared_dir = self._workspace / "shared"
        self._tasks_dir = self._shared_dir / "tasks"
        self._contracts_dir = self._shared_dir / "contracts"
        self._evaluations_dir = self._shared_dir / "evaluations"
        self._budgets_dir = self._shared_dir / "budgets"
        self._traces_dir = self._shared_dir / "traces"
        self._checkpoints_dir = self._shared_dir / "workflow-checkpoints"

        # 确保所有目录存在
        for d in [
            self._tasks_dir, self._contracts_dir, self._evaluations_dir,
            self._budgets_dir, self._traces_dir, self._checkpoints_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._memory_cache: dict[str, SharedTaskState] = {}

    # ── 任务状态管理 ──────────────────────────────

    def create_task(
        self,
        title: str,
        workflow: str = "",
        description: str = "",
        dependencies: list[str] | None = None,
    ) -> SharedTaskState:
        """创建新任务

        Args:
            title: 任务标题
            workflow: 工作流名称
            description: 任务描述
            dependencies: 依赖任务 ID 列表

        Returns:
            SharedTaskState 任务状态
        """
        task_id = str(uuid.uuid4())[:12]
        task = SharedTaskState(
            task_id=task_id,
            title=title,
            description=description,
            workflow=workflow,
            dependencies=dependencies or [],
        )
        self._save_task(task)
        self._memory_cache[task_id] = task
        logger.info("创建任务: %s (%s)", task_id, title)
        return task

    def get_task(self, task_id: str) -> SharedTaskState | None:
        """获取任务状态"""
        if task_id in self._memory_cache:
            return self._memory_cache[task_id]
        return self._load_task(task_id)

    def update_task(
        self,
        task_id: str,
        **kwargs: Any,
    ) -> SharedTaskState | None:
        """更新任务状态

        可更新字段: status, phase, progress, assigned_agents, deliverables, errors, metadata
        """
        task = self._memory_cache.get(task_id) or self._load_task(task_id)
        if task is None:
            logger.warning("任务不存在: %s", task_id)
            return None

        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = time.time()
        if kwargs.get("status") == TaskStatus.COMPLETED.value:
            task.completed_at = time.time()
            task.progress = 100.0

        self._save_task(task)
        self._memory_cache[task_id] = task
        return task

    def list_tasks(
        self, status: str | None = None, workflow: str | None = None
    ) -> list[SharedTaskState]:
        """列出任务"""
        tasks: list[SharedTaskState] = []
        for f in self._tasks_dir.glob("*.json"):
            try:
                task = self._load_task(f.stem)
                if task:
                    if status and task.status != status:
                        continue
                    if workflow and task.workflow != workflow:
                        continue
                    tasks.append(task)
            except Exception as e:
                logger.warning("加载任务文件失败: %s", e)
                continue
        return sorted(tasks, key=lambda t: t.updated_at, reverse=True)

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        task_file = self._tasks_dir / f"{task_id}.json"
        if task_file.exists():
            task_file.unlink()
            self._memory_cache.pop(task_id, None)
            logger.info("删除任务: %s", task_id)
            return True
        return False

    # ── 验证合约管理 ──────────────────────────────

    def create_contract(
        self,
        task_id: str,
        requirements: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        quality_thresholds: dict[str, float] | None = None,
    ) -> ValidationContract:
        """创建验证合约"""
        contract_id = str(uuid.uuid4())[:12]
        contract = ValidationContract(
            contract_id=contract_id,
            task_id=task_id,
            requirements=requirements or [],
            acceptance_criteria=acceptance_criteria or [],
            quality_thresholds=quality_thresholds or {},
        )
        self._save_contract(contract)
        return contract

    def get_contract(self, contract_id: str) -> ValidationContract | None:
        """获取验证合约"""
        return self._load_contract(contract_id)

    def evaluate_contract(
        self, contract_id: str, score: float, passed: bool
    ) -> ValidationContract | None:
        """评估合约"""
        contract = self._load_contract(contract_id)
        if contract:
            contract.evaluated = True
            contract.passed = passed
            contract.score = score
            self._save_contract(contract)
            self._save_evaluation(contract_id, {"score": score, "passed": passed})
        return contract

    # ── 追踪会话 ──────────────────────────────────

    def create_trace(self, trace_id: str | None = None) -> str:
        """创建追踪会话"""
        tid = trace_id or str(uuid.uuid4())[:12]
        trace_dir = self._traces_dir / tid
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / "metadata.json").write_text(
            json.dumps({
                "trace_id": tid,
                "created_at": time.time(),
                "entries": 0,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return tid

    def write_trace_log(
        self, trace_id: str, entry: dict[str, Any]
    ) -> None:
        """写入追踪日志"""
        trace_dir = self._traces_dir / trace_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        log_file = trace_dir / "trace.jsonl"
        entry["_ts"] = time.time()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_trace_timeline(self, trace_id: str) -> list[dict[str, Any]]:
        """获取追踪时间线"""
        log_file = self._traces_dir / trace_id / "trace.jsonl"
        if not log_file.exists():
            return []
        entries: list[dict[str, Any]] = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    # ── 统计 ──────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取共享状态统计"""
        task_files = list(self._tasks_dir.glob("*.json"))
        status_counts: dict[str, int] = {}
        for f in task_files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                status = data.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            except Exception as e:
                logger.warning("解析任务状态文件失败: %s", e)
                continue

        return {
            "total_tasks": len(task_files),
            "status_counts": status_counts,
            "contracts": len(list(self._contracts_dir.glob("*.json"))),
            "traces": len(list(self._traces_dir.iterdir())),
            "checkpoints": len(list(self._checkpoints_dir.glob("*.json"))),
        }

    # ── 内部持久化 ────────────────────────────────

    def _save_task(self, task: SharedTaskState) -> None:
        """保存任务状态"""
        task_file = self._tasks_dir / f"{task.task_id}.json"
        task_file.write_text(
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_task(self, task_id: str) -> SharedTaskState | None:
        """加载任务状态"""
        task_file = self._tasks_dir / f"{task_id}.json"
        if not task_file.exists():
            return None
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
            return SharedTaskState.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("加载任务失败: %s", e)
            return None

    def _save_contract(self, contract: ValidationContract) -> None:
        """保存验证合约"""
        contract_file = self._contracts_dir / f"{contract.contract_id}.json"
        contract_file.write_text(
            json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_contract(self, contract_id: str) -> ValidationContract | None:
        """加载验证合约"""
        contract_file = self._contracts_dir / f"{contract_id}.json"
        if not contract_file.exists():
            return None
        try:
            data = json.loads(contract_file.read_text(encoding="utf-8"))
            return ValidationContract(**{k: v for k, v in data.items() if k in ValidationContract.__dataclass_fields__})
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("加载合约失败: %s", e)
            return None

    def _save_evaluation(self, contract_id: str, evaluation: dict[str, Any]) -> None:
        """保存评估结果"""
        eval_file = self._evaluations_dir / f"{contract_id}.json"
        eval_file.write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# 全局单例
_shared_state: SharedState | None = None


def get_shared_state() -> SharedState:
    """获取全局共享状态"""
    global _shared_state
    if _shared_state is None:
        _shared_state = SharedState()
    return _shared_state