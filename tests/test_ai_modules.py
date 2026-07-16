"""
AI 模块测试套件

测试统一 AI 接口层、竞品分析引擎、多模型融合引擎的核心功能。
"""

from __future__ import annotations

import asyncio

import pytest

from pycoder.ai.benchmark.analyzer import CompetitiveAnalyzer
from pycoder.ai.fusion.engine import (
    FusionEngine,
    FusionMode,
    HeuristicEvaluator,
    IFusionProvider,
    ProviderResult,
)
from pycoder.ai.interface.base import AICapabilityRegistry, AIFacade
from pycoder.ai.interface.types import (
    CodeGenerationRequest,
    ProviderCapability,
)


# ══════════════════════════════════════════════════════════
# Mock Provider 用于测试
# ══════════════════════════════════════════════════════════


class MockFusionProvider(IFusionProvider):
    """Mock 融合 Provider"""

    def __init__(self, name: str, score: float = 0.8, content: str = "test"):
        self._name = name
        self._capability = ProviderCapability(
            provider=name,
            code_generation=score,
            code_analysis=score,
            natural_language=score,
            reasoning=score,
            tool_use=score,
        )
        self._content = content

    @property
    def name(self) -> str:
        return self._name

    @property
    def capability(self) -> ProviderCapability:
        return self._capability

    async def generate(
        self, prompt: str, system_prompt: str = "", **kwargs
    ) -> ProviderResult:
        return ProviderResult(
            provider=self._name,
            content=f"```python\ndef {self._name}_func():\n    return '{self._content}'\n```",
            confidence=0.85,
            latency_ms=100.0,
        )


class FailingProvider(IFusionProvider):
    """会失败的 Mock Provider"""

    @property
    def name(self) -> str:
        return "failing"

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(provider="failing")

    async def generate(
        self, prompt: str, system_prompt: str = "", **kwargs
    ) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            content="",
            error="Simulated failure",
        )


# ══════════════════════════════════════════════════════════
# AICapabilityRegistry 测试
# ══════════════════════════════════════════════════════════


class TestAICapabilityRegistry:
    """测试能力注册表"""

    def test_registry_initialization(self):
        """测试注册表初始化"""
        registry = AICapabilityRegistry()
        assert registry.list_generators() == {}
        assert registry.list_analyzers() == {}
        assert registry.list_nlu_engines() == {}
        assert registry.all_capabilities() == {
            "generators": [],
            "analyzers": [],
            "nlu_engines": [],
            "tool_executors": [],
            "memory_managers": [],
            "planners": [],
        }

    def test_all_capabilities_empty(self):
        """测试空注册表的全能力查询"""
        registry = AICapabilityRegistry()
        caps = registry.all_capabilities()
        assert caps["generators"] == []
        assert caps["analyzers"] == []


# ══════════════════════════════════════════════════════════
# AIFacade 测试
# ══════════════════════════════════════════════════════════


class TestAIFacade:
    """测试 AI 统一门面"""

    def test_facade_initialization(self):
        """测试门面初始化"""
        registry = AICapabilityRegistry()
        facade = AIFacade(registry)
        assert facade.registry is registry
        assert facade.get_metrics() == {}

    def test_facade_metrics_tracking(self):
        """测试指标追踪"""
        registry = AICapabilityRegistry()
        facade = AIFacade(registry)
        facade._record_metric("test", 0.5)
        facade._record_metric("test", 0.3)
        metrics = facade.get_metrics()
        assert "test" in metrics
        assert metrics["test"]["count"] == 2

    def test_facade_no_generator_raises(self):
        """测试无生成器时抛异常"""
        registry = AICapabilityRegistry()
        facade = AIFacade(registry)

        async def _test():
            with pytest.raises(RuntimeError, match="没有可用的代码生成器"):
                await facade.generate_code(CodeGenerationRequest(prompt="test"))

        asyncio.run(_test())


# ══════════════════════════════════════════════════════════
# CompetitiveAnalyzer 测试
# ══════════════════════════════════════════════════════════


