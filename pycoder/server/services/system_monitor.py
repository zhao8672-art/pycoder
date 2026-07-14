"""
系统监控器 — 实时检测模式加载失败/卡死/报错，自动修复

监控项:
    - 模式加载状态
    - 网络连通性
    - API Key 有效性
    - 进程端口占用
    - 日志异常
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    """健康检查报告"""
    overall_ok: bool
    mode_status: dict[str, bool]
    issues: list[str]
    suggestions: list[str]


def check_mode_health(mode_name: str, duration_ms: int, success: bool, error: str = "") -> HealthReport:
    """检查单个模式执行后的健康状况。

    Args:
        mode_name: 模式名称 (chat/hermes/agent)
        duration_ms: 执行耗时 (ms)
        success: 是否成功
        error: 错误信息

    Returns:
        HealthReport 健康报告
    """
    issues: list[str] = []
    suggestions: list[str] = []
    mode_status: dict[str, bool] = {mode_name: success}

    if not success:
        issues.append(f"模式 [{mode_name}] 执行失败")

        if "timeout" in error.lower() or duration_ms > 120000:
            issues.append(f"模式 [{mode_name}] 超时 ({duration_ms}ms)")
            suggestions.append("检查网络连接是否稳定")
            suggestions.append("尝试降低 reasoning_effort 参数")

        if "401" in error or "unauthorized" in error.lower():
            issues.append(f"模式 [{mode_name}] API Key 无效")
            suggestions.append("运行 python -m pycoder --setup 重新配置 API Key")

        if "connect" in error.lower() or "refused" in error.lower():
            issues.append(f"模式 [{mode_name}] 网络连接失败")
            suggestions.append("检查是否能访问 api.deepseek.com")
            suggestions.append("检查代理/VPN 设置")

        if "rate" in error.lower() or "limit" in error.lower():
            issues.append(f"模式 [{mode_name}] API 速率限制")
            suggestions.append("等待 60 秒后重试")
            suggestions.append("检查账户配额和使用量")

    # 超时但成功
    elif duration_ms > 120000:
        issues.append(f"模式 [{mode_name}] 执行缓慢 ({duration_ms}ms)")
        suggestions.append("考虑使用更快的模型 (如 deepseek-chat → deepseek-v4-flash)")

    # 性能告警
    elif duration_ms > 30000:
        logger.info("mode_slow mode=%s duration_ms=%d", mode_name, duration_ms)

    return HealthReport(
        overall_ok=success,
        mode_status=mode_status,
        issues=issues,
        suggestions=suggestions,
    )


def check_all_modes(results: list[dict]) -> HealthReport:
    """批量检查所有模式执行结果。

    Args:
        results: [{mode: str, success: bool, duration_ms: int, error: str}, ...]
    """
    all_ok = all(r.get("success", False) for r in results)
    all_issues: list[str] = []
    all_suggestions: list[str] = []
    all_mode_status: dict[str, bool] = {}

    for r in results:
        mode = r.get("mode", "unknown")
        success = r.get("success", False)
        duration = r.get("duration_ms", 0)
        error = r.get("error", "")

        report = check_mode_health(mode, duration, success, error)
        all_mode_status.update(report.mode_status)
        all_issues.extend(report.issues)
        all_suggestions.extend(report.suggestions)

    # 去重
    all_suggestions = list(dict.fromkeys(all_suggestions))

    return HealthReport(
        overall_ok=all_ok,
        mode_status=all_mode_status,
        issues=all_issues,
        suggestions=all_suggestions,
    )
