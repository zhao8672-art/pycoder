"""P5: 可观测性 — 指标收集 + 分布式追踪

提供轻量级可观测性，不依赖外部库（OpenTelemetry 可选）:

  1. MetricsCollector — 计数器/直方图/仪表
     - API 调用次数、错误率
     - 延迟分布（P50/P95/P99）
     - Token 消耗

  2. TracingSpan — 分布式追踪（OpenTelemetry 可用时启用，否则 no-op）
     - span 上下文管理器
     - 属性标注

使用方式:
    from pycoder.server.services.observability import (
        get_metrics, track_latency, track_tokens,
    )

    # 记录指标
    metrics = get_metrics()
    metrics.increment("api_calls", labels={"endpoint": "/chat"})
    metrics.observe("latency_ms", 150.0, labels={"endpoint": "/chat"})

    # 追踪 span
    with tracing_span("chat_stream", attributes={"model": "deepseek-chat"}):
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 指标数据结构
# ══════════════════════════════════════════════════════════


@dataclass
class HistogramData:
    """直方图数据"""

    count: int = 0
    sum: float = 0.0
    min: float = float("inf")
    max: float = 0.0
    values: list[float] = field(default_factory=list)  # 保留最近 N 个用于分位数

    def observe(self, value: float, *, max_samples: int = 1000):
        self.count += 1
        self.sum += value
        self.min = min(self.min, value)
        self.max = max(self.max, value)
        self.values.append(value)
        # 保留最近 max_samples 个样本
        if len(self.values) > max_samples:
            self.values = self.values[-max_samples:]

    @property
    def avg(self) -> float:
        return self.sum / self.count if self.count > 0 else 0.0

    def percentile(self, p: float) -> float:
        """计算分位数（p ∈ [0, 100]，线性插值法）"""
        if not self.values:
            return 0.0
        sorted_vals = sorted(self.values)
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]
        # 线性插值法（与 numpy.percentile 默认一致）
        rank = p / 100 * (n - 1)
        lower = int(rank)
        upper = min(lower + 1, n - 1)
        frac = rank - lower
        return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


@dataclass
class CounterData:
    """计数器数据"""

    value: int = 0

    def increment(self, n: int = 1):
        self.value += n


# ══════════════════════════════════════════════════════════
# 指标收集器
# ══════════════════════════════════════════════════════════

_LabelKey = tuple[tuple[str, str], ...]


def _label_key(labels: dict[str, str] | None) -> _LabelKey:
    """将 labels dict 转为可哈希的 key"""
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


class MetricsCollector:
    """轻量级指标收集器（线程安全）

    支持三种指标类型:
      - Counter（计数器）: 单调递增，如 API 调用次数
      - Histogram（直方图）: 分布统计，如延迟
      - Gauge（仪表）: 任意值，如当前活跃会话数
    """

    def __init__(self):
        self._counters: dict[str, dict[_LabelKey, CounterData]] = defaultdict(dict)
        self._histograms: dict[str, dict[_LabelKey, HistogramData]] = defaultdict(dict)
        self._gauges: dict[str, dict[_LabelKey, float]] = defaultdict(dict)
        self._lock = threading.Lock()

    def increment(self, name: str, n: int = 1, *, labels: dict[str, str] | None = None):
        """计数器递增"""
        key = _label_key(labels)
        with self._lock:
            if key not in self._counters[name]:
                self._counters[name][key] = CounterData()
            self._counters[name][key].increment(n)

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None):
        """直方图观察值"""
        key = _label_key(labels)
        with self._lock:
            if key not in self._histograms[name]:
                self._histograms[name][key] = HistogramData()
            self._histograms[name][key].observe(value)

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None):
        """设置仪表值"""
        key = _label_key(labels)
        with self._lock:
            self._gauges[name][key] = value

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        key = _label_key(labels)
        with self._lock:
            data = self._counters.get(name, {}).get(key)
            return data.value if data else 0

    def get_histogram(self, name: str, labels: dict[str, str] | None = None) -> HistogramData:
        key = _label_key(labels)
        with self._lock:
            return self._histograms.get(name, {}).get(key, HistogramData())

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = _label_key(labels)
        with self._lock:
            return self._gauges.get(name, {}).get(key, 0.0)

    def snapshot(self) -> dict[str, Any]:
        """生成指标快照（用于 /metrics 端点）"""
        with self._lock:
            counters = {
                name: [{"labels": dict(k), "value": d.value} for k, d in labels_map.items()]
                for name, labels_map in self._counters.items()
            }
            histograms = {
                name: [
                    {
                        "labels": dict(k),
                        "count": d.count,
                        "sum": round(d.sum, 3),
                        "min": round(d.min, 3) if d.count > 0 else 0,
                        "max": round(d.max, 3),
                        "avg": round(d.avg, 3),
                        "p50": round(d.percentile(50), 3),
                        "p95": round(d.percentile(95), 3),
                        "p99": round(d.percentile(99), 3),
                    }
                    for k, d in labels_map.items()
                ]
                for name, labels_map in self._histograms.items()
            }
            gauges = {
                name: [{"labels": dict(k), "value": v} for k, v in labels_map.items()]
                for name, labels_map in self._gauges.items()
            }
        return {"counters": counters, "histograms": histograms, "gauges": gauges}

    def reset(self):
        """清空所有指标（测试用）"""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()


# ══════════════════════════════════════════════════════════
# 便捷装饰器/上下文管理器
# ══════════════════════════════════════════════════════════


@contextmanager
def track_latency(name: str, *, labels: dict[str, str] | None = None) -> Iterator[None]:
    """追踪代码块延迟

    Usage:
        with track_latency("chat_stream", labels={"model": "deepseek-chat"}):
            await bridge.chat_stream(message)
    """
    metrics = get_metrics()
    start = time.perf_counter()
    success = True
    try:
        yield
    except Exception:
        success = False
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        error_label = "false" if success else "true"
        merged_labels = {**(labels or {}), "error": error_label}
        metrics.observe(name, elapsed_ms, labels=merged_labels)
        metrics.increment(f"{name}_total", labels=merged_labels)


def track_tokens(model: str, input_tokens: int, output_tokens: int):
    """记录 token 消耗"""
    metrics = get_metrics()
    metrics.observe("input_tokens", input_tokens, labels={"model": model})
    metrics.observe("output_tokens", output_tokens, labels={"model": model})
    metrics.increment("token_total", input_tokens + output_tokens, labels={"model": model})


# ══════════════════════════════════════════════════════════
# 分布式追踪（OpenTelemetry 可选）
# ══════════════════════════════════════════════════════════

_tracer_available: bool | None = None
_tracer = None


def _init_tracer():
    """初始化 OpenTelemetry tracer（可选）"""
    global _tracer_available, _tracer
    if _tracer_available is not None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("pycoder")
        _tracer_available = True
        logger.info("otel_tracing_enabled")
    except ImportError:
        _tracer_available = False
        logger.debug("otel_tracing_disabled no_opentelemetry")


@contextmanager
def tracing_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """追踪 span（OpenTelemetry 可用时启用，否则 no-op）

    Usage:
        with tracing_span("chat_stream", attributes={"model": "deepseek-chat"}):
            ...
    """
    global _tracer_available
    if _tracer_available is None:
        _init_tracer()

    if _tracer_available and _tracer is not None:
        with _tracer.start_as_current_span(name) as span:
            if attributes:
                for k, v in attributes.items():
                    try:
                        span.set_attribute(k, v)
                    except (TypeError, ValueError):
                        pass
            yield span
    else:
        # no-op span
        yield None


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_metrics_instance: MetricsCollector | None = None
_metrics_lock = threading.Lock()


def get_metrics() -> MetricsCollector:
    """获取全局 MetricsCollector 单例"""
    global _metrics_instance
    if _metrics_instance is None:
        with _metrics_lock:
            if _metrics_instance is None:
                _metrics_instance = MetricsCollector()
    return _metrics_instance


__all__ = [
    "HistogramData",
    "CounterData",
    "MetricsCollector",
    "track_latency",
    "track_tokens",
    "tracing_span",
    "get_metrics",
]
