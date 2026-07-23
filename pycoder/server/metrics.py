"""
Prometheus 指标暴露 — 为监控系统提供标准指标端点

暴露端点:
  GET /metrics — Prometheus 格式的指标数据

指标包括:
  - pycoder_requests_total — HTTP 请求计数
  - pycoder_request_duration_seconds — 请求延迟直方图
  - pycoder_llm_calls_total — LLM API 调用计数
  - pycoder_llm_tokens_total — LLM Token 消耗
  - pycoder_active_sessions — 活跃会话数
  - pycoder_errors_total — 错误计数
  - pycoder_pipeline_runs_total — 流水线执行计数
  - pycoder_memory_entries — 记忆条目数
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

# ── 简易指标存储（不依赖 prometheus_client 库）──

_METRICS: dict[str, float] = {}
_HISTOGRAMS: dict[str, list[float]] = {}
_START_TIMES: dict[str, float] = {}


def counter_inc(name: str, value: float = 1.0) -> None:
    """计数器递增"""
    _METRICS[name] = _METRICS.get(name, 0.0) + value


def gauge_set(name: str, value: float) -> None:
    """仪表设置"""
    _METRICS[name] = value


def histogram_observe(name: str, value: float) -> None:
    """直方图记录"""
    if name not in _HISTOGRAMS:
        _HISTOGRAMS[name] = []
    _HISTOGRAMS[name].append(value)


def track_time(name: str) -> None:
    """开始计时"""
    _START_TIMES[name] = time.time()


def stop_track(name: str) -> float:
    """停止计时并记录"""
    if name in _START_TIMES:
        elapsed = time.time() - _START_TIMES.pop(name)
        histogram_observe(name, elapsed)
        return elapsed
    return 0.0


# ── 中间件：自动记录请求指标 ──


async def metrics_middleware(request: Request, call_next: Any) -> Response:
    """自动记录所有 HTTP 请求的指标"""
    path = request.url.path
    method = request.method

    counter_inc("pycoder_requests_total")
    counter_inc(f"pycoder_requests_total{path.replace('/', '_')}")

    start = time.time()
    try:
        response = await call_next(request)
        status = str(response.status_code)
        counter_inc(f"pycoder_responses_total{status}")
        return response
    except Exception:
        counter_inc("pycoder_errors_total")
        counter_inc(f"pycoder_errors_total{path.replace('/', '_')}")
        raise
    finally:
        elapsed = time.time() - start
        histogram_observe("pycoder_request_duration_seconds", elapsed)
        histogram_observe(
            f"pycoder_request_duration_seconds_{method}_{path.replace('/', '_')}",
            elapsed,
        )


# ── Prometheus 格式输出 ──


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    """Prometheus 标准指标端点"""
    # 收集运行时指标
    _collect_runtime_metrics()

    lines = []

    # 计数器
    for name, value in sorted(_METRICS.items()):
        metric_name = _sanitize_metric_name(name)
        lines.append(f"# TYPE {metric_name} counter")
        lines.append(f"{metric_name} {value}")

    # 直方图
    for name, values in sorted(_HISTOGRAMS.items()):
        if not values:
            continue
        metric_name = _sanitize_metric_name(name)
        sorted_values = sorted(values)
        count = len(sorted_values)
        total = sum(sorted_values)

        lines.append(f"# TYPE {metric_name} histogram")
        lines.append(f"{metric_name}_count {count}")
        lines.append(f"{metric_name}_sum {total:.6f}")

        if count > 0:
            lines.append(f"{metric_name}_bucket{{le=\"0.1\"}} {_count_le(sorted_values, 0.1)}")
            lines.append(f"{metric_name}_bucket{{le=\"0.5\"}} {_count_le(sorted_values, 0.5)}")
            lines.append(f"{metric_name}_bucket{{le=\"1.0\"}} {_count_le(sorted_values, 1.0)}")
            lines.append(f"{metric_name}_bucket{{le=\"5.0\"}} {_count_le(sorted_values, 5.0)}")
            lines.append(f"{metric_name}_bucket{{le=\"+Inf\"}} {count}")

    # 进程信息
    import os
    lines.append(f"# TYPE pycoder_process_info gauge")
    lines.append(f"pycoder_process_info{{pid=\"{os.getpid()}\"}} 1")

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; charset=utf-8",
    )


def _collect_runtime_metrics() -> None:
    """收集运行时指标"""
    import os
    import sys

    # 内存使用
    try:
        import psutil
        process = psutil.Process()
        gauge_set("pycoder_memory_rss_bytes", process.memory_info().rss)
        gauge_set("pycoder_cpu_percent", process.cpu_percent())
    except ImportError:
        pass

    # Python 对象计数
    gauge_set("pycoder_python_version_major", sys.version_info.major)
    gauge_set("pycoder_python_version_minor", sys.version_info.minor)


def _sanitize_metric_name(name: str) -> str:
    """将内部名称转换为 Prometheus 兼容的指标名"""
    if name.startswith("pycoder_"):
        return name
    return f"pycoder_{name}"


def _count_le(values: list[float], le: float) -> int:
    """统计 <= le 的值数量"""
    return sum(1 for v in values if v <= le)


# ── 公开 API ──


def record_llm_call(
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost: float = 0.0,
    duration_ms: float = 0.0,
) -> None:
    """记录 LLM API 调用指标"""
    counter_inc("pycoder_llm_calls_total")
    counter_inc(f"pycoder_llm_calls_total_{model}")
    counter_inc("pycoder_llm_tokens_total", tokens_in + tokens_out)
    counter_inc("pycoder_llm_tokens_in_total", tokens_in)
    counter_inc("pycoder_llm_tokens_out_total", tokens_out)
    counter_inc("pycoder_llm_cost_total", cost)
    histogram_observe("pycoder_llm_duration_seconds", duration_ms / 1000.0)


def record_pipeline_run(status: str, duration_ms: float = 0.0) -> None:
    """记录流水线执行指标"""
    counter_inc("pycoder_pipeline_runs_total")
    counter_inc(f"pycoder_pipeline_runs_total_{status}")
    if duration_ms > 0:
        histogram_observe("pycoder_pipeline_duration_seconds", duration_ms / 1000.0)


def record_error(error_type: str) -> None:
    """记录错误指标"""
    counter_inc("pycoder_errors_total")
    counter_inc(f"pycoder_errors_total_{error_type}")


def set_active_sessions(count: int) -> None:
    """设置活跃会话数"""
    gauge_set("pycoder_active_sessions", count)


def set_memory_entries(count: int) -> None:
    """设置记忆条目数"""
    gauge_set("pycoder_memory_entries", count)