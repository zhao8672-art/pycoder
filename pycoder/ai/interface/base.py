"""
AI 能力抽象接口层

定义了 PyCoder AI 系统中所有核心能力的抽象接口(ABC)。
每种能力有独立的接口，支持多种实现(Provider)的即插即用。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pycoder.ai.interface.types import (
    AnalysisResult,
    CapabilityInfo,
    CodeAnalysisRequest,
    CodeGenerationRequest,
    CodeGenerationResult,
    NLUResult,
    PlanResult,
    ProviderCapability,
    ToolCallResult,
)

# ══════════════════════════════════════════════════════════
# 代码生成器接口
# ══════════════════════════════════════════════════════════


class ICodeGenerator(ABC):
    """代码生成能力接口

    对应竞品: Codex 代码生成特性
    要求: 高准确率、多策略支持、迭代优化
    """

    @abstractmethod
    async def generate(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """生成代码"""
        ...

    @abstractmethod
    async def generate_stream(
        self, request: CodeGenerationRequest
    ) -> AsyncIterator[str]:
        """流式生成代码"""
        ...

    @abstractmethod
    async def complete(self, prefix: str, suffix: str = "", language: str = "") -> str:
        """代码补全 (Fill-in-the-Middle)"""
        ...

    @abstractmethod
    async def refactor(
        self, code: str, instruction: str, language: str = ""
    ) -> CodeGenerationResult:
        """代码重构"""
        ...

    @abstractmethod
    def get_capability_info(self) -> ProviderCapability:
        """获取代码生成能力评分"""
        ...


# ══════════════════════════════════════════════════════════
# 代码分析器接口
# ══════════════════════════════════════════════════════════


class ICodeAnalyzer(ABC):
    """代码分析能力接口

    对应竞品: OpenClaw 代码分析能力
    要求: 多层次分析(语法/语义/结构/架构)、安全/性能/质量评估
    """

    @abstractmethod
    async def analyze(self, request: CodeAnalysisRequest) -> AnalysisResult:
        """分析代码"""
        ...

    @abstractmethod
    async def find_issues(self, code: str, language: str = "") -> list[dict]:
        """查找问题"""
        ...

    @abstractmethod
    async def suggest_improvements(
        self, code: str, language: str = ""
    ) -> list[dict]:
        """建议改进"""
        ...

    @abstractmethod
    async def calculate_metrics(self, code: str, language: str = "") -> dict:
        """计算代码度量"""
        ...

    @abstractmethod
    async def compare_versions(
        self, old_code: str, new_code: str, language: str = ""
    ) -> AnalysisResult:
        """版本对比分析"""
        ...

    @abstractmethod
    def get_capability_info(self) -> ProviderCapability:
        """获取分析能力评分"""
        ...


# ══════════════════════════════════════════════════════════
# 自然语言理解接口
# ══════════════════════════════════════════════════════════


class INaturalLanguageUnderstanding(ABC):
    """自然语言理解接口

    对应竞品: Hermes 自然语言理解优势
    要求: 高精度意图识别、实体提取、歧义消解、情感分析
    """

    @abstractmethod
    async def understand(self, text: str, context: dict | None = None) -> NLUResult:
        """理解自然语言"""
        ...

    @abstractmethod
    async def extract_tasks(self, text: str) -> list[str]:
        """从描述中提取任务列表"""
        ...

    @abstractmethod
    async def detect_ambiguity(self, text: str) -> float:
        """检测歧义程度 (0-1)"""
        ...

    @abstractmethod
    async def classify_intent(self, text: str) -> tuple[str, float]:
        """分类意图"""
        ...

    @abstractmethod
    async def rephrase(self, text: str, style: str = "concise") -> str:
        """改写文本"""
        ...

    @abstractmethod
    def get_capability_info(self) -> ProviderCapability:
        """获取 NLU 能力评分"""
        ...


# ══════════════════════════════════════════════════════════
# 工具执行器接口
# ══════════════════════════════════════════════════════════


class IToolExecutor(ABC):
    """工具执行能力接口

    提供统一的工具发现、校验、执行和结果处理能力。
    """

    @abstractmethod
    async def execute(self, tool_name: str, params: dict) -> ToolCallResult:
        """执行工具"""
        ...

    @abstractmethod
    async def list_tools(self) -> list[CapabilityInfo]:
        """列出可用工具"""
        ...

    @abstractmethod
    async def validate_params(self, tool_name: str, params: dict) -> bool:
        """校验参数"""
        ...

    @abstractmethod
    def get_capability_info(self) -> ProviderCapability:
        """获取工具执行能力评分"""
        ...


# ══════════════════════════════════════════════════════════
# 记忆管理接口
# ══════════════════════════════════════════════════════════


class IMemoryManager(ABC):
    """记忆管理能力接口

    提供工作记忆、项目知识、情景记忆、长期记忆的多级管理。
    """

    @abstractmethod
    async def remember(self, key: str, value: Any, ttl: int = 0) -> None:
        """存储记忆"""
        ...

    @abstractmethod
    async def recall(self, key: str) -> Any | None:
        """回忆记忆"""
        ...

    @abstractmethod
    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """搜索相关记忆"""
        ...

    @abstractmethod
    async def summarize_context(self, messages: list[dict]) -> str:
        """压缩上下文"""
        ...

    @abstractmethod
    async def forget(self, key: str) -> bool:
        """删除记忆"""
        ...

    @abstractmethod
    def get_capability_info(self) -> ProviderCapability:
        """获取记忆能力评分"""
        ...


# ══════════════════════════════════════════════════════════
# 任务规划器接口
# ══════════════════════════════════════════════════════════


class IPlanner(ABC):
    """任务规划能力接口

    负责将复杂任务分解为可执行的子任务序列。
    """

    @abstractmethod
    async def plan(self, task: str, context: dict | None = None) -> PlanResult:
        """制定执行计划"""
        ...

    @abstractmethod
    async def replan(
        self, original_plan: PlanResult, failure_reason: str
    ) -> PlanResult:
        """失败后重新规划"""
        ...

    @abstractmethod
    async def estimate_complexity(self, task: str) -> float:
        """预估任务复杂度 (0-1)"""
        ...

    @abstractmethod
    def get_capability_info(self) -> ProviderCapability:
        """获取规划能力评分"""
        ...


# ══════════════════════════════════════════════════════════
# 能力注册表
# ══════════════════════════════════════════════════════════


class AICapabilityRegistry:
    """AI 能力注册表 — 管理所有 AI 能力实现

    支持注册、发现、查询和动态切换 AI 能力的具体实现。
    """

    def __init__(self) -> None:
        self._generators: dict[str, ICodeGenerator] = {}
        self._analyzers: dict[str, ICodeAnalyzer] = {}
        self._nlu_engines: dict[str, INaturalLanguageUnderstanding] = {}
        self._tool_executors: dict[str, IToolExecutor] = {}
        self._memory_managers: dict[str, IMemoryManager] = {}
        self._planners: dict[str, IPlanner] = {}
        self._defaults: dict[str, str] = {}

    # ── 注册 ──

    def register_generator(self, name: str, gen: ICodeGenerator) -> None:
        self._generators[name] = gen
        if not self._defaults.get("generator"):
            self._defaults["generator"] = name

    def register_analyzer(self, name: str, analyzer: ICodeAnalyzer) -> None:
        self._analyzers[name] = analyzer
        if not self._defaults.get("analyzer"):
            self._defaults["analyzer"] = name

    def register_nlu(self, name: str, nlu: INaturalLanguageUnderstanding) -> None:
        self._nlu_engines[name] = nlu
        if not self._defaults.get("nlu"):
            self._defaults["nlu"] = name

    def register_tool_executor(self, name: str, executor: IToolExecutor) -> None:
        self._tool_executors[name] = executor
        if not self._defaults.get("tool_executor"):
            self._defaults["tool_executor"] = name

    def register_memory(self, name: str, memory: IMemoryManager) -> None:
        self._memory_managers[name] = memory
        if not self._defaults.get("memory"):
            self._defaults["memory"] = name

    def register_planner(self, name: str, planner: IPlanner) -> None:
        self._planners[name] = planner
        if not self._defaults.get("planner"):
            self._defaults["planner"] = name

    # ── 获取 ──

    def get_generator(self, name: str | None = None) -> ICodeGenerator | None:
        name = name or self._defaults.get("generator", "")
        return self._generators.get(name)

    def get_analyzer(self, name: str | None = None) -> ICodeAnalyzer | None:
        name = name or self._defaults.get("analyzer", "")
        return self._analyzers.get(name)

    def get_nlu(self, name: str | None = None) -> INaturalLanguageUnderstanding | None:
        name = name or self._defaults.get("nlu", "")
        return self._nlu_engines.get(name)

    def get_tool_executor(self, name: str | None = None) -> IToolExecutor | None:
        name = name or self._defaults.get("tool_executor", "")
        return self._tool_executors.get(name)

    def get_memory(self, name: str | None = None) -> IMemoryManager | None:
        name = name or self._defaults.get("memory", "")
        return self._memory_managers.get(name)

    def get_planner(self, name: str | None = None) -> IPlanner | None:
        name = name or self._defaults.get("planner", "")
        return self._planners.get(name)

    # ── 查询 ──

    def list_generators(self) -> dict[str, ProviderCapability]:
        return {k: v.get_capability_info() for k, v in self._generators.items()}

    def list_analyzers(self) -> dict[str, ProviderCapability]:
        return {k: v.get_capability_info() for k, v in self._analyzers.items()}

    def list_nlu_engines(self) -> dict[str, ProviderCapability]:
        return {k: v.get_capability_info() for k, v in self._nlu_engines.items()}

    def all_capabilities(self) -> dict[str, list[str]]:
        """获取所有已注册的能力列表"""
        return {
            "generators": list(self._generators.keys()),
            "analyzers": list(self._analyzers.keys()),
            "nlu_engines": list(self._nlu_engines.keys()),
            "tool_executors": list(self._tool_executors.keys()),
            "memory_managers": list(self._memory_managers.keys()),
            "planners": list(self._planners.keys()),
        }


# ══════════════════════════════════════════════════════════
# AI 统一门面
# ══════════════════════════════════════════════════════════


class AIFacade:
    """AI 统一门面 — 对外提供所有 AI 能力的统一入口

    封装了底层各 Provider 的复杂性，提供简单一致的 API。
    所有 AI 操作都通过此门面进行，确保：
    - 统一的错误处理
    - 自动的 Provider 降级
    - 完整的调用追踪
    - 性能指标收集
    """

    def __init__(self, registry: AICapabilityRegistry | None = None) -> None:
        self._registry = registry or AICapabilityRegistry()
        self._metrics: dict[str, list[float]] = {}
        self._error_counts: dict[str, int] = {}

    @property
    def registry(self) -> AICapabilityRegistry:
        return self._registry

    # ── 代码生成 ──

    async def generate_code(
        self, request: CodeGenerationRequest, provider: str | None = None
    ) -> CodeGenerationResult:
        gen = self._registry.get_generator(provider)
        if not gen:
            fallbacks = self._registry.list_generators()
            if not fallbacks:
                raise RuntimeError("没有可用的代码生成器")
            gen = self._registry.get_generator(list(fallbacks.keys())[0])
        assert gen is not None
        start = time.time()
        try:
            result = await gen.generate(request)
            self._record_metric("code_gen", time.time() - start)
            return result
        except Exception:
            self._error_counts["code_gen"] = self._error_counts.get("code_gen", 0) + 1
            raise

    # ── 代码分析 ──

    async def analyze_code(
        self, request: CodeAnalysisRequest, provider: str | None = None
    ) -> AnalysisResult:
        analyzer = self._registry.get_analyzer(provider)
        if not analyzer:
            fallbacks = self._registry.list_analyzers()
            if not fallbacks:
                raise RuntimeError("没有可用的代码分析器")
            analyzer = self._registry.get_analyzer(list(fallbacks.keys())[0])
        assert analyzer is not None
        start = time.time()
        try:
            result = await analyzer.analyze(request)
            self._record_metric("code_analysis", time.time() - start)
            return result
        except Exception:
            self._error_counts["code_analysis"] = (
                self._error_counts.get("code_analysis", 0) + 1
            )
            raise

    # ── NLU ──

    async def understand(
        self, text: str, context: dict | None = None, provider: str | None = None
    ) -> NLUResult:
        nlu = self._registry.get_nlu(provider)
        if not nlu:
            fallbacks = self._registry.list_nlu_engines()
            if not fallbacks:
                raise RuntimeError("没有可用的 NLU 引擎")
            nlu = self._registry.get_nlu(list(fallbacks.keys())[0])
        assert nlu is not None
        start = time.time()
        try:
            result = await nlu.understand(text, context)
            self._record_metric("nlu", time.time() - start)
            return result
        except Exception:
            self._error_counts["nlu"] = self._error_counts.get("nlu", 0) + 1
            raise

    # ── 指标 ──

    def _record_metric(self, name: str, elapsed: float) -> None:
        if name not in self._metrics:
            self._metrics[name] = []
        self._metrics[name].append(elapsed)

    def get_metrics(self) -> dict[str, dict[str, float]]:
        result = {}
        for name, values in self._metrics.items():
            if values:
                result[name] = {
                    "avg_ms": sum(values) / len(values) * 1000,
                    "count": len(values),
                    "errors": self._error_counts.get(name, 0),
                }
        return result
