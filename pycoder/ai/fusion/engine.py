"""
多模型融合引擎 — 整合 OpenClaw/Hermes/Codex 三方优势

设计理念:
    单一模型无法在所有维度表现最优。融合引擎将不同模型的能力
    按维度组合，通过多种融合策略（Best-of-N、Ensemble、Pipeline、
    Specialist）输出最优结果。

融合策略:
    ┌──────────────────────────────────────────────────────┐
    │                FusionEngine                          │
    ├──────────────────────────────────────────────────────┤
    │  BEST_OF_N  │ 多模型并行执行 → 投票/评分选最优         │
    │  ENSEMBLE   │ 多模型并行执行 → 加权合并结果            │
    │  PIPELINE   │ 串行流水线：A 输出 → B 优化 → C 审查     │
    │  SPECIALIST │ 按任务类型自动选择最佳模型               │
    │  FALLBACK   │ 按优先级依次尝试 → 失败自动切换          │
    └──────────────────────────────────────────────────────┘

使用示例:
    engine = FusionEngine()
    engine.register("deepseek", DeepSeekProvider())
    engine.register("qwen", QwenProvider())

    result = await engine.fuse(
        prompt="实现快速排序",
        mode=FusionMode.BEST_OF_N,
        providers=["deepseek", "qwen"],
        evaluator=my_evaluator,
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from pycoder.ai.interface.types import (
    FusionContext,
    FusionMode,
    FusionResult,
    ProviderCapability,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 抽象 Provider 接口
# ══════════════════════════════════════════════════════════


@dataclass
class ProviderResult:
    """单个 Provider 的执行结果"""

    provider: str
    content: str
    confidence: float = 0.0
    latency_ms: float = 0.0
    token_usage: dict = field(default_factory=dict)
    error: str = ""


class IFusionProvider(ABC):
    """融合引擎 Provider 接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称"""
        ...

    @property
    @abstractmethod
    def capability(self) -> ProviderCapability:
        """能力评分"""
        ...

    @abstractmethod
    async def generate(
        self, prompt: str, system_prompt: str = "", **kwargs
    ) -> ProviderResult:
        """生成回复"""
        ...


class IResultEvaluator(ABC):
    """结果评估器接口"""

    @abstractmethod
    async def evaluate(
        self, prompt: str, results: list[ProviderResult]
    ) -> list[float]:
        """评估多个结果并返回分数"""
        ...

    @abstractmethod
    async def select_best(
        self, prompt: str, results: list[ProviderResult]
    ) -> int:
        """选择最佳结果的索引"""
        ...


# ══════════════════════════════════════════════════════════
# 评估器实现
# ══════════════════════════════════════════════════════════


class HeuristicEvaluator(IResultEvaluator):
    """启发式评估器 — 基于规则的评分"""

    def __init__(self) -> None:
        self._weights = {
            "completeness": 0.3,  # 完整性
            "correctness": 0.3,  # 正确性
            "conciseness": 0.15,  # 简洁性
            "structure": 0.15,  # 结构
            "documentation": 0.10,  # 文档
        }

    async def evaluate(
        self, prompt: str, results: list[ProviderResult]
    ) -> list[float]:
        scores = []
        for r in results:
            if r.error:
                scores.append(0.0)
                continue

            content = r.content

            # 完整性: 是否有代码块
            has_code = "```" in content
            completeness = 0.8 if has_code else 0.4

            # 正确性: 长度合理性 (非空且不太短)
            correctness = min(len(content) / 500.0, 1.0) if content else 0.0

            # 简洁性: 过长扣分
            conciseness = max(0.5, 1.0 - len(content) / 8000.0)

            # 结构: 是否有注释和格式化
            has_comments = "#" in content or "//" in content
            structure = 0.7 if has_comments else 0.5

            # 文档: 是否有解释
            has_explanation = (
                "解释" in content or "说明" in content or "Explanation" in content
            )
            documentation = 0.6 if has_explanation else 0.3

            score = (
                completeness * self._weights["completeness"]
                + correctness * self._weights["correctness"]
                + conciseness * self._weights["conciseness"]
                + structure * self._weights["structure"]
                + documentation * self._weights["documentation"]
            )
            scores.append(round(score, 3))

        return scores

    async def select_best(
        self, prompt: str, results: list[ProviderResult]
    ) -> int:
        scores = await self.evaluate(prompt, results)
        if not scores:
            return -1
        return scores.index(max(scores))


# ══════════════════════════════════════════════════════════
# 融合引擎核心
# ══════════════════════════════════════════════════════════


class FusionEngine:
    """多模型融合引擎

    核心能力:
    - 动态 Provider 注册与发现
    - 多种融合策略智能选择
    - 并行执行与超时控制
    - 结果评估与择优
    - 性能追踪与诊断
    """

    def __init__(self, evaluator: IResultEvaluator | None = None) -> None:
        self._providers: dict[str, IFusionProvider] = {}
        self._evaluator = evaluator or HeuristicEvaluator()
        self._stats: dict[str, dict] = {}

    # ── Provider 管理 ──

    def register(self, provider: IFusionProvider) -> None:
        """注册 Provider"""
        self._providers[provider.name] = provider
        logger.info(
            "融合引擎注册 Provider: %s (综合评分: %.2f)",
            provider.name,
            provider.capability.overall_score,
        )

    def unregister(self, name: str) -> None:
        """移除 Provider"""
        self._providers.pop(name, None)

    def get_provider(self, name: str) -> IFusionProvider | None:
        """获取 Provider"""
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        """列出所有 Provider"""
        return list(self._providers.keys())

    # ── 融合策略 ──

    async def fuse(
        self,
        prompt: str,
        mode: FusionMode = FusionMode.BEST_OF_N,
        providers: list[str] | None = None,
        system_prompt: str = "",
        context: FusionContext | None = None,
        **kwargs,
    ) -> FusionResult:
        """按指定模式融合多个模型的结果"""
        context = context or FusionContext(mode=mode)

        active = [p for p in (providers or self.list_providers()) if p in self._providers]
        if not active:
            return FusionResult(
                final_output="",
                fusion_mode=mode,
                total_time_ms=0,
            )

        start = time.time()

        if mode == FusionMode.BEST_OF_N:
            result = await self._fuse_best_of_n(prompt, active, system_prompt, **kwargs)
        elif mode == FusionMode.ENSEMBLE:
            result = await self._fuse_ensemble(prompt, active, system_prompt, **kwargs)
        elif mode == FusionMode.PIPELINE:
            result = await self._fuse_pipeline(prompt, active, system_prompt, **kwargs)
        elif mode == FusionMode.SPECIALIST:
            result = await self._fuse_specialist(prompt, active, system_prompt, **kwargs)
        elif mode == FusionMode.FALLBACK:
            result = await self._fuse_fallback(prompt, active, system_prompt, **kwargs)
        else:
            result = await self._fuse_best_of_n(prompt, active, system_prompt, **kwargs)

        result.fusion_mode = mode
        result.total_time_ms = (time.time() - start) * 1000

        # 统计
        for name, contrib in result.provider_contributions.items():
            if name not in self._stats:
                self._stats[name] = {"calls": 0, "total_time_ms": 0, "contributions": 0}
            self._stats[name]["calls"] += 1
            self._stats[name]["contributions"] += contrib

        return result

    # ── 各策略实现 ──

    async def _fuse_best_of_n(
        self, prompt: str, providers: list[str], system_prompt: str, **kwargs
    ) -> FusionResult:
        """Best-of-N: 多模型并行执行 → 评估器选最优"""
        results = await self._execute_parallel(prompt, providers, system_prompt, **kwargs)
        valid = [r for r in results if not r.error]
        if not valid:
            return FusionResult(
                final_output="所有模型均返回错误",
                total_time_ms=sum(r.latency_ms for r in results),
            )

        best_idx = await self._evaluator.select_best(prompt, valid)
        best = valid[best_idx]

        return FusionResult(
            final_output=best.content,
            provider_contributions={best.provider: 1.0},
            consensus_level=1.0 if len(valid) == 1 else 0.7,
            total_time_ms=best.latency_ms,
        )

    async def _fuse_ensemble(
        self, prompt: str, providers: list[str], system_prompt: str, **kwargs
    ) -> FusionResult:
        """Ensemble: 多模型并行 → 加权合并"""
        results = await self._execute_parallel(prompt, providers, system_prompt, **kwargs)
        valid = [r for r in results if not r.error]
        if not valid:
            return FusionResult(
                final_output="所有模型均返回错误",
                total_time_ms=sum(r.latency_ms for r in results),
            )

        scores = await self._evaluator.evaluate(prompt, valid)
        total_score = sum(scores)
        if total_score == 0:
            # 全部分为 0，使用平均
            weights = {valid[i].provider: 1.0 / len(valid) for i in range(len(valid))}
        else:
            weights = {valid[i].provider: scores[i] / total_score for i in range(len(valid))}

        # 简单拼接各模型结果（标记来源）
        parts = []
        for i, r in enumerate(valid):
            weight = weights.get(r.provider, 0)
            if weight > 0.2:  # 只合并权重 > 20% 的结果
                parts.append(
                    f"<!-- 来自 {r.provider} (得分: {scores[i]:.2f}) -->\n{r.content}"
                )

        if not parts:
            # 回退到最佳
            return await self._fuse_best_of_n(prompt, providers, system_prompt, **kwargs)

        return FusionResult(
            final_output="\n\n---\n\n".join(parts),
            provider_contributions=weights,
            consensus_level=1.0 - (max(weights.values()) - min(weights.values())),
            total_time_ms=max(r.latency_ms for r in valid),
        )

    async def _fuse_pipeline(
        self, prompt: str, providers: list[str], system_prompt: str, **kwargs
    ) -> FusionResult:
        """Pipeline: A 生成 → B 优化 → C 审查"""
        if len(providers) < 2:
            return await self._fuse_best_of_n(prompt, providers, system_prompt, **kwargs)

        results: list[ProviderResult] = []
        current_prompt = prompt
        contributions: dict[str, float] = {}

        for i, name in enumerate(providers):
            provider = self._providers[name]
            stage_prompt = current_prompt
            if i > 0:
                # 后续阶段: 在前一阶段输出基础上优化
                stage_prompt = (
                    f"前一步生成的代码:\n```\n{results[-1].content}\n```\n\n"
                    f"请优化以上代码: {prompt}"
                )

            result = await provider.generate(stage_prompt, system_prompt, **kwargs)
            results.append(result)
            current_prompt = stage_prompt

            # 贡献递减
            contributions[name] = 1.0 / (i + 1)

        final = results[-1] if results else ProviderResult(
            provider="unknown", content="", error="Pipeline 无结果"
        )

        return FusionResult(
            final_output=final.content,
            provider_contributions=contributions,
            consensus_level=0.5,
            total_time_ms=sum(r.latency_ms for r in results),
        )

    async def _fuse_specialist(
        self, prompt: str, providers: list[str], system_prompt: str, **kwargs
    ) -> FusionResult:
        """Specialist: 根据任务类型选择最佳模型"""
        task_type = self._classify_task(prompt)

        # 根据任务类型匹配最佳 Provider
        specialist_map = {
            "code_generation": "code_generation",
            "code_analysis": "code_analysis",
            "debugging": "reasoning",
            "refactoring": "code_analysis",
            "explanation": "natural_language",
            "documentation": "natural_language",
            "testing": "code_generation",
        }

        target_dim = specialist_map.get(task_type, "code_generation")
        best_provider = None
        best_score = -1.0

        for name in providers:
            provider = self._providers.get(name)
            if provider:
                score = getattr(provider.capability, target_dim, 0)
                if score > best_score:
                    best_score = score
                    best_provider = name

        if best_provider:
            provider = self._providers[best_provider]
            result = await provider.generate(prompt, system_prompt, **kwargs)
            return FusionResult(
                final_output=result.content,
                provider_contributions={best_provider: 1.0},
                consensus_level=0.8,
                total_time_ms=result.latency_ms,
            )

        return await self._fuse_best_of_n(prompt, providers, system_prompt, **kwargs)

    async def _fuse_fallback(
        self, prompt: str, providers: list[str], system_prompt: str, **kwargs
    ) -> FusionResult:
        """Fallback: 按优先级依次尝试，失败自动切换"""
        for name in providers:
            provider = self._providers.get(name)
            if not provider:
                continue
            try:
                result = await provider.generate(prompt, system_prompt, **kwargs)
                if not result.error:
                    return FusionResult(
                        final_output=result.content,
                        provider_contributions={name: 1.0},
                        consensus_level=0.5,
                        total_time_ms=result.latency_ms,
                    )
            except Exception as exc:
                logger.warning("融合引擎 Fallback: %s 失败 → %s", name, exc)

        return FusionResult(
            final_output="所有 Provider 均调用失败",
            total_time_ms=0,
        )

    # ── 辅助方法 ──

    async def _execute_parallel(
        self, prompt: str, providers: list[str], system_prompt: str, **kwargs
    ) -> list[ProviderResult]:
        """并行执行多个 Provider"""
        tasks = []
        for name in providers:
            provider = self._providers.get(name)
            if provider:
                tasks.append(self._execute_single(provider, prompt, system_prompt, **kwargs))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        output = []
        for r in results:
            if isinstance(r, Exception):
                output.append(ProviderResult(
                    provider="unknown",
                    content="",
                    error=str(r),
                ))
            else:
                output.append(r)
        return output

    async def _execute_single(
        self, provider: IFusionProvider, prompt: str, system_prompt: str, **kwargs
    ) -> ProviderResult:
        """执行单个 Provider"""
        try:
            return await provider.generate(prompt, system_prompt, **kwargs)
        except Exception as exc:
            return ProviderResult(
                provider=provider.name,
                content="",
                error=str(exc),
            )

    def _classify_task(self, prompt: str) -> str:
        """基于关键词对任务类型进行简单分类"""
        p = prompt.lower()
        gen_kw = ["生成", "创建", "写", "实现", "generate", "create", "write", "implement"]
        if any(kw in p for kw in gen_kw):
            return "code_generation"
        if any(kw in p for kw in ["分析", "检查", "审查", "analyze", "review", "check", "inspect"]):
            return "code_analysis"
        if any(kw in p for kw in ["修复", "调试", "bug", "错误", "fix", "debug", "error", "bug"]):
            return "debugging"
        if any(kw in p for kw in ["重构", "优化", "改进", "refactor", "optimize", "improve"]):
            return "refactoring"
        if any(kw in p for kw in ["解释", "说明", "是什么", "为什么", "explain", "what is", "why"]):
            return "explanation"
        if any(kw in p for kw in ["文档", "注释", "doc", "comment"]):
            return "documentation"
        if any(kw in p for kw in ["测试", "test", "spec"]):
            return "testing"
        return "code_generation"

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取融合统计"""
        return {
            "providers": self.list_providers(),
            "stats": dict(self._stats),
            "evaluator": type(self._evaluator).__name__,
        }


# ══════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════

_engine: FusionEngine | None = None


def get_fusion_engine() -> FusionEngine:
    """获取融合引擎单例"""
    global _engine
    if _engine is None:
        _engine = FusionEngine()
    return _engine
