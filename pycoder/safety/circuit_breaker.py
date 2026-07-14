"""
熔断器 — 异常检测与自动保护

防止 AI 陷入失败-重试循环或触发级联故障。
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(str, enum.Enum):
    """熔断器状态"""
    CLOSED = "closed"            # 正常，允许调用
    OPEN = "open"                # 熔断，拒绝调用
    HALF_OPEN = "half_open"      # 半开，探测性尝试


@dataclass
class CircuitConfig:
    """熔断器配置"""
    failure_threshold: int = 5           # 连续失败 N 次后熔断
    success_threshold: int = 3           # 半开状态下连续成功 N 次后恢复
    timeout_seconds: float = 60.0        # 熔断持续时间
    half_open_max_requests: int = 1      # 半开状态下允许的探测请求数
    error_types: tuple[type[Exception], ...] = (Exception,)  # 计为失败的异常类型


class CircuitBreaker:
    """
    熔断器

    三种状态:
    - CLOSED: 正常工作，统计失败次数
    - OPEN: 熔断中，快速失败
    - HALF_OPEN: 探测恢复，有限通过

    使用方式:
        breaker = CircuitBreaker("file_operations")

        async with breaker:
            result = await do_something()
            breaker.record_success()
    """

    def __init__(self, name: str, config: CircuitConfig | None = None):
        self.name = name
        self.config = config or CircuitConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._last_state_change: float = time.time()
        self._total_calls = 0
        self._total_failures = 0
        self._half_open_requests = 0

    @property
    def state(self) -> CircuitState:
        """当前状态"""
        self._maybe_transition()
        return self._state

    @property
    def is_open(self) -> bool:
        """是否处于熔断状态"""
        return self.state == CircuitState.OPEN

    def before_call(self) -> bool:
        """
        调用前检查 —— 返回是否可以调用

        Returns:
            True 如果允许调用，False 如果需要拒绝
        """
        self._maybe_transition()

        if self._state == CircuitState.OPEN:
            logger.warning("熔断器 '%s' 已断开，拒绝调用", self.name)
            return False

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_requests >= self.config.half_open_max_requests:
                logger.info("熔断器 '%s' 半开状态探测请求已达上限", self.name)
                return False
            self._half_open_requests += 1

        self._total_calls += 1
        return True

    def record_success(self) -> None:
        """记录成功"""
        self._total_calls += 1

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
                logger.info("熔断器 '%s' 已恢复 (半开 → 关闭)", self.name)
        else:
            # CLOSED 状态，重置失败计数
            self._failure_count = 0

    def record_failure(self, error: Exception | None = None) -> None:
        """记录失败"""
        self._total_calls += 1
        self._total_failures += 1

        if error and not isinstance(error, self.config.error_types):
            return  # 不计入熔断统计

        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态下失败 → 重新熔断
            self._transition_to(CircuitState.OPEN)
            logger.warning("熔断器 '%s' 半开探测失败，重新熔断", self.name)
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
                logger.error(
                    "熔断器 '%s' 已断开! 连续 %d 次失败",
                    self.name, self._failure_count,
                )

    def reset(self) -> None:
        """手动重置熔断器"""
        self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
        self._half_open_requests = 0

    def force_open(self) -> None:
        """强制断开"""
        self._transition_to(CircuitState.OPEN)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "failure_rate": self._total_failures / max(self._total_calls, 1),
            "last_failure_time": self._last_failure_time,
            "last_state_change": self._last_state_change,
        }

    # ── 私有方法 ───────────────────────────

    def _maybe_transition(self) -> None:
        """检查是否需要状态转换"""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.config.timeout_seconds:
                self._transition_to(CircuitState.HALF_OPEN)
                logger.info("熔断器 '%s' 超时，进入半开状态", self.name)

    def _transition_to(self, new_state: CircuitState) -> None:
        """执行状态转换"""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self._success_count = 0
            self._half_open_requests = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_requests = 0

        logger.debug(
            "熔断器 '%s': %s → %s", self.name, old_state.value, new_state.value,
        )

    async def __aenter__(self) -> "CircuitBreaker":
        if not self.before_call():
            raise CircuitBreakerOpenError(self.name)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.record_failure(exc_val)
            return False  # 继续传播异常
        self.record_success()
        return False


class CircuitBreakerOpenError(Exception):
    """熔断器断开异常"""

    def __init__(self, breaker_name: str):
        self.breaker_name = breaker_name
        super().__init__(f"熔断器 '{breaker_name}' 已断开，操作被拒绝")


class CircuitBreakerRegistry:
    """
    熔断器注册表 —— 管理多个能力对应的熔断器
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        config: CircuitConfig | None = None,
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """获取熔断器"""
        return self._breakers.get(name)

    def reset_all(self) -> None:
        """重置所有熔断器"""
        for breaker in self._breakers.values():
            breaker.reset()

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器状态"""
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}
