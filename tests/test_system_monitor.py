"""系统监控器测试

覆盖:
  - HealthReport: 健康检查报告数据类
  - check_mode_health: 单模式健康检查
    - 成功路径
    - 超时失败
    - 401 认证失败
    - 网络连接失败
    - 速率限制
    - 执行缓慢（成功但慢）
    - 性能告警（中等慢速）
  - check_all_modes: 批量模式检查
    - 全部成功
    - 部分失败
    - 全部失败
    - 去重建议
"""
from __future__ import annotations

import pytest

from pycoder.server.services.system_monitor import (
    HealthReport,
    check_all_modes,
    check_mode_health,
)


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════
# HealthReport 测试
# ══════════════════════════════════════════════════════════


class TestHealthReport:
    """健康检查报告数据类"""

    def test_healthy_report(self):
        """健康报告"""
        report = HealthReport(
            overall_ok=True,
            mode_status={"chat": True, "agent": True},
            issues=[],
            suggestions=[],
        )
        assert report.overall_ok is True
        assert report.mode_status == {"chat": True, "agent": True}
        assert len(report.issues) == 0
        assert len(report.suggestions) == 0

    def test_unhealthy_report(self):
        """不健康报告"""
        report = HealthReport(
            overall_ok=False,
            mode_status={"chat": False, "agent": True},
            issues=["chat 模式连接失败"],
            suggestions=["检查网络连接"],
        )
        assert report.overall_ok is False
        assert len(report.issues) == 1
        assert len(report.suggestions) == 1


# ══════════════════════════════════════════════════════════
# check_mode_health 成功路径测试
# ══════════════════════════════════════════════════════════


class TestCheckModeHealthSuccess:
    """成功执行"""

    def test_successful_execution(self):
        """正常成功执行"""
        report = check_mode_health("chat", duration_ms=5000, success=True)
        assert report.overall_ok is True
        assert report.mode_status == {"chat": True}
        assert len(report.issues) == 0
        assert len(report.suggestions) == 0

    def test_successful_agent_execution(self):
        """Agent 正常执行"""
        report = check_mode_health("agent", duration_ms=15000, success=True)
        assert report.overall_ok is True
        assert report.mode_status == {"agent": True}
        assert len(report.issues) == 0

    def test_successful_hermes_execution(self):
        """Hermes 正常执行"""
        report = check_mode_health("hermes", duration_ms=8000, success=True)
        assert report.overall_ok is True
        assert report.mode_status == {"hermes": True}


# ══════════════════════════════════════════════════════════
# check_mode_health 失败路径测试
# ══════════════════════════════════════════════════════════


class TestCheckModeHealthFailure:
    """失败执行"""

    def test_failure_basic(self):
        """基本失败"""
        report = check_mode_health("chat", duration_ms=1000, success=False, error="未知错误")
        assert report.overall_ok is False
        assert report.mode_status == {"chat": False}
        assert len(report.issues) >= 1
        assert "执行失败" in report.issues[0]

    def test_timeout_failure(self):
        """超时失败"""
        report = check_mode_health(
            "chat", duration_ms=150000, success=False, error="timeout"
        )
        assert report.overall_ok is False
        assert any("超时" in issue for issue in report.issues)
        assert any("网络连接" in s for s in report.suggestions)
        assert any("reasoning_effort" in s for s in report.suggestions)

    def test_timeout_failure_by_duration(self):
        """按耗时判断超时（即使 error 不含 timeout）"""
        report = check_mode_health(
            "chat", duration_ms=130000, success=False, error="unknown"
        )
        assert any("超时" in issue for issue in report.issues)

    def test_401_unauthorized(self):
        """401 认证失败"""
        report = check_mode_health(
            "chat", duration_ms=500, success=False, error="401 Unauthorized"
        )
        assert report.overall_ok is False
        assert any("API Key 无效" in issue for issue in report.issues)
        assert any("--setup" in s for s in report.suggestions)

    def test_unauthorized_string(self):
        """unauthorized 字符串匹配"""
        report = check_mode_health(
            "chat", duration_ms=500, success=False, error="unauthorized access"
        )
        assert any("API Key 无效" in issue for issue in report.issues)

    def test_connection_refused(self):
        """连接拒绝"""
        report = check_mode_health(
            "chat", duration_ms=500, success=False, error="Connection refused"
        )
        assert report.overall_ok is False
        assert any("网络连接失败" in issue for issue in report.issues)
        assert any("api.deepseek.com" in s for s in report.suggestions)
        assert any("代理" in s for s in report.suggestions)

    def test_connect_timeout(self):
        """连接超时"""
        report = check_mode_health(
            "chat", duration_ms=500, success=False, error="connect timeout"
        )
        assert any("网络连接失败" in issue for issue in report.issues)

    def test_rate_limit(self):
        """速率限制"""
        report = check_mode_health(
            "chat", duration_ms=500, success=False, error="rate limit exceeded"
        )
        assert report.overall_ok is False
        assert any("速率限制" in issue for issue in report.issues)
        assert any("等待 60 秒" in s for s in report.suggestions)
        assert any("配额" in s for s in report.suggestions)

    def test_rate_limit_variant(self):
        """速率限制变体"""
        report = check_mode_health(
            "chat", duration_ms=500, success=False, error="Too many requests, limit reached"
        )
        assert any("速率限制" in issue for issue in report.issues)


