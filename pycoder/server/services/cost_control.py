"""P2-4: 成本熔断与 Token 预算控制

在 ChatBridge 调用 LLM 前检查 token 预算，超限时阻断调用，避免：
  - 单次任务消耗过多 Token
  - 恶意用户耗尽 API 配额
  - 自演化陷入死循环消耗资源

三级 Token 预算：
  1. per_request_limit — 单次请求上限（防异常长请求）
  2. per_session_limit — 单会话累计上限（防单次使用过量）
  3. per_hour_limit    — 每小时累计上限（防持续滥用）

复用现有实现：
  - pycoder.providers.cost.CostTracker — 已有的 USD 计费与持久化
  - pycoder.server.chat_bridge.estimate_tokens — 已有的 token 估算

用法:
  from pycoder.server.services.cost_control import get_cost_controller

  ctrl = get_cost_controller()
  ok, reason = ctrl.check_before_call(estimated_tokens=2000)
  if not ok:
      yield ChatEvent(event_type="error", content=f"成本超限: {reason}")
      return
  # ... 调用 LLM ...
  ctrl.record_usage(input_tokens=usage["prompt_tokens"],
                    output_tokens=usage["completion_tokens"])
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 预算配置
# ══════════════════════════════════════════════════════════


@dataclass
class TokenBudget:
    """Token 预算配置"""

    per_request_limit: int = 100_000  # 单次请求最大 token
    per_session_limit: int = 1_000_000  # 单会话最大 token
    per_hour_limit: int = 5_000_000  # 每小时最大 token


@dataclass
class UsageAccumulator:
    """累计用量计数器"""

    used_tokens: int = 0
    request_count: int = 0
    last_reset: float = field(default_factory=time.time)


# ══════════════════════════════════════════════════════════
# 成本熔断控制器
# ══════════════════════════════════════════════════════════


class CostController:
    """成本熔断控制器 — 三级 Token 预算检查"""

    def __init__(
        self,
        budget: TokenBudget | None = None,
        cost_tracker: object | None = None,
    ) -> None:
        self.budget = budget or TokenBudget()
        self._session = UsageAccumulator()
        self._hourly = UsageAccumulator()
        # 复用已有的 CostTracker 单例记录 USD 计费
        self._cost_tracker = cost_tracker

    def check_before_call(self, estimated_tokens: int) -> tuple[bool, str]:
        """调用 LLM 前检查是否超预算

        Args:
            estimated_tokens: 预估本次请求将消耗的 token 数

        Returns:
            (是否允许, 原因说明) — False 时 reason 描述哪级限制超限
        """
        # 1. 单次请求限制
        if estimated_tokens > self.budget.per_request_limit:
            return False, (
                f"单次请求 token {estimated_tokens} 超限 " f"(限制 {self.budget.per_request_limit})"
            )

        # 2. 会话累计限制
        if self._session.used_tokens + estimated_tokens > self.budget.per_session_limit:
            return False, (
                f"会话累计 token {self._session.used_tokens} 即将超限 "
                f"(限制 {self.budget.per_session_limit})"
            )

        # 3. 小时累计限制（先尝试重置）
        self._maybe_reset_hourly()
        if self._hourly.used_tokens + estimated_tokens > self.budget.per_hour_limit:
            return False, (
                f"小时累计 token {self._hourly.used_tokens} 即将超限 "
                f"(限制 {self.budget.per_hour_limit})"
            )

        return True, ""

    def record_usage(self, input_tokens: int, output_tokens: int, model: str = "") -> None:
        """记录实际使用量（调用 LLM 后）

        同时更新三级计数器，并委托给 CostTracker 进行 USD 计费。
        """
        total = input_tokens + output_tokens

        # 更新会话与小时计数器
        self._session.used_tokens += total
        self._session.request_count += 1
        self._hourly.used_tokens += total
        self._hourly.request_count += 1

        # 委托 CostTracker 记录 USD 计费
        if self._cost_tracker is not None:
            try:
                self._cost_tracker.record(
                    model or "unknown",
                    {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": total,
                    },
                )
            except (AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:
                logger.warning("cost_tracker_record_failed error=%s", e)

        logger.info(
            "token_usage_recorded input=%d output=%d session_total=%d hourly_total=%d",
            input_tokens,
            output_tokens,
            self._session.used_tokens,
            self._hourly.used_tokens,
        )

    def _maybe_reset_hourly(self) -> None:
        """超过 1 小时则重置小时计数器"""
        if time.time() - self._hourly.last_reset > timedelta(hours=1).total_seconds():
            self._hourly = UsageAccumulator()

    def get_usage_report(self) -> dict:
        """获取用量报告"""
        self._maybe_reset_hourly()
        return {
            "session": {
                "tokens": self._session.used_tokens,
                "requests": self._session.request_count,
                "limit": self.budget.per_session_limit,
            },
            "hourly": {
                "tokens": self._hourly.used_tokens,
                "requests": self._hourly.request_count,
                "limit": self.budget.per_hour_limit,
            },
            "per_request_limit": self.budget.per_request_limit,
        }

    def reset_session(self) -> None:
        """重置会话计数（新会话开始时调用）"""
        self._session = UsageAccumulator()

    def reset_hourly(self) -> None:
        """强制重置小时计数（测试用）"""
        self._hourly = UsageAccumulator()


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_controller: CostController | None = None


def get_cost_controller() -> CostController:
    """获取全局 CostController 单例

    延迟初始化 CostTracker 以避免循环导入。预算可通过环境变量自定义：
      PYCODER_TOKEN_REQUEST_LIMIT  — 单次请求上限
      PYCODER_TOKEN_SESSION_LIMIT   — 会话上限
      PYCODER_TOKEN_HOUR_LIMIT      — 小时上限
    """
    global _controller
    if _controller is None:
        import os

        budget = TokenBudget(
            per_request_limit=int(os.environ.get("PYCODER_TOKEN_REQUEST_LIMIT", 100_000)),
            per_session_limit=int(os.environ.get("PYCODER_TOKEN_SESSION_LIMIT", 1_000_000)),
            per_hour_limit=int(os.environ.get("PYCODER_TOKEN_HOUR_LIMIT", 5_000_000)),
        )
        # 复用 CostTracker 单例（USD 计费）
        tracker = None
        try:
            from pycoder.providers.cost import get_cost_tracker

            tracker = get_cost_tracker()
        except (ImportError, RuntimeError) as e:
            logger.debug("cost_tracker_unavailable error=%s", e)
        _controller = CostController(budget=budget, cost_tracker=tracker)
    return _controller


def reset_cost_controller() -> None:
    """重置单例（测试用）"""
    global _controller
    _controller = None


__all__ = [
    "TokenBudget",
    "UsageAccumulator",
    "CostController",
    "get_cost_controller",
    "reset_cost_controller",
]
