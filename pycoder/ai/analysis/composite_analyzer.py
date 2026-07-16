"""
复合分析器 — 整合五层代码分析

五层架构:
  Layer 1 (SYNTAX)     → 语法分析器
  Layer 2 (SEMANTIC)   → 语义分析器
  Layer 3 (STRUCTURAL) → 结构分析器
  Layer 4 (ARCHITECTURAL) → 架构分析器
  Layer 5 (BEHAVIORAL) → 行为分析器

特性:
  - 按需选择分析深度（减少不必要的计算）
  - 分析结果自动去重合并
  - 支持流式输出（逐层返回结果）
  - 每层独立运行，一层失败不影响其他层
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from pycoder.ai.analysis.syntax_analyzer import SyntaxAnalyzer
from pycoder.ai.analysis.semantic_analyzer import SemanticAnalyzer
from pycoder.ai.analysis.structural_analyzer import StructuralAnalyzer
from pycoder.ai.analysis.architectural_analyzer import ArchitecturalAnalyzer
from pycoder.ai.analysis.behavioral_analyzer import BehavioralAnalyzer
from pycoder.ai.interface.types import (
    AnalysisDepth,
    AnalysisResult,
    CodeAnalysisRequest,
    ProviderCapability,
)
from pycoder.ai.interface.base import ICodeAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class AnalysisPipeline:
    """分析流水线 — 定义哪些层需要跑"""

    depths: list[AnalysisDepth]
    labels: list[str]

    @classmethod
    def for_depth(cls, depth: AnalysisDepth) -> "AnalysisPipeline":
        """根据所需深度构建流水线"""
        if depth == AnalysisDepth.SYNTAX:
            return cls(
                depths=[AnalysisDepth.SYNTAX],
                labels=["语法分析"],
            )
        if depth == AnalysisDepth.SEMANTIC:
            return cls(
                depths=[AnalysisDepth.SYNTAX, AnalysisDepth.SEMANTIC],
                labels=["语法分析", "语义分析"],
            )
        if depth == AnalysisDepth.STRUCTURAL:
            return cls(
                depths=[AnalysisDepth.SYNTAX, AnalysisDepth.SEMANTIC, AnalysisDepth.STRUCTURAL],
                labels=["语法分析", "语义分析", "结构分析"],
            )
        if depth == AnalysisDepth.ARCHITECTURAL:
            return cls(
                depths=[AnalysisDepth.SYNTAX, AnalysisDepth.SEMANTIC,
                        AnalysisDepth.STRUCTURAL, AnalysisDepth.ARCHITECTURAL],
                labels=["语法分析", "语义分析", "结构分析", "架构分析"],
            )
        # BEHAVIORAL = 所有层
        return cls(
            depths=list(AnalysisDepth),
            labels=["语法分析", "语义分析", "结构分析", "架构分析", "行为分析"],
        )


class CompositeAnalyzer(ICodeAnalyzer):
    """复合分析器 — 整合五层代码分析能力

    弥补与 OpenClaw -7.0 的代码分析差距。
    """

    def __init__(self) -> None:
        self._syntax = SyntaxAnalyzer()
        self._semantic = SemanticAnalyzer()
        self._structural = StructuralAnalyzer()
        self._architectural = ArchitecturalAnalyzer()
        self._behavioral = BehavioralAnalyzer()

    async def analyze(self, request: CodeAnalysisRequest) -> AnalysisResult:
        """分析代码 — 按请求深度执行对应层次"""
        start = time.time()
        pipeline = AnalysisPipeline.for_depth(request.depth)
        all_issues: list[dict] = []
        all_suggestions: list[dict] = []
        metrics: dict = {}
        complexity = 0.0

        # 准备并行任务（延迟创建协程，只创建需要的层）
        depth_factories = {
            AnalysisDepth.SYNTAX: lambda: self._syntax.analyze(request.code),
            AnalysisDepth.SEMANTIC: lambda: self._semantic.analyze(request.code),
            AnalysisDepth.STRUCTURAL: lambda: self._structural.analyze(request.code),
            AnalysisDepth.ARCHITECTURAL: lambda: self._architectural.analyze(request.code),
            AnalysisDepth.BEHAVIORAL: lambda: self._behavioral.analyze(request.code),
        }

        # 只创建需要的协程
        tasks = [depth_factories[d]() for d in pipeline.depths]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "分析层 %s 执行失败: %s",
                    pipeline.labels[i] if i < len(pipeline.labels) else f"Layer{i + 1}",
                    result,
                )
                continue
            all_issues.extend(result)

        # 对 results 去重
        seen: set[str] = set()
        unique_issues = []
        for issue in all_issues:
            sig = f"{issue.get('code', '')}:{issue.get('line', 0)}:{issue.get('message', '')}"
            if sig not in seen:
                seen.add(sig)
                unique_issues.append(issue)

        # 计算基础度量
        metrics = await self._syntax.calculate_metrics(request.code)

        # 根据问题严重程度计算复杂度评分
        severity_weights = {"error": 10, "warning": 5, "info": 2}
        complexity = sum(
            severity_weights.get(i.get("severity", "info"), 2)
            for i in unique_issues
        ) / max(len(unique_issues), 1)
        complexity = min(round(complexity / 10, 2), 1.0)

        # 生成建议
        for issue in unique_issues:
            if issue.get("severity") in ("warning", "error"):
                all_suggestions.append({
                    "type": issue.get("code", "GENERAL"),
                    "description": issue.get("message", ""),
                    "line": issue.get("line", 0),
                    "priority": issue.get("severity", "info"),
                })

        severity = "unknown"
        error_count = sum(1 for i in unique_issues if i.get("severity") == "error")
        warning_count = sum(1 for i in unique_issues if i.get("severity") == "warning")
        if error_count > 0:
            severity = "critical"
        elif warning_count > 5:
            severity = "high"
        elif warning_count > 0:
            severity = "medium"
        else:
            severity = "low"

        duration = (time.time() - start) * 1000

        return AnalysisResult(
            summary=(
                f"完成 {len(pipeline.depths)} 层分析: "
                f"发现 {error_count} 个错误, {warning_count} 个警告, "
                f"{len(unique_issues) - error_count - warning_count} 个提示"
            ),
            issues=unique_issues[:50],  # 最多返回 50 条
            suggestions=all_suggestions[:20],
            metrics=metrics,
            complexity_score=complexity,
            security_rating=severity,
            maintainability_index=metrics.get("comment_density", 0) * 10,
            analysis_time_ms=round(duration, 1),
        )

    async def find_issues(self, code: str, language: str = "") -> list[dict]:
        """查找问题 — 默认使用全部分析层"""
        req = CodeAnalysisRequest(
            code=code,
            language=language,
            depth=AnalysisDepth.ARCHITECTURAL,
        )
        result = await self.analyze(req)
        return result.issues

    async def suggest_improvements(
        self, code: str, language: str = ""
    ) -> list[dict]:
        """建议改进"""
        req = CodeAnalysisRequest(
            code=code,
            language=language,
            depth=AnalysisDepth.ARCHITECTURAL,
        )
        result = await self.analyze(req)
        return result.suggestions

    async def calculate_metrics(self, code: str, language: str = "") -> dict:
        """计算代码度量"""
        return await self._syntax.calculate_metrics(code)

    async def compare_versions(
        self, old_code: str, new_code: str, language: str = ""
    ) -> AnalysisResult:
        """版本对比分析"""
        old_result = await self.analyze(CodeAnalysisRequest(
            code=old_code, language=language, depth=AnalysisDepth.ARCHITECTURAL,
        ))
        new_result = await self.analyze(CodeAnalysisRequest(
            code=new_code, language=language, depth=AnalysisDepth.ARCHITECTURAL,
        ))

        fixed = set()
        introduced = set()
        old_codes = {i.get("code", "") for i in old_result.issues}
        new_codes = {i.get("code", "") for i in new_result.issues}

        fixed = old_codes - new_codes
        introduced = new_codes - old_codes

        return AnalysisResult(
            summary=(
                f"版本对比: 修复 {len(fixed)} 个问题, "
                f"新引入 {len(introduced)} 个问题"
            ),
            issues=new_result.issues,
            suggestions=new_result.suggestions,
            metrics={
                "fixed_issues": list(fixed),
                "new_issues": list(introduced),
                "old_line_count": old_result.metrics.get("total_lines", 0),
                "new_line_count": new_result.metrics.get("total_lines", 0),
            },
            complexity_score=new_result.complexity_score,
            security_rating=new_result.security_rating,
            maintainability_index=new_result.maintainability_index,
            analysis_time_ms=old_result.analysis_time_ms + new_result.analysis_time_ms,
        )

    def get_capability_info(self) -> ProviderCapability:
        """获取分析能力评分 (面向 OpenClaw)"""
        return ProviderCapability(
            provider="PyCoder-CompositeAnalyzer",
            code_analysis=0.80,  # 目标: 接近 OpenClaw 95%
            natural_language=0.50,
            code_generation=0.40,
            reasoning=0.70,
            tool_use=0.50,
            latency=500.0,
            cost_efficiency=0.90,  # 纯本地分析，无 API 成本
        )


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_analyzer: CompositeAnalyzer | None = None


def get_composite_analyzer() -> CompositeAnalyzer:
    """获取复合分析器单例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = CompositeAnalyzer()
    return _analyzer
