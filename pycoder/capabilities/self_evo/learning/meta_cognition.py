"""
元认知模块 — 系统自我意识、反思和学习能力

核心能力:
  1. 自我监控 — 实时追踪系统健康状态、性能指标和错误率
  2. 反思分析 — 定期分析执行历史，识别系统性问题模式
  3. 能力评估 — 量化评估各功能模块的成熟度和可用性
  4. 进化建议 — 基于自我认知生成优先级排序的改进建议

元认知闭环:
  监控 → 反思 → 评估 → 建议 → 执行 → 验证

用法:
  from pycoder.capabilities.self_evo.learning.meta_cognition import (
      MetaCognition,
      SelfAssessment,
      get_meta_cognition,
  )

  mc = MetaCognition()
  assessment = mc.self_assess()
  print(assessment.overall_health)
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

META_DB = Path.home() / ".pycoder" / "learning" / "meta_cognition.json"


@dataclass
class SystemHealth:
    """系统健康状态"""

    overall: str  # healthy / degraded / critical
    cpu_usage: float = 0.0
    memory_usage_mb: float = 0.0
    error_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    uptime_seconds: float = 0.0
    active_sessions: int = 0
    components: dict[str, str] = field(default_factory=dict)


@dataclass
class CapabilityMaturity:
    """能力成熟度评估"""

    name: str
    level: str  # initial / developing / mature / optimized
    score: float  # 0-100
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class SelfAssessment:
    """自我评估报告"""

    timestamp: float = 0.0
    overall_health: str = "unknown"
    health_details: SystemHealth | None = None
    capabilities: list[CapabilityMaturity] = field(default_factory=list)
    system_patterns: list[dict[str, Any]] = field(default_factory=list)
    improvement_priorities: list[dict[str, Any]] = field(default_factory=list)
    evolution_score: float = 0.0


class MetaCognition:
    """元认知引擎 — 系统自我意识"""

    def __init__(self):
        self._history: list[SelfAssessment] = self._load_history()
        self._last_assessment: float = 0.0
        self._status_snapshots: list[dict[str, Any]] = []
        self._error_patterns: dict[str, int] = defaultdict(int)
        self._start_time = time.time()

    # ══════════════════════════════════════════════════════
    # 持久化
    # ══════════════════════════════════════════════════════

    def _load_history(self) -> list[SelfAssessment]:
        if META_DB.exists():
            try:
                data = json.loads(META_DB.read_text(encoding="utf-8"))
                return [
                    SelfAssessment(**item)
                    for item in data.get("assessments", [])
                ]
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def _save_history(self) -> None:
        META_DB.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "assessments": [
                self._assessment_to_dict(a) for a in self._history[-50:]
            ],
            "updated_at": time.time(),
        }
        META_DB.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _assessment_to_dict(a: SelfAssessment) -> dict[str, Any]:
        """将 SelfAssessment 转换为 JSON 可序列化字典"""
        if hasattr(a.health_details, "__dict__"):
            health = a.health_details.__dict__
        elif isinstance(a.health_details, dict):
            health = a.health_details
        else:
            health = None
        return {
            "timestamp": a.timestamp,
            "overall_health": a.overall_health,
            "health_details": health,
            "capabilities": [c.__dict__ if hasattr(c, "__dict__") else c for c in a.capabilities],
            "system_patterns": a.system_patterns,
            "improvement_priorities": a.improvement_priorities,
            "evolution_score": a.evolution_score,
        }

    # ══════════════════════════════════════════════════════
    # 自我监控
    # ══════════════════════════════════════════════════════

    def check_health(self) -> SystemHealth:
        """检查系统健康状态"""
        import psutil

        process = psutil.Process()
        cpu = process.cpu_percent(interval=0.1)
        mem = process.memory_info().rss / (1024 * 1024)

        # 错误率计算
        total_ops = len(self._status_snapshots)
        error_ops = sum(1 for s in self._status_snapshots if s.get("error"))
        error_rate = error_ops / max(total_ops, 1)

        # 组件状态
        components = {}
        try:
            from pycoder.capabilities.self_evo.learning import get_learning_engine

            get_learning_engine()
            components["learning_engine"] = "healthy"
        except Exception as e:
            components["learning_engine"] = f"degraded: {e}"

        try:
            from pycoder.memory import SessionMemoryEngine

            components["memory"] = "healthy"
        except ImportError:
            components["memory"] = "unavailable"

        try:
            from pycoder.safety import SandboxManager

            components["sandbox"] = "healthy"
        except ImportError:
            components["sandbox"] = "unavailable"

        try:
            from pycoder.multimodal.vision_client import VisionClient

            components["multimodal"] = "healthy"
        except ImportError:
            components["multimodal"] = "unavailable"

        # 整体状态判定
        if error_rate > 0.1 or cpu > 90:
            overall = "critical"
        elif error_rate > 0.05 or cpu > 70:
            overall = "degraded"
        else:
            overall = "healthy"

        return SystemHealth(
            overall=overall,
            cpu_usage=round(cpu, 1),
            memory_usage_mb=round(mem, 1),
            error_rate=round(error_rate, 3),
            avg_response_time_ms=0.0,
            uptime_seconds=time.time() - self._start_time,
            components=components,
        )

    def record_status(self, operation: str, error: bool = False, duration_ms: float = 0.0) -> None:
        """记录操作状态快照"""
        self._status_snapshots.append(
            {
                "operation": operation,
                "error": error,
                "duration_ms": duration_ms,
                "timestamp": time.time(),
            }
        )
        if error:
            self._error_patterns[operation] += 1

        # 限制快照数量
        if len(self._status_snapshots) > 1000:
            self._status_snapshots = self._status_snapshots[-500:]

    # ══════════════════════════════════════════════════════
    # 反思分析
    # ══════════════════════════════════════════════════════

    def reflect(self) -> dict[str, Any]:
        """反思近期执行历史，识别系统性问题模式"""
        if not self._status_snapshots:
            return {"patterns": [], "insights": ["暂无足够数据进行分析"]}

        recent = self._status_snapshots[-100:]
        total = len(recent)
        errors = sum(1 for s in recent if s.get("error"))
        error_rate = errors / max(total, 1)

        patterns: list[dict[str, Any]] = []

        # 高频错误模式
        if self._error_patterns:
            top_errors = sorted(
                self._error_patterns.items(), key=lambda x: x[1], reverse=True
            )[:5]
            patterns.append(
                {
                    "type": "high_frequency_errors",
                    "severity": "high" if errors > 5 else "medium",
                    "details": [
                        {"operation": op, "count": count} for op, count in top_errors
                    ],
                    "recommendation": "建议对高频错误操作进行根因分析",
                }
            )

        # 错误率趋势
        if error_rate > 0.3:
            patterns.append(
                {
                    "type": "high_error_rate",
                    "severity": "critical",
                    "details": {"error_rate": round(error_rate, 2)},
                    "recommendation": "错误率过高，建议暂停自动进化，进行系统诊断",
                }
            )

        # 慢操作检测
        slow_ops = [s for s in recent if s.get("duration_ms", 0) > 5000]
        if slow_ops:
            patterns.append(
                {
                    "type": "slow_operations",
                    "severity": "medium",
                    "details": {
                        "count": len(slow_ops),
                        "operations": list(set(s["operation"] for s in slow_ops)),
                    },
                    "recommendation": "存在慢操作，建议检查性能瓶颈",
                }
            )

        insights = []
        if error_rate < 0.05:
            insights.append("系统运行稳定，错误率低")
        if error_rate > 0.2:
            insights.append("错误率偏高，需要关注")
        if self._error_patterns:
            most_common = max(self._error_patterns, key=self._error_patterns.get)
            insights.append(f"最常见错误操作: {most_common} ({self._error_patterns[most_common]}次)")

        return {
            "patterns": patterns,
            "insights": insights,
            "error_rate": round(error_rate, 3),
            "total_operations": total,
            "error_count": errors,
        }

    # ══════════════════════════════════════════════════════
    # 能力评估
    # ══════════════════════════════════════════════════════

    def assess_capabilities(self) -> list[CapabilityMaturity]:
        """评估各功能模块的成熟度"""
        capabilities: list[CapabilityMaturity] = []

        # 评估每个模块
        evaluations = [
            {
                "name": "代码扫描",
                "module": "pycoder.capabilities.self_evo",
                "check": self._check_import("pycoder.capabilities.self_evo"),
                "strengths": ["AST 静态分析", "多种扫描类型", "严重度过滤"],
                "weaknesses": [],
                "recs": ["增加更多扫描规则"],
            },
            {
                "name": "自动修复",
                "module": "pycoder.capabilities.self_evo.engine",
                "check": self._check_import("pycoder.capabilities.self_evo.engine"),
                "strengths": ["Git 隔离", "测试门禁", "LLM 驱动"],
                "weaknesses": [],
                "recs": [],
            },
            {
                "name": "学习引擎",
                "module": "pycoder.capabilities.self_evo.learning",
                "check": self._check_import("pycoder.capabilities.self_evo.learning"),
                "strengths": ["知识库", "经验缓冲区", "模式提取", "反馈循环"],
                "weaknesses": [],
                "recs": [],
            },
            {
                "name": "持久化记忆",
                "module": "pycoder.memory",
                "check": self._check_import("pycoder.memory"),
                "strengths": ["SQLite 存储", "会话记忆", "向量检索"],
                "weaknesses": [],
                "recs": ["增强与进化模块的集成"],
            },
            {
                "name": "安全沙箱",
                "module": "pycoder.safety",
                "check": self._check_import("pycoder.safety"),
                "strengths": ["Docker 隔离", "权限引擎", "熔断器", "回滚"],
                "weaknesses": [],
                "recs": ["增强进化过程的沙箱保护"],
            },
            {
                "name": "多模态",
                "module": "pycoder.multimodal",
                "check": self._check_import("pycoder.multimodal"),
                "strengths": ["OCR", "视觉模型", "图像分析"],
                "weaknesses": [],
                "recs": ["扩展到音频和视频处理"],
            },
            {
                "name": "插件系统",
                "module": "pycoder.plugins",
                "check": self._check_import("pycoder.plugins"),
                "strengths": ["BasePlugin", "注册中心", "钩子"],
                "weaknesses": [],
                "recs": ["增加更多内置插件"],
            },
            {
                "name": "错误监控",
                "module": "pycoder.observability",
                "check": self._check_import("pycoder.observability"),
                "strengths": ["Sentry 集成", "条件加载"],
                "weaknesses": [],
                "recs": ["增加 OpenTelemetry 支持"],
            },
        ]

        for ev in evaluations:
            level = "mature" if ev["check"] else "developing"
            score = 85 if ev["check"] else 40
            if not ev["weaknesses"] and len(ev["recs"]) == 0:
                level = "optimized"
                score = 95

            capabilities.append(
                CapabilityMaturity(
                    name=ev["name"],
                    level=level,
                    score=score,
                    strengths=ev["strengths"],
                    weaknesses=ev["weaknesses"],
                    recommendations=ev["recs"],
                )
            )

        return capabilities

    def _check_import(self, module: str) -> bool:
        """检查模块是否可导入"""
        try:
            __import__(module)
            return True
        except ImportError:
            return False

    # ══════════════════════════════════════════════════════
    # 自我评估
    # ══════════════════════════════════════════════════════

    def self_assess(self) -> SelfAssessment:
        """执行完整的自我评估"""
        health = self.check_health()
        capabilities = self.assess_capabilities()
        reflection = self.reflect()

        # 计算进化分数
        cap_scores = [c.score for c in capabilities]
        avg_cap_score = sum(cap_scores) / max(len(cap_scores), 1)
        health_score = 100 if health.overall == "healthy" else (60 if health.overall == "degraded" else 30)
        evolution_score = round((avg_cap_score * 0.6 + health_score * 0.4), 1)

        # 优先级排序
        priorities = []
        for c in capabilities:
            if c.score < 70:
                priorities.append(
                    {
                        "capability": c.name,
                        "current_level": c.level,
                        "target_level": "mature",
                        "priority": "high" if c.score < 50 else "medium",
                        "recommendations": c.recommendations,
                    }
                )

        assessment = SelfAssessment(
            timestamp=time.time(),
            overall_health=health.overall,
            health_details=health,
            capabilities=capabilities,
            system_patterns=reflection["patterns"],
            improvement_priorities=priorities,
            evolution_score=evolution_score,
        )

        self._history.append(assessment)
        self._last_assessment = time.time()
        self._save_history()

        return assessment

    def get_evolution_progress(self) -> dict[str, Any]:
        """获取进化进度"""
        if len(self._history) < 2:
            return {"trend": "insufficient_data", "current_score": 0, "score_delta": 0}

        first = self._history[0].evolution_score
        last = self._history[-1].evolution_score
        delta = last - first

        if delta > 5:
            trend = "improving"
        elif delta < -5:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "current_score": last,
            "initial_score": first,
            "score_delta": round(delta, 1),
            "assessments_count": len(self._history),
        }


# 全局单例
_meta: MetaCognition | None = None


def get_meta_cognition() -> MetaCognition:
    global _meta
    if _meta is None:
        _meta = MetaCognition()
    return _meta


__all__ = [
    "MetaCognition",
    "SelfAssessment",
    "SystemHealth",
    "CapabilityMaturity",
    "get_meta_cognition",
]