"""代码度量与安全扫描 — 弥补与 OpenClaw -6.5/-6.0 的差距

功能:
  1. 代码度量: McCabe复杂度, 可维护性指数, 耦合度, 注释密度
  2. 安全扫描: OWASP Top 10, 敏感信息泄漏, 危险函数调用
"""

from __future__ import annotations

from pycoder.ai.security.metrics_analyzer import MetricsAnalyzer
from pycoder.ai.security.vulnerability_scanner import VulnerabilityScanner
from pycoder.ai.security.composite_scanner import CompositeSecurityScanner, get_scanner

__all__ = [
    "MetricsAnalyzer",
    "VulnerabilityScanner",
    "CompositeSecurityScanner",
    "get_scanner",
]
