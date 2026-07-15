"""Model registry - single source of truth for model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelInfo:
    """模型元数据"""

    id: str
    name: str
    provider: str
    api_base: str
    pricing_input: float  # $/M tokens
    pricing_output: float
    context_window: int  # max tokens
    max_output_tokens: int
    supports_fim: bool = False
    supports_tools: bool = True
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_cache: bool = False
    description: str = ""
    tags: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 所有模型注册表
# ══════════════════════════════════════════════════════════

ALL_MODELS: dict[str, ModelInfo] = {
    # DeepSeek V4 系列
    "deepseek-chat": ModelInfo(
        id="deepseek-chat",
        name="DeepSeek V4 Flash",
        provider="deepseek",
        api_base="https://api.deepseek.com",
        pricing_input=0.14,
        pricing_output=0.28,
        context_window=1048576,
        max_output_tokens=8192,
        supports_fim=True,
        supports_tools=True,
        supports_cache=True,
        description="1M上下文, 默认主力模型, 极致性价比",
        tags=["recommended", "coding", "fast", "standard"],
    ),
    "deepseek-coder": ModelInfo(
        id="deepseek-coder",
        name="DeepSeek V4 Pro",
        provider="deepseek",
        api_base="https://api.deepseek.com",
        pricing_input=0.41,
        pricing_output=0.83,
        context_window=1048576,
        max_output_tokens=8192,
        supports_fim=True,
        supports_tools=True,
        supports_cache=True,
        description="1.6T/49B MoE, 复杂Agent任务, 1M上下文",
        tags=["coding", "agent", "reasoning", "standard"],
    ),
    "deepseek-reasoner": ModelInfo(
        id="deepseek-reasoner",
        name="DeepSeek V4 Reasoner",
        provider="deepseek",
        api_base="https://api.deepseek.com",
        pricing_input=0.55,
        pricing_output=2.19,
        context_window=1048576,
        max_output_tokens=8192,
        supports_fim=False,
        supports_tools=True,
        supports_reasoning=True,
        supports_cache=True,
        description="深度推理, 复杂Bug修复与架构设计",
        tags=["reasoning", "deep-think", "premium"],
    ),
    # Qwen3-Coder 系列
    "qwen-coder-plus": ModelInfo(
        id="qwen-coder-plus",
        name="Qwen3-Coder Plus",
        provider="qwen",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        pricing_input=0.35,
        pricing_output=1.20,
        context_window=131072,
        max_output_tokens=8192,
        supports_fim=True,
        supports_tools=True,
        description="4800亿MoE, 代码能力追平Claude 4",
        tags=["coding", "chinese-optimized", "standard"],
    ),
    "qwen-coder-turbo": ModelInfo(
        id="qwen-coder-turbo",
        name="Qwen3-Coder Turbo",
        provider="qwen",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        pricing_input=0.15,
        pricing_output=0.60,
        context_window=131072,
        max_output_tokens=4096,
        supports_fim=True,
        supports_tools=True,
        description="快速版, 代码补全首选",
        tags=["coding", "fast", "chinese-optimized"],
    ),
    "qwen-max": ModelInfo(
        id="qwen-max",
        name="Qwen3 Max",
        provider="qwen",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        pricing_input=0.80,
        pricing_output=2.00,
        context_window=131072,
        max_output_tokens=8192,
        supports_fim=False,
        supports_tools=True,
        description="旗舰模型, 深度推理与复杂分析",
        tags=["reasoning", "complex", "premium"],
    ),
    "qwen-plus": ModelInfo(
        id="qwen-plus",
        name="Qwen3 Plus",
        provider="qwen",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        pricing_input=0.14,
        pricing_output=0.40,
        context_window=131072,
        max_output_tokens=4096,
        supports_fim=False,
        supports_tools=True,
        description="均衡模型, 日常编程对话",
        tags=["balanced", "daily", "economy"],
    ),
    # GLM-4 系列
    "glm-4": ModelInfo(
        id="glm-4",
        name="GLM-4",
        provider="glm",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        pricing_input=0.10,
        pricing_output=0.10,
        context_window=131072,
        max_output_tokens=4096,
        supports_fim=False,
        supports_tools=True,
        description="128K上下文, $0.10/M极低价格",
        tags=["cheap", "chinese-optimized", "economy"],
    ),
    "glm-4-flash": ModelInfo(
        id="glm-4-flash",
        name="GLM-4 Flash",
        provider="glm",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        pricing_input=0.10,
        pricing_output=0.10,
        context_window=128000,
        max_output_tokens=4096,
        supports_fim=False,
        supports_tools=True,
        description="快速版, 简单任务和预算敏感场景",
        tags=["cheap", "fast", "economy"],
    ),
    "glm-4v-flash": ModelInfo(
        id="glm-4v-flash",
        name="GLM-4V Flash",
        provider="glm",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        pricing_input=0.10,
        pricing_output=0.10,
        context_window=128000,
        max_output_tokens=4096,
        supports_fim=False,
        supports_tools=True,
        supports_vision=True,
        description="视觉版, 支持图像理解",
        tags=["vision", "multimodal", "economy"],
    ),
    # OpenAI 系列
    "gpt-4o-mini": ModelInfo(
        id="gpt-4o-mini",
        name="GPT-4o mini",
        provider="openai",
        api_base="https://api.openai.com/v1",
        pricing_input=0.15,
        pricing_output=0.60,
        context_window=128000,
        max_output_tokens=16384,
        supports_fim=False,
        supports_tools=True,
        supports_vision=True,
        description="高性价比, 128K上下文, 支持视觉与工具调用",
        tags=["recommended", "coding", "fast", "multimodal"],
    ),
    "gpt-4o": ModelInfo(
        id="gpt-4o",
        name="GPT-4o",
        provider="openai",
        api_base="https://api.openai.com/v1",
        pricing_input=2.50,
        pricing_output=10.00,
        context_window=128000,
        max_output_tokens=16384,
        supports_fim=False,
        supports_tools=True,
        supports_vision=True,
        supports_cache=True,
        description="旗舰模型, 复杂推理与多模态任务",
        tags=["reasoning", "multimodal", "premium"],
    ),
    # OpenRouter 系列（聚合路由平台）
    "openrouter-deepseek-chat": ModelInfo(
        id="openrouter-deepseek-chat",
        name="DeepSeek V4 Flash (via OpenRouter)",
        provider="openrouter",
        api_base="https://openrouter.ai/api/v1",
        pricing_input=0.17,
        pricing_output=0.34,
        context_window=1048576,
        max_output_tokens=8192,
        supports_fim=True,
        supports_tools=True,
        supports_cache=True,
        description="通过 OpenRouter 路由的 DeepSeek, 含平台加价",
        tags=["recommended", "coding", "aggregator", "standard"],
    ),
    # NVIDIA NIM 系列
    "z-ai/glm-5.2": ModelInfo(
        id="z-ai/glm-5.2",
        name="GLM-5.2 (NVIDIA NIM)",
        provider="nvidia",
        api_base="https://integrate.api.nvidia.com/v1",
        pricing_input=2.00,
        pricing_output=5.00,
        context_window=1048576,
        max_output_tokens=16384,
        supports_fim=False,
        supports_tools=True,
        supports_reasoning=True,
        description="753B MoE/1M上下文, 旗舰编程推理, SWE-bench 62.1%",
        tags=["coding", "reasoning", "premium", "agent"],
    ),

    # ── Agnes AI 系列 (Sapiens AI) ──
    "agnes-2.0-flash": ModelInfo(
        id="agnes-2.0-flash",
        name="Agnes 2.0 Flash",
        provider="agnes",
        api_base="https://apihub.agnes-ai.com/v1",
        pricing_input=0.0,
        pricing_output=0.0,
        context_window=524288,  # 512K 稳定，曾支持 1M
        max_output_tokens=65536,  # 64K 输出
        supports_fim=True,
        supports_tools=True,
        supports_reasoning=True,
        supports_vision=True,
        supports_cache=True,
        description="免费多模态模型, 512K上下文, Claw-Eval Top10, 工具调用/编码/视觉",
        tags=["free", "recommended", "coding", "agent", "vision", "reasoning"],
    ),
    "agnes-1.5-flash": ModelInfo(
        id="agnes-1.5-flash",
        name="Agnes 1.5 Flash",
        provider="agnes",
        api_base="https://apihub.agnes-ai.com/v1",
        pricing_input=0.0,
        pricing_output=0.0,
        context_window=262144,  # 256K
        max_output_tokens=65536,
        supports_fim=True,
        supports_tools=True,
        supports_reasoning=True,
        supports_vision=True,
        description="免费多模态模型, 256K上下文, 上一代版本",
        tags=["free", "coding", "agent", "vision"],
    ),
}


# ══════════════════════════════════════════════════════════
# 统一 Provider 接口
# ══════════════════════════════════════════════════════════


class BaseProvider:
    """统一模型提供商基类"""

    def __init__(self, name: str, display_name: str, api_base: str):
        self.name = name
        self.display_name = display_name
        self.api_base = api_base

    def get_models(self) -> list[ModelInfo]:
        """获取该提供商的所有模型"""
        return [m for m in ALL_MODELS.values() if m.provider == self.name]

    def get_model(self, model_id: str) -> ModelInfo | None:
        """获取指定模型信息"""
        return ALL_MODELS.get(model_id)

    def get_pricing(self, model_id: str) -> dict | None:
        """获取模型定价"""
        model = ALL_MODELS.get(model_id)
        if model:
            return {"input": model.pricing_input, "output": model.pricing_output}
        return None

    def supports_feature(self, model_id: str, feature: str) -> bool:
        """检查模型是否支持某特性"""
        model = ALL_MODELS.get(model_id)
        if not model:
            return False
        features = {
            "fim": model.supports_fim,
            "tools": model.supports_tools,
            "reasoning": model.supports_reasoning,
            "vision": model.supports_vision,
            "cache": model.supports_cache,
        }
        return features.get(feature, False)

    def estimate_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """估算费用"""
        model = ALL_MODELS.get(model_id)
        if not model:
            return 0.0
        input_cost = (input_tokens / 1_000_000) * model.pricing_input
        output_cost = (output_tokens / 1_000_000) * model.pricing_output
        return round(input_cost + output_cost, 6)

    def setup(self, api_key: str, **kwargs) -> dict:
        """配置 Provider"""
        return {
            "model_provider": self.name,
            "api_key": api_key,
            "api_base": self.api_base,
            "models": [m.id for m in self.get_models()],
        }


class DeepSeekProvider(BaseProvider):
    """DeepSeek (深度求索)"""

    def __init__(self):
        super().__init__("deepseek", "DeepSeek (深度求索)", "https://api.deepseek.com")


class QwenProvider(BaseProvider):
    """通义千问 (阿里云)"""

    def __init__(self):
        super().__init__(
            "qwen", "通义千问 (阿里云)", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )


class GLMProvider(BaseProvider):
    """智谱 GLM"""

    def __init__(self):
        super().__init__("glm", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4")


class OpenAIProvider(BaseProvider):
    """OpenAI"""

    def __init__(self):
        super().__init__("openai", "OpenAI", "https://api.openai.com/v1")


class OpenRouterProvider(BaseProvider):
    """OpenRouter 聚合路由平台"""

    def __init__(self):
        super().__init__("openrouter", "OpenRouter", "https://openrouter.ai/api/v1")


class NVIDIAProvider(BaseProvider):
    """NVIDIA NIM (GPU加速推理)"""

    def __init__(self):
        super().__init__("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1")


# ══════════════════════════════════════════════════════════
# 全局查询函数
# ══════════════════════════════════════════════════════════


def get_all_models() -> dict[str, ModelInfo]:
    """获取所有模型"""
    return ALL_MODELS


def get_model_info(model_id: str) -> ModelInfo | None:
    """获取模型信息"""
    return ALL_MODELS.get(model_id)


def get_models_by_provider(provider: str) -> list[ModelInfo]:
    """按提供商获取模型"""
    return [m for m in ALL_MODELS.values() if m.provider == provider]


def get_models_by_tag(tag: str) -> list[ModelInfo]:
    """按标签获取模型"""
    return [m for m in ALL_MODELS.values() if tag in m.tags]


def get_recommended_models() -> list[ModelInfo]:
    """推荐模型列表"""
    return [
        ALL_MODELS["deepseek-chat"],
        ALL_MODELS["deepseek-coder"],
        ALL_MODELS["qwen-coder-plus"],
        ALL_MODELS["glm-4"],
        ALL_MODELS["z-ai/glm-5.2"],
    ]


def get_provider_for_model(model_id: str) -> BaseProvider | None:
    """获取模型对应的 Provider 实例"""
    model = ALL_MODELS.get(model_id)
    if not model:
        return None
    if model.provider == "deepseek":
        return DeepSeekProvider()
    elif model.provider == "qwen":
        return QwenProvider()
    elif model.provider == "glm":
        return GLMProvider()
    elif model.provider == "openai":
        return OpenAIProvider()
    elif model.provider == "openrouter":
        return OpenRouterProvider()
    elif model.provider == "nvidia":
        return NVIDIAProvider()
    return None


def compare_models(
    input_tokens: int = 4000, output_tokens: int = 1000, model_ids: list[str] = None
) -> list[dict]:
    """比较多个模型的预估费用"""
    if model_ids is None:
        model_ids = [
            "deepseek-chat",
            "deepseek-coder",
            "qwen-coder-plus",
            "qwen-coder-turbo",
            "glm-4",
            "glm-4-flash",
        ]

    results = []
    for mid in model_ids:
        model = ALL_MODELS.get(mid)
        if not model:
            continue
        ip_cost = (input_tokens / 1_000_000) * model.pricing_input
        op_cost = (output_tokens / 1_000_000) * model.pricing_output
        results.append(
            {
                "model_id": mid,
                "model_name": model.name,
                "provider": model.provider,
                "input_cost": round(ip_cost, 6),
                "output_cost": round(op_cost, 6),
                "total_cost": round(ip_cost + op_cost, 6),
                "tags": model.tags,
            }
        )

    return sorted(results, key=lambda x: x["total_cost"])
