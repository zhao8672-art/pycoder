"""熔断器模块测试

覆盖:
  - CircuitConfig: 配置默认值与自定义
  - CircuitBreaker: 状态转换（CLOSED → OPEN → HALF_OPEN → CLOSED）
  - CircuitBreaker: before_call / record_success / record_failure
  - CircuitBreaker: 异步上下文管理器
  - CircuitBreaker: 统计信息与手动控制
  - CircuitBreakerRegistry: 注册表管理
  - CircuitBreakerOpenError: 异常类
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from pycoder.safety.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitConfig,
    CircuitState,
)


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


class CustomError(Exception):
    """自定义异常类型，用于测试 error_types 过滤"""


# ══════════════════════════════════════════════════════════
# CircuitConfig 测试
# ══════════════════════════════════════════════════════════


class TestCircuitConfig:
    """熔断器配置"""

    def test_default_values(self):
        """默认配置值"""
        config = CircuitConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 3
        assert config.timeout_seconds == 60.0
        assert config.half_open_max_requests == 1

    def test_custom_values(self):
        """自定义配置"""
        config = CircuitConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout_seconds=10.0,
            half_open_max_requests=5,
            error_types=(ValueError, KeyError),
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 2
        assert config.timeout_seconds == 10.0
        assert config.half_open_max_requests == 5


# ══════════════════════════════════════════════════════════
# CircuitBreaker 状态转换测试
# ══════════════════════════════════════════════════════════


class TestCircuitBreakerStateTransitions:
    """熔断器状态转换"""

    def test_initial_state_is_closed(self):
        """初始状态为 CLOSED"""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_open is False

    def test_transition_to_open_on_failures(self):
        """连续失败达到阈值后进入 OPEN 状态"""
        breaker = CircuitBreaker("test", CircuitConfig(failure_threshold=3))
        # 允许调用
        for _ in range(3):
            assert breaker.before_call() is True
            breaker.record_failure()
        # 达到阈值后应拒绝
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open is True

    def test_transition_to_half_open_after_timeout(self):
        """超时后从 OPEN 进入 HALF_OPEN"""
        breaker = CircuitBreaker("test", CircuitConfig(
            failure_threshold=1, timeout_seconds=0.01,
        ))
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # 等待超时
        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

    def test_transition_back_to_closed_on_success_in_half_open(self):
        """HALF_OPEN 状态下连续成功恢复到 CLOSED"""
        breaker = CircuitBreaker("test", CircuitConfig(
            failure_threshold=1, success_threshold=2,
            timeout_seconds=0.01, half_open_max_requests=3,
        ))
        # 触发熔断
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # 等待进入 HALF_OPEN
        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

        # 连续成功（half_open_max_requests=3 允许足够探测请求）
        for _ in range(2):
            assert breaker.before_call() is True
            breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_reopen_on_failure_in_half_open(self):
        """HALF_OPEN 状态下失败重新进入 OPEN"""
        breaker = CircuitBreaker("test", CircuitConfig(
            failure_threshold=1, timeout_seconds=0.01,
        ))
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

        # 探测失败
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


# ══════════════════════════════════════════════════════════
# CircuitBreaker 调用控制测试
# ══════════════════════════════════════════════════════════


class TestCircuitBreakerCallControl:
    """调用前检查与记录"""

    def test_before_call_allows_when_closed(self):
        """CLOSED 状态允许调用"""
        breaker = CircuitBreaker("test")
        assert breaker.before_call() is True

    def test_before_call_rejects_when_open(self):
        """OPEN 状态拒绝调用"""
        breaker = CircuitBreaker("test", CircuitConfig(failure_threshold=1))
        breaker.before_call()
        breaker.record_failure()
        assert breaker.before_call() is False

    def test_half_open_limits_requests(self):
        """HALF_OPEN 状态限制探测请求数"""
        breaker = CircuitBreaker("test", CircuitConfig(
            failure_threshold=1, timeout_seconds=0.01, half_open_max_requests=2,
        ))
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.02)
        assert breaker.state == CircuitState.HALF_OPEN

        # 允许前 2 个探测请求
        assert breaker.before_call() is True
        assert breaker.before_call() is True
        # 第 3 个被拒绝
        assert breaker.before_call() is False

    def test_record_success_resets_failure_count(self):
        """成功记录在 CLOSED 状态重置失败计数"""
        breaker = CircuitBreaker("test", CircuitConfig(failure_threshold=3))
        for _ in range(2):
            breaker.before_call()
            breaker.record_failure()
        # 还没到阈值
        assert breaker.state == CircuitState.CLOSED
        # 一次成功应重置
        breaker.before_call()
        breaker.record_success()
        # 再失败 2 次不应触发
        for _ in range(2):
            breaker.before_call()
            breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    def test_record_failure_with_non_matching_error_type(self):
        """不匹配的异常类型不计入失败"""
        breaker = CircuitBreaker("test", CircuitConfig(
            failure_threshold=2, error_types=(ValueError,),
        ))
        for _ in range(3):
            breaker.before_call()
            breaker.record_failure(CustomError("非标准错误"))
        # 不应触发熔断（CustomError 不在 error_types 中）
        assert breaker._failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    def test_record_failure_with_matching_error_type(self):
        """匹配的异常类型计入失败"""
        breaker = CircuitBreaker("test", CircuitConfig(
            failure_threshold=2, error_types=(ValueError, CustomError),
        ))
        for _ in range(2):
            breaker.before_call()
            breaker.record_failure(CustomError("匹配错误"))
        assert breaker.state == CircuitState.OPEN


# ══════════════════════════════════════════════════════════
# CircuitBreaker 手动控制与统计测试
# ══════════════════════════════════════════════════════════


class TestCircuitBreakerManualControl:
    """手动控制与统计"""

    def test_reset_restores_closed(self):
        """手动重置恢复到 CLOSED"""
        breaker = CircuitBreaker("test", CircuitConfig(failure_threshold=1))
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0
        assert breaker._success_count == 0

    def test_force_open(self):
        """强制断开"""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED
        breaker.force_open()
        assert breaker.state == CircuitState.OPEN

    def test_get_stats(self):
        """获取统计信息"""
        breaker = CircuitBreaker("file_ops")
        breaker.before_call()
        breaker.record_success()
        breaker.before_call()
        breaker.record_failure()

        stats = breaker.get_stats()
        assert stats["name"] == "file_ops"
        assert stats["state"] == CircuitState.CLOSED.value
        # before_call 和 record_* 各递增 total_calls，共 4 次
        assert stats["total_calls"] == 4
        assert stats["total_failures"] == 1
        assert 0 < stats["failure_rate"] < 1


# ══════════════════════════════════════════════════════════
# CircuitBreaker 异步上下文管理器测试
# ══════════════════════════════════════════════════════════


class TestCircuitBreakerAsyncContext:
    """异步上下文管理器"""

    @pytest.mark.asyncio
    async def test_successful_operation(self):
        """成功操作自动记录成功"""
        breaker = CircuitBreaker("test")
        async with breaker:
            pass  # 无异常
        # __aenter__ 调用 before_call，__aexit__ 调用 record_success
        # 各递增 total_calls 一次，共 2 次
        stats = breaker.get_stats()
        assert stats["total_calls"] == 2

    @pytest.mark.asyncio
    async def test_failed_operation(self):
        """失败操作自动记录失败"""
        breaker = CircuitBreaker("test", CircuitConfig(failure_threshold=5))

        class TestError(Exception):
            pass

        with pytest.raises(TestError):
            async with breaker:
                raise TestError("操作失败")

        # 失败应被记录
        stats = breaker.get_stats()
        assert stats["total_failures"] == 1

    @pytest.mark.asyncio
    async def test_open_breaker_raises(self):
        """熔断器断开时 __aenter__ 抛出异常"""
        breaker = CircuitBreaker("test", CircuitConfig(failure_threshold=1))
        breaker.before_call()
        breaker.record_failure()

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            async with breaker:
                pass
        assert "test" in str(exc_info.value)


# ══════════════════════════════════════════════════════════
# CircuitBreakerRegistry 测试
# ══════════════════════════════════════════════════════════


class TestCircuitBreakerRegistry:
    """熔断器注册表"""

    def test_get_or_create_creates_new(self):
        """获取不存在的熔断器时创建新实例"""
        registry = CircuitBreakerRegistry()
        breaker = registry.get_or_create("file_ops")
        assert isinstance(breaker, CircuitBreaker)
        assert breaker.name == "file_ops"

    def test_get_or_create_returns_existing(self):
        """获取已存在的熔断器返回同一实例"""
        registry = CircuitBreakerRegistry()
        b1 = registry.get_or_create("file_ops")
        b2 = registry.get_or_create("file_ops")
        assert b1 is b2

    def test_get_or_create_with_config(self):
        """创建时传入自定义配置"""
        registry = CircuitBreakerRegistry()
        config = CircuitConfig(failure_threshold=10)
        breaker = registry.get_or_create("custom", config)
        assert breaker.config.failure_threshold == 10

    def test_get_returns_none_for_missing(self):
        """获取不存在的熔断器返回 None"""
        registry = CircuitBreakerRegistry()
        assert registry.get("nonexistent") is None

    def test_get_returns_existing(self):
        """获取存在的熔断器"""
        registry = CircuitBreakerRegistry()
        registry.get_or_create("test_breaker")
        assert registry.get("test_breaker") is not None

    def test_get_all_stats(self):
        """获取所有熔断器统计"""
        registry = CircuitBreakerRegistry()
        registry.get_or_create("breaker_a")
        registry.get_or_create("breaker_b")
        stats = registry.get_all_stats()
        assert "breaker_a" in stats
        assert "breaker_b" in stats
        assert stats["breaker_a"]["state"] == CircuitState.CLOSED.value

    def test_reset_all(self):
        """重置所有熔断器"""
        registry = CircuitBreakerRegistry()
        b1 = registry.get_or_create("b1", CircuitConfig(failure_threshold=1))
        b2 = registry.get_or_create("b2", CircuitConfig(failure_threshold=1))

        # 触发两个熔断器
        b1.before_call()
        b1.record_failure()
        b2.before_call()
        b2.record_failure()
        assert b1.state == CircuitState.OPEN
        assert b2.state == CircuitState.OPEN

        registry.reset_all()
        assert b1.state == CircuitState.CLOSED
        assert b2.state == CircuitState.CLOSED


# ══════════════════════════════════════════════════════════
# CircuitBreakerOpenError 测试
# ══════════════════════════════════════════════════════════


class TestCircuitBreakerOpenError:
    """熔断器断开异常"""

    def test_error_message(self):
        """异常消息包含熔断器名称"""
        error = CircuitBreakerOpenError("my_breaker")
        assert "my_breaker" in str(error)
        assert error.breaker_name == "my_breaker"