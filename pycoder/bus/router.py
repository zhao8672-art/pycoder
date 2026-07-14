"""
智能路由器 — 将能力调用路由到最优实现

功能:
- 根据能力 ID 或语义描述路由到正确的处理器
- 多个实现提供同一能力时，选择最优（负载/延迟/质量）
- 能力不存在时，建议替代方案或推荐安装插件
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """路由决策结果"""

    capability_id: str
    handler_id: str
    confidence: float = 1.0  # 置信度 0-1
    alternatives: list[str] = field(default_factory=list)
    suggestion: str = ""
    fallback_used: bool = False


class IntelligentRouter:
    """
    智能路由器

    职责:
    1. 精确匹配: capability_id 直接查找
    2. 语义路由: 自然语言描述 → 最匹配的能力
    3. 多实现选择: 同一能力的多个实现 → 选最优
    4. 降级建议: 能力不存在时，推荐替代方案
    """

    def __init__(self, registry: Any):  # CapabilityRegistry
        self._registry = registry
        self._latency_records: dict[str, list[float]] = {}
        self._error_counts: dict[str, int] = {}

    def route(self, capability_id: str, params: dict[str, Any] | None = None) -> RouteDecision:
        """
        路由一个能力调用

        Args:
            capability_id: 能力 ID 或自然语言描述
            params: 调用参数（用于智能推断）

        Returns:
            RouteDecision 路由决策
        """
        # 1. 精确匹配
        if self._registry.exists(capability_id):
            return RouteDecision(
                capability_id=capability_id,
                handler_id=capability_id,
                confidence=1.0,
            )

        # 2. 语义搜索
        matches = self._registry.search(capability_id)
        if matches:
            best = matches[0]
            confidence = 0.8 if len(matches) == 1 else 0.6
            return RouteDecision(
                capability_id=best.id,
                handler_id=best.id,
                confidence=confidence,
                alternatives=[m.id for m in matches[1:4]],
            )

        # 3. 自然语言搜索
        desc_matches = self._registry.search_by_description(capability_id)
        if desc_matches:
            best = desc_matches[0]
            return RouteDecision(
                capability_id=best.id,
                handler_id=best.id,
                confidence=0.5,
                alternatives=[m.id for m in desc_matches[1:4]],
                suggestion=f"未找到 '{capability_id}'，推荐使用 '{best.id}' ({best.name})",
            )

        # 4. 智能建议
        suggestion = self._generate_suggestion(capability_id)
        return RouteDecision(
            capability_id=capability_id,
            handler_id="",
            confidence=0.0,
            suggestion=suggestion or f"未找到能力 '{capability_id}'，请检查拼写或安装相应的插件",
        )

    def route_by_description(self, description: str) -> RouteDecision:
        """通过自然语言描述路由"""
        matches = self._registry.search_by_description(description)
        if matches:
            best = matches[0]
            return RouteDecision(
                capability_id=best.id,
                handler_id=best.id,
                confidence=0.7,
                alternatives=[m.id for m in matches[1:5]],
                suggestion=f"根据描述 '{description}'，匹配到 '{best.id}' ({best.name})",
            )

        return RouteDecision(
            capability_id="",
            handler_id="",
            confidence=0.0,
            suggestion=f"未找到与 '{description}' 匹配的能力，建议安装相关插件",
        )

    def record_latency(self, capability_id: str, latency_ms: float) -> None:
        """记录能力调用的延迟（用于后续负载均衡）"""
        if capability_id not in self._latency_records:
            self._latency_records[capability_id] = []
        records = self._latency_records[capability_id]
        records.append(latency_ms)
        # 只保留最近 100 条
        if len(records) > 100:
            self._latency_records[capability_id] = records[-100:]

    def record_error(self, capability_id: str) -> None:
        """记录能力调用失败"""
        self._error_counts[capability_id] = self._error_counts.get(capability_id, 0) + 1

    def get_performance_summary(self) -> dict[str, dict[str, float]]:
        """获取能力性能汇总"""
        summary: dict[str, dict[str, float]] = {}
        for cap_id, records in self._latency_records.items():
            if records:
                summary[cap_id] = {
                    "avg_latency_ms": sum(records) / len(records),
                    "p95_latency_ms": (
                        sorted(records)[int(len(records) * 0.95)]
                        if len(records) >= 20
                        else max(records)
                    ),
                    "error_count": self._error_counts.get(cap_id, 0),
                    "total_calls": len(records),
                }
        return summary

    def _generate_suggestion(self, query: str) -> str:
        """根据查询生成智能建议"""
        query_lower = query.lower()

        # 检查是否可能是拼写错误
        all_ids = [d.id for d in self._registry.list_all()]
        for real_id in all_ids:
            # 简单的编辑距离启发式
            if self._similar(query_lower, real_id.lower()):
                return f"未找到 '{query}'，您是否想调用 '{real_id}'？"

        # 根据关键词推荐类别
        if any(w in query_lower for w in ["编辑", "写", "read", "write", "edit"]):
            editor_caps = self._registry.list_by_category(
                __import__(
                    "pycoder.bus.protocol", fromlist=["CapabilityCategory"]
                ).CapabilityCategory.EDITOR
            )
            if editor_caps:
                return f"可用编辑器能力: {', '.join(c.id for c in editor_caps[:5])}"

        if any(w in query_lower for w in ["git", "shell", "执行", "命令", "commit"]):
            system_caps = self._registry.list_by_category(
                __import__(
                    "pycoder.bus.protocol", fromlist=["CapabilityCategory"]
                ).CapabilityCategory.SYSTEM
            )
            if system_caps:
                return f"可用系统能力: {', '.join(c.id for c in system_caps[:5])}"

        return f"未找到能力 '{query}'。可安装插件来扩展能力。可用能力总数: {self._registry.count}"

    @staticmethod
    def _similar(a: str, b: str, threshold: float = 0.6) -> bool:
        """简单的字符串相似度检查"""
        if not a or not b:
            return False
        # 最长公共子序列比例
        m, n = len(a), len(b)
        if m == 0 or n == 0:
            return False
        # 使用内置的 SequenceMatcher
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio() > threshold
