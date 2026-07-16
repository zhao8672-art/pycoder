"""上下文感知 NLU 引擎 — 弥补与 Hermes -5.5 的差距

三层 NLU 管道:
  Layer 1: 规则快速通道 (0 Token, <1ms)
  Layer 2: 嵌入相似度 (<10ms)
  Layer 3: LLM深度理解 (仅在歧义>阈值时)
"""

from __future__ import annotations

from pycoder.ai.nlu.rule_classifier import RuleClassifier
from pycoder.ai.nlu.embedding_matcher import EmbeddingMatcher
from pycoder.ai.nlu.deep_analyzer import DeepAnalyzer
from pycoder.ai.nlu.composite_nlu import CompositeNLUEngine, get_nlu_engine

__all__ = [
    "RuleClassifier",
    "EmbeddingMatcher",
    "DeepAnalyzer",
    "CompositeNLUEngine",
    "get_nlu_engine",
]
