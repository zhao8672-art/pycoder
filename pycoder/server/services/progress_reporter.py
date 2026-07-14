"""
Agent 执行进度报告器 — 独立的进度展示模块

职责:
    1. 跟踪 AI 对话全链路执行进度（6 个阶段）
    2. 实时计算完成百分比、已用/预计剩余时间
    3. 记录关键里程碑节点完成状态
    4. 不涉及任何用户对话消息的存储或渲染

使用方式:
    reporter = ProgressReporter()
    reporter.set_stages([...])
    reporter.set_callback(lambda ev: ws.send_json(ev))

    # 在每步执行前后调用
    await reporter.advance("intent", "正在分析意图...")
    # ... do work ...
    await reporter.complete_stage("intent", True)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class StageDef:
    """阶段定义"""
    id: str
    label: str                 # 中文名称
    description: str           # 详细描述


@dataclass
class Milestone:
    """里程碑节点"""
    step: str                  # 步骤名称
    status: str = "pending"    # pending | active | done | error


class ProgressReporter:
    """Agent 执行进度报告器 — 生成给前端的 progress 事件"""

    def __init__(self):
        self._stages: list[StageDef] = []
        self._milestones: list[Milestone] = []
        self._current_idx: int = 0
        self._stage_status: dict[str, str] = {}   # stage_id → pending/active/done/error
        self._start_time: float = 0.0
        self._stage_times: dict[str, float] = {}   # stage_id → elapsed seconds
        self._callback: Callable[[dict], Awaitable[None]] | None = None
        self._total_eta_seconds: int = 60          # 总预估秒数，随执行动态调整

    def set_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """设置进度事件回调（通常连接到 WebSocket 发送）"""
        self._callback = callback

    def set_stages(self, stages: list[StageDef], total_eta: int = 60) -> None:
        """设置总执行阶段列表"""
        self._stages = stages
        self._current_idx = 0
        self._start_time = time.monotonic()
        self._total_eta_seconds = total_eta
        self._milestones = []
        self._stage_status = {}
        for s in stages:
            self._stage_status[s.id] = "pending"
            self._milestones.append(Milestone(step=s.label, status="pending"))
        if self._milestones:
            self._milestones[0].status = "active"
            self._stage_status[stages[0].id] = "active"

    async def emit_progress(self, stage: str, description: str) -> None:
        """发送进度事件到前端"""
        if not self._callback:
            return

        current_step = self._current_idx
        total_steps = len(self._stages)
        percent = int((current_step / max(total_steps, 1)) * 100) if total_steps > 0 else 0

        elapsed = time.monotonic() - self._start_time
        # 动态估算剩余时间: 已用时间 / 进度比例 * (1 - 进度比例)
        remaining = 0
        if percent > 0 and percent < 100:
            remaining = int((elapsed / percent) * (100 - percent))
        elif percent == 0:
            remaining = self._total_eta_seconds

        milestones_data = []
        for m in self._milestones:
            milestones_data.append({
                "step": m.step,
                "status": m.status,
            })

        event = {
            "type": "progress",
            "phase": stage,
            "stage": description,
            "current_step": current_step,
            "total_steps": total_steps,
            "percent": min(percent, 100),
            "elapsed_seconds": int(elapsed),
            "eta_seconds": remaining,
            "milestones": milestones_data,
        }

        try:
            await self._callback(event)
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("progress_callback_failed: %s", e)
            pass  # 回调失败不影响主流程

    async def advance(
        self,
        stage_id: str,
        description: str,
        success: bool = True,
        force_complete_all: bool = False,
    ) -> None:
        """推进到下一个阶段

        Args:
            stage_id: 阶段 ID（必须已通过 set_stages 注册）
            description: 当前阶段描述文案
            success: 是否成功完成前一个阶段
            force_complete_all: 是否强制标记所有阶段完成
        """
        if force_complete_all:
            # 直接完成所有阶段
            for i, s in enumerate(self._stages):
                self._stage_status[s.id] = "done"
                if i < len(self._milestones):
                    self._milestones[i].status = "done"
            self._current_idx = len(self._stages)
            await self.emit_progress("完成", "全部任务执行完成")
            return

        # 更新上一个（当前）阶段状态
        if self._current_idx > 0:
            prev_id = self._stages[self._current_idx - 1].id
            # 如果上一个阶段没有明确标记 done，这里自动标记
            if self._stage_status.get(prev_id) == "active":
                self._stage_status[prev_id] = "done" if success else "error"
                if self._current_idx - 1 < len(self._milestones):
                    self._milestones[self._current_idx - 1].status = "done" if success else "error"

        # 查找目标 stage_id 的索引
        target_idx = -1
        for i, s in enumerate(self._stages):
            if s.id == stage_id:
                target_idx = i
                break
        if target_idx < 0:
            return  # 未注册的阶段，忽略

        # 标记新阶段为 active
        self._stage_status[stage_id] = "active"
        if target_idx < len(self._milestones):
            self._milestones[target_idx].status = "active"
        self._current_idx = target_idx + 1  # 1-based count

        await self.emit_progress(stage_id, description)

    def mark_milestone(self, step_index: int, status: str = "done") -> None:
        """手动标记指定里程碑状态"""
        if 0 <= step_index < len(self._milestones):
            self._milestones[step_index].status = status

    def mark_stage_error(self, stage_id: str, description: str) -> None:
        """将阶段标记为错误"""
        self._stage_status[stage_id] = "error"
        self.emit_progress(stage_id, f"⚠️ {description}")

    def reset(self) -> None:
        """重置进度状态"""
        self._current_idx = 0
        self._stage_status = {}
        self._milestones = []
        self._start_time = 0.0
