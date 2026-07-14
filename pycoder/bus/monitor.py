"""
可观测性 — 能力总线的全链路追踪与监控

提供每次能力调用的追踪、延迟监控和错误统计。
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any

from pycoder.bus.protocol import CapabilityCall, CapabilityResult, CallTrace, TrustLevel

logger = logging.getLogger(__name__)


class BusMonitor:
    """
    总线监控器 —— 全链路追踪和性能监控

    功能:
    - 每次能力调用的全链路追踪
    - 延迟、成功率、错误率实时监控
    - 能力调用图谱（谁调用了谁，频率如何）
    - 成本归因（每次调用的 token 消耗估算）
    """

    def __init__(self, max_traces: int = 10000):
        self._traces: list[CallTrace] = []
        self._max_traces = max_traces
        self._call_graph: dict[str, set[str]] = defaultdict(set)
        self._category_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "total_calls": 0,
            "success_calls": 0,
            "error_calls": 0,
            "total_latency_ms": 0.0,
        })

    def start_trace(self, call: CapabilityCall, definition: Any) -> CallTrace:
        """开始追踪一次调用"""
        trace = CallTrace(
            trace_id=call.trace_id,
            capability_id=call.capability_id,
            params_summary=self._summarize_params(call.params),
            permission_required=getattr(definition, 'permission', TrustLevel.READ_ONLY),
            permission_granted=True,
            user_confirmed=False,
            success=False,
            duration_ms=0.0,
            caller=call.caller,
            start_time=time.monotonic(),
        )
        return trace

    def end_trace(self, trace: CallTrace, result: CapabilityResult) -> None:
        """结束追踪"""
        trace.end_time = time.monotonic()
        trace.duration_ms = (trace.end_time - trace.start_time) * 1000
        trace.success = result.success
        trace.error = result.error

        self._traces.append(trace)
        if len(self._traces) > self._max_traces:
            self._traces = self._traces[-self._max_traces:]

        # 更新统计
        cap_id = trace.capability_id
        stats = self._category_stats[cap_id]
        stats["total_calls"] += 1
        if result.success:
            stats["success_calls"] += 1
        else:
            stats["error_calls"] += 1
        stats["total_latency_ms"] += trace.duration_ms

        # 更新调用图谱
        self._call_graph[trace.caller].add(cap_id)

    def get_recent_traces(self, limit: int = 100) -> list[CallTrace]:
        """获取最近的追踪记录"""
        return list(reversed(self._traces[-limit:]))

    def get_trace(self, trace_id: str) -> CallTrace | None:
        """根据 trace_id 查找追踪记录"""
        for t in self._traces:
            if t.trace_id == trace_id:
                return t
        return None

    def get_stats(self) -> dict[str, Any]:
        """获取全局统计信息"""
        total_calls = sum(s["total_calls"] for s in self._category_stats.values())
        total_errors = sum(s["error_calls"] for s in self._category_stats.values())

        return {
            "total_calls": total_calls,
            "total_errors": total_errors,
            "error_rate": total_errors / max(total_calls, 1),
            "avg_latency_ms": sum(s["total_latency_ms"] for s in self._category_stats.values()) / max(total_calls, 1),
            "per_capability": dict(self._category_stats),
            "call_graph": {k: list(v) for k, v in self._call_graph.items()},
            "traces_stored": len(self._traces),
        }

    def get_health_report(self) -> dict[str, Any]:
        """生成健康报告"""
        stats = self.get_stats()

        # 检测异常
        anomalies: list[str] = []
        for cap_id, cap_stats in self._category_stats.items():
            calls = cap_stats["total_calls"]
            if calls > 0:
                error_rate = cap_stats["error_calls"] / calls
                if error_rate > 0.1:
                    anomalies.append(f"{cap_id}: 错误率 {error_rate:.1%}")
                avg_latency = cap_stats["total_latency_ms"] / calls
                if avg_latency > 5000:
                    anomalies.append(f"{cap_id}: 平均延迟 {avg_latency:.0f}ms")

        return {
            **stats,
            "anomalies": anomalies,
            "healthy": len(anomalies) == 0,
            "report_time": time.time(),
        }

    def clear(self) -> None:
        """清空所有监控数据"""
        self._traces.clear()
        self._call_graph.clear()
        self._category_stats.clear()

    @staticmethod
    def _summarize_params(params: dict[str, Any], max_length: int = 200) -> str:
        """生成参数摘要（不记录敏感信息）"""
        safe_params = {}
        sensitive_keys = {"api_key", "password", "token", "secret", "key"}

        for k, v in params.items():
            if k.lower() in sensitive_keys:
                safe_params[k] = "***"
            elif isinstance(v, str) and len(v) > 100:
                safe_params[k] = v[:100] + "..."
            else:
                safe_params[k] = v

        summary = json.dumps(safe_params, ensure_ascii=False, default=str)
        return summary[:max_length]
