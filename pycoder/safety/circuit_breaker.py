"""
三级熔断器 — 借鉴生产级 Agent 团队方案

提供三种熔断:
1. 代码风险熔断: 检测高危代码自动阻断提交
2. 进度超时熔断: 子任务超时自动分析 + 预警
3. 权限操作熔断: 高危操作必须人工确认

用法:
  from pycoder.safety.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry

  cb = CircuitBreaker("self_evo", failure_threshold=3, recovery_timeout=300)
  if cb.is_open:
      return "熔断器已打开，拒绝执行"

  try:
      result = await risky_operation()
      cb.record_success()
  except Exception as e:
      cb.record_failure(e)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出的异常"""
    def __init__(self, name: str, last_error: str = ""):
        self.name = name
        self.breaker_name = name  # 兼容测试引用
        self.last_error = last_error
        super().__init__(f"熔断器 [{name}] 已打开: {last_error}")


class CircuitState(StrEnum):
    """熔断器状态"""
    CLOSED = "closed"           # 正常
    OPEN = "open"               # 已熔断
    HALF_OPEN = "half_open"     # 半开（试探性恢复）


class RiskLevel(StrEnum):
    """操作风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── 高危代码模式 ──
_HIGH_RISK_PATTERNS = [
    r"rm\s+-rf\s+/",                    # 删除根目录
    r"os\.system\(.*rm\s+-rf",          # 调用系统删除
    r"DROP\s+(TABLE|DATABASE)",         # 删库
    r"DELETE\s+FROM\s+\w+\s*$",        # 无 WHERE 的 DELETE
    r"eval\(.*__import__",              # 动态 eval 导入
    r"exec\(.*input",                   # exec 用户输入
    r"subprocess\.call\(.*shell=True",  # shell=True 风险
    r"pickle\.loads",                   # 不安全的反序列化
    r"yaml\.load\(.*Loader=yaml\.Loader",  # 不安全的 YAML
    r"__import__\(.*os\.",              # 动态导入 OS 模块
]


def scan_code_risk(code: str) -> list[dict[str, Any]]:
    """扫描代码中的高危模式

    Returns:
        [{"pattern": "rm -rf /", "severity": "critical", "line": 5}, ...]
    """
    import re

    risks: list[dict[str, Any]] = []
    for line_no, line in enumerate(code.split("\n"), 1):
        for pattern in _HIGH_RISK_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                risks.append({
                    "pattern": pattern,
                    "severity": "critical",
                    "line": line_no,
                    "content": line.strip()[:100],
                })
    return risks


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5          # 连续失败次数阈值
    success_threshold: int = 3          # 半开状态需连续成功次数
    timeout_seconds: float = 60.0       # 恢复超时（秒）
    half_open_max_requests: int = 1     # 半开状态最大探测请求数
    error_types: tuple[type[Exception], ...] = ()  # 计入失败的异常类型（空=全部计入）
    recovery_timeout: float = 300.0     # 恢复超时（秒）— 兼容旧代码
    progress_timeout: float = 600.0     # 进度超时（秒）
    risk_level: RiskLevel = RiskLevel.MEDIUM


CircuitConfig = CircuitBreakerConfig  # 别名，兼容测试引用


class CircuitBreaker:
    """熔断器 — 防止级联失败

    状态机:
      CLOSED → (连续失败 >= threshold) → OPEN
      OPEN → (等待 recovery_timeout) → HALF_OPEN
      HALF_OPEN → (连续成功 >= success_threshold) → CLOSED
      HALF_OPEN → (失败) → OPEN
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_count = 0       # 半开状态已处理的请求数
        self._last_failure_time: float = 0.0
        self._last_success_time: float = 0.0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._total_calls: int = 0
        self._last_error: str = ""
        self._created_at = time.time()

    @property
    def state(self) -> CircuitState:
        """当前状态（自动检测 OPEN → HALF_OPEN 转换）"""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.config.timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                self._half_open_count = 0
                logger.info("circuit_half_open: name=%s", self.name)
        return self._state

    @property
    def is_open(self) -> bool:
        """检查是否已熔断"""
        return self.state == CircuitState.OPEN

    def before_call(self) -> bool:
        """调用前检查 — 如果熔断器打开则返回 False

        Returns:
            True 如果允许调用
        """
        if self.is_open:
            return False

        # HALF_OPEN 状态限制探测请求数
        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_count >= self.config.half_open_max_requests:
                return False
            self._half_open_count += 1

        self._total_calls += 1
        return True

    def force_open(self) -> None:
        """强制断开熔断器"""
        self._state = CircuitState.OPEN
        self._last_failure_time = time.time()

    async def __aenter__(self):
        """异步上下文管理器入口"""
        if self.is_open:
            raise CircuitBreakerOpenError(self.name, self._last_error)
        self._total_calls += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type is not None:
            self.record_failure(str(exc_val) if exc_val else "")
        else:
            self.record_success()
        return False  # 不抑制异常

    def record_success(self) -> None:
        """记录成功"""
        self._total_calls += 1
        self._success_count += 1
        self._total_successes += 1
        self._last_success_time = time.time()

        if self._state == CircuitState.CLOSED:
            # 在 CLOSED 状态成功时重置失败计数
            self._failure_count = 0
        elif self._state == CircuitState.HALF_OPEN:
            if self._success_count >= self.config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_count = 0
                logger.info("circuit_closed: name=%s", self.name)

    def record_failure(self, error: Exception | str = "") -> None:
        """记录失败

        Args:
            error: 异常对象或错误描述字符串
        """
        # 如果配置了 error_types，检查是否匹配
        if self.config.error_types and isinstance(error, Exception):
            if not isinstance(error, self.config.error_types):
                # 不匹配的异常类型不计入失败
                return

        self._total_calls += 1
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.time()
        self._last_error = str(error)[:200] if error else ""

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("circuit_reopened: name=%s", self.name)
        elif self._failure_count >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_open: name=%s failures=%d error=%s",
                self.name, self._failure_count, self._last_error[:100],
            )

    def reset(self) -> None:
        """手动重置熔断器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_count = 0
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._last_error = ""
        logger.info("circuit_reset: name=%s", self.name)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = self._total_calls
        return {
            "name": self.name,
            "state": self.state.value,
            "total_calls": total,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "failure_rate": self._total_failures / max(total, 1),
            "last_error": self._last_error[:200],
            "last_failure_time": self._last_failure_time,
            "uptime": time.time() - self._created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "last_error": self._last_error[:200],
            "last_failure_time": self._last_failure_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "progress_timeout": self.config.progress_timeout,
            },
        }


class CircuitBreakerRegistry:
    """熔断器注册表 — 全局管理所有熔断器"""

    _instance: CircuitBreakerRegistry | None = None
    _breakers: dict[str, CircuitBreaker] = {}

    def __new__(cls) -> CircuitBreakerRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get(self, name: str) -> CircuitBreaker | None:
        """获取熔断器，不存在时返回 None"""
        return self._breakers.get(name)

    def get_or_create(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get_all(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器状态"""
        return {name: cb.to_dict() for name, cb in self._breakers.items()}

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器统计信息"""
        return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """重置所有熔断器"""
        for cb in self._breakers.values():
            cb.reset()

    def check_progress_timeout(
        self,
        name: str,
        start_time: float,
        timeout: float | None = None,
    ) -> bool:
        """检查任务是否超时

        Returns:
            True 如果已超时
        """
        cb = self.get_or_create(name)
        effective_timeout = timeout or cb.config.progress_timeout
        elapsed = time.time() - start_time
        if elapsed > effective_timeout:
            logger.warning(
                "progress_timeout: name=%s elapsed=%.0fs timeout=%.0fs",
                name, elapsed, effective_timeout,
            )
            cb.record_failure(f"进度超时: {elapsed:.0f}s > {effective_timeout:.0f}s")
            return True
        return False