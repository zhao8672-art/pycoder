"""项目管理闭环 — 7 阶段状态机定义

定义项目生命周期的 7 个阶段及其顺序流转规则。
每个阶段是一个独立的 Strategy，可被替换或 mock。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Protocol

from pycoder.lifecycle.context import PhaseRecord, ProjectContext


class LifecyclePhase(IntEnum):
    """项目生命周期 7 阶段（值代表执行顺序）"""

    INTAKE = 1  # 任务接收
    ANALYZE = 2  # 需求分析
    DESIGN = 3  # 方案设计
    DEVELOP = 4  # 代码开发
    TEST = 5  # 测试验证
    HEAL = 6  # 自愈修正
    DELIVER = 7  # 交付管理

    @classmethod
    def ordered(cls) -> list[LifecyclePhase]:
        """按执行顺序返回所有阶段"""
        return sorted(cls, key=lambda p: p.value)

    @property
    def label(self) -> str:
        """中文标签"""
        labels = {
            LifecyclePhase.INTAKE: "任务接收",
            LifecyclePhase.ANALYZE: "需求分析",
            LifecyclePhase.DESIGN: "方案设计",
            LifecyclePhase.DEVELOP: "代码开发",
            LifecyclePhase.TEST: "测试验证",
            LifecyclePhase.HEAL: "自愈修正",
            LifecyclePhase.DELIVER: "交付管理",
        }
        return labels.get(self, self.name)

    @property
    def description(self) -> str:
        """阶段描述"""
        descs = {
            LifecyclePhase.INTAKE: "解析用户需求，提取任务目标与约束条件",
            LifecyclePhase.ANALYZE: "结构化需求分析，识别功能点、非功能需求与风险",
            LifecyclePhase.DESIGN: "架构方案设计，技术选型与接口定义",
            LifecyclePhase.DEVELOP: "按 DAG 任务图执行代码开发",
            LifecyclePhase.TEST: "自动生成测试用例并执行验证",
            LifecyclePhase.HEAL: "测试失败时自动修复，质量门禁复核",
            LifecyclePhase.DELIVER: "打包交付物，生成文档与经验沉淀",
        }
        return descs.get(self, "")

    def next(self) -> LifecyclePhase | None:
        """获取下一阶段（无则返回 None）"""
        ordered = LifecyclePhase.ordered()
        idx = ordered.index(self)
        return ordered[idx + 1] if idx + 1 < len(ordered) else None

    def prev(self) -> LifecyclePhase | None:
        """获取上一阶段"""
        ordered = LifecyclePhase.ordered()
        idx = ordered.index(self)
        return ordered[idx - 1] if idx > 0 else None


class PhaseStrategy(Protocol):
    """阶段策略接口 — 每个阶段实现此接口

    设计要点：
    - orchestrator 只调用 execute()，不关心内部实现
    - 每个阶段可独立替换为 mock 或新实现
    - 阶段产出写入 ctx，orchestrator 不介入
    """

    async def execute(self, ctx: ProjectContext) -> PhaseRecord:
        """执行该阶段

        Args:
            ctx: 项目上下文（可读写）

        Returns:
            PhaseRecord: 阶段执行记录（也写入 ctx.phases）
        """
        ...


# ── 阶段流转规则 ────────────────────────────────────

# 可跳过的阶段（如质量门禁通过时 HEAL 可跳过）
SKIPPABLE_PHASES = {LifecyclePhase.HEAL}

# 必须通过质量门禁才能进入下一阶段的阶段
GATED_PHASES = {LifecyclePhase.DESIGN, LifecyclePhase.DEVELOP, LifecyclePhase.TEST}


def should_advance(ctx: ProjectContext, phase: LifecyclePhase) -> bool:
    """判断是否可以进入下一阶段

    规则：
    - 阶段状态为 passed → 可进入
    - 阶段状态为 skipped → 可进入（仅限可跳过阶段）
    - 阶段状态为 failed → 不可进入（需人工介入或重试）
    """
    record = ctx.phases.get(phase.name)
    if record is None:
        return False

    if record.status == "passed":
        return True

    if record.status == "skipped" and phase in SKIPPABLE_PHASES:
        return True

    return False


def get_progress(ctx: ProjectContext) -> float:
    """计算项目整体进度 (0.0 - 1.0)"""
    total = len(LifecyclePhase.ordered())
    completed = sum(
        1
        for p in LifecyclePhase.ordered()
        if ctx.phases.get(p.name, PhaseRecord(phase=p.name)).is_terminal
    )
    return completed / total if total > 0 else 0.0
