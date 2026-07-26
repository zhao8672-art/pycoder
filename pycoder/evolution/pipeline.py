"""
进化流水线 — 自动化运行完整的进化闭环

流程: observe → analyze → generate → validate → apply → learn

8 阶段映射:
  1. INTAKE     → observe()  采集数据
  2. DESIGN     → 任务分级与方案规划
  3. DECOMPOSE  → analyze()  LLM 分析拆解
  4. ENV_SETUP  → 环境校验
  5. DEVELOP    → generate() 生成修复方案
  6. TEST       → validate() 安全验证
  7. DEPLOY     → apply()    应用修复
  8. REVIEW     → learn()    经验沉淀 + 知识库迭代
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pycoder.evolution.models import (
    EvolutionConfig,
    EvolutionPhase,
    EvolutionReport,
    EvolutionTask,
)

logger = logging.getLogger(__name__)


class EvolutionPipeline:
    """进化管线 — 自动化运行完整的进化闭环

    流程: observe → analyze → generate → validate → apply → learn
    """

    def __init__(self, brain):
        """初始化进化管线

        Args:
            brain: EvolutionBrain 实例，负责核心决策逻辑
        """
        self._brain = brain
        self._reports: list[EvolutionReport] = []

    async def run(
        self,
        task_type: str = "auto_fix",
        target: str = "",
        description: str = "",
        auto_apply: bool = False,
    ) -> EvolutionReport:
        """运行一次完整的 8 阶段进化闭环流水线

        阶段:
          1. INTAKE     → observe()  采集数据
          2. DESIGN     → 任务分级与方案规划
          3. DECOMPOSE  → analyze()  LLM 分析拆解
          4. ENV_SETUP  → 环境校验
          5. DEVELOP    → generate() 生成修复方案
          6. TEST       → validate() 安全验证
          7. DEPLOY     → apply()    应用修复
          8. REVIEW     → learn()    经验沉淀 + 知识库迭代
        """
        report = await self._brain.run_pipeline(
            task_type=task_type,
            target=target,
            description=description,
            auto_apply=auto_apply,
        )
        self._reports.append(report)
        if len(self._reports) > 100:
            self._reports = self._reports[-100:]
        return report

    def _calculate_grade(self, task: EvolutionTask) -> float:
        """计算进化评分 (0-100)"""
        score = 0.0

        if task.errors_collected:
            score += min(20, len(task.errors_collected) * 2)

        if task.llm_analysis and len(task.llm_analysis) > 50:
            score += 20

        if task.fix_plan and len(task.fix_plan) > 50:
            score += 20

        if task.validation_result.get("passed"):
            score += 15

        if task.applied:
            score += 10

        if task.test_passed:
            score += 15

        return min(score, 100)

    async def _build_metrics(self, task: EvolutionTask) -> dict[str, Any]:
        """构建进化指标"""
        metrics: dict[str, Any] = {
            "phases": len([p for p in EvolutionPhase if task.phase >= p]),
            "errors_collected": len(task.errors_collected),
            "analysis_length": len(task.llm_analysis),
            "fix_plan_length": len(task.fix_plan),
            "validated": task.validation_result.get("passed", False),
            "applied": task.applied,
            "tests_passed": task.test_passed,
        }

        # 聚合历史趋势
        try:
            from pycoder.capabilities.self_evo.learning.metrics_tracker import get_metrics_tracker
            tracker = get_metrics_tracker()
            metrics["historical_success_rate"] = tracker.get_success_rate()
        except (ImportError, AttributeError):
            metrics["historical_success_rate"] = 0.0

        return metrics

    def _generate_recommendations(self, task: EvolutionTask) -> list[str]:
        """生成改进建议"""
        recs = []

        if not task.errors_collected:
            recs.append("建议: 启用更多日志和监控以收集进化数据")
        if not task.llm_analysis or len(task.llm_analysis) < 50:
            recs.append("建议: 配置 LLM API Key 以启用深度分析")
        if not task.validation_result.get("passed"):
            recs.append("建议: 检查 safety 模块配置和沙箱规则")
        if task.applied and not task.test_passed:
            recs.append("建议: 修复的代码导致测试失败，需要人工审查")
        if task.lessons:
            recs.append(f"经验: {task.lessons[:200]}")

        return recs

    def get_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取最近的进化报告"""
        return [
            {
                "task_id": r.task_id,
                "success": r.success,
                "phases": r.phases_completed,
                "grade": r.grade,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in self._reports[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        """获取进化统计"""
        if not self._reports:
            return {"total": 0, "success_rate": 0, "avg_grade": 0}

        total = len(self._reports)
        success = sum(1 for r in self._reports if r.success)
        avg_grade = sum(r.grade for r in self._reports) / max(total, 1)
        avg_duration = sum(r.duration_ms for r in self._reports) / max(total, 1)

        return {
            "total": total,
            "success": success,
            "failure": total - success,
            "success_rate": round(success / total * 100, 1),
            "avg_grade": round(avg_grade, 1),
            "avg_duration_ms": round(avg_duration, 0),
        }


__all__ = ["EvolutionPipeline"]
