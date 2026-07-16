"""
多策略代码生成器 — 策略选择 + ICodeGenerator 实现

根据任务特征自动选择最佳生成策略:

  SINGLE_PASS  → 简单代码 (<50字描述, 无测试)
  ITERATIVE    → 复杂算法 (>50字描述 或 高复杂度关键词)
  TEST_DRIVEN  → 有测试用例
  SPEC_DRIVEN  → 有规约/接口定义
"""

from __future__ import annotations

import logging

from collections.abc import AsyncIterator

from pycoder.ai.interface.types import (
    CodeGenerationRequest,
    CodeGenerationResult,
    CodeGenStrategy,
    ProviderCapability,
)
from pycoder.ai.interface.base import ICodeGenerator
from pycoder.ai.generation.single_pass import SinglePassGenerator
from pycoder.ai.generation.iterative import IterativeGenerator
from pycoder.ai.generation.test_driven import TestDrivenGenerator

logger = logging.getLogger(__name__)

# 触发迭代策略的关键词
COMPLEX_KEYWORDS = [
    "二分", "排序", "搜索", "递归", "动态规划", "回溯",
    "树", "图", "哈希表", "堆", "优先队列",
    "并发", "多线程", "异步", "线程安全",
    "加密", "解密", "签名", "认证",
    "解析器", "编译器", "解释器",
    "优化", "高性能", "大规模",
]


class MultiStrategyGenerator(ICodeGenerator):
    """多策略代码生成器 — 自动选择最佳策略

    弥补与 Codex -6.0 的代码生成差距。
    """

    def __init__(self) -> None:
        self._single = SinglePassGenerator()
        self._iterative = IterativeGenerator()
        self._tdd = TestDrivenGenerator()

    async def generate(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """自动选择策略并生成代码"""
        strategy = self._select_strategy(request)

        if strategy == CodeGenStrategy.SINGLE_PASS:
            logger.info("选择策略: SINGLE_PASS")
            return await self._single.generate(request)

        elif strategy == CodeGenStrategy.ITERATIVE:
            logger.info("选择策略: ITERATIVE (3轮优化)")
            return await self._iterative.generate(request)

        elif strategy == CodeGenStrategy.TEST_DRIVEN:
            logger.info("选择策略: TEST_DRIVEN")
            return await self._tdd.generate(request)

        else:
            logger.info("默认策略: SINGLE_PASS")
            return await self._single.generate(request)

    async def generate_stream(
        self, request: CodeGenerationRequest
    ) -> "AsyncIterator[str]":
        """流式生成"""
        strategy = self._select_strategy(request)

        if strategy == CodeGenStrategy.ITERATIVE:
            result = await self._iterative.generate(request)
            yield result.code
        else:
            result = await self._single.generate(request)
            yield result.code

    async def complete(self, prefix: str, suffix: str = "", language: str = "") -> str:
        """FIM 代码补全"""
        return await self._single.complete(prefix, suffix, language)

    async def refactor(
        self, code: str, instruction: str, language: str = ""
    ) -> CodeGenerationResult:
        """代码重构"""
        request = CodeGenerationRequest(
            prompt=f"重构以下{language}代码: {instruction}",
            language=language,
            context=code,
            strategy=CodeGenStrategy.ITERATIVE,
            max_tokens=4096,
        )
        result = await self._iterative.generate(request)
        return result

    def _select_strategy(self, request: CodeGenerationRequest) -> CodeGenStrategy:
        """根据请求特征选择策略"""
        # 1. 有测试用例 → TDD
        if request.test_cases:
            return CodeGenStrategy.TEST_DRIVEN

        # 2. 已有策略指定 → 按指定
        if request.strategy != CodeGenStrategy.SINGLE_PASS:
            return request.strategy

        prompt = request.prompt.lower()

        # 3. 复杂关键词 → ITERATIVE
        for kw in COMPLEX_KEYWORDS:
            if kw.lower() in prompt:
                return CodeGenStrategy.ITERATIVE

        # 4. 长描述 → ITERATIVE
        if len(prompt) > 80:
            return CodeGenStrategy.ITERATIVE

        # 5. 简单 → SINGLE_PASS
        return CodeGenStrategy.SINGLE_PASS

    def get_capability_info(self) -> ProviderCapability:
        """获取能力评分 (面向 Codex)"""
        return ProviderCapability(
            provider="PyCoder-MultiStrategyGenerator",
            code_generation=0.82,  # 目标: 接近 Codex 93%
            code_analysis=0.40,
            natural_language=0.50,
            reasoning=0.75,
            tool_use=0.50,
            latency=800.0,
            cost_efficiency=0.80,
        )


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_generator: MultiStrategyGenerator | None = None


def get_generator() -> MultiStrategyGenerator:
    """获取生成器单例"""
    global _generator
    if _generator is None:
        _generator = MultiStrategyGenerator()
    return _generator
