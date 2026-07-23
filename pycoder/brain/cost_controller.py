"""
成本控制器 — 借鉴 Hermes 成本熔断体系

Token 预算管理 + 成本跟踪 + 熔断机制

特性:
  - Token 预算分配: 按工作流类型分配预算
  - 实时成本跟踪: 每次 Agent 调用后记录消耗
  - 成本熔断: 预算使用率 > 80% 暂停新任务分发
  - 成本仪表盘: 汇总统计与可视化数据

工作流预算:
  | 工作流 | 预算(tokens) |
  | fullstack-dev | 150K |
  | api-service | 80K |
  | hotfix | 50K |
  | code-review | 30K |

用法:
  from pycoder.brain.cost_controller import CostController, CostBudget

  controller = CostController()
  budget = controller.create_budget("fullstack-dev", token_limit=150000)
  controller.record_cost(budget.id, "architect", 5000, 0.01)
  if controller.is_over_budget(budget.id):
      print("预算超支，暂停新任务")
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class BudgetStatus(StrEnum):
    """预算状态"""
    ACTIVE = "active"
    WARNING = "warning"   # > 80% 使用
    PAUSED = "paused"     # 已暂停
    EXCEEDED = "exceeded"  # 已超支
    CLOSED = "closed"


@dataclass
class CostEntry:
    """单次成本记录"""
    timestamp: float = field(default_factory=time.time)
    agent_role: str = ""
    model: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    operation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "agent_role": self.agent_role,
            "model": self.model,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_total": self.tokens_input + self.tokens_output,
            "cost_usd": round(self.cost_usd, 6),
            "operation": self.operation,
        }


@dataclass
class CostBudget:
    """成本预算"""
    budget_id: str
    workflow_name: str
    token_limit: int
    cost_limit_usd: float = 0.0
    tokens_used: int = 0
    cost_used: float = 0.0
    status: BudgetStatus = BudgetStatus.ACTIVE
    entries: list[CostEntry] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    paused_at: float = 0.0

    @property
    def usage_pct(self) -> float:
        """Token 使用率"""
        if self.token_limit <= 0:
            return 0.0
        return self.tokens_used / self.token_limit * 100

    @property
    def cost_usage_pct(self) -> float:
        """成本使用率"""
        if self.cost_limit_usd <= 0:
            return 0.0
        return self.cost_used / self.cost_limit_usd * 100

    @property
    def is_warning(self) -> bool:
        return self.usage_pct >= 80.0

    @property
    def is_exceeded(self) -> bool:
        return self.tokens_used >= self.token_limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "workflow_name": self.workflow_name,
            "token_limit": self.token_limit,
            "tokens_used": self.tokens_used,
            "usage_pct": round(self.usage_pct, 1),
            "cost_used": round(self.cost_used, 6),
            "status": self.status.value,
            "entries_count": len(self.entries),
            "created_at": self.created_at,
        }


class CostController:
    """成本控制器

    管理 Token 预算和成本追踪，支持:
      - 按工作流预设预算
      - 实时成本累计
      - 预算告警 (80%)
      - 超支暂停
      - 成本统计

    用法:
        controller = CostController()
        budget = controller.create_budget("fullstack-dev", token_limit=150000)
        controller.record_cost(budget.id, "architect", 5000, 0.01)
    """

    # 预设工作流预算
    WORKFLOW_BUDGETS: dict[str, tuple[int, float]] = {
        "fullstack-dev": (150000, 0.30),   # tokens, USD
        "api-service": (80000, 0.16),
        "ad-video": (120000, 0.24),
        "hotfix": (50000, 0.10),
        "code-review": (30000, 0.06),
        "default": (100000, 0.20),
    }

    # 单次调用成本上限
    MAX_SINGLE_CALL_COST: float = 0.05  # USD

    def __init__(self):
        self._budgets: dict[str, CostBudget] = {}
        self._global_stats: dict[str, Any] = {
            "total_tokens": 0,
            "total_cost": 0.0,
            "total_calls": 0,
        }

    def create_budget(
        self,
        workflow_name: str,
        token_limit: int | None = None,
        cost_limit_usd: float | None = None,
    ) -> CostBudget:
        """创建成本预算

        Args:
            workflow_name: 工作流名称
            token_limit: Token 上限
            cost_limit_usd: 成本上限 (USD)

        Returns:
            CostBudget 预算对象
        """
        budget_id = str(uuid.uuid4())[:12]

        # 使用预设或自定义
        if token_limit is None or cost_limit_usd is None:
            preset = self.WORKFLOW_BUDGETS.get(workflow_name, self.WORKFLOW_BUDGETS["default"])
            token_limit = token_limit or preset[0]
            cost_limit_usd = cost_limit_usd or preset[1]

        budget = CostBudget(
            budget_id=budget_id,
            workflow_name=workflow_name,
            token_limit=token_limit,
            cost_limit_usd=cost_limit_usd,
        )

        self._budgets[budget_id] = budget
        logger.info(
            "创建预算: %s tokens=%d cost=$%.2f",
            budget_id, token_limit, cost_limit_usd,
        )
        return budget

    def get_budget(self, budget_id: str) -> CostBudget | None:
        """获取预算"""
        return self._budgets.get(budget_id)

    def record_cost(
        self,
        budget_id: str,
        agent_role: str,
        tokens: int,
        cost_usd: float = 0.0,
        model: str = "",
        operation: str = "",
        tokens_input: int = 0,
        tokens_output: int = 0,
    ) -> CostEntry | None:
        """记录一次成本

        Args:
            budget_id: 预算 ID
            agent_role: Agent 角色
            tokens: Token 消耗量
            cost_usd: 成本 (USD)
            model: 模型名
            operation: 操作描述
            tokens_input: 输入 token 数
            tokens_output: 输出 token 数

        Returns:
            CostEntry 或 None（预算不存在时）
        """
        budget = self._budgets.get(budget_id)
        if budget is None:
            logger.warning("预算不存在: %s", budget_id)
            return None

        # 检查是否已暂停
        if budget.status == BudgetStatus.PAUSED:
            logger.warning("预算已暂停: %s", budget_id)
            return None

        entry = CostEntry(
            agent_role=agent_role,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
            operation=operation,
        )

        budget.entries.append(entry)
        budget.tokens_used += tokens
        budget.cost_used += cost_usd

        # 全局统计
        self._global_stats["total_tokens"] += tokens
        self._global_stats["total_cost"] += cost_usd
        self._global_stats["total_calls"] += 1

        # 状态更新
        if budget.is_exceeded:
            budget.status = BudgetStatus.EXCEEDED
            logger.warning("预算超支: %s (%.0f%%)", budget_id, budget.usage_pct)
        elif budget.is_warning and budget.status == BudgetStatus.ACTIVE:
            budget.status = BudgetStatus.WARNING
            logger.warning("预算告警: %s (%.0f%%)", budget_id, budget.usage_pct)

        return entry

    def pause_budget(self, budget_id: str) -> bool:
        """暂停预算"""
        budget = self._budgets.get(budget_id)
        if budget:
            budget.status = BudgetStatus.PAUSED
            budget.paused_at = time.time()
            logger.info("预算暂停: %s", budget_id)
            return True
        return False

    def resume_budget(self, budget_id: str) -> bool:
        """恢复预算"""
        budget = self._budgets.get(budget_id)
        if budget and budget.status == BudgetStatus.PAUSED:
            budget.status = BudgetStatus.ACTIVE
            logger.info("预算恢复: %s", budget_id)
            return True
        return False

    def is_over_budget(self, budget_id: str) -> bool:
        """检查是否超预算"""
        budget = self._budgets.get(budget_id)
        if budget is None:
            return False
        return budget.status in (BudgetStatus.PAUSED, BudgetStatus.EXCEEDED)

    def should_pause_new_tasks(self) -> bool:
        """检查是否应该暂停新任务（全局 80% 阈值）"""
        total_usage = sum(b.usage_pct for b in self._budgets.values())
        active_budgets = sum(
            1 for b in self._budgets.values()
            if b.status == BudgetStatus.ACTIVE
        )
        if active_budgets == 0:
            return False
        avg_usage = total_usage / active_budgets
        return avg_usage >= 80.0

    def close_budget(self, budget_id: str) -> bool:
        """关闭预算"""
        budget = self._budgets.get(budget_id)
        if budget:
            budget.status = BudgetStatus.CLOSED
            logger.info("预算关闭: %s", budget_id)
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        """获取全局统计"""
        active = sum(
            1 for b in self._budgets.values()
            if b.status == BudgetStatus.ACTIVE
        )
        warning = sum(
            1 for b in self._budgets.values()
            if b.status == BudgetStatus.WARNING
        )
        exceeded = sum(
            1 for b in self._budgets.values()
            if b.status == BudgetStatus.EXCEEDED
        )

        return {
            "global": dict(self._global_stats),
            "budgets": {
                "total": len(self._budgets),
                "active": active,
                "warning": warning,
                "exceeded": exceeded,
            },
            "workflow_presets": {
                k: {"tokens": v[0], "cost_limit": v[1]}
                for k, v in self.WORKFLOW_BUDGETS.items()
            },
        }

    def get_budget_details(self, budget_id: str) -> dict[str, Any] | None:
        """获取预算详情"""
        budget = self._budgets.get(budget_id)
        if budget is None:
            return None
        return {
            **budget.to_dict(),
            "recent_entries": [
                e.to_dict() for e in budget.entries[-20:]
            ],
            "by_agent": self._aggregate_by_agent(budget),
        }

    def _aggregate_by_agent(self, budget: CostBudget) -> dict[str, dict[str, Any]]:
        """按 Agent 聚合成本"""
        agg: dict[str, dict[str, Any]] = {}
        for entry in budget.entries:
            role = entry.agent_role or "unknown"
            if role not in agg:
                agg[role] = {"calls": 0, "tokens": 0, "cost": 0.0}
            agg[role]["calls"] += 1
            agg[role]["tokens"] += entry.tokens_input + entry.tokens_output
            agg[role]["cost"] += entry.cost_usd
        return agg


# 全局单例
_cost_controller: CostController | None = None


def get_cost_controller() -> CostController:
    """获取全局成本控制器"""
    global _cost_controller
    if _cost_controller is None:
        _cost_controller = CostController()
    return _cost_controller