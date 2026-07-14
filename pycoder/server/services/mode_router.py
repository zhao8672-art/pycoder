"""
模式路由器 — 根据意图调度三种工作模式

支持:
    - 单模式直接路由
    - 复合意图拆分为多模式并行/串行
    - 资源管控防止抢占
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field


class Mode(Enum):
    CHAT = "chat"
    HERMES = "hermes"
    AGENT = "agent"


@dataclass
class ModeTask:
    task_id: str
    mode: Mode
    command: str
    reason: str = ""
    depends_on: list[str] = field(default_factory=list)


# ── 资源限制 ──
MODE_CONCURRENCY: dict[Mode, int] = {
    Mode.CHAT: 1,
    Mode.HERMES: 1,
    Mode.AGENT: 1,
}


class ModeRouter:

    def route(self, category: str, reason: str = "") -> list[ModeTask]:
        """根据任务类别路由到对应模式。

        Args:
            category: 任务类别 (chat / hermes / agent)
            reason: 分类理由

        Returns:
            模式任务列表
        """
        mapping: dict[str, Mode] = {
            "chat": Mode.CHAT,
            "hermes": Mode.HERMES,
            "agent": Mode.AGENT,
        }

        mode = mapping.get(category, Mode.CHAT)

        return [
            ModeTask(
                task_id=f"task-{mode.value}",
                mode=mode,
                command="",  # 由调用方填充
                reason=reason or f"自动路由到 {mode.value} 模式",
            )
        ]

    def can_parallel(self, task_a: ModeTask, task_b: ModeTask) -> bool:
        """判断两个任务是否可以并行。"""
        # 不同模式可以并行
        if task_a.mode != task_b.mode:
            return True
        # 同模式串行（防止抢占）
        return False

    def get_max_concurrent(self, mode: Mode) -> int:
        """获取模式最大并发数。"""
        return MODE_CONCURRENCY.get(mode, 1)
