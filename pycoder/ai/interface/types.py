"""
AI 统一接口类型定义

定义 AI 模块间传递的所有数据结构，确保类型安全和接口一致性。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ══════════════════════════════════════════════════════════
# 枚举类型
# ══════════════════════════════════════════════════════════


class CodeGenStrategy(Enum):
    """代码生成策略"""

    SINGLE_PASS = auto()  # 单次生成
    ITERATIVE = auto()  # 迭代优化
    TEST_DRIVEN = auto()  # 测试驱动
    SPEC_DRIVEN = auto()  # 规约驱动
    TEMPLATE_BASED = auto()  # 模板生成


class AnalysisDepth(Enum):
    """代码分析深度"""

    SYNTAX = auto()  # 语法级
    SEMANTIC = auto()  # 语义级
    STRUCTURAL = auto()  # 结构级
    ARCHITECTURAL = auto()  # 架构级
    BEHAVIORAL = auto()  # 行为级


class NLUStrategy(Enum):
    """自然语言理解策略"""

    RULE_BASED = auto()  # 规则匹配
    EMBEDDING = auto()  # 嵌入向量
    HYBRID = auto()  # 混合模式
    CHAIN_OF_THOUGHT = auto()  # 思维链


class FusionMode(Enum):
    """多模型融合模式"""

    BEST_OF_N = auto()  # N 选最优
    ENSEMBLE = auto()  # 集成投票
    PIPELINE = auto()  # 流水线
    FALLBACK = auto()  # 降级链
    SPECIALIST = auto()  # 专家分工


# ══════════════════════════════════════════════════════════
# Provider 与能力定义
# ══════════════════════════════════════════════════════════


@dataclass
class ModelProvider:
    """模型提供商"""

    name: str
    display_name: str
    priority: int = 0
    capabilities: set[str] = field(default_factory=set)
    max_context: int = 8192
    pricing_per_1k: dict[str, float] = field(default_factory=dict)
    api_base: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)


@dataclass
class ProviderCapability:
    """Provider 能力评分"""

    provider: str
    code_generation: float = 0.0  # 0-1
    code_analysis: float = 0.0
    natural_language: float = 0.0
    reasoning: float = 0.0
    tool_use: float = 0.0
    latency: float = 0.0  # 毫秒
    cost_efficiency: float = 0.0  # 0-1

    @property
    def overall_score(self) -> float:
        weights = {
            "code_generation": 0.25,
            "code_analysis": 0.20,
            "natural_language": 0.15,
            "reasoning": 0.20,
            "tool_use": 0.10,
            "cost_efficiency": 0.10,
        }
        return sum(
            getattr(self, k) * w for k, w in weights.items()
        )


@dataclass
class CapabilityInfo:
    """能力注册信息"""

    id: str
    name: str
    category: str
    version: str = "1.0.0"
    provider: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    is_streaming: bool = False


# ══════════════════════════════════════════════════════════
# 代码生成
# ══════════════════════════════════════════════════════════


@dataclass
class CodeGenerationRequest:
    """代码生成请求"""

    prompt: str
    language: str = ""
    context: str = ""  # 上下文代码
    strategy: CodeGenStrategy = CodeGenStrategy.SINGLE_PASS
    constraints: list[str] = field(default_factory=list)  # 约束条件
    test_cases: list[str] = field(default_factory=list)  # TDD 测试用例
    max_tokens: int = 4096
    temperature: float = 0.3
    stop_sequences: list[str] = field(default_factory=list)


@dataclass
class CodeGenerationResult:
    """代码生成结果"""

    code: str
    language: str
    strategy_used: CodeGenStrategy
    token_usage: dict = field(default_factory=dict)
    generation_time_ms: float = 0.0
    passes_tests: bool = False
    alternatives: list[str] = field(default_factory=list)  # 备选方案
    explanation: str = ""
    confidence: float = 0.0  # 0-1


# ══════════════════════════════════════════════════════════
# 代码分析
# ══════════════════════════════════════════════════════════


@dataclass
class CodeAnalysisRequest:
    """代码分析请求"""

    code: str
    language: str = ""
    depth: AnalysisDepth = AnalysisDepth.SEMANTIC
    focus_areas: list[str] = field(default_factory=list)  # security, performance, etc.
    reference_code: str = ""  # 参考代码（用于对比分析）


@dataclass
class AnalysisResult:
    """代码分析结果"""

    summary: str
    issues: list[dict] = field(default_factory=list)  # 问题列表
    suggestions: list[dict] = field(default_factory=list)  # 建议列表
    metrics: dict = field(default_factory=dict)  # 代码度量
    complexity_score: float = 0.0
    security_rating: str = "unknown"  # low/medium/high/critical
    maintainability_index: float = 0.0
    analysis_time_ms: float = 0.0


# ══════════════════════════════════════════════════════════
# 自然语言理解
# ══════════════════════════════════════════════════════════


@dataclass
class NLUResult:
    """NLU 结果"""

    intent: str
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    ambiguity_score: float = 0.0  # 歧义程度 (越高越模糊)
    sentiment: str = "neutral"
    urgency: str = "normal"  # low/normal/high/critical
    sub_intents: list[str] = field(default_factory=list)
    extracted_tasks: list[str] = field(default_factory=list)
    context_required: list[str] = field(default_factory=list)  # 需要补充的上下文
    processing_time_ms: float = 0.0


# ══════════════════════════════════════════════════════════
# 工具执行
# ══════════════════════════════════════════════════════════


@dataclass
class ToolCallResult:
    """工具调用结果"""

    tool_name: str
    success: bool
    result: Any = None
    error: str = ""
    execution_time_ms: float = 0.0
    side_effects: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)  # 产生的文件/资源


# ══════════════════════════════════════════════════════════
# 任务规划
# ══════════════════════════════════════════════════════════


@dataclass
class PlanNode:
    """规划节点"""

    id: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    estimated_duration_ms: float = 0.0
    assigned_agent: str = ""
    tool_calls: list[str] = field(default_factory=list)


@dataclass
class PlanResult:
    """规划结果"""

    plan_id: str
    nodes: list[PlanNode]
    estimated_total_ms: float = 0.0
    risk_level: str = "low"
    fallback_plan: list[PlanNode] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 多模型融合
# ══════════════════════════════════════════════════════════


@dataclass
class FusionContext:
    """融合上下文"""

    mode: FusionMode = FusionMode.BEST_OF_N
    providers: list[str] = field(default_factory=list)
    task_type: str = ""
    quality_threshold: float = 0.7
    max_latency_ms: float = 5000.0
    max_cost_usd: float = 0.01


@dataclass
class FusionResult:
    """融合结果"""

    final_output: str
    provider_contributions: dict[str, float] = field(default_factory=dict)
    fusion_mode: FusionMode = FusionMode.BEST_OF_N
    consensus_level: float = 0.0  # 多模型一致性
    total_time_ms: float = 0.0
    total_cost_usd: float = 0.0


# ══════════════════════════════════════════════════════════
# 竞品分析与基准测试
# ══════════════════════════════════════════════════════════


@dataclass
class FeatureGap:
    """功能差距"""

    feature: str
    pycoder_score: float  # 0-10
    competitor_score: float  # 0-10
    competitor_name: str
    gap: float  # competitor - pycoder
    priority: str = "medium"  # low/medium/high/critical
    recommendation: str = ""


@dataclass
class CompetitiveAnalysis:
    """竞品分析报告"""

    timestamp: float = field(default_factory=time.time)
    pycoder_version: str = "0.5.0"
    competitors: list[str] = field(default_factory=list)
    feature_gaps: list[FeatureGap] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)
    overall_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)


@dataclass
class PerformanceMetrics:
    """性能指标"""

    # 代码生成
    code_gen_accuracy: float = 0.0  # pass@1
    code_gen_latency_ms: float = 0.0
    code_gen_token_efficiency: float = 0.0  # 有效代码/总token

    # 自然语言理解
    nlu_intent_accuracy: float = 0.0
    nlu_entity_f1: float = 0.0
    nlu_ambiguity_detection: float = 0.0

    # 代码分析
    analysis_precision: float = 0.0
    analysis_recall: float = 0.0
    analysis_latency_ms: float = 0.0

    # 综合
    overall_score: float = 0.0
    cost_per_task_usd: float = 0.0
    user_satisfaction: float = 0.0


@dataclass
class PerformanceBenchmark:
    """性能基准测试"""

    pycoder_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    competitor_metrics: dict[str, PerformanceMetrics] = field(default_factory=dict)
    test_dataset: str = ""
    test_date: str = ""
    summary: str = ""
