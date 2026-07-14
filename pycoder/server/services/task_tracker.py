"""
TaskTracker — 任务定义与追踪模块

职责：
    1. 从用户首次输入中提取任务目标和关键参数
    2. 维护任务状态机（6状态 + 进度百分比）
    3. 生成上下文锚点，注入每次 LLM 调用以确保不迷失目标
    4. 支持多子任务降级、重试、优先级重排

与 V2 引擎的关系：
    独立于 brain/task_planner.py（后者侧重规划分解）——
    TaskTracker 侧重运行时追踪与上下文锚定，两者互补。

用法:
    tracker = TaskTracker()
    task = tracker.initialize("用户原始需求: 写一个FastAPI认证系统")
    # 每次 LLM 调用前:
    anchor = tracker.get_anchor(max_length=300)
    messages.insert(0, {"role": "system", "content": anchor})
    # 完成后:
    tracker.mark_complete(success=True)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import Enum


class TaskPhase(Enum):
    """任务阶段"""

    INIT = "init"  # 任务初始化中
    ANALYZING = "analyzing"  # 分析需求
    PLANNING = "planning"  # 规划步骤
    EXECUTING = "executing"  # 执行中
    VERIFYING = "verifying"  # 验证结果
    DONE = "done"  # 完成
    FAILED = "failed"  # 失败
    IDLE = "idle"  # 无任务


@dataclass
class TaskAnchor:
    """上下文锚点 —— 注入每次 LLM 调用的固定前缀，防止上下文漂移"""

    goal: str  # 一句话任务目标
    parameters: dict  # 关键参数 (技术栈/语言/约束)
    current_phase: str  # 当前阶段
    completed_steps: list[str]  # 已完成步骤摘要
    next_step: str  # 下一步
    last_decision: str  # 最近关键决策
    drift_warnings: list[str]  # 偏离警告列表

    def to_prompt(self, max_length: int = 500) -> str:
        """生成注入 LLM 的上下文锚点文本"""
        lines = [
            "## 🎯 当前任务锚点",
            f"**目标**: {self.goal[:200]}",
            f"**阶段**: {self.current_phase}",
        ]
        if self.parameters:
            params_str = ", ".join(f"{k}={v}" for k, v in list(self.parameters.items())[:6])
            lines.append(f"**参数**: {params_str}")
        if self.completed_steps:
            lines.append(f"**已完成**: {' → '.join(self.completed_steps[-5:])}")
        if self.next_step:
            lines.append(f"**下一步**: {self.next_step[:200]}")
        if self.last_decision:
            lines.append(f"**最近决策**: {self.last_decision[:150]}")
        if self.drift_warnings:
            lines.append(f"**⚠️ 偏离提醒**: {'; '.join(self.drift_warnings[-3:])}")

        result = "\n".join(lines)
        if len(result) > max_length:
            result = result[: max_length - 50] + "\n...(锚点截断)"
        return result


@dataclass
class SubTask:
    """子任务"""

    id: str
    description: str
    status: str = "pending"  # pending / active / done / failed
    priority: int = 5  # 1=最高, 10=最低 (越小越高)
    retries: int = 0
    max_retries: int = 2
    started_at: float = 0.0
    completed_at: float = 0.0


class TaskTracker:
    """任务定义与追踪器

    维护当前会话的任务状态，提供上下文锚点生成。
    不依赖 LLM——所有状态由调用方显式更新。
    """

    def __init__(self):
        self._task_id: str = ""
        self._goal: str = ""
        self._parameters: dict = {}
        self._phase: TaskPhase = TaskPhase.IDLE
        self._subtasks: list[SubTask] = []
        self._completed_steps: list[str] = []
        self._next_step: str = ""
        self._last_decision: str = ""
        self._drift_warnings: list[str] = []
        self._start_time: float = 0.0
        self._decisions: list[tuple[str, str]] = []  # (timestamp, decision)

    # ══════════════════════════════════════════════════════
    # 任务初始化
    # ══════════════════════════════════════════════════════

    def initialize(self, goal: str, parameters: dict | None = None) -> TaskAnchor:
        """从用户输入初始化一个新任务

        Args:
            goal: 用户原始需求描述
            parameters: 技术栈/约束等键值对

        Returns:
            TaskAnchor 上下文锚点
        """
        self._task_id = hashlib.md5(goal.encode(), usedforsecurity=False).hexdigest()[:12]
        self._goal = goal
        self._parameters = parameters or {}
        self._phase = TaskPhase.INIT
        self._subtasks = []
        self._completed_steps = []
        self._next_step = "解析需求"
        self._last_decision = ""
        self._drift_warnings = []
        self._start_time = time.monotonic()
        self._decisions = []

        return self.get_anchor()

    def set_phase(self, phase: TaskPhase) -> None:
        """手动设置当前阶段"""
        self._phase = phase

    def set_next_step(self, step_description: str) -> None:
        self._next_step = step_description

    def record_decision(self, decision: str) -> None:
        """记录关键决策点"""
        self._last_decision = decision
        self._decisions.append(
            (
                time.strftime("%H:%M:%S"),
                decision,
            )
        )

    # ══════════════════════════════════════════════════════
    # 子任务管理
    # ══════════════════════════════════════════════════════

    def add_subtask(self, description: str, priority: int = 5) -> SubTask:
        """添加子任务"""
        st = SubTask(
            id=f"st-{len(self._subtasks) + 1:02d}",
            description=description[:200],
            priority=priority,
        )
        self._subtasks.append(st)
        return st

    def start_subtask(self, subtask_id: str) -> None:
        for st in self._subtasks:
            if st.id == subtask_id:
                st.status = "active"
                st.started_at = time.monotonic()
                return

    def complete_subtask(self, subtask_id: str, success: bool = True) -> None:
        for st in self._subtasks:
            if st.id == subtask_id:
                st.status = "done" if success else "failed"
                st.completed_at = time.monotonic()
                if success:
                    self._completed_steps.append(st.description[:80])
                elif st.retries < st.max_retries:
                    st.retries += 1
                    st.status = "pending"  # 重试
                return

    # ══════════════════════════════════════════════════════
    # 进度计算
    # ══════════════════════════════════════════════════════

    @property
    def progress_percent(self) -> int:
        """完成百分比"""
        if not self._subtasks:
            # 无子任务时基于阶段估算
            phase_map = {
                TaskPhase.INIT: 5,
                TaskPhase.ANALYZING: 15,
                TaskPhase.PLANNING: 25,
                TaskPhase.EXECUTING: 60,
                TaskPhase.VERIFYING: 85,
                TaskPhase.DONE: 100,
                TaskPhase.FAILED: 0,
                TaskPhase.IDLE: 0,
            }
            return phase_map.get(self._phase, 0)

        total = len(self._subtasks)
        done = sum(1 for st in self._subtasks if st.status == "done")
        return int(done / max(total, 1) * 100)

    @property
    def elapsed_seconds(self) -> int:
        if self._start_time == 0:
            return 0
        return int(time.monotonic() - self._start_time)

    @property
    def is_active(self) -> bool:
        return self._phase not in (TaskPhase.IDLE, TaskPhase.DONE, TaskPhase.FAILED)

    # ══════════════════════════════════════════════════════
    # 偏离警告
    # ══════════════════════════════════════════════════════

    def add_drift_warning(self, warning: str) -> None:
        """添加偏离警告"""
        self._drift_warnings.append(f"[{time.strftime('%H:%M:%S')}] {warning[:150]}")
        # 最多保留 10 条
        if len(self._drift_warnings) > 10:
            self._drift_warnings = self._drift_warnings[-10:]

    # ══════════════════════════════════════════════════════
    # 标记完成
    # ══════════════════════════════════════════════════════

    def mark_complete(self, success: bool = True) -> TaskAnchor:
        """标记任务结束"""
        self._phase = TaskPhase.DONE if success else TaskPhase.FAILED
        self._next_step = ""
        return self.get_anchor()

    # ══════════════════════════════════════════════════════
    # 上下文锚点
    # ══════════════════════════════════════════════════════

    def get_anchor(self) -> TaskAnchor:
        """获取当前上下文锚点"""
        return TaskAnchor(
            goal=self._goal,
            parameters=self._parameters,
            current_phase=self._phase.value,
            completed_steps=list(self._completed_steps),
            next_step=self._next_step,
            last_decision=self._last_decision,
            drift_warnings=list(self._drift_warnings),
        )

    def get_status(self) -> dict:
        """获取完整状态字典（供 WebSocket 推送）"""
        return {
            "task_id": self._task_id,
            "goal": self._goal[:200],
            "phase": self._phase.value,
            "progress_percent": self.progress_percent,
            "elapsed_seconds": self.elapsed_seconds,
            "subtasks": [
                {
                    "id": st.id,
                    "description": st.description[:80],
                    "status": st.status,
                    "priority": st.priority,
                }
                for st in self._subtasks
            ],
            "completed_steps": self._completed_steps[-5:],
            "next_step": self._next_step[:200],
            "last_decision": self._last_decision[:150],
            "drift_warnings": self._drift_warnings[-3:],
        }
