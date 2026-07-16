"""
PyCoder AI 统一能力接口层

本模块定义了 PyCoder AI 系统的标准化抽象接口，实现模块化、可插拔的 AI 架构。

设计原则:
    - 接口隔离: 每种 AI 能力有独立接口
    - 依赖倒置: 高层模块依赖抽象，不依赖具体实现
    - 开闭原则: 对扩展开放，对修改封闭
    - 单一职责: 每个接口只负责一种能力

架构分层:
    ┌─────────────────────────────────────────────┐
    │          AIFacade (统一门面)                  │
    ├─────────────────────────────────────────────┤
    │  ICodeGenerator  │  ICodeAnalyzer  │  INLU   │
    ├─────────────────────────────────────────────┤
    │  IToolExecutor   │  IMemoryManager │ IPlanner│
    ├─────────────────────────────────────────────┤
    │         AICapabilityRegistry (能力注册)       │
    └─────────────────────────────────────────────┘
"""

from __future__ import annotations

from pycoder.ai.analysis import (  # noqa: F401
    AnalysisPipeline,
    ArchitecturalAnalyzer,
    BehavioralAnalyzer,
    CompositeAnalyzer,
    SemanticAnalyzer,
    StructuralAnalyzer,
    SyntaxAnalyzer,
    get_composite_analyzer,
)
from pycoder.ai.nlu import (  # noqa: F401
    CompositeNLUEngine,
    DeepAnalyzer,
    EmbeddingMatcher,
    RuleClassifier,
    get_nlu_engine,
)
from pycoder.ai.benchmark.analyzer import (  # noqa: F401
    CompetitiveAnalyzer,
    get_analyzer,
)
from pycoder.ai.fusion.engine import (  # noqa: F401
    FusionEngine,
    get_fusion_engine,
)
from pycoder.ai.interface.base import (
    AICapabilityRegistry,
    AIFacade,
    ICodeAnalyzer,
    ICodeGenerator,
    IMemoryManager,
    INaturalLanguageUnderstanding,
    IPlanner,
    IToolExecutor,
)
from pycoder.ai.interface.types import (
    AnalysisResult,
    CapabilityInfo,
    CodeAnalysisRequest,
    CodeGenerationRequest,
    CodeGenerationResult,
    CompetitiveAnalysis,
    FeatureGap,
    FusionContext,
    FusionResult,
    ModelProvider,
    NLUResult,
    PerformanceBenchmark,
    PerformanceMetrics,
    PlanNode,
    PlanResult,
    ProviderCapability,
    ToolCallResult,
)

__all__ = [
    # 抽象接口
    "AIFacade",
    "ICodeGenerator",
    "ICodeAnalyzer",
    "INaturalLanguageUnderstanding",
    "IToolExecutor",
    "IMemoryManager",
    "IPlanner",
    "AICapabilityRegistry",
    # 引擎
    "CompetitiveAnalyzer",
    "get_analyzer",
    "FusionEngine",
    "get_fusion_engine",
    # 分析模块
    "CompositeAnalyzer",
    "SyntaxAnalyzer",
    "SemanticAnalyzer",
    "StructuralAnalyzer",
    "ArchitecturalAnalyzer",
    "BehavioralAnalyzer",
    "get_composite_analyzer",
    "AnalysisPipeline",
    # NLU 模块
    "CompositeNLUEngine",
    "RuleClassifier",
    "EmbeddingMatcher",
    "DeepAnalyzer",
    "get_nlu_engine",
    # 类型定义
    "CodeGenerationRequest",
    "CodeGenerationResult",
    "CodeAnalysisRequest",
    "AnalysisResult",
    "NLUResult",
    "ToolCallResult",
    "PlanNode",
    "PlanResult",
    "CapabilityInfo",
    "ModelProvider",
    "ProviderCapability",
    "FusionContext",
    "FusionResult",
    "CompetitiveAnalysis",
    "FeatureGap",
    "PerformanceBenchmark",
    "PerformanceMetrics",
]