# ══════════════════════════════════════════════════════════
# check_mode_health 性能告警测试
# ══════════════════════════════════════════════════════════


class TestCheckModeHealthPerformance:
    """性能告警"""

    def test_slow_but_success(self):
        """成功但缓慢（> 120s）"""
        report = check_mode_health("chat", duration_ms=130000, success=True)
        assert report.overall_ok is True  # 成功就是 OK
        assert any("执行缓慢" in issue for issue in report.issues)
        assert any("更快的模型" in s for s in report.suggestions)

    def test_moderate_slow(self):
        """中等慢速（30s-120s）仅记录日志"""
        report = check_mode_health("chat", duration_ms=35000, success=True)
        assert report.overall_ok is True
        # 30s-120s 不产生 issues，仅记录日志
        assert len(report.issues) == 0

    def test_normal_speed(self):
        """正常速度"""
        report = check_mode_health("chat", duration_ms=5000, success=True)
        assert report.overall_ok is True
        assert len(report.issues) == 0


# ══════════════════════════════════════════════════════════
# check_all_modes 测试
# ══════════════════════════════════════════════════════════


class TestCheckAllModes:
    """批量模式检查"""

    def test_all_success(self):
        """全部成功"""
        results = [
            {"mode": "chat", "success": True, "duration_ms": 5000, "error": ""},
            {"mode": "agent", "success": True, "duration_ms": 8000, "error": ""},
            {"mode": "hermes", "success": True, "duration_ms": 3000, "error": ""},
        ]
        report = check_all_modes(results)
        assert report.overall_ok is True
        assert report.mode_status == {"chat": True, "agent": True, "hermes": True}
        assert len(report.issues) == 0

    def test_partial_failure(self):
        """部分失败"""
        results = [
            {"mode": "chat", "success": True, "duration_ms": 5000, "error": ""},
            {"mode": "agent", "success": False, "duration_ms": 500, "error": "401 Unauthorized"},
            {"mode": "hermes", "success": True, "duration_ms": 3000, "error": ""},
        ]
        report = check_all_modes(results)
        assert report.overall_ok is False
        assert report.mode_status["agent"] is False
        assert len(report.issues) >= 2  # 失败 + API Key 无效

    def test_all_failure(self):
        """全部失败"""
        results = [
            {"mode": "chat", "success": False, "duration_ms": 500, "error": "timeout"},
            {"mode": "agent", "success": False, "duration_ms": 500, "error": "Connection refused"},
        ]
        report = check_all_modes(results)
        assert report.overall_ok is False
        assert len(report.issues) >= 4  # 每个模式至少 2 个 issue

    def test_suggestions_deduplicated(self):
        """建议去重"""
        results = [
            {"mode": "chat", "success": False, "duration_ms": 500, "error": "Connection refused"},
            {"mode": "agent", "success": False, "duration_ms": 500, "error": "Connection refused"},
        ]
        report = check_all_modes(results)
        # 去重后建议不应重复
        suggestions_set = set(report.suggestions)
        assert len(suggestions_set) == len(report.suggestions)

    def test_unknown_mode_defaults(self):
        """未知模式默认值"""
        results = [
            {"success": False, "error": "timeout"},
        ]
        report = check_all_modes(results)
        assert report.overall_ok is False
        assert "unknown" in report.mode_status

    def test_empty_results(self):
        """空结果列表"""
        report = check_all_modes([])
        assert report.overall_ok is True
        assert len(report.mode_status) == 0
        assert len(report.issues) == 0

    def test_mode_with_multiple_issues(self):
        """一个模式匹配多个 issue 规则"""
        results = [
            {
                "mode": "chat",
                "success": False,
                "duration_ms": 150000,
                "error": "timeout: connect refused",
            },
        ]
        report = check_all_modes(results)
        assert report.overall_ok is False
        # 应匹配: 执行失败 + 超时 + 连接失败
        assert len(report.issues) >= 3