class TestCompetitiveAnalyzer:
    """测试竞品分析引擎"""

    def setup_method(self):
        self.analyzer = CompetitiveAnalyzer()

    def test_capability_gaps(self):
        """测试能力差距分析"""
        gaps = self.analyzer.analyze_capability_gaps()
        assert "OpenClaw" in gaps
        assert "Hermes" in gaps
        assert "Codex" in gaps
        # PyCoder 在代码生成上应该弱于 Codex
        assert gaps["Codex"]["code_generation"] > 0

    def test_best_competitor_per_dimension(self):
        """测试每维度最佳竞品识别"""
        best = self.analyzer.find_best_competitor_per_dimension()
        assert best["code_generation"] == "Codex"
        assert best["code_analysis"] == "OpenClaw"
        assert best["natural_language"] == "Hermes"

    def test_feature_gaps_filtered(self):
        """测试按优先级筛选功能差距"""
        critical_gaps = self.analyzer.get_feature_gaps("critical")
        high_gaps = self.analyzer.get_feature_gaps("high")
        assert len(critical_gaps) > 0
        assert len(high_gaps) > len(critical_gaps)
        # critical gaps 不应包含 high/medium/low 优先级的
        for gap in critical_gaps:
            assert gap.priority == "critical"

    def test_swot_generation(self):
        """测试 SWOT 分析生成"""
        swot = self.analyzer.generate_swot()
        assert len(swot.strengths) > 0
        assert len(swot.weaknesses) > 0
        assert len(swot.opportunities) > 0
        assert len(swot.threats) > 0

    def test_roadmap_generation(self):
        """测试改进路线图生成"""
        roadmap = self.analyzer.generate_roadmap()
        assert len(roadmap) > 0
        phases = {r["phase"] for r in roadmap}
        assert "P0 (立即)" in phases

    def test_full_analysis(self):
        """测试完整分析报告"""
        report = self.analyzer.run_full_analysis()
        assert report.pycoder_version == "0.5.0"
        assert len(report.competitors) == 3
        assert len(report.feature_gaps) > 0
        assert report.overall_score > 0
        assert len(report.recommendations) > 0

    def test_markdown_output(self):
        """测试 Markdown 输出"""
        report = self.analyzer.run_full_analysis()
        markdown = self.analyzer.to_markdown(report)
        assert "# PyCoder AI 竞品分析报告" in markdown
        assert "## SWOT 分析" in markdown
        assert "## 功能差距分析" in markdown

    def test_performance_benchmark(self):
        """测试性能基准"""
        bench = self.analyzer.generate_performance_benchmark()
        assert bench.pycoder_metrics.overall_score > 0
        assert "Codex" in bench.competitor_metrics
        assert "OpenClaw" in bench.competitor_metrics
        assert "Hermes" in bench.competitor_metrics
        assert bench.summary != ""


# ══════════════════════════════════════════════════════════
# FusionEngine 测试
# ══════════════════════════════════════════════════════════


