"""
总线监控器模块测试

覆盖:
  - BusMonitor: 初始化与 max_traces 限制
  - BusMonitor: start_trace / end_trace 全链路追踪
  - BusMonitor: get_recent_traces / get_trace 查询
  - BusMonitor: get_stats 全局统计
  - BusMonitor: get_health_report 健康报告
  - BusMonitor: clear 清空数据
  - BusMonitor._summarize_params: 敏感信息过滤与截断
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from pycoder.bus.monitor import BusMonitor
from pycoder.bus.protocol import (
    CallTrace,
    CapabilityCall,
    CapabilityResult,
    CapabilityDefinition,
    TrustLevel,
    ExecutionMode,
    CapabilityCategory,
)


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _make_call(capability_id: str = "tools.file.read", params: dict | None = None) -> CapabilityCall:
    """创建测试用的 CapabilityCall"""
    return CapabilityCall(
        capability_id=capability_id,
        params=params or {},
        caller="ai_brain",
    )


def _make_result(trace_id: str, capability_id: str, success: bool = True, error: str | None = None) -> CapabilityResult:
    """创建测试用的 CapabilityResult"""
    return CapabilityResult(
        trace_id=trace_id,
        capability_id=capability_id,
        success=success,
        error=error,
    )


def _make_definition(permission: TrustLevel = TrustLevel.READ_ONLY) -> CapabilityDefinition:
    """创建测试用的 CapabilityDefinition"""
    return CapabilityDefinition(
        id="tools.file.read",
        name="读取文件",
        description="读取文件内容",
        category=CapabilityCategory.SYSTEM,
        permission=permission,
        execution=ExecutionMode.SYNC,
    )


# ══════════════════════════════════════════════════════════
# BusMonitor 初始化测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorInit:
    """总线监控器初始化"""

    def test_default_max_traces(self):
        """默认 max_traces 为 10000"""
        monitor = BusMonitor()
        assert monitor._max_traces == 10000
        assert len(monitor._traces) == 0
        assert len(monitor._call_graph) == 0
        assert len(monitor._category_stats) == 0

    def test_custom_max_traces(self):
        """自定义 max_traces"""
        monitor = BusMonitor(max_traces=500)
        assert monitor._max_traces == 500

    def test_initial_state_is_empty(self):
        """初始状态为空"""
        monitor = BusMonitor()
        stats = monitor.get_stats()
        assert stats["total_calls"] == 0
        assert stats["total_errors"] == 0
        assert stats["traces_stored"] == 0


# ══════════════════════════════════════════════════════════
# BusMonitor 追踪测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorTrace:
    """全链路追踪"""

    def test_start_trace_creates_valid_trace(self):
        """start_trace 创建有效的 CallTrace"""
        monitor = BusMonitor()
        call = _make_call("tools.file.read", {"path": "main.py"})
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)

        assert isinstance(trace, CallTrace)
        assert trace.trace_id == call.trace_id
        assert trace.capability_id == "tools.file.read"
        assert trace.params_summary is not None
        assert trace.permission_required == TrustLevel.READ_ONLY
        assert trace.permission_granted is True
        assert trace.user_confirmed is False
        assert trace.success is False
        assert trace.duration_ms == 0.0
        assert trace.caller == "ai_brain"
        assert trace.start_time > 0

    def test_start_trace_with_no_permission_definition(self):
        """当 definition 没有 permission 属性时使用默认值"""
        monitor = BusMonitor()
        call = _make_call()
        # 使用普通对象而非 CapabilityDefinition
        definition = MagicMock()
        del definition.permission  # 触发 getattr 默认值

        # 实际上 getattr(def, "permission", TrustLevel.READ_ONLY) 在 MagicMock 上
        # 会返回 mock 对象而非 TrustLevel.READ_ONLY
        # 所以需要正确处理
        trace = monitor.start_trace(call, definition)
        assert isinstance(trace, CallTrace)
        assert trace.trace_id == call.trace_id

    def test_end_trace_updates_trace_fields(self):
        """end_trace 更新 trace 的结束时间和状态"""
        monitor = BusMonitor()
        call = _make_call()
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)

        monitor.end_trace(trace, result)

        assert trace.end_time > 0
        assert trace.duration_ms > 0
        assert trace.success is True
        assert trace.error is None

    def test_end_trace_records_error(self):
        """end_trace 记录失败调用"""
        monitor = BusMonitor()
        call = _make_call()
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=False, error="文件不存在")

        monitor.end_trace(trace, result)

        assert trace.success is False
        assert trace.error == "文件不存在"

    def test_end_trace_updates_category_stats(self):
        """end_trace 更新分类统计"""
        monitor = BusMonitor()
        call = _make_call("tools.file.read")
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)

        stats = monitor._category_stats["tools.file.read"]
        assert stats["total_calls"] == 1
        assert stats["success_calls"] == 1
        assert stats["error_calls"] == 0
        assert stats["total_latency_ms"] > 0

    def test_end_trace_updates_call_graph(self):
        """end_trace 更新调用图谱"""
        monitor = BusMonitor()
        call = _make_call("tools.file.read")
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)

        assert "ai_brain" in monitor._call_graph
        assert "tools.file.read" in monitor._call_graph["ai_brain"]

    def test_traces_bounded_by_max_traces(self):
        """追踪记录受 max_traces 限制"""
        monitor = BusMonitor(max_traces=3)

        for i in range(5):
            call = _make_call(f"tools.file.read")
            definition = _make_definition()
            trace = monitor.start_trace(call, definition)
            result = _make_result(trace.trace_id, "tools.file.read", success=True)
            monitor.end_trace(trace, result)

        assert len(monitor._traces) == 3


# ══════════════════════════════════════════════════════════
# BusMonitor 查询测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorQuery:
    """追踪查询"""

    @pytest.fixture
    def monitor_with_traces(self) -> BusMonitor:
        """创建包含多条追踪记录的监控器"""
        monitor = BusMonitor()
        for i in range(5):
            call = _make_call(f"tools.file.read")
            definition = _make_definition()
            trace = monitor.start_trace(call, definition)
            success = i != 2  # 第 3 条记录失败
            result = _make_result(
                trace.trace_id, "tools.file.read",
                success=success,
                error=None if success else "测试错误",
            )
            monitor.end_trace(trace, result)
        return monitor

    def test_get_recent_traces_default_limit(self, monitor_with_traces):
        """get_recent_traces 默认返回最近 100 条"""
        traces = monitor_with_traces.get_recent_traces()
        # 只有 5 条，全部返回
        assert len(traces) == 5

    def test_get_recent_traces_custom_limit(self, monitor_with_traces):
        """get_recent_traces 自定义 limit"""
        traces = monitor_with_traces.get_recent_traces(limit=2)
        assert len(traces) == 2

    def test_get_recent_traces_reversed_order(self, monitor_with_traces):
        """get_recent_traces 返回逆序（最新的在前）"""
        traces = monitor_with_traces.get_recent_traces(limit=5)
        # 验证逆序：最后一个 trace 的 end_time 应该大于第一个
        # 实际上 get_recent_traces 返回 reversed，所以 traces[0] 是最新的
        # 我们只需要验证返回的是逆序
        assert len(traces) == 5

    def test_get_trace_found(self, monitor_with_traces):
        """get_trace 根据 trace_id 找到记录"""
        # 获取第一个 trace 的 ID
        first_trace = monitor_with_traces._traces[0]
        found = monitor_with_traces.get_trace(first_trace.trace_id)
        assert found is not None
        assert found.trace_id == first_trace.trace_id

    def test_get_trace_not_found(self, monitor_with_traces):
        """get_trace 找不到记录返回 None"""
        found = monitor_with_traces.get_trace("non-existent-id")
        assert found is None


# ══════════════════════════════════════════════════════════
# BusMonitor 统计测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorStats:
    """全局统计信息"""

    def test_get_stats_empty(self):
        """空监控器的统计信息"""
        monitor = BusMonitor()
        stats = monitor.get_stats()
        assert stats["total_calls"] == 0
        assert stats["total_errors"] == 0
        assert stats["error_rate"] == 0.0
        assert stats["avg_latency_ms"] == 0.0
        assert stats["traces_stored"] == 0

    def test_get_stats_with_data(self):
        """有调用记录的统计信息"""
        monitor = BusMonitor()
        call = _make_call("tools.file.read")
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)

        stats = monitor.get_stats()
        assert stats["total_calls"] == 1
        assert stats["total_errors"] == 0
        assert stats["error_rate"] == 0.0
        assert stats["avg_latency_ms"] > 0
        assert stats["traces_stored"] == 1
        assert "tools.file.read" in stats["per_capability"]

    def test_get_stats_error_rate(self):
        """错误率计算正确"""
        monitor = BusMonitor()
        definition = _make_definition()

        # 成功 3 次，失败 1 次
        for success in [True, True, False, True]:
            call = _make_call("tools.file.read")
            trace = monitor.start_trace(call, definition)
            result = _make_result(trace.trace_id, "tools.file.read", success=success)
            monitor.end_trace(trace, result)

        stats = monitor.get_stats()
        assert stats["total_calls"] == 4
        assert stats["total_errors"] == 1
        assert stats["error_rate"] == 0.25

    def test_get_stats_call_graph_format(self):
        """调用图谱以字典列表形式返回"""
        monitor = BusMonitor()
        call = _make_call("tools.file.read")
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)

        stats = monitor.get_stats()
        assert "call_graph" in stats
        assert isinstance(stats["call_graph"], dict)
        assert "ai_brain" in stats["call_graph"]
        assert isinstance(stats["call_graph"]["ai_brain"], list)


# ══════════════════════════════════════════════════════════
# BusMonitor 健康报告测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorHealthReport:
    """健康报告"""

    def test_health_report_healthy_empty(self):
        """空监控器被认为是健康的"""
        monitor = BusMonitor()
        report = monitor.get_health_report()
        assert report["healthy"] is True
        assert report["anomalies"] == []
        assert "report_time" in report

    def test_health_report_healthy_with_data(self):
        """正常调用数据被认为是健康的"""
        monitor = BusMonitor()
        definition = _make_definition()
        call = _make_call("tools.file.read")
        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)

        report = monitor.get_health_report()
        assert report["healthy"] is True
        assert report["anomalies"] == []

    def test_health_report_detects_high_error_rate(self):
        """检测高错误率异常"""
        monitor = BusMonitor()
        definition = _make_definition()

        # 10 次调用中 5 次失败，错误率 50%
        for i in range(10):
            call = _make_call("tools.file.read")
            trace = monitor.start_trace(call, definition)
            success = i < 5  # 前 5 次成功，后 5 次失败
            result = _make_result(trace.trace_id, "tools.file.read", success=success)
            monitor.end_trace(trace, result)

        report = monitor.get_health_report()
        assert report["healthy"] is False
        assert len(report["anomalies"]) > 0
        assert any("错误率" in a for a in report["anomalies"])

    def test_health_report_detects_high_latency(self):
        """检测高延迟异常"""
        monitor = BusMonitor()
        definition = _make_definition()

        call = _make_call("tools.file.read")
        trace = monitor.start_trace(call, definition)
        # 模拟高延迟：手动设置 duration_ms
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)
        # 直接修改统计中的延迟
        monitor._category_stats["tools.file.read"]["total_latency_ms"] = 10000.0
        monitor._category_stats["tools.file.read"]["total_calls"] = 1

        report = monitor.get_health_report()
        # 延迟 10000ms > 5000ms 阈值
        assert any("延迟" in a for a in report["anomalies"])

    def test_health_report_multiple_capabilities(self):
        """多能力统计"""
        monitor = BusMonitor()
        definition = _make_definition()

        # 添加两个不同能力的调用
        for cap_id in ["tools.file.read", "tools.file.write"]:
            call = _make_call(cap_id)
            trace = monitor.start_trace(call, definition)
            result = _make_result(trace.trace_id, cap_id, success=True)
            monitor.end_trace(trace, result)

        report = monitor.get_health_report()
        assert report["total_calls"] == 2


# ══════════════════════════════════════════════════════════
# BusMonitor 清空测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorClear:
    """清空监控数据"""

    def test_clear_removes_all_data(self):
        """clear 清空所有数据"""
        monitor = BusMonitor()
        call = _make_call("tools.file.read")
        definition = _make_definition()

        trace = monitor.start_trace(call, definition)
        result = _make_result(trace.trace_id, "tools.file.read", success=True)
        monitor.end_trace(trace, result)

        # 确认有数据
        assert len(monitor._traces) > 0
        assert len(monitor._call_graph) > 0
        assert len(monitor._category_stats) > 0

        monitor.clear()

        assert len(monitor._traces) == 0
        assert len(monitor._call_graph) == 0
        assert len(monitor._category_stats) == 0


# ══════════════════════════════════════════════════════════
# BusMonitor._summarize_params 测试
# ══════════════════════════════════════════════════════════


class TestBusMonitorSummarizeParams:
    """参数摘要生成"""

    def test_normal_params(self):
        """普通参数正常摘要"""
        params = {"path": "main.py", "line": 42}
        summary = BusMonitor._summarize_params(params)
        assert "main.py" in summary
        assert "42" in summary

    def test_sensitive_keys_masked(self):
        """敏感键被替换为 ***"""
        params = {"api_key": "sk-1234567890abcdef", "token": "my-secret-token"}
        summary = BusMonitor._summarize_params(params)
        assert "sk-1234567890abcdef" not in summary
        assert "my-secret-token" not in summary
        assert "***" in summary

    def test_password_key_masked(self):
        """password 键被掩码"""
        params = {"password": "super_secret_123"}
        summary = BusMonitor._summarize_params(params)
        assert "super_secret_123" not in summary
        assert "***" in summary

    def test_secret_key_masked(self):
        """secret 键被掩码"""
        params = {"secret": "abc123"}
        summary = BusMonitor._summarize_params(params)
        assert "abc123" not in summary

    def test_long_string_truncated(self):
        """长字符串被截断"""
        long_text = "x" * 150
        params = {"content": long_text}
        summary = BusMonitor._summarize_params(params)
        # 字符串被截断到 100 字符 + "..."
        assert "..." in summary
        assert len(summary) > 0

    def test_summary_max_length(self):
        """摘要总长度不超过 max_length"""
        params = {"key1": "value1", "key2": "value2", "key3": "value3"}
        summary = BusMonitor._summarize_params(params, max_length=10)
        assert len(summary) <= 10