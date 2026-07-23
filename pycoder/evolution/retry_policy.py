"""
失败分级重试策略 — 借鉴生产级 Agent 团队方案

分级:
  - TRANSIENT: 轻度异常（网络超时、临时锁），自动重试 3 次
  - PERMANENT: 重度异常（代码逻辑错误、权限不足），暂停 + 告警
  - FATAL: 致命异常（磁盘满、OOM），立即停止

用法:
  from pycoder.evolution.retry_policy import RetryPolicy, ErrorSeverity

  policy = RetryPolicy(max_retries=3)
  result = await policy.execute(lambda: risky_operation())
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class ErrorSeverity(StrEnum):
    """错误严重程度"""
    TRANSIENT = "transient"   # 可自动重试
    PERMANENT = "permanent"   # 需人工介入
    FATAL = "fatal"           # 立即停止


# ── 错误模式 → 严重程度映射 ──
_TRANSIENT_PATTERNS = [
    "timeout", "connection refused", "connection reset",
    "temporary failure", "try again", "rate limit",
    "too many requests", "service unavailable", "503",
    "network", "timed out", "deadlock", "lock",
    "resource temporarily unavailable",
]
_PERMANENT_PATTERNS = [
    "permission denied", "access denied", "unauthorized",
    "forbidden", "401", "403", "not found", "404",
    "invalid", "syntax error", "type error", "attribute error",
    "key error", "value error", "import error",
]
_FATAL_PATTERNS = [
    "out of memory", "disk full", "no space",
    "kernel", "segfault", "bus error",
    "system error", "fatal", "panic",
]


def classify_error(error: Exception | str) -> ErrorSeverity:
    """根据错误信息自动分类严重程度"""
    msg = str(error).lower() if isinstance(error, Exception) else error.lower()

    for pattern in _FATAL_PATTERNS:
        if pattern in msg:
            return ErrorSeverity.FATAL

    for pattern in _PERMANENT_PATTERNS:
        if pattern in msg:
            return ErrorSeverity.PERMANENT

    for pattern in _TRANSIENT_PATTERNS:
        if pattern in msg:
            return ErrorSeverity.TRANSIENT

    # 默认：未知错误视为永久错误，需人工确认
    return ErrorSeverity.PERMANENT


@dataclass
class RetryResult:
    """重试执行结果"""
    success: bool
    result: Any = None
    error: str = ""
    severity: ErrorSeverity = ErrorSeverity.PERMANENT
    attempts: int = 0
    total_duration_ms: float = 0.0
    retry_history: list[dict] = field(default_factory=list)


class RetryPolicy:
    """失败分级重试策略

    特性:
      - 自动识别错误类型，分级处理
      - TRANSIENT: 指数退避重试（1s, 2s, 4s）
      - PERMANENT: 立即停止，不重试
      - FATAL: 立即停止 + 严重告警
      - 支持自定义错误分类器
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_multiplier: float = 2.0,
        classifier: Callable[[Exception], ErrorSeverity] | None = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self._classifier = classifier or classify_error

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        context: str = "",
        **kwargs: Any,
    ) -> RetryResult:
        """执行函数，失败时按策略重试

        Args:
            func: 异步函数
            context: 调用上下文标识（用于日志）
            *args, **kwargs: 传递给 func 的参数

        Returns:
            RetryResult
        """
        start = time.monotonic()
        last_error: Exception | None = None
        history: list[dict] = []

        for attempt in range(1, self.max_retries + 2):  # 总尝试次数 = 1(首次) + max_retries
            try:
                result = await func(*args, **kwargs)
                duration = (time.monotonic() - start) * 1000
                logger.debug(
                    "retry_success attempt=%d/%d context=%s duration=%.1fms",
                    attempt, self.max_retries + 1, context, duration,
                )
                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt,
                    total_duration_ms=duration,
                    retry_history=history,
                )
            except Exception as e:
                last_error = e
                severity = self._classifier(e)
                error_info = {
                    "attempt": attempt,
                    "error": str(e)[:200],
                    "type": type(e).__name__,
                    "severity": severity.value,
                    "timestamp": time.time(),
                }
                history.append(error_info)

                if severity == ErrorSeverity.FATAL:
                    logger.critical(
                        "retry_fatal: context=%s error=%s attempt=%d",
                        context, str(e)[:200], attempt,
                    )
                    break

                if severity == ErrorSeverity.PERMANENT:
                    logger.warning(
                        "retry_permanent: context=%s error=%s attempt=%d",
                        context, str(e)[:200], attempt,
                    )
                    break

                if attempt > self.max_retries:
                    logger.warning(
                        "retry_exhausted: context=%s max_retries=%d error=%s",
                        context, self.max_retries, str(e)[:200],
                    )
                    break

                # TRANSIENT: 指数退避
                delay = min(self.base_delay * (self.backoff_multiplier ** (attempt - 1)), self.max_delay)
                logger.info(
                    "retry_wait: context=%s attempt=%d delay=%.1fs error=%s",
                    context, attempt, delay, str(e)[:100],
                )
                await asyncio.sleep(delay)

        duration = (time.monotonic() - start) * 1000
        return RetryResult(
            success=False,
            error=str(last_error) if last_error else "未知错误",
            severity=self._classifier(last_error) if last_error else ErrorSeverity.PERMANENT,
            attempts=len(history),
            total_duration_ms=duration,
            retry_history=history,
        )

    def execute_sync(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> RetryResult:
        """同步版本"""
        start = time.monotonic()
        last_error: Exception | None = None
        history: list[dict] = []

        for attempt in range(1, self.max_retries + 2):
            try:
                result = func(*args, **kwargs)
                return RetryResult(
                    success=True, result=result, attempts=attempt,
                    total_duration_ms=(time.monotonic() - start) * 1000,
                    retry_history=history,
                )
            except Exception as e:
                last_error = e
                severity = self._classifier(e)
                history.append({
                    "attempt": attempt, "error": str(e)[:200],
                    "type": type(e).__name__, "severity": severity.value,
                    "timestamp": time.time(),
                })
                if severity in (ErrorSeverity.FATAL, ErrorSeverity.PERMANENT):
                    break
                if attempt > self.max_retries:
                    break
                delay = min(self.base_delay * (self.backoff_multiplier ** (attempt - 1)), self.max_delay)
                time.sleep(delay)

        return RetryResult(
            success=False,
            error=str(last_error) if last_error else "未知错误",
            severity=self._classifier(last_error) if last_error else ErrorSeverity.PERMANENT,
            attempts=len(history),
            total_duration_ms=(time.monotonic() - start) * 1000,
            retry_history=history,
        )