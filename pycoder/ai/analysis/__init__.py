"""多层级代码分析引擎 - 弥补与 OpenClaw -7.0 的差距

五层分析架构:
  SYNTAX      → AST解析 → 语法错误/风格问题
  SEMANTIC    → 类型推导 → 类型错误/空引用
  STRUCTURAL  → 调用图   → 耦合度/循环依赖
  ARCHITECTURAL → 模式识别 → 架构异味/设计问题
  BEHAVIORAL  → 复杂度分析 → 性能热点

设计:
  - 各层独立可插拔，通过 CompositeAnalyzer 整合
  - 支持按需选择分析深度（避免不必要的开销）
  - 每层输出标准化的 Issue 和 Suggestion 列表
"""

from __future__ import annotations

from pycoder.ai.analysis.syntax_analyzer import SyntaxAnalyzer
from pycoder.ai.analysis.semantic_analyzer import SemanticAnalyzer
from pycoder.ai.analysis.structural_analyzer import StructuralAnalyzer
from pycoder.ai.analysis.architectural_analyzer import ArchitecturalAnalyzer
from pycoder.ai.analysis.behavioral_analyzer import BehavioralAnalyzer
from pycoder.ai.analysis.composite_analyzer import (
    AnalysisPipeline,
    CompositeAnalyzer,
    get_composite_analyzer,
)

__all__ = [
    "SyntaxAnalyzer",
    "SemanticAnalyzer",
    "StructuralAnalyzer",
    "ArchitecturalAnalyzer",
    "BehavioralAnalyzer",
    "CompositeAnalyzer",
    "AnalysisPipeline",
    "get_composite_analyzer",
]
