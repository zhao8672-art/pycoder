"""快速验证 AI 模块"""
import sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\pycode")

print("=== 1. 导入接口层 ===")
from pycoder.ai.interface.base import AIFacade, AICapabilityRegistry
print("  AIFacade, AICapabilityRegistry: OK")

from pycoder.ai.interface.types import (
    CodeGenerationRequest, AnalysisDepth,
    NLUResult, ProviderCapability,
)
print("  类型定义: OK")

print("\n=== 2. 导入分析引擎 ===")
from pycoder.ai.analysis import (
    CompositeAnalyzer, SyntaxAnalyzer, SemanticAnalyzer,
    StructuralAnalyzer, ArchitecturalAnalyzer, BehavioralAnalyzer,
    get_composite_analyzer,
)
print("  所有分析器: OK")

print("\n=== 3. 导入 NLU 引擎 ===")
from pycoder.ai.nlu import (
    CompositeNLUEngine, RuleClassifier, EmbeddingMatcher,
    DeepAnalyzer, get_nlu_engine,
)
print("  所有 NLU 模块: OK")

print("\n=== 4. 导入融合引擎 ===")
from pycoder.ai.fusion.engine import FusionEngine, HeuristicEvaluator
print("  FusionEngine, HeuristicEvaluator: OK")

print("\n=== 5. 导入竞品分析 ===")
from pycoder.ai.benchmark.analyzer import CompetitiveAnalyzer
print("  CompetitiveAnalyzer: OK")

print("\n=== 6. 导入统一入口 ===")
from pycoder.ai import (
    AIFacade, CompositeAnalyzer, CompositeNLUEngine,
    FusionEngine, CompetitiveAnalyzer,
)
print("  统一入口: OK")

print("\n=== 7. 快速功能测试 ===")
# 分析器
code = """
def hello(name):
    print(f"Hello {name}")
    return name

class MyClass:
    def method(self):
        pass
"""
import asyncio

async def test():
    # CompositeAnalyzer
    analyzer = CompositeAnalyzer()
    from pycoder.ai.interface.types import CodeAnalysisRequest
    result = await analyzer.analyze(CodeAnalysisRequest(code=code, language="python"))
    print(f"  分析器: {len(result.issues)} issues, {len(result.suggestions)} suggestions, {result.summary[:60]}...")

    # SyntaxAnalyzer 独立
    syntax = SyntaxAnalyzer()
    metrics = await syntax.calculate_metrics(code)
    print(f"  语法度量: {metrics}")

    # NLU
    nlu = CompositeNLUEngine()
    nlu_result = await nlu.understand("写一个快速排序算法")
    print(f"  NLU: intent={nlu_result.intent}, confidence={nlu_result.confidence}, ambiguity={nlu_result.ambiguity_score}")

    # RuleClassifier
    rule = RuleClassifier()
    rule_r = await rule.classify("修复这个 bug，程序崩溃了")
    print(f"  规则分类: domain={rule_r['domain']}, task={rule_r['task_type']}, ambiguity={rule_r['ambiguity_score']}")

    # EmbeddingMatcher
    embed = EmbeddingMatcher()
    matches = await embed.match("帮我写一个函数解析 JSON")
    print(f"  嵌入匹配: Top={matches[0]['intent']}, confidence={matches[0]['confidence']}")

    # CompetitiveAnalyzer
    ca = CompetitiveAnalyzer()
    report = ca.run_full_analysis()
    print(f"  竞品分析: score={report.overall_score}, gaps={len(report.feature_gaps)}, recs={len(report.recommendations)}")

    # FusionEngine
    from pycoder.ai.fusion.engine import (
        IFusionProvider, ProviderResult, FusionMode,
    )
    from pycoder.ai.interface.types import ProviderCapability

    class _MockProvider(IFusionProvider):
        def __init__(self, name, score=0.8):
            self._name = name
            self._cap = ProviderCapability(provider=name, code_generation=score)
        @property
        def name(self):
            return self._name
        @property
        def capability(self):
            return self._cap
        async def generate(self, prompt, system_prompt="", **kw):
            return ProviderResult(
                provider=self._name, content="def f(): pass",
                confidence=0.85, latency_ms=100.0,
            )

    engine = FusionEngine()
    engine.register(_MockProvider("deepseek", 0.85))
    engine.register(_MockProvider("qwen", 0.70))
    fr = await engine.fuse("test", mode=FusionMode.BEST_OF_N, providers=["deepseek", "qwen"])
    print(f"  融合引擎: output_len={len(fr.final_output)}, time={fr.total_time_ms:.0f}ms")

    print("\n=== ✅ 所有模块验证通过 ===")

asyncio.run(test())
