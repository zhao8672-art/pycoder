"""P2-4: 成本熔断与 Token 预算控制测试

验证三级 Token 预算检查、用量记录、小时重置与用量报告。
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from pycoder.server.services.cost_control import (
    CostController,
    TokenBudget,
    UsageAccumulator,
    get_cost_controller,
    reset_cost_controller,
)


# ══════════════════════════════════════════════════════════
# TestTokenBudget — 预算配置
# ══════════════════════════════════════════════════════════


class TestTokenBudget:
    """TokenBudget 默认值与自定义"""

    def test_default_limits(self):
        b = TokenBudget()
        assert b.per_request_limit == 100_000
        assert b.per_session_limit == 1_000_000
        assert b.per_hour_limit == 5_000_000

    def test_custom_limits(self):
        b = TokenBudget(per_request_limit=500, per_session_limit=5000, per_hour_limit=10000)
        assert b.per_request_limit == 500
        assert b.per_session_limit == 5000
        assert b.per_hour_limit == 10000


# ══════════════════════════════════════════════════════════
# TestCheckBeforeCall — 三级预算检查
# ══════════════════════════════════════════════════════════


class TestCheckBeforeCall:
    """check_before_call 三级限制检查"""

    def test_within_all_limits_returns_ok(self):
        ctrl = CostController(budget=TokenBudget(
            per_request_limit=1000, per_session_limit=5000, per_hour_limit=10000,
        ))
        ok, reason = ctrl.check_before_call(500)
        assert ok is True
        assert reason == ""

    def test_per_request_limit_exceeded(self):
        """单次请求超限"""
        ctrl = CostController(budget=TokenBudget(per_request_limit=1000))
        ok, reason = ctrl.check_before_call(2000)
        assert ok is False
        assert "单次请求" in reason
        assert "2000" in reason

    def test_session_limit_exceeded(self):
        """会话累计超限"""
        ctrl = CostController(budget=TokenBudget(
            per_request_limit=10000, per_session_limit=3000, per_hour_limit=100000,
        ))
        # 先消耗 2500
        ctrl.record_usage(1500, 1000)
        assert ctrl._session.used_tokens == 2500
        # 再请求 600 → 2500+600=3100 > 3000
        ok, reason = ctrl.check_before_call(600)
        assert ok is False
        assert "会话累计" in reason

    def test_hour_limit_exceeded(self):
        """小时累计超限"""
        ctrl = CostController(budget=TokenBudget(
            per_request_limit=100000, per_session_limit=1000000, per_hour_limit=5000,
        ))
        # 消耗 4500
        ctrl.record_usage(3000, 1500)
        # 再请求 600 → 4500+600=5100 > 5000
        ok, reason = ctrl.check_before_call(600)
        assert ok is False
        assert "小时累计" in reason

    def test_request_limit_checked_first(self):
        """单次请求限制优先于会话/小时限制检查"""
        ctrl = CostController(budget=TokenBudget(
            per_request_limit=100, per_session_limit=1000, per_hour_limit=10000,
        ))
        ok, reason = ctrl.check_before_call(200)
        assert not ok
        assert "单次请求" in reason


# ══════════════════════════════════════════════════════════
# TestRecordUsage — 用量记录
# ══════════════════════════════════════════════════════════


class TestRecordUsage:
    """record_usage 更新计数器"""

    def test_updates_session_and_hourly(self):
        ctrl = CostController()
        ctrl.record_usage(100, 50)
        assert ctrl._session.used_tokens == 150
        assert ctrl._hourly.used_tokens == 150
        assert ctrl._session.request_count == 1

    def test_multiple_calls_accumulate(self):
        ctrl = CostController()
        ctrl.record_usage(100, 50)
        ctrl.record_usage(200, 100)
        assert ctrl._session.used_tokens == 450
        assert ctrl._session.request_count == 2

    def test_delegates_to_cost_tracker(self):
        """委托 CostTracker.record 记录 USD 计费"""
        mock_tracker = MagicMock()
        ctrl = CostController(cost_tracker=mock_tracker)
        ctrl.record_usage(100, 50, model="deepseek-chat")
        mock_tracker.record.assert_called_once_with(
            "deepseek-chat",
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )

    def test_cost_tracker_failure_does_not_crash(self):
        """CostTracker 异常不影响主流程"""
        failing_tracker = MagicMock()
        failing_tracker.record.side_effect = RuntimeError("disk full")
        ctrl = CostController(cost_tracker=failing_tracker)
        # 不应抛异常
        ctrl.record_usage(100, 50)
        assert ctrl._session.used_tokens == 150

    def test_no_cost_tracker_still_records(self):
        """无 CostTracker 时仍记录 token 计数"""
        ctrl = CostController(cost_tracker=None)
        ctrl.record_usage(100, 50)
        assert ctrl._session.used_tokens == 150


# ══════════════════════════════════════════════════════════
# TestHourlyReset — 小时重置
# ══════════════════════════════════════════════════════════


class TestHourlyReset:
    """_maybe_reset_hourly 小时计数器重置"""

    def test_resets_after_one_hour(self):
        ctrl = CostController(budget=TokenBudget(per_hour_limit=10000))
        ctrl.record_usage(1000, 500)
        assert ctrl._hourly.used_tokens == 1500
        # 模拟时间流逝超过 1 小时
        ctrl._hourly.last_reset = time.time() - 3700  # 1小时+100秒
        ctrl.check_before_call(100)
        assert ctrl._hourly.used_tokens == 0
        assert ctrl._hourly.request_count == 0

    def test_does_not_reset_within_hour(self):
        ctrl = CostController()
        ctrl.record_usage(100, 50)
        # 立即检查，不应重置
        ctrl.check_before_call(10)
        assert ctrl._hourly.used_tokens == 150

    def test_reset_hourly_method(self):
        """reset_hourly 强制重置（测试用）"""
        ctrl = CostController()
        ctrl.record_usage(500, 500)
        assert ctrl._hourly.used_tokens == 1000
        ctrl.reset_hourly()
        assert ctrl._hourly.used_tokens == 0

    def test_session_not_reset_by_hourly(self):
        """小时重置不影响会话计数"""
        ctrl = CostController(budget=TokenBudget(per_hour_limit=10000))
        ctrl.record_usage(1000, 500)
        ctrl._hourly.last_reset = time.time() - 3700
        ctrl.check_before_call(100)
        # 会话计数应保留
        assert ctrl._session.used_tokens == 1500


# ══════════════════════════════════════════════════════════
# TestUsageReport — 用量报告
# ══════════════════════════════════════════════════════════


class TestUsageReport:
    """get_usage_report 报告内容"""

    def test_empty_report(self):
        ctrl = CostController()
        report = ctrl.get_usage_report()
        assert report["session"]["tokens"] == 0
        assert report["hourly"]["tokens"] == 0
        assert report["per_request_limit"] == 100_000

    def test_report_after_usage(self):
        ctrl = CostController(budget=TokenBudget(
            per_request_limit=5000, per_session_limit=10000, per_hour_limit=50000,
        ))
        ctrl.record_usage(200, 100)
        ctrl.record_usage(300, 150)
        report = ctrl.get_usage_report()
        assert report["session"]["tokens"] == 750
        assert report["session"]["requests"] == 2
        assert report["hourly"]["tokens"] == 750
        assert report["session"]["limit"] == 10000

    def test_reset_session_clears_session_only(self):
        ctrl = CostController()
        ctrl.record_usage(100, 50)
        ctrl.reset_session()
        report = ctrl.get_usage_report()
        assert report["session"]["tokens"] == 0
        # 小时不重置
        assert report["hourly"]["tokens"] == 150


# ══════════════════════════════════════════════════════════
# TestSingleton — 全局单例与环境变量
# ══════════════════════════════════════════════════════════


class TestSingleton:
    """get_cost_controller 单例与环境变量配置"""

    def test_singleton_returns_same_instance(self, monkeypatch):
        reset_cost_controller()
        monkeypatch.delenv("PYCODER_TOKEN_REQUEST_LIMIT", raising=False)
        c1 = get_cost_controller()
        c2 = get_cost_controller()
        assert c1 is c2

    def test_env_var_overrides_budget(self, monkeypatch):
        reset_cost_controller()
        monkeypatch.setenv("PYCODER_TOKEN_REQUEST_LIMIT", "9999")
        monkeypatch.setenv("PYCODER_TOKEN_SESSION_LIMIT", "8888")
        monkeypatch.setenv("PYCODER_TOKEN_HOUR_LIMIT", "7777")
        ctrl = get_cost_controller()
        assert ctrl.budget.per_request_limit == 9999
        assert ctrl.budget.per_session_limit == 8888
        assert ctrl.budget.per_hour_limit == 7777
        reset_cost_controller()

    def test_reset_clears_singleton(self):
        c1 = get_cost_controller()
        reset_cost_controller()
        c2 = get_cost_controller()
        assert c1 is not c2
