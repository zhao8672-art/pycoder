"""
PyCoder 进化模块 — 数据模型定义

包含进化任务、报告、配置等核心数据结构。
从 core.py 拆分而来，降低单文件复杂度。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvolutionPhase(StrEnum):
    """进化阶段"""

    OBSERVE = "observe"  # 采集数据
    ANALYZE = "analyze"  # LLM 分析
    GENERATE = "generate"  # 生成方案
    VALIDATE = "validate"  # 安全验证
    APPLY = "apply"  # 应用修改
    LEARN = "learn"  # 经验沉淀
    DONE = "done"  # 完成
    FAILED = "failed"  # 失败


@dataclass
class EvolutionTask:
    """单次进化任务"""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_type: str = "auto_fix"  # auto_fix / policy_optimize / knowledge_build
    target: str = ""  # 目标文件或模块
    description: str = ""
    phase: EvolutionPhase = EvolutionPhase.OBSERVE
    errors_collected: list[dict[str, Any]] = field(default_factory=list)
    llm_analysis: str = ""
    fix_plan: str = ""
    fix_code: str = ""
    validation_result: dict[str, Any] = field(default_factory=dict)
    applied: bool = False
    test_passed: bool = False
    rollback_performed: bool = False
    grade: float = 0.0
    lessons: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        phase_value = self.phase.value if hasattr(self.phase, "value") else str(self.phase)
        return {
            "id": self.id,
            "task_type": self.task_type,
            "target": self.target,
            "description": self.description,
            "phase": phase_value,
            "errors_collected": (
                self.errors_collected if isinstance(self.errors_collected, list) else []
            ),
            "llm_analysis": self.llm_analysis[:500],
            "fix_plan": self.fix_plan[:500],
            "applied": self.applied,
            "test_passed": self.test_passed,
            "rollback_performed": self.rollback_performed,
            "grade": self.grade,
            "lessons": self.lessons[:300],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class EvolutionReport:
    """进化报告"""

    task_id: str = ""
    success: bool = False
    phases_completed: list[str] = field(default_factory=list)
    issues_found: int = 0
    fixes_generated: int = 0
    fixes_applied: int = 0
    tests_passed: bool = False
    grade: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class EvolutionConfig:
    """进化配置"""

    auto_apply: bool = False  # 是否自动应用修复
    max_files_per_run: int = 3
    max_llm_tokens: int = 8192
    llm_model: str = "deepseek-chat"
    safety_strict: bool = True
    test_timeout_seconds: int = 300
    evolution_interval_seconds: int = 3600  # 自动进化间隔
    cost_budget_daily_usd: float = 5.0
    min_grade_threshold: float = 70.0
    max_retries: int = 3
