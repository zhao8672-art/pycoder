"""P5: 可观测性测试 — 指标收集 + 追踪

覆盖:
  - MetricsCollector: Counter/Histogram/Gauge
  - track_latency: 延迟追踪上下文
  - track_tokens: token 消耗记录
  - tracing_span: OpenTelemetry 可选追踪（no-op fallback）
  - snapshot: 指标快照导出
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from pycoder.server.services.observability import (
    CounterData,
    HistogramData,
    MetricsCollector,
    get_metrics,
    track_latency,
    track_tokens,
    tracing_span,
)


# ══════════════════════════════════════════════════════════
# MetricsCollector
# ══════════════════════════════════════════════════════════


class TestCounter:

    def test_increment(self):
        m = MetricsCollector()
        m.increment("api_calls")
        assert m.get_counter("api_calls") == 1

    def test_increment_with_n(self):
        m = MetricsCollector()
        m.increment("requests", 5)
        assert m.get_counter("requests") == 5

    def test_increment_with_labels(self):
        m = MetricsCollector()
        m.increment("calls", labels={"endpoint": "/chat"})
        m.increment("calls", labels={"endpoint": "/chat"})
        m.increment("calls", labels={"endpoint": "/code"})
        assert m.get_counter("calls", {"endpoint": "/chat"}) == 2
        assert m.get_counter("calls", {"endpoint": "/code"}) == 1

    def test_nonexistent_counter_returns_zero(self):
        m = MetricsCollector()
        assert m.get_counter("nonexistent") == 0


class TestHistogram:

    def test_observe(self):
        m = MetricsCollector()
        m.observe("latency", 100.0)
        m.observe("latency", 200.0)
        m.observe("latency", 300.0)
        h = m.get_histogram("latency")
        assert h.count == 3
        assert h.sum == 600.0
        assert h.min == 100.0
        assert h.max == 300.0
        assert h.avg == 200.0

    def test_percentile(self):
        m = MetricsCollector()
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            m.observe("lat", v)
        h = m.get_histogram("lat")
        # 线性插值法：P50 = 55, P95 ≈ 95.5, P99 ≈ 99.1
        assert 50 <= h.percentile(50) <= 60
        assert 90 <= h.percentile(95) <= 100
        assert 95 <= h.percentile(99) <= 100

    def test_observe_with_labels(self):
        m = MetricsCollector()
        m.observe("latency", 100, labels={"model": "a"})
        m.observe("latency", 200, labels={"model": "b"})
        ha = m.get_histogram("latency", {"model": "a"})
        hb = m.get_histogram("latency", {"model": "b"})
        assert ha.avg == 100
        assert hb.avg == 200

    def test_empty_histogram(self):
        m = MetricsCollector()
        h = m.get_histogram("nonexistent")
        assert h.count == 0
        assert h.percentile(50) == 0.0

    def test_max_samples_limit(self):
        """直方图保留最近 N 个样本"""
        m = MetricsCollector()
        for i in range(1500):
            m.observe("lat", float(i))
        h = m.get_histogram("lat")
        assert len(h.values) == 1000  # max_samples
        assert h.count == 1500  # 总计数仍记录


class TestGauge:

    def test_set_and_get(self):
        m = MetricsCollector()
        m.set_gauge("active_sessions", 5)
        assert m.get_gauge("active_sessions") == 5.0

    def test_overwrite(self):
        m = MetricsCollector()
        m.set_gauge("temp", 10)
        m.set_gauge("temp", 20)
        assert m.get_gauge("temp") == 20.0

    def test_with_labels(self):
        m = MetricsCollector()
        m.set_gauge("memory", 100, labels={"service": "a"})
        m.set_gauge("memory", 200, labels={"service": "b"})
        assert m.get_gauge("memory", {"service": "a"}) == 100
        assert m.get_gauge("memory", {"service": "b"}) == 200


# ══════════════════════════════════════════════════════════
# track_latency
# ══════════════════════════════════════════════════════════


class TestTrackLatency:

    def test_records_latency_on_success(self):
        metrics = MetricsCollector()
        with patch("pycoder.server.services.observability.get_metrics",
                   return_value=metrics):
            with track_latency("test_op", labels={"tag": "x"}):
                time.sleep(0.01)
        h = metrics.get_histogram("test_op", {"tag": "x", "error": "false"})
        assert h.count == 1
        assert h.avg >= 10  # 至少 10ms

    def test_records_error_on_exception(self):
        metrics = MetricsCollector()
        with patch("pycoder.server.services.observability.get_metrics",
                   return_value=metrics):
            with pytest.raises(ValueError):
                with track_latency("failing_op"):
                    raise ValueError("boom")
        counter = metrics.get_counter("failing_op_total",
                                       {"error": "true"})
        assert counter == 1

    def test_increments_counter(self):
        metrics = MetricsCollector()
        with patch("pycoder.server.services.observability.get_metrics",
                   return_value=metrics):
            with track_latency("op"):
                pass
        assert metrics.get_counter("op_total", {"error": "false"}) == 1


# ══════════════════════════════════════════════════════════
# track_tokens
# ══════════════════════════════════════════════════════════


class TestTrackTokens:

    def test_records_token_usage(self):
        metrics = MetricsCollector()
        with patch("pycoder.server.services.observability.get_metrics",
                   return_value=metrics):
            track_tokens("deepseek-chat", 100, 50)
        input_h = metrics.get_histogram("input_tokens", {"model": "deepseek-chat"})
        output_h = metrics.get_histogram("output_tokens", {"model": "deepseek-chat"})
        assert input_h.count == 1
        assert input_h.sum == 100
        assert output_h.sum == 50
        total = metrics.get_counter("token_total", {"model": "deepseek-chat"})
        assert total == 150


# ══════════════════════════════════════════════════════════
# tracing_span
# ══════════════════════════════════════════════════════════


class TestTracingSpan:

    def test_span_context_manager(self):
        """tracing_span 作为上下文管理器可用"""
        with tracing_span("test_span") as span:
            # 无 OpenTelemetry 时 span 为 None
            pass

    def test_span_with_attributes(self):
        with tracing_span("test", attributes={"key": "value"}):
            pass

    def test_span_no_op_when_otel_unavailable(self, monkeypatch):
        """OpenTelemetry 不可用时 span 为 None（no-op）"""
        import pycoder.server.services.observability as obs
        monkeypatch.setattr(obs, "_tracer_available", False)
        monkeypatch.setattr(obs, "_tracer", None)
        with tracing_span("no_otel") as span:
            assert span is None


# ══════════════════════════════════════════════════════════
# snapshot
# ══════════════════════════════════════════════════════════


class TestSnapshot:

    def test_snapshot_contains_all_metric_types(self):
        m = MetricsCollector()
        m.increment("counter1")
        m.observe("hist1", 100)
        m.set_gauge("gauge1", 5)
        snap = m.snapshot()
        assert "counters" in snap
        assert "histograms" in snap
        assert "gauges" in snap
        assert "counter1" in snap["counters"]
        assert "hist1" in snap["histograms"]
        assert "gauge1" in snap["gauges"]

    def test_histogram_snapshot_includes_percentiles(self):
        m = MetricsCollector()
        for v in [10, 20, 30, 40, 50]:
            m.observe("lat", v)
        snap = m.snapshot()
        hist = snap["histograms"]["lat"][0]
        assert "p50" in hist
        assert "p95" in hist
        assert "p99" in hist
        assert "avg" in hist
        assert hist["count"] == 5

    def test_reset_clears_all(self):
        m = MetricsCollector()
        m.increment("c1")
        m.observe("h1", 1.0)
        m.set_gauge("g1", 1)
        m.reset()
        assert m.get_counter("c1") == 0
        assert m.get_histogram("h1").count == 0
        assert m.get_gauge("g1") == 0.0


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestSingleton:

    def test_get_metrics_returns_same_instance(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


# ══════════════════════════════════════════════════════════
# 线程安全
# ══════════════════════════════════════════════════════════


class TestThreadSafety:

    def test_concurrent_increment(self):
        """多线程并发递增不丢数据"""
        import threading
        m = MetricsCollector()
        def worker():
            for _ in range(100):
                m.increment("concurrent")
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert m.get_counter("concurrent") == 1000
