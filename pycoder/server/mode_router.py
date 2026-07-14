"""P1: Plan/Act 双模式 — ModeRouter + 工具白名单

借鉴 Cline 的 Plan/Act 分离设计:
    - Plan 模式: 只读工具（read_file, search_files, grep），制定计划，无写操作
    - Act 模式: 全量工具，基于审批计划执行

集成点: UnifiedAgentEngine 在 chat_stream 前通过 ModeRouter 确定模式。
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class AgentMode(Enum):
    """Agent 执行模式"""

    PLAN = "plan"  # 只读模式 — 理解需求，制定计划
    ACT = "act"  # 执行模式 — 全量工具，实施变更
    AUTO = "auto"  # 自动选择 — 根据任务复杂度决定


# 模式→工具白名单 (Plan 模式下仅允许这些工具)
PLAN_MODE_TOOLS: set[str] = {
    "read_file",
    "list_files",
    "search_files",
    "grep",
    "FINISH",
    "plan_mode_respond",
}

# 危险工具 — Act 模式下也需确认
DANGEROUS_TOOLS: set[str] = {
    "execute_command",
    "terminal",
    "delete_file",
    "rm",
    "format",
}


class ModeRouter:
    """Plan/Act 模式路由器

    用法:
        router = ModeRouter(default_mode=AgentMode.AUTO)
        router.auto_select(task_complexity="high")  # → PLAN

        if router.is_tool_allowed("write_file"):
            execute_tool("write_file", ...)
    """

    def __init__(self, default_mode: AgentMode = AgentMode.AUTO) -> None:
        self._mode = default_mode
        self._plan: str = ""  # 当前计划文本
        self._plan_approved: bool = False

    # ── 模式管理 ──

    @property
    def mode(self) -> AgentMode:
        return self._mode

    def switch_to(self, mode: AgentMode) -> None:
        """切换执行模式"""
        old = self._mode
        self._mode = mode
        logger.info("mode_switched from=%s to=%s", old.value, mode.value)

    def auto_select(self, task_complexity: str) -> AgentMode:
        """根据任务复杂度自动选择模式。

        - high: 复杂任务 → 先 Plan 后 Act
        - medium/low: 直接 Act
        """
        if task_complexity in ("high", "very_high"):
            self.switch_to(AgentMode.PLAN)
        elif self._mode == AgentMode.AUTO:
            self.switch_to(AgentMode.ACT)
        return self._mode

    # ── 工具权限 ──

    def is_tool_allowed(self, tool_name: str) -> tuple[bool, str]:
        """检查工具在当前模式下是否允许。

        Returns:
            (allowed: bool, reason: str)
        """
        # AUTO 模式 = Act 模式（允许所有）
        if self._mode in (AgentMode.AUTO, AgentMode.ACT):
            if tool_name in DANGEROUS_TOOLS:
                return self._plan_approved, f"危险工具 '{tool_name}' 需要计划审批"
            return True, ""

        # Plan 模式 — 仅允许白名单工具
        if tool_name in PLAN_MODE_TOOLS:
            return True, ""
        return False, f"Plan 模式下禁止使用 '{tool_name}'"

    # ── 计划管理 ──

    @property
    def plan(self) -> str:
        return self._plan

    def set_plan(self, plan_text: str) -> None:
        """Agent 在 Plan 模式下制定的计划"""
        self._plan = plan_text
        self._plan_approved = False
        logger.info("plan_set length=%d", len(plan_text))

    def approve_plan(self) -> None:
        """用户审批通过计划 → 切换到 Act 模式"""
        self._plan_approved = True
        self.switch_to(AgentMode.ACT)
        logger.info("plan_approved switching_to_act")

    def reject_plan(self, feedback: str = "") -> None:
        """用户拒绝计划 → 返回 Plan 模式修订"""
        self._plan_approved = False
        self._plan = f"{self._plan}\n\n---\n用户反馈: {feedback}" if feedback else self._plan
        logger.info("plan_rejected feedback=%s", feedback[:100] if feedback else "(none)")

    def reset(self) -> None:
        """重置计划状态"""
        self._plan = ""
        self._plan_approved = False


# 全局单例
_mode_router: ModeRouter | None = None


def get_mode_router() -> ModeRouter:
    """获取 ModeRouter 单例"""
    global _mode_router
    if _mode_router is None:
        _mode_router = ModeRouter()
    return _mode_router
