"""项目管理闭环 — 上下文数据模型

定义贯穿 7 阶段的 ProjectContext，承载任务元数据、阶段产出物和进度状态。
设计原则：纯数据，无业务逻辑，可序列化。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProjectStatus(StrEnum):
    """项目生命周期状态"""

    PENDING = "pending"  # 待启动
    RUNNING = "running"  # 执行中
    PAUSED = "paused"  # 已暂停（等待人工确认）
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 已失败
    CANCELLED = "cancelled"  # 已取消


@dataclass
class PhaseArtifact:
    """阶段产出物"""

    phase: str  # 阶段标识
    name: str  # 产出物名称
    content: str = ""  # 文本内容
    files: list[str] = field(default_factory=list)  # 关联文件
    metadata: dict[str, Any] = field(default_factory=dict)  # 扩展元数据
    created_at: float = field(default_factory=time.time)


@dataclass
class PhaseRecord:
    """单阶段执行记录"""

    phase: str  # 阶段标识
    status: str = "pending"  # pending | running | passed | failed | skipped
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0
    gate_passed: bool = False  # 质量门禁是否通过
    gate_score: float = 0.0  # 门禁评分
    artifacts: list[PhaseArtifact] = field(default_factory=list)
    error: str = ""  # 失败原因

    @property
    def is_terminal(self) -> bool:
        """是否处于终态"""
        return self.status in ("passed", "failed", "skipped")

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 1),
            "gate_passed": self.gate_passed,
            "gate_score": round(self.gate_score, 1),
            "artifacts": len(self.artifacts),
            "error": self.error,
        }


@dataclass
class ProjectContext:
    """项目上下文 — 贯穿整个生命周期的共享状态

    在 7 阶段间传递，每个阶段读取前序产出、写入自身产出。
    所有字段均可序列化为 dict，便于持久化和 API 返回。
    """

    # ── 标识 ──
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    request: str = ""  # 用户原始需求描述

    # ── 配置 ──
    workspace: str = ""  # 工作目录
    model: str = "deepseek-chat"  # LLM 模型
    auto_apply: bool = False  # 是否自动应用修改（False=需人工确认）
    quality_gate_level: int = 2  # 质量门禁级别 (1-4)

    # ── 状态 ──
    status: ProjectStatus = ProjectStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    # ── 阶段记录 ──
    phases: dict[str, PhaseRecord] = field(default_factory=dict)
    current_phase: str = ""  # 当前执行阶段

    # ── 累积产出物（跨阶段共享）──
    artifacts: list[PhaseArtifact] = field(default_factory=list)

    # ── 需求分析产出 ──
    requirements: dict[str, Any] = field(default_factory=dict)  # 结构化需求

    # ── 方案设计产出 ──
    design: dict[str, Any] = field(default_factory=dict)  # 架构方案

    # ── 任务分解产出 ──
    task_dag: dict[str, Any] = field(default_factory=dict)  # DAG 任务图

    # ── 开发产出 ──
    developed_files: list[str] = field(default_factory=list)

    # ── 测试产出 ──
    test_results: dict[str, Any] = field(default_factory=dict)

    # ── 交付产出 ──
    delivery: dict[str, Any] = field(default_factory=dict)

    # ── 经验学习 ──
    lessons: list[str] = field(default_factory=list)

    def touch(self) -> None:
        """更新时间戳"""
        self.updated_at = time.time()

    def add_artifact(self, artifact: PhaseArtifact) -> None:
        """添加产出物"""
        self.artifacts.append(artifact)
        phase_rec = self.phases.setdefault(artifact.phase, PhaseRecord(phase=artifact.phase))
        phase_rec.artifacts.append(artifact)
        self.touch()

    def get_phase(self, phase: str) -> PhaseRecord:
        """获取阶段记录（不存在则创建）"""
        return self.phases.setdefault(phase, PhaseRecord(phase=phase))

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于 API 返回/持久化）"""
        return {
            "project_id": self.project_id,
            "request": self.request[:500],
            "workspace": self.workspace,
            "model": self.model,
            "auto_apply": self.auto_apply,
            "quality_gate_level": self.quality_gate_level,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "current_phase": self.current_phase,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
            "artifacts_count": len(self.artifacts),
            "developed_files": len(self.developed_files),
            "requirements_keys": list(self.requirements.keys()),
            "design_keys": list(self.design.keys()),
            "lessons": len(self.lessons),
        }
