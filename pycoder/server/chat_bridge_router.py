"""ChatBridge 子模块 — Provider 路由与模型端点解析

从 chat_bridge.py 拆分而来，负责：
- Provider API Base 映射
- 模型 → Provider 自动检测
- 模型名称 → API 端点解析
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════
# API Base 映射
# ══════════════════════════════════════════════════════════

PROVIDER_API_BASES: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "agnes": "https://api.agnes-ai.cn/v1",
}


def _detect_provider(model: str) -> str:
    """检测模型所属的提供商 — 支持更多模型前缀

    防错机制（优先级从高到低）：
    1. 从 ALL_MODELS 注册表反查（最权威，避免前缀匹配陷阱）
    2. 大小写不敏感的前缀匹配（修复 "Agnes-2.5-Flash" 大写 A 不匹配的问题）
    3. 包含斜杠的模型 ID（如 google/gemini-2.0-flash）→ openrouter
    4. 兜底 → deepseek
    """
    if not model:
        return "deepseek"

    # ── 优先级 1：从 ALL_MODELS 注册表反查真实 provider ──
    try:
        from pycoder.providers.registry import ALL_MODELS

        info = ALL_MODELS.get(model)
        if info and info.provider:
            return info.provider
    except ImportError:
        pass

    # ── 优先级 2：大小写不敏感的前缀匹配 ──
    m_lower = model.lower()
    if m_lower.startswith("deepseek"):
        return "deepseek"
    if m_lower.startswith("qwen"):
        return "qwen"
    if m_lower.startswith("glm"):
        return "glm"
    # 注意：避免误匹配，gpt / o1 / o3 等以 "gpt" 或 "o" 开头但需更严格判断
    if m_lower.startswith("gpt") or m_lower.startswith("o1") or m_lower.startswith("o3"):
        return "openai"
    if m_lower.startswith("claude"):
        return "anthropic"
    if m_lower.startswith("gemini"):
        return "google"
    if m_lower.startswith("z-") or m_lower.startswith("nvidia-"):
        return "nvidia"
    if m_lower.startswith("agnes"):
        return "agnes"
    if m_lower.startswith("openrouter"):
        return "openrouter"

    # ── 优先级 3：包含斜杠的模型 ID → openrouter ──
    if "/" in model:
        return "openrouter"

    # ── 兜底 ──
    return "deepseek"


# ══════════════════════════════════════════════════════════
# P4: 多模型路由支持
# ══════════════════════════════════════════════════════════

MODEL_ROUTING: dict[str, dict[str, str]] = {
    "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base": "https://api.deepseek.com",
    },
    "deepseek-reasoner": {
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "base": "https://api.deepseek.com",
    },
    "qwen": {
        "provider": "qwen",
        "model": "qwen-coder-plus",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "glm": {
        "provider": "glm",
        "model": "glm-4-flash",
        "base": "https://open.bigmodel.cn/api/paas/v4",
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base": "https://api.openai.com/v1",
    },
}


def _resolve_model_endpoint(model: str) -> tuple[str, str]:
    """解析模型名称为 API Base URL + 实际模型名

    Args:
        model: 模型名称（deepseek/qwen/glm/gpt-4o-mini 等）

    Returns:
        (api_base_url, resolved_model_name)
    """
    # 检查是否匹配已知模型
    route = MODEL_ROUTING.get(model)
    if route:
        return route["base"], route["model"]

    # 通过前缀匹配
    for prefix, route in [
        ("deepseek-reasoner", MODEL_ROUTING.get("deepseek-reasoner")),
        ("deepseek", MODEL_ROUTING.get("deepseek")),
        ("qwen", MODEL_ROUTING.get("qwen")),
        ("glm", MODEL_ROUTING.get("glm")),
        ("gpt", MODEL_ROUTING.get("gpt-4o-mini")),
    ]:
        if model.startswith(prefix) and route:
            return route["base"], model

    # 默认回退到 DeepSeek
    return (
        PROVIDER_API_BASES.get("deepseek", "https://api.deepseek.com"),
        model,
    )


__all__ = [
    "PROVIDER_API_BASES",
    "_detect_provider",
    "MODEL_ROUTING",
    "_resolve_model_endpoint",
]
