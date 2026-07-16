"""
复合安全扫描器 — 整合度量分析 + 漏洞扫描

提供统一的安全审计 + 代码度量 API。
"""

from __future__ import annotations

import logging

from pycoder.ai.security.metrics_analyzer import MetricsAnalyzer
from pycoder.ai.security.vulnerability_scanner import VulnerabilityScanner

logger = logging.getLogger(__name__)


class CompositeSecurityScanner:
    """复合安全扫描器 — 度量 + 漏洞"""

    def __init__(self) -> None:
        self._metrics = MetricsAnalyzer()
        self._vuln = VulnerabilityScanner()

    async def full_audit(self, code: str, language: str = "python") -> dict:
        """完整代码审计"""
        metrics = await self._metrics.analyze(code, language)
        vulns = await self._vuln.scan(code, language)

        severity_counts = {"critical": 0, "warning": 0, "info": 0}
        for v in vulns:
            sev = v.get("severity", "info")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        risk_level = "low"
        if severity_counts["critical"] > 0:
            risk_level = "critical"
        elif severity_counts["warning"] > 3:
            risk_level = "high"
        elif severity_counts["warning"] > 0:
            risk_level = "medium"

        return {
            "risk_level": risk_level,
            "summary": {
                "vulnerabilities": len(vulns),
                "critical": severity_counts["critical"],
                "warnings": severity_counts["warning"],
                "infos": severity_counts["info"],
            },
            "metrics": {
                "complexity": metrics["complexity"],
                "maintainability": metrics["maintainability"],
                "coupling": metrics["coupling"],
                "structure": metrics["structure"],
            },
            "findings": vulns,
            "detail_metrics": metrics,
        }


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_scanner: CompositeSecurityScanner | None = None


def get_scanner() -> CompositeSecurityScanner:
    """获取扫描器单例"""
    global _scanner
    if _scanner is None:
        _scanner = CompositeSecurityScanner()
    return _scanner
