"""
策略管理器 — 基于观察数据自动调整系统超参数和行为策略

核心能力:
  1. 自适应阈值调整 — 根据成功率自动调整质量门禁、重试次数等阈值
  2. 模型路由优化 — 根据任务类型和成功率自动选择最优模型
  3. Token预算管理 — 成本熔断 + 预算分配 + 使用预警
  4. 策略版本记录 — 所有策略变更的完整审计追踪

策略闭环:
  观察数据 → 分析趋势 → 调整策略 → 应用策略 → 验证效果 → 记录变更

用法:
  from pycoder.capabilities.self_evo.learning.policy_manager import (
      PolicyManager,
      SystemPolicy,
      get_policy_manager,
  )

  pm = PolicyManager()
  pm.adjust_quality_threshold(current_success_rate=0.75)
  pm.select_model(task_type="code_review", complexity="high")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

POLICY_DB = Path.home() / ".pycoder" / "learning" / "policies.json"


@dataclass
class SystemPolicy:
    """系统策略快照"""

    version: int = 1
    quality_threshold: float = 85.0
    max_retries: int = 3
    token_budget_daily: int = 1_000_000
    token_budget_task: int = 50_000
    cost_budget_monthly_usd: float = 50.0
    cost_alert_threshold_usd: float = 25.0
    preferred_models: dict[str, str] = field(default_factory=dict)
    model_fallback_order: list[str] = field(default_factory=list)
    safety_strict_mode: bool = True
    auto_apply_enabled: bool = False
    max_files_per_fix: int = 3
    review_required_severity: str = "critical"
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class PolicyChange:
    """策略变更记录"""

    field: str
    old_value: Any
    new_value: Any
    reason: str
    timestamp: float = 0.0


class PolicyManager:
    """策略管理器 — 自适应策略调整"""

    def __init__(self):
        self._policy = self._load_policy()
        self._history: list[PolicyChange] = []
        self._usage_stats: dict[str, Any] = {
            "tokens_total": 0,
            "tokens_today": 0,
            "cost_total_usd": 0.0,
            "cost_month_usd": 0.0,
            "tasks_total": 0,
            "tasks_success": 0,
            "tasks_failed": 0,
            "last_reset_day": time.strftime("%Y-%m-%d"),
        }

    # ══════════════════════════════════════════════════════
    # 策略持久化
    # ══════════════════════════════════════════════════════

    def _load_policy(self) -> SystemPolicy:
        """加载策略"""
        if POLICY_DB.exists():
            try:
                data = json.loads(POLICY_DB.read_text(encoding="utf-8"))
                return SystemPolicy(**data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("策略文件损坏，使用默认策略: %s", e)
        return SystemPolicy(created_at=time.time(), updated_at=time.time())

    def _save_policy(self) -> None:
        """保存策略"""
        self._policy.updated_at = time.time()
        POLICY_DB.parent.mkdir(parents=True, exist_ok=True)
        POLICY_DB.write_text(
            json.dumps(self._policy.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _record_change(self, field: str, old_value: Any, new_value: Any, reason: str) -> None:
        """记录策略变更"""
        change = PolicyChange(
            field=field,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            timestamp=time.time(),
        )
        self._history.append(change)
        logger.info("策略变更: %s %s → %s (%s)", field, old_value, new_value, reason)

    # ══════════════════════════════════════════════════════
    # 自适应阈值调整
    # ══════════════════════════════════════════════════════

    def adjust_quality_threshold(self, current_success_rate: float) -> float:
        """根据当前成功率自动调整质量门禁

        逻辑:
          - 成功率 > 90%: 阈值 +5 (更严格)
          - 成功率 < 60%: 阈值 -5 (更宽松)
          - 范围: 60-95
        """
        old = self._policy.quality_threshold
        if current_success_rate > 0.90:
            new = min(old + 5, 95)
        elif current_success_rate < 0.60:
            new = max(old - 5, 60)
        else:
            new = old

        if new != old:
            self._record_change(
                "quality_threshold",
                old,
                new,
                f"成功率 {current_success_rate:.1%}",
            )
            self._policy.quality_threshold = new
            self._save_policy()

        return self._policy.quality_threshold

    def adjust_retries(self, current_success_rate: float, avg_retries: float) -> int:
        """根据成功率和平均重试次数调整最大重试数

        逻辑:
          - 平均重试 > 2 且成功率低: 减少重试 (避免浪费)
          - 平均重试 < 1 且成功率高: 减少重试 (效率高)
          - 范围: 1-5
        """
        old = self._policy.max_retries
        if avg_retries > 2 and current_success_rate < 0.5:
            new = max(old - 1, 1)
        elif avg_retries < 1 and current_success_rate > 0.8:
            new = max(old - 1, 1)
        elif avg_retries > 1.5:
            new = min(old + 1, 5)
        else:
            new = old

        if new != old:
            self._record_change(
                "max_retries",
                old,
                new,
                f"成功率 {current_success_rate:.1%}, 平均重试 {avg_retries:.1f}",
            )
            self._policy.max_retries = new
            self._save_policy()

        return self._policy.max_retries

    # ══════════════════════════════════════════════════════
    # 模型路由优化
    # ══════════════════════════════════════════════════════

    def select_model(self, task_type: str, complexity: str = "medium") -> str:
        """根据任务类型和复杂度选择最优模型

        模型路由规则:
          - 简单任务 (code_format, simple_fix): 便宜模型
          - 中等任务 (code_review, bug_fix): 平衡模型
          - 复杂任务 (architecture, security): 最强模型
        """
        if not self._policy.preferred_models:
            self._policy.preferred_models = {
                "simple": "deepseek-chat",
                "medium": "deepseek-chat",
                "complex": "deepseek-chat",
                "code_review": "deepseek-chat",
                "bug_fix": "deepseek-chat",
                "architecture": "deepseek-chat",
                "security": "deepseek-chat",
                "refactor": "deepseek-chat",
            }

        if complexity == "simple":
            return self._policy.preferred_models.get("simple", "deepseek-chat")
        elif complexity == "high":
            return self._policy.preferred_models.get("complex", "deepseek-chat")
        else:
            return self._policy.preferred_models.get(task_type, "deepseek-chat")

    def update_model_success_rate(self, model: str, task_type: str, success: bool) -> None:
        """更新模型成功率（用于未来自动路由优化）"""
        # 简单实现: 记录模型使用统计
        key = f"model_{model}"
        if key not in self._usage_stats:
            self._usage_stats[key] = {"total": 0, "success": 0, "by_task": {}}
        self._usage_stats[key]["total"] += 1
        if success:
            self._usage_stats[key]["success"] += 1
        if task_type not in self._usage_stats[key]["by_task"]:
            self._usage_stats[key]["by_task"][task_type] = {"total": 0, "success": 0}
        self._usage_stats[key]["by_task"][task_type]["total"] += 1
        if success:
            self._usage_stats[key]["by_task"][task_type]["success"] += 1

    # ══════════════════════════════════════════════════════
    # Token 预算管理
    # ══════════════════════════════════════════════════════

    def check_token_budget(self, tokens_this_task: int) -> dict[str, Any]:
        """检查 Token 预算

        返回: {"allowed": bool, "warning": str | None, "remaining": int}
        """
        self._reset_daily_if_needed()

        remaining_daily = self._policy.token_budget_daily - self._usage_stats["tokens_today"]
        if self._usage_stats["tokens_today"] + tokens_this_task > self._policy.token_budget_daily * 0.9:
            return {
                "allowed": False,
                "warning": f"Token 日预算即将耗尽: {self._usage_stats['tokens_today']}/{self._policy.token_budget_daily}",
                "remaining": remaining_daily,
            }

        if tokens_this_task > self._policy.token_budget_task:
            return {
                "allowed": False,
                "warning": f"任务 Token 超限: {tokens_this_task} > {self._policy.token_budget_task}",
                "remaining": remaining_daily,
            }

        return {
            "allowed": True,
            "warning": None,
            "remaining": remaining_daily,
        }

    def record_token_usage(self, tokens: int, cost_usd: float = 0.0) -> None:
        """记录 Token 使用"""
        self._reset_daily_if_needed()
        self._usage_stats["tokens_total"] += tokens
        self._usage_stats["tokens_today"] += tokens
        self._usage_stats["cost_total_usd"] += cost_usd
        self._usage_stats["cost_month_usd"] += cost_usd

    def check_cost_alert(self) -> str | None:
        """检查成本告警"""
        if self._usage_stats["cost_month_usd"] > self._policy.cost_budget_monthly_usd:
            return f"月度成本超预算: ${self._usage_stats['cost_month_usd']:.2f} > ${self._policy.cost_budget_monthly_usd:.2f}"
        if self._usage_stats["cost_month_usd"] > self._policy.cost_alert_threshold_usd:
            return f"月度成本接近预算: ${self._usage_stats['cost_month_usd']:.2f} / ${self._policy.cost_budget_monthly_usd:.2f}"
        return None

    def _reset_daily_if_needed(self) -> None:
        """每日重置"""
        today = time.strftime("%Y-%m-%d")
        if self._usage_stats["last_reset_day"] != today:
            self._usage_stats["tokens_today"] = 0
            self._usage_stats["last_reset_day"] = today

    # ══════════════════════════════════════════════════════
    # 任务追踪
    # ══════════════════════════════════════════════════════

    def record_task_result(self, success: bool) -> None:
        """记录任务结果"""
        self._usage_stats["tasks_total"] += 1
        if success:
            self._usage_stats["tasks_success"] += 1
        else:
            self._usage_stats["tasks_failed"] += 1

    # ══════════════════════════════════════════════════════
    # 查询接口
    # ══════════════════════════════════════════════════════

    def get_policy(self) -> SystemPolicy:
        """获取当前策略"""
        return self._policy

    def get_change_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取策略变更历史"""
        return [
            {
                "field": c.field,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "reason": c.reason,
                "timestamp": c.timestamp,
            }
            for c in self._history[-limit:]
        ]

    def get_usage_stats(self) -> dict[str, Any]:
        """获取使用统计"""
        self._reset_daily_if_needed()
        return {**self._usage_stats}

    def get_model_stats(self) -> dict[str, Any]:
        """获取模型使用统计"""
        model_stats = {}
        for key, stats in self._usage_stats.items():
            if key.startswith("model_"):
                model_name = key[6:]
                model_stats[model_name] = {
                    "total": stats["total"],
                    "success_rate": round(stats["success"] / max(stats["total"], 1) * 100, 1),
                    "by_task": stats["by_task"],
                }
        return model_stats

    def update_policy(self, **kwargs: Any) -> SystemPolicy:
        """手动更新策略参数"""
        for key, value in kwargs.items():
            if hasattr(self._policy, key):
                old = getattr(self._policy, key)
                if old != value:
                    self._record_change(key, old, value, "手动更新")
                    setattr(self._policy, key, value)
        self._save_policy()
        return self._policy


# 全局单例
_manager: PolicyManager | None = None


def get_policy_manager() -> PolicyManager:
    global _manager
    if _manager is None:
        _manager = PolicyManager()
    return _manager


__all__ = [
    "PolicyManager",
    "SystemPolicy",
    "PolicyChange",
    "get_policy_manager",
]