"""
复合 NLU 引擎 — 三层管道整合

三层 NLU:
  Layer 1: 规则快速通道 (0 Token, <1ms) → 置信度 >= 0.7 直接返回
  Layer 2: 嵌入相似度匹配 (<10ms) → 置信度 >= 0.7 返回
  Layer 3: LLM 深度理解 (仅在歧义 > 0.4 时触发)

弥补与 Hermes -5.5 的 NLU 差距。
"""

from __future__ import annotations

import logging
import time

from pycoder.ai.interface.types import (
    NLUResult,
    ProviderCapability,
)
from pycoder.ai.interface.base import INaturalLanguageUnderstanding
from pycoder.ai.nlu.rule_classifier import RuleClassifier
from pycoder.ai.nlu.embedding_matcher import EmbeddingMatcher
from pycoder.ai.nlu.deep_analyzer import DeepAnalyzer

logger = logging.getLogger(__name__)


class CompositeNLUEngine(INaturalLanguageUnderstanding):
    """三层复合 NLU 引擎

    规则 → 嵌入 → LLM (逐层降级)
    """

    def __init__(self) -> None:
        self._rule = RuleClassifier()
        self._embedding = EmbeddingMatcher()
        self._deep = DeepAnalyzer()

    async def understand(
        self, text: str, context: dict | None = None
    ) -> NLUResult:
        """理解自然语言 — 三层管道

        策略:
          Layer 1: 规则分类 → 置信度 >= 0.7 → 直接返回
          Layer 2: 嵌入匹配 → 置信度 >= 0.7 → 返回
          Layer 3: LLM 深度分析 → 返回完整结果
        """
        start = time.time()

        # ── Layer 1: 规则快速通道 ──
        rule_result = await self._rule.classify(text)
        if rule_result["confidence"] >= 0.7 and rule_result["ambiguity_score"] < 0.4:
            return NLUResult(
                intent=rule_result["task_type"],
                entities={"domain": rule_result["domain"]},
                confidence=rule_result["confidence"],
                ambiguity_score=rule_result["ambiguity_score"],
                sentiment=rule_result["sentiment"],
                urgency="normal",
                sub_intents=[],
                extracted_tasks=[],
                context_required=[],
                processing_time_ms=round((time.time() - start) * 1000, 1),
            )

        # ── Layer 2: 嵌入相似度 ──
        matches = await self._embedding.match(text)
        if matches and matches[0]["confidence"] >= 0.7:
            best = matches[0]
            return NLUResult(
                intent=best["intent"],
                entities={"domain": rule_result["domain"]},
                confidence=best["confidence"],
                ambiguity_score=rule_result["ambiguity_score"],
                sentiment=rule_result["sentiment"],
                urgency="normal",
                sub_intents=[],
                extracted_tasks=[best["intent"]],
                context_required=[],
                processing_time_ms=round((time.time() - start) * 1000, 1),
            )

        # ── Layer 3: LLM 深度分析 (歧义高或无法分类) ──
        if rule_result["ambiguity_score"] > 0.4:
            deep_result = await self._deep.analyze(text, context)
            return NLUResult(
                intent=deep_result.get("core_intent", text)[:100],
                entities=deep_result.get("entities", {}),
                confidence=deep_result.get("confidence", 0.5),
                ambiguity_score=rule_result["ambiguity_score"],
                sentiment=rule_result["sentiment"],
                urgency=deep_result.get("urgency", "normal"),
                sub_intents=deep_result.get("sub_intents", []),
                extracted_tasks=[],
                context_required=deep_result.get("required_context", []),
                processing_time_ms=deep_result.get("processing_time_ms", 0),
            )

        # 默认：使用 Layer 1 结果
        return NLUResult(
            intent=rule_result["task_type"],
            entities={"domain": rule_result["domain"]},
            confidence=rule_result["confidence"],
            ambiguity_score=rule_result["ambiguity_score"],
            sentiment=rule_result["sentiment"],
            urgency="normal",
            processing_time_ms=round((time.time() - start) * 1000, 1),
        )

    async def extract_tasks(self, text: str) -> list[str]:
        """从描述中提取任务列表"""
        result = await self.understand(text)
        if result.sub_intents:
            return result.sub_intents
        return [result.intent]

    async def detect_ambiguity(self, text: str) -> float:
        """检测歧义程度"""
        result = await self._rule.classify(text)
        return result["ambiguity_score"]

    async def classify_intent(self, text: str) -> tuple[str, float]:
        """分类意图"""
        result = await self.understand(text)
        return result.intent, result.confidence

    async def rephrase(self, text: str, style: str = "concise") -> str:
        """改写文本 — 使用规则简化"""
        if style == "concise":
            # 简单的精简规则
            clean = text.strip()
            for prefix in ["帮我", "我想", "我需要", "请", "请问", "能不能", "可以吗"]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix):].strip()
            return clean
        return text

    def get_capability_info(self) -> ProviderCapability:
        """获取 NLU 能力评分 (面向 Hermes)"""
        return ProviderCapability(
            provider="PyCoder-CompositeNLU",
            natural_language=0.82,  # 目标：接近 Hermes 92%
            code_generation=0.40,
            code_analysis=0.50,
            reasoning=0.75,
            tool_use=0.60,
            latency=150.0,  # Layer 1+2 可在 10ms 内完成
            cost_efficiency=0.95,  # 多数请求层 1+2 完成 (0 Token)
        )


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_nlu: CompositeNLUEngine | None = None


def get_nlu_engine() -> CompositeNLUEngine:
    """获取 NLU 引擎单例"""
    global _nlu
    if _nlu is None:
        _nlu = CompositeNLUEngine()
    return _nlu
