"""
模型配置管理 — 统一管理所有 AI 模型提供商和参数配置。

功能:
- 支持多种模型提供商（OpenAI、Anthropic、Google、DeepSeek、Qwen、GLM）
- 模型参数配置（temperature、max_tokens、top_p 等）
- 模型切换与管理
- API 端点配置
- 智能模型选择
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class ModelInfo:
    """模型信息"""

    id: str
    name: str
    provider: str
    context_window: int
    max_tokens: int
    input_price: float = 0.0
    output_price: float = 0.0
    capabilities: list[str] = field(default_factory=list)
    recommended: bool = False
    description: str = ""


@dataclass
class ProviderInfo:
    """提供商信息"""

    id: str
    name: str
    key_name: str
    env_name: str
    base_url: str = ""
    api_version: str = ""
    register_url: str = ""
    docs_url: str = ""
    pricing_page: str = ""
    models: list[ModelInfo] = field(default_factory=list)
    free_trial: str = ""
    price_summary: str = ""


@dataclass
class ModelConfig:
    """模型配置"""

    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.95
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stop: list[str] = field(default_factory=list)
    system_prompt: str = ""


# ── 模型注册表 ──────────────────────────────────────────

# ── 缓存机制 ──────────────────────────────────────────────


class CacheEntry:
    def __init__(self, data: Any, ttl: float = 300):
        self.data = data
        self.created_at = time.time()
        self.ttl = ttl

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class SimpleCache:
    def __init__(self):
        self._cache: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            return entry.data
        if entry and entry.is_expired():
            del self._cache[key]
        return None

    def set(self, key: str, data: Any, ttl: float = 300):
        self._cache[key] = CacheEntry(data, ttl)

    def clear(self, key: str = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def keys(self):
        return list(self._cache.keys())


_config_cache = SimpleCache()


def cached(ttl: float = 300):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{kwargs}"
            cached_data = _config_cache.get(key)
            if cached_data is not None:
                return cached_data

            result = func(*args, **kwargs)
            _config_cache.set(key, result, ttl)
            return result

        return wrapper

    return decorator


def invalidate_cache():
    """失效所有缓存"""
    _config_cache.clear()


# ── 模型注册表 ──────────────────────────────────────────

MODEL_REGISTRY: dict[str, ProviderInfo] = {
    "deepseek": ProviderInfo(
        id="deepseek",
        name="DeepSeek (深度求索)",
        key_name="DEEPSEEK_API_KEY",
        env_name="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1",
        register_url="https://platform.deepseek.com/api_keys",
        docs_url="https://platform.deepseek.com/api-docs",
        pricing_page="https://platform.deepseek.com/pricing",
        free_trial="注册即送 500 万 tokens",
        price_summary="输入 $0.14/M | 输出 $0.28/M",
        models=[
            ModelInfo(
                id="deepseek-chat",
                name="DeepSeek Chat",
                provider="deepseek",
                context_window=128000,
                max_tokens=4096,
                input_price=0.14,
                output_price=0.28,
                capabilities=["chat", "code"],
                recommended=True,
                description="通用对话模型，中文理解优秀",
            ),
            ModelInfo(
                id="deepseek-v4-pro",
                name="DeepSeek V4 Pro",
                provider="deepseek",
                context_window=128000,
                max_tokens=4096,
                input_price=0.28,
                output_price=0.84,
                capabilities=["chat", "code", "vision"],
                recommended=True,
                description="旗舰模型，多模态能力强",
            ),
            ModelInfo(
                id="deepseek-v4-flash",
                name="DeepSeek V4 Flash",
                provider="deepseek",
                context_window=128000,
                max_tokens=4096,
                input_price=0.07,
                output_price=0.14,
                capabilities=["chat", "code"],
                description="高速模型，性价比高",
            ),
            ModelInfo(
                id="deepseek-coder",
                name="DeepSeek Coder",
                provider="deepseek",
                context_window=128000,
                max_tokens=4096,
                input_price=0.14,
                output_price=0.28,
                capabilities=["code"],
                description="代码专用模型",
            ),
        ],
    ),
    "qwen": ProviderInfo(
        id="qwen",
        name="通义千问 (阿里云)",
        key_name="QWEN_API_KEY",
        env_name="DASHSCOPE_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        register_url="https://dashscope.console.aliyun.com/apiKey",
        docs_url="https://help.aliyun.com/zh/dashscope",
        pricing_page="https://help.aliyun.com/zh/dashscope/developer-reference/tongyi-thousand-questions-metering-and-billing",
        free_trial="新用户 100 万 tokens 免费",
        price_summary="输入 $0.15-$0.80/M | 输出 $0.60-$2.00/M",
        models=[
            ModelInfo(
                id="qwen3.6-plus",
                name="Qwen 3.6B Plus",
                provider="qwen",
                context_window=128000,
                max_tokens=8192,
                input_price=0.15,
                output_price=0.60,
                capabilities=["chat", "code"],
                recommended=True,
                description="128K 上下文，代码能力强",
            ),
            ModelInfo(
                id="qwen3.6-flash",
                name="Qwen 3.6B Flash",
                provider="qwen",
                context_window=128000,
                max_tokens=8192,
                input_price=0.03,
                output_price=0.12,
                capabilities=["chat", "code"],
                description="高速模型，成本低",
            ),
            ModelInfo(
                id="qwen-coder-plus",
                name="Qwen Coder Plus",
                provider="qwen",
                context_window=128000,
                max_tokens=8192,
                input_price=0.30,
                output_price=1.20,
                capabilities=["code"],
                description="代码专用，超长上下文",
            ),
            ModelInfo(
                id="qwen-max",
                name="Qwen Max",
                provider="qwen",
                context_window=200000,
                max_tokens=8192,
                input_price=0.80,
                output_price=2.00,
                capabilities=["chat", "code", "vision"],
                description="旗舰模型，200K 上下文",
            ),
        ],
    ),
    "glm": ProviderInfo(
        id="glm",
        name="智谱 GLM (BigModel)",
        key_name="GLM_API_KEY",
        env_name="GLM_API_KEY",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        register_url="https://open.bigmodel.cn/usercenter/apikeys",
        docs_url="https://open.bigmodel.cn/dev/api",
        pricing_page="https://open.bigmodel.cn/pricing",
        free_trial="注册即送 1000 万 tokens，多款免费模型永久免费",
        price_summary="免费模型: GLM-4.7-Flash, GLM-4-Flash-250414, GLM-4V-Flash 等",
        models=[
            # ===== 免费模型 =====
            ModelInfo(
                id="glm-4.7-flash",
                name="GLM-4.7 Flash (免费)",
                provider="glm",
                context_window=200000,
                max_tokens=128000,
                input_price=0.0,
                output_price=0.0,
                capabilities=["chat", "code", "function_call", "thinking"],
                recommended=True,
                description="30B级 SOTA 模型，200K 上下文，永久免费",
            ),
            ModelInfo(
                id="glm-4-flash-250414",
                name="GLM-4-Flash-250414 (免费)",
                provider="glm",
                context_window=128000,
                max_tokens=16000,
                input_price=0.0,
                output_price=0.0,
                capabilities=["chat", "code", "function_call"],
                description="智谱首个免费大模型，128K 上下文，多语言支持",
            ),
            ModelInfo(
                id="glm-4.6v-flash",
                name="GLM-4.6V-Flash (免费)",
                provider="glm",
                context_window=128000,
                max_tokens=32000,
                input_price=0.0,
                output_price=0.0,
                capabilities=["chat", "vision", "reasoning"],
                description="免费视觉推理模型，128K 上下文",
            ),
            ModelInfo(
                id="glm-4.1v-thinking-flash",
                name="GLM-4.1V-Thinking-Flash (免费)",
                provider="glm",
                context_window=64000,
                max_tokens=16000,
                input_price=0.0,
                output_price=0.0,
                capabilities=["chat", "vision", "thinking"],
                description="免费视觉思考模型，支持深度思考",
            ),
            ModelInfo(
                id="glm-4v-flash",
                name="GLM-4V-Flash (免费)",
                provider="glm",
                context_window=16000,
                max_tokens=1000,
                input_price=0.0,
                output_price=0.0,
                capabilities=["vision"],
                description="免费图像理解模型，26种语言支持",
            ),
            # ===== 付费模型 =====
            ModelInfo(
                id="glm-5",
                name="GLM-5",
                provider="glm",
                context_window=128000,
                max_tokens=4096,
                input_price=0.10,
                output_price=0.10,
                capabilities=["chat", "code", "vision"],
                description="最新旗舰模型",
            ),
            ModelInfo(
                id="glm-4",
                name="GLM-4",
                provider="glm",
                context_window=128000,
                max_tokens=4096,
                input_price=0.10,
                output_price=0.10,
                capabilities=["chat", "code", "vision"],
                description="通用模型",
            ),
            ModelInfo(
                id="glm-4-flash",
                name="GLM-4 Flash",
                provider="glm",
                context_window=128000,
                max_tokens=4096,
                input_price=0.10,
                output_price=0.10,
                capabilities=["chat", "code"],
                description="高性价比快速模型",
            ),
            ModelInfo(
                id="glm-4v-flash-plus",
                name="GLM-4V Flash Plus",
                provider="glm",
                context_window=128000,
                max_tokens=4096,
                input_price=0.10,
                output_price=0.10,
                capabilities=["chat", "vision"],
                description="视觉增强版",
            ),
        ],
    ),
    "openai": ProviderInfo(
        id="openai",
        name="OpenAI",
        key_name="OPENAI_API_KEY",
        env_name="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        register_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs",
        pricing_page="https://openai.com/pricing",
        free_trial="新用户 $5 免费额度",
        price_summary="GPT-4o: 输入 $5/M | 输出 $15/M",
        models=[
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                provider="openai",
                context_window=128000,
                max_tokens=16384,
                input_price=5.00,
                output_price=15.00,
                capabilities=["chat", "vision"],
                recommended=True,
                description="OpenAI 旗舰模型，多模态",
            ),
            ModelInfo(
                id="gpt-4o-mini",
                name="GPT-4o mini",
                provider="openai",
                context_window=128000,
                max_tokens=16384,
                input_price=0.15,
                output_price=0.60,
                capabilities=["chat", "vision"],
                description="低成本高速模型",
            ),
            ModelInfo(
                id="gpt-4-turbo",
                name="GPT-4 Turbo",
                provider="openai",
                context_window=128000,
                max_tokens=16384,
                input_price=10.00,
                output_price=30.00,
                capabilities=["chat"],
                description="超长上下文模型",
            ),
            ModelInfo(
                id="gpt-3.5-turbo",
                name="GPT-3.5 Turbo",
                provider="openai",
                context_window=16384,
                max_tokens=4096,
                input_price=0.50,
                output_price=1.50,
                capabilities=["chat"],
                description="经典模型，成本低",
            ),
        ],
    ),
    "anthropic": ProviderInfo(
        id="anthropic",
        name="Anthropic Claude",
        key_name="ANTHROPIC_API_KEY",
        env_name="ANTHROPIC_API_KEY",
        base_url="https://api.anthropic.com/v1",
        register_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com/claude/docs",
        pricing_page="https://www.anthropic.com/pricing",
        free_trial="新用户 $20 免费额度",
        price_summary="Claude 3.5 Sonnet: 输入 $3/M | 输出 $15/M",
        models=[
            ModelInfo(
                id="claude-3-5-sonnet",
                name="Claude 3.5 Sonnet",
                provider="anthropic",
                context_window=200000,
                max_tokens=4096,
                input_price=3.00,
                output_price=15.00,
                capabilities=["chat", "code", "vision"],
                recommended=True,
                description="最强代码模型之一",
            ),
            ModelInfo(
                id="claude-3-opus",
                name="Claude 3 Opus",
                provider="anthropic",
                context_window=200000,
                max_tokens=4096,
                input_price=15.00,
                output_price=75.00,
                capabilities=["chat", "vision"],
                description="最强模型，成本高",
            ),
            ModelInfo(
                id="claude-3-haiku",
                name="Claude 3 Haiku",
                provider="anthropic",
                context_window=200000,
                max_tokens=4096,
                input_price=0.25,
                output_price=1.25,
                capabilities=["chat"],
                description="最快模型，成本极低",
            ),
        ],
    ),
    "google": ProviderInfo(
        id="google",
        name="Google Gemini",
        key_name="GOOGLE_API_KEY",
        env_name="GOOGLE_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        register_url="https://ai.google.dev/gemini-api",
        docs_url="https://ai.google.dev/docs",
        pricing_page="https://ai.google.dev/pricing",
        free_trial="免费额度可用",
        price_summary="Gemini 1.5 Pro: 输入 $1.25/M | 输出 $5/M",
        models=[
            ModelInfo(
                id="gemini-1.5-pro",
                name="Gemini 1.5 Pro",
                provider="google",
                context_window=1000000,
                max_tokens=8192,
                input_price=1.25,
                output_price=5.00,
                capabilities=["chat", "code", "vision"],
                recommended=True,
                description="1M 上下文，多模态",
            ),
            ModelInfo(
                id="gemini-1.5-flash",
                name="Gemini 1.5 Flash",
                provider="google",
                context_window=1000000,
                max_tokens=8192,
                input_price=0.15,
                output_price=0.60,
                capabilities=["chat", "code", "vision"],
                description="高速模型，1M 上下文",
            ),
            ModelInfo(
                id="gemini-1.0-pro",
                name="Gemini 1.0 Pro",
                provider="google",
                context_window=32768,
                max_tokens=2048,
                input_price=0.15,
                output_price=0.60,
                capabilities=["chat"],
                description="基础模型",
            ),
        ],
    ),
}


# ── 配置管理 ─────────────────────────────────────────────


def get_config_dir() -> Path:
    """获取配置目录"""
    return Path.home() / ".pycoder"


def get_config_path() -> Path:
    """获取配置文件路径"""
    return get_config_dir() / "config.json"


def get_key_path() -> Path:
    """获取加密密钥文件路径"""
    return get_config_dir() / "secret.key"


def _generate_key() -> bytes:
    """生成加密密钥"""
    return Fernet.generate_key()


def _load_key() -> bytes:
    """加载加密密钥，如果不存在则生成"""
    key_path = get_key_path()
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        with open(key_path, "rb") as f:
            return f.read()

    key = _generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    return key


def _encrypt_string(value: str) -> str:
    """加密字符串"""
    key = _load_key()
    fernet = Fernet(key)
    return fernet.encrypt(value.encode()).decode()


def _decrypt_string(encrypted_value: str) -> str | None:
    """解密字符串，失败返回 None"""
    try:
        key = _load_key()
        fernet = Fernet(key)
        return fernet.decrypt(encrypted_value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def load_config() -> dict:
    """加载配置"""
    path = get_config_path()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(config: dict):
    """保存配置"""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(get_config_path(), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ── API Key 管理 ───────────────────────────────────────


def get_api_key(provider: str) -> str | None:
    """获取指定提供商的 API Key"""
    if provider not in MODEL_REGISTRY:
        return None

    reg = MODEL_REGISTRY[provider]

    key = os.environ.get(reg.env_name)
    if key:
        return key

    if reg.key_name != reg.env_name:
        key = os.environ.get(reg.key_name)
        if key:
            return key

    config = load_config()
    api_keys = config.get("provider", {}).get("api_keys", {})

    encrypted_key = api_keys.get(provider)
    if encrypted_key:
        decrypted = _decrypt_string(encrypted_key)
        if decrypted:
            return decrypted
        return encrypted_key

    return None


def set_api_key(provider: str, api_key: str, set_default: bool = True) -> dict:
    """设置 API Key（加密存储）"""
    if provider not in MODEL_REGISTRY:
        return {
            "success": False,
            "provider": provider,
            "message": f"不支持的提供商: {provider}，可选: {list(MODEL_REGISTRY.keys())}",
        }

    config = load_config()

    if "provider" not in config:
        config["provider"] = {}
    if "api_keys" not in config["provider"]:
        config["provider"]["api_keys"] = {}

    encrypted_key = _encrypt_string(api_key)
    config["provider"]["api_keys"][provider] = encrypted_key

    if set_default:
        config["provider"]["default"] = provider

    save_config(config)
    invalidate_cache()

    reg = MODEL_REGISTRY[provider]
    os.environ[reg.env_name] = api_key

    return {
        "success": True,
        "provider": provider,
        "name": reg.name,
        "message": f"✅ {reg.name} API Key 已配置（加密存储）",
    }


def check_all_keys() -> dict:
    """检查所有提供商的 API Key 配置状态"""
    status = {}
    for pid, reg in MODEL_REGISTRY.items():
        key = get_api_key(pid)
        status[pid] = {
            "name": reg.name,
            "configured": bool(key),
            "key_preview": (key[:8] + "..." + key[-4:]) if key and len(key) > 12 else "N/A",
            "env_var": reg.env_name,
        }
    return status


# ── 模型管理 ─────────────────────────────────────────────


@cached(ttl=300)
def get_all_models() -> list[ModelInfo]:
    """获取所有可用模型"""
    models = []
    for provider in MODEL_REGISTRY.values():
        models.extend(provider.models)
    return models


@cached(ttl=300)
def get_models_for_provider(provider: str) -> list[ModelInfo]:
    """获取指定提供商的模型列表"""
    if provider not in MODEL_REGISTRY:
        return []
    return MODEL_REGISTRY[provider].models


@cached(ttl=300)
def get_model_info(model_id: str) -> ModelInfo | None:
    """获取模型详细信息"""
    for provider in MODEL_REGISTRY.values():
        for model in provider.models:
            if model.id == model_id:
                return model
    return None


@cached(ttl=300)
def get_provider_for_model(model_id: str) -> ProviderInfo | None:
    """获取模型所属提供商"""
    for provider in MODEL_REGISTRY.values():
        for model in provider.models:
            if model.id == model_id:
                return provider
    return None


@cached(ttl=300)
def get_recommended_models() -> list[ModelInfo]:
    """获取推荐模型"""
    models = []
    for provider in MODEL_REGISTRY.values():
        for model in provider.models:
            if model.recommended:
                models.append(model)
    return models


@cached(ttl=300)
def get_models_by_capability(capability: str) -> list[ModelInfo]:
    """按能力筛选模型"""
    models = []
    for provider in MODEL_REGISTRY.values():
        for model in provider.models:
            if capability in model.capabilities:
                models.append(model)
    return models


def get_default_model() -> str:
    """获取默认模型"""
    config = load_config()
    default_provider = config.get("provider", {}).get("default", "deepseek")
    default_model_id = config.get("provider", {}).get("default_model")

    if default_model_id:
        model = get_model_info(default_model_id)
        if model:
            return model.id

    if default_provider in MODEL_REGISTRY:
        for model in MODEL_REGISTRY[default_provider].models:
            if model.recommended:
                return model.id

    return "deepseek-chat"


def set_default_model(model_id: str) -> dict:
    """设置默认模型"""
    model = get_model_info(model_id)
    if not model:
        return {"success": False, "message": f"模型 {model_id} 不存在"}

    config = load_config()
    if "provider" not in config:
        config["provider"] = {}
    config["provider"]["default"] = model.provider
    config["provider"]["default_model"] = model_id
    save_config(config)
    invalidate_cache()

    return {
        "success": True,
        "model": model_id,
        "provider": model.provider,
        "message": f"✅ 默认模型已设置为 {model.name}",
    }


# ── 参数配置 ─────────────────────────────────────────────


def get_model_config() -> ModelConfig:
    """获取当前模型参数配置"""
    config = load_config()
    model_config = config.get("model_config", {})

    return ModelConfig(
        temperature=model_config.get("temperature", 0.7),
        max_tokens=model_config.get("max_tokens", 4096),
        top_p=model_config.get("top_p", 0.95),
        frequency_penalty=model_config.get("frequency_penalty", 0.0),
        presence_penalty=model_config.get("presence_penalty", 0.0),
        stop=model_config.get("stop", []),
        system_prompt=model_config.get("system_prompt", ""),
    )


def save_model_config(config: ModelConfig):
    """保存模型参数配置"""
    config_dict = {
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "top_p": config.top_p,
        "frequency_penalty": config.frequency_penalty,
        "presence_penalty": config.presence_penalty,
        "stop": config.stop,
        "system_prompt": config.system_prompt,
    }

    full_config = load_config()
    full_config["model_config"] = config_dict
    save_config(full_config)


def update_model_config(**kwargs) -> dict:
    """更新模型参数配置"""
    current_config = get_model_config()

    for key, value in kwargs.items():
        if hasattr(current_config, key):
            setattr(current_config, key, value)

    save_model_config(current_config)

    return {
        "success": True,
        "config": {
            "temperature": current_config.temperature,
            "max_tokens": current_config.max_tokens,
            "top_p": current_config.top_p,
            "frequency_penalty": current_config.frequency_penalty,
            "presence_penalty": current_config.presence_penalty,
            "stop": current_config.stop,
            "system_prompt": (
                current_config.system_prompt[:50] + "..." if current_config.system_prompt else ""
            ),
        },
        "message": "✅ 模型参数配置已更新",
    }


# ── 智能模型选择 ───────────────────────────────────────


def suggest_model(task_type: str = "chat") -> str:
    """
    根据任务类型智能推荐模型。

    Args:
        task_type: 任务类型 (chat/code/vision/long)

    Returns:
        推荐的模型 ID
    """
    configured_providers = [pid for pid in MODEL_REGISTRY if get_api_key(pid)]

    if not configured_providers:
        return "deepseek-chat"

    candidates = []

    if task_type == "code":
        for pid in configured_providers:
            for model in MODEL_REGISTRY[pid].models:
                if "code" in model.capabilities:
                    candidates.append((model.input_price + model.output_price, model.id))

    elif task_type == "vision":
        for pid in configured_providers:
            for model in MODEL_REGISTRY[pid].models:
                if "vision" in model.capabilities:
                    candidates.append((model.input_price + model.output_price, model.id))

    elif task_type == "long":
        for pid in configured_providers:
            for model in MODEL_REGISTRY[pid].models:
                if model.context_window >= 1000000:
                    candidates.append((model.input_price + model.output_price, model.id))

    else:
        for pid in configured_providers:
            for model in MODEL_REGISTRY[pid].models:
                if model.recommended:
                    candidates.append((model.input_price + model.output_price, model.id))

    if not candidates:
        return get_default_model()

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]