class TestFusionEngine:
    """测试多模型融合引擎"""

    def setup_method(self):
        self.engine = FusionEngine()
        self.engine.register(MockFusionProvider("deepseek", 0.85, "deepseek_result"))
        self.engine.register(MockFusionProvider("qwen", 0.70, "qwen_result"))
        self.engine.register(MockFusionProvider("glm", 0.65, "glm_result"))
        self.engine.register(FailingProvider())

    def test_provider_registration(self):
        """测试 Provider 注册"""
        assert "deepseek" in self.engine.list_providers()
        assert "qwen" in self.engine.list_providers()
        assert "failing" in self.engine.list_providers()

    def test_get_provider(self):
        """测试获取 Provider"""
        p = self.engine.get_provider("deepseek")
        assert p is not None
        assert p.name == "deepseek"

    def test_get_nonexistent_provider(self):
        """测试获取不存在的 Provider"""
        assert self.engine.get_provider("nonexistent") is None

    def test_unregister_provider(self):
        """测试移除 Provider"""
        self.engine.unregister("qwen")
        assert "qwen" not in self.engine.list_providers()

    @pytest.mark.asyncio
    async def test_fuse_best_of_n(self):
        """测试 Best-of-N 融合"""
        result = await self.engine.fuse(
            "写一个快速排序",
            mode=FusionMode.BEST_OF_N,
            providers=["deepseek", "qwen", "glm"],
        )
        assert result.final_output != ""
        assert len(result.provider_contributions) > 0
        assert result.total_time_ms > 0

    @pytest.mark.asyncio
    async def test_fuse_ensemble(self):
        """测试 Ensemble 融合"""
        result = await self.engine.fuse(
            "实现二分查找",
            mode=FusionMode.ENSEMBLE,
            providers=["deepseek", "qwen", "glm"],
        )
        assert result.final_output != ""
        assert result.fusion_mode == FusionMode.ENSEMBLE
        assert result.consensus_level > 0

    @pytest.mark.asyncio
    async def test_fuse_pipeline(self):
        """测试 Pipeline 融合"""
        result = await self.engine.fuse(
            "写一个冒泡排序",
            mode=FusionMode.PIPELINE,
            providers=["deepseek", "qwen"],
        )
        assert result.final_output != ""
        assert result.fusion_mode == FusionMode.PIPELINE

    @pytest.mark.asyncio
    async def test_fuse_specialist(self):
        """测试 Specialist 融合"""
        result = await self.engine.fuse(
            "分析这段代码的性能问题",
            mode=FusionMode.SPECIALIST,
            providers=["deepseek", "qwen", "glm"],
        )
        assert result.final_output != ""
        assert result.fusion_mode == FusionMode.SPECIALIST
        assert len(result.provider_contributions) >= 1

    @pytest.mark.asyncio
    async def test_fuse_fallback(self):
        """测试 Fallback 融合"""
        result = await self.engine.fuse(
            "测试 fallback",
            mode=FusionMode.FALLBACK,
            providers=["deepseek", "qwen"],
        )
        assert result.final_output != ""
        assert result.fusion_mode == FusionMode.FALLBACK

    @pytest.mark.asyncio
    async def test_fuse_fallback_all_fail(self):
        """测试 Fallback 全部失败"""
        result = await self.engine.fuse(
            "测试全部失败",
            mode=FusionMode.FALLBACK,
            providers=["failing"],
        )
        assert result.fusion_mode == FusionMode.FALLBACK

    @pytest.mark.asyncio
    async def test_fuse_no_providers(self):
        """测试无 Provider"""
        engine = FusionEngine()
        result = await engine.fuse("test", mode=FusionMode.BEST_OF_N)
        assert result.final_output == ""
        assert result.total_time_ms == 0

    def test_stats(self):
        """测试统计"""
        stats = self.engine.get_stats()
        assert "providers" in stats
        assert "stats" in stats
        assert "evaluator" in stats


# ══════════════════════════════════════════════════════════
# HeuristicEvaluator 测试
# ══════════════════════════════════════════════════════════


class TestHeuristicEvaluator:
    """测试启发式评估器"""

    def setup_method(self):
        self.evaluator = HeuristicEvaluator()

    @pytest.mark.asyncio
    async def test_evaluate_good_result(self):
        """测试评估高质量结果"""
        result = ProviderResult(
            provider="test",
            content=(
                "```python\n"
                "def sort(arr):\n"
                "    # 快速排序实现\n"
                "    return sorted(arr)\n"
                "```\n\n"
                "解释: 使用内置sorted函数进行排序"
            ),
        )
        scores = await self.evaluator.evaluate("排序", [result])
        assert len(scores) == 1
        assert scores[0] > 0.5

    @pytest.mark.asyncio
    async def test_evaluate_error_result(self):
        """测试评估错误结果"""
        result = ProviderResult(provider="test", content="", error="API Error")
        scores = await self.evaluator.evaluate("排序", [result])
        assert scores[0] == 0.0

    @pytest.mark.asyncio
    async def test_select_best(self):
        """测试选择最佳结果"""
        good = ProviderResult(
            provider="good",
            content="```python\n# Good code\ndef hello():\n    return 'hello'\n```",
        )
        better = ProviderResult(
            provider="better",
            content=(
                "```python\n"
                "# Excellent code with docs\n"
                "# 返回问候语\n"
                "def hello(name: str = 'world') -> str:\n"
                '    """生成问候语"""\n'
                "    return f'Hello, {name}!'\n"
                "```\n\n"
                "说明: 这是一个改进版本"
            ),
        )
        best_idx = await self.evaluator.select_best("greeting", [good, better])
        assert best_idx == 1  # better should win


# ══════════════════════════════════════════════════════════
# 单例测试
# ══════════════════════════════════════════════════════════


class TestSingletons:
    """测试单例"""

    def test_analyzer_singleton(self):
        """测试分析器单例"""
        from pycoder.ai.benchmark.analyzer import get_analyzer

        a1 = get_analyzer()
        a2 = get_analyzer()
        assert a1 is a2

    def test_fusion_engine_singleton(self):
        """测试融合引擎单例"""
        from pycoder.ai.fusion.engine import get_fusion_engine

        e1 = get_fusion_engine()
        e2 = get_fusion_engine()
        assert e1 is e2
