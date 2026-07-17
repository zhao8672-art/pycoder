"""
ModelManager v2.0 — 统一的模型与 API Key 管理

功能:
- 自动检测环境变量和配置文件中的 API Key
- 智能推荐最佳可用模型
- 一键验证 API Key 可用性
- 自动降级（Key 失效时切换到下一个可用模型）
- 零配置使用（检测到环境变量自动加载）

用法:
    manager = ModelManager()
    manager.auto_detect()           # 自动检测所有可用的 Key
    model = manager.recommend()     # 推荐最佳模型
    keys = manager.check_all()      # 检查所有 Key 状态
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pycoder.providers.registry import ALL_MODELS, ModelInfo

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 提供商定义
# ══════════════════════════════════════════════════════════

PROVIDER_DEFS = {
    "deepseek": {
        "name": "DeepSeek (深度求索)",
        "env_vars": ["DEEPSEEK_API_KEY"],
        "register_url": "https://platform.deepseek.com/api_keys",
        "free_trial": "注册即送 500 万 tokens",
        "price_summary": "输入 $0.14/M, 输出 $0.28/M",
        "recommended_model": "deepseek-chat",
        "priority": 0,  # 最高优先级（性价比最高，Key 有效）
    },
    "qwen": {
        "name": "通义千问 (阿里云 DashScope)",
        "env_vars": ["DASHSCOPE_API_KEY", "QWEN_API_KEY"],
        "register_url": "https://dashscope.console.aliyun.com/apiKey",
        "free_trial": "新用户 100 万 tokens 免费",
        "price_summary": "输入 $0.15/M, 输出 $0.60/M",
        "recommended_model": "qwen-coder-plus",
        "priority": 2,
    },
    "glm": {
        "name": "智谱 GLM (智谱AI)",
        "env_vars": ["GLM_API_KEY"],
        "register_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "free_trial": "注册即送 1000 万 tokens",
        "price_summary": "输入 $0.10/M, 输出 $0.10/M",
        "recommended_model": "glm-4-flash",
        "priority": 3,
    },
    "openai": {
        "name": "OpenAI",
        "env_vars": ["OPENAI_API_KEY"],
        "register_url": "https://platform.openai.com/api-keys",
        "free_trial": "付费使用",
        "price_summary": "输入 $2.50/M, 输出 $10.00/M",
        "recommended_model": "gpt-4o-mini",
        "priority": 4,
    },
    "openrouter": {
        "name": "OpenRouter",
        "env_vars": ["OPENROUTER_API_KEY"],
        "register_url": "https://openrouter.ai/keys",
        "free_trial": "支持多种免费模型",
        "price_summary": "按模型定价",
        "recommended_model": "openrouter-deepseek-chat",
        "priority": 5,
    },
    "nvidia": {
        "name": "NVIDIA NIM (GPU加速推理)",
        "env_vars": ["NVIDIA_API_KEY"],
        "register_url": "https://build.nvidia.com/explore/discover",
        "free_trial": "注册即送 1000 次免费调用",
        "price_summary": "输入 $2.00/M, 输出 $5.00/M",
        "recommended_model": "z-ai/glm-5.2",
        "priority": 6,
    },
    "agnes": {
        "name": "Agnes AI (Sapiens AI)",
        "env_vars": ["AGNES_API_KEY"],
        "register_url": "https://platform.agnes-ai.com",
        "free_trial": "永久免费，无限调用",
        "price_summary": "输入 $0/M, 输出 $0/M",
        "recommended_model": "agnes-2.0-flash",
        "priority": 99,  # 最低优先级（Key 经常失效）
    },
}

# 注册默认模型（无 Key 时）
DEFAULT_FREE_MODEL = "deepseek-chat"


# ══════════════════════════════════════════════════════════
# 配置管理
# ══════════════════════════════════════════════════════════


def _config_path() -> Path:
    return Path.home() / ".pycoder" / "config.json"


def _load_config() -> dict:
    path = _config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"Failed to load config: {e}")
            pass
    return {}


def _save_config(config: dict):
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════
# ModelManager
# ══════════════════════════════════════════════════════════


class ModelManager:
    """统一的模型与 Key 管理器（config.json 是唯一数据源）"""

    # 已知失效 Key 黑名单（自动加入，避免反复 401）
    _blocked_keys: set[str] = set()
    _verified_providers: set[str] = set()

    def __init__(self):
        self._detected: dict[str, str] = {}  # provider → api_key
        self._selected_model: str = ""
        self._validated: dict[str, bool] = {}  # provider → is_valid
        self._last_error: str = ""

    # ── 启动引导：从 config.json 加载并同步到环境变量 ──

    def bootstrap_keys(self) -> dict[str, str]:
        """从 config.json 加载所有 Key 并同步到 os.environ。

        这是启动时唯一需要调用的方法。之后无论进程如何重启，
        os.environ 中都会有正确的 Key。
        """
        config = _load_config()
        api_keys = config.get("provider", {}).get("api_keys", {})
        self._detected = {}

        for provider, key in api_keys.items():
            if key and provider in PROVIDER_DEFS:
                if key in ModelManager._blocked_keys:
                    continue
                self._detected[provider] = key
                # 同步到环境变量（确保子进程和所有模块可见）
                env_key = PROVIDER_DEFS[provider]["env_vars"][0]
                os.environ[env_key] = key
                logger.info(
                    "bootstrap_key provider=%s prefix=%s...%s",
                    provider, key[:12], key[-4:],
                )

        # 加载失效 Key 列表
        for blocked in config.get("blocked_keys", []):
            ModelManager._blocked_keys.add(blocked)

        logger.info(
            "bootstrap_complete providers=%s",
            list(self._detected.keys()),
        )
        return dict(self._detected)

    def auto_detect(self) -> dict[str, str]:
        """检测所有可用 Key（os.environ 中，由 bootstrap_keys 注入）"""
        self._detected = {}
        for provider, defs in PROVIDER_DEFS.items():
            for env_var in defs["env_vars"]:
                key = os.environ.get(env_var, "").strip()
                if key and key not in ModelManager._blocked_keys:
                    self._detected[provider] = key
                    break
        return dict(self._detected)

    def get_key(self, provider: str) -> str:
        """获取指定提供商的 API Key"""
        return self._detected.get(provider, "")

    def get_all_keys(self) -> dict[str, str]:
        """获取所有 Key"""
        return dict(self._detected)

    def get_model_info(self, model_id: str) -> ModelInfo | None:
        """获取模型元数据"""
        if model_id in ALL_MODELS:
            return ALL_MODELS[model_id]
        return None

    def get_available_models(self) -> list[dict]:
        """
        获取当前可用的模型列表（含 API Base 等信息）。

        Returns:
            [{"id": "...", "name": "...", "provider": "...", ...}, ...]
        """
        self.auto_detect()
        custom_bases = self.get_all_custom_api_bases()
        result = []
        for mid, info in ALL_MODELS.items():
            provider = info.provider
            has_key = provider in self._detected
            # 优先使用自定义 API Base
            api_base = custom_bases.get(mid, info.api_base)
            result.append(
                {
                    "id": mid,
                    "name": info.name,
                    "provider": provider,
                    "available": has_key,
                    "pricing": f"${info.pricing_input:.2f}/${info.pricing_output:.2f}",
                    "pricing_input": info.pricing_input,
                    "pricing_output": info.pricing_output,
                    "context": info.context_window,
                    "max_output": info.max_output_tokens,
                    "api_base": api_base,
                    "features": self._get_features(info),
                    "custom_api_base": mid in custom_bases,
                }
            )
        return result

    # ── Key 验证 ──

    async def validate_key(self, provider: str, key: str) -> bool:
        """
        验证 API Key 是否有效。
        向模型 API 发送一个极小的请求来检查。
        """
        import httpx

        defs = PROVIDER_DEFS.get(provider)
        if not defs:
            return False

        try:
            api_base = ALL_MODELS[defs["recommended_model"]].api_base
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    (
                        f"{api_base}/chat/completions"
                        if provider in ("deepseek", "qwen", "openai", "openrouter")
                        else f"{api_base}/chat/completions"
                    ),
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": defs["recommended_model"],
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                return resp.status_code == 200
        except (httpx.HTTPError, OSError, ConnectionError, KeyError, TimeoutError) as e:
            logger.warning("api_key_validate_failed provider=%s error=%s", provider, e)
            return False

    def check_all(self) -> dict[str, bool]:
        """同步检查所有 Key 状态（仅本地检测，不发起网络请求）"""
        self.auto_detect()
        result = {}
        for provider in PROVIDER_DEFS:
            result[provider] = provider in self._detected
        return result

    def format_status(self) -> str:
        """格式化显示 Key 状态"""
        self.auto_detect()
        lines = ["📋 API Key 状态检测:\n"]
        for provider, defs in PROVIDER_DEFS.items():
            has = provider in self._detected
            key_preview = ""
            if has:
                k = self._detected[provider]
                key_preview = f"...{k[-6:]}" if len(k) > 10 else k[:8]
            icon = "✅" if has else "❌"
            lines.append(
                f"  {icon} {defs['name']}: {'已配置 (' + key_preview + ')' if has else '未配置'}"
            )
            if not has:
                lines.append(f"     注册: {defs['register_url']}")
                lines.append(f"     配置: 设置环境变量 {defs['env_vars'][0]}")

        available = list(self._detected.keys())
        if available:
            best_model, best_provider = self.recommend()
            lines.append(f"\n💡 推荐模型: {best_model}")
            lines.append(f"   提供商: {PROVIDER_DEFS[best_provider]['name']}")
        else:
            lines.append("\n⚠️ 未检测到任何 API Key")
            lines.append("   使用默认模型需要配置 Key")
            lines.append("   快速开始: 设置环境变量 DEEPSEEK_API_KEY=sk-xxx")

        return "\n".join(lines)

    def format_setup_guide(self, provider: str = None) -> str:
        """生成配置指南"""
        lines = [f"\n{'='*50}", "  API Key 配置指南", f"{'='*50}\n"]

        targets = [provider] if provider else PROVIDER_DEFS
        for prov in targets:
            if prov not in PROVIDER_DEFS:
                continue
            defs = PROVIDER_DEFS[prov]
            has = prov in self._detected

            lines.append(f"📌 {defs['name']}")
            lines.append(f"   状态: {'✅ 已配置' if has else '❌ 未配置'}")
            lines.append(f"   注册: {defs['register_url']}")
            lines.append(f"   推荐模型: {defs['recommended_model']}")
            if defs.get("free_trial"):
                lines.append(f"   免费额度: {defs['free_trial']}")
            if defs.get("price_summary"):
                lines.append(f"   价格参考: {defs['price_summary']}")
            lines.append("   配置方式:")
            lines.append(f"     方1️⃣  设置环境变量: set {defs['env_vars'][0]}=sk-xxx")
            lines.append(f"     方2️⃣  在 PyCoder 中运行: /setup {prov} YOUR_KEY")
            lines.append("")

        return "\n".join(lines)

    # ── Key 失效标记与持久化 ──

    def mark_key_invalid(self, provider: str):
        """标记 Key 失效（加入黑名单，永久跳过）"""
        key = self._detected.get(provider, "")
        if key:
            ModelManager._blocked_keys.add(key)
            self._validated[provider] = False
            logger.warning("key_marked_invalid provider=%s prefix=%s...%s",
                provider, key[:12], key[-4:])
            config = _load_config()
            if "blocked_keys" not in config:
                config["blocked_keys"] = []
            if key not in config["blocked_keys"]:
                config["blocked_keys"].append(key)
                _save_config(config)
            if provider in self._detected:
                del self._detected[provider]

    def mark_key_valid(self, provider: str):
        """标记 Key 有效"""
        ModelManager._verified_providers.add(provider)
        self._validated[provider] = True

    def load_blocked_keys(self):
        """从配置加载已知失效 Key"""
        config = _load_config()
        for key in config.get("blocked_keys", []):
            ModelManager._blocked_keys.add(key)

    def save_key(self, provider: str, api_key: str, set_default: bool = True) -> dict:
        """保存 API Key 到 config.json，同时同步到环境变量"""
        if provider not in PROVIDER_DEFS:
            return {"success": False, "error": f"不支持的提供商: {provider}"}
        config = _load_config()
        if "provider" not in config:
            config["provider"] = {}
        if "api_keys" not in config["provider"]:
            config["provider"]["api_keys"] = {}
        config["provider"]["api_keys"][provider] = api_key
        if set_default:
            config["provider"]["default"] = provider
        _save_config(config)
        # 同步到当前进程环境变量
        env_key = PROVIDER_DEFS[provider]["env_vars"][0]
        os.environ[env_key] = api_key
        self._detected[provider] = api_key
        return {"success": True, "message": f"✅ {PROVIDER_DEFS[provider]['name']} Key 已保存"}

    def get_saved_key(self, provider: str) -> str:
        config = _load_config()
        return config.get("provider", {}).get("api_keys", {}).get(provider, "")

    # ── 模型偏好持久化 ──

    def save_model_preference(self, model_id: str) -> dict:
        """保存用户选择的模型到配置（下次启动自动使用）"""
        if model_id not in ALL_MODELS:
            return {"success": False, "error": f"未知模型: {model_id}"}
        config = _load_config()
        config["selected_model"] = model_id
        # 同时更新默认模型，确保推荐也优先使用
        if "provider" not in config:
            config["provider"] = {}
        config["provider"]["default_model"] = model_id
        _save_config(config)
        self._selected_model = model_id
        return {"success": True, "message": f"✅ 默认模型已切换为 {model_id}"}

    def load_model_preference(self) -> str:
        """读取用户保存的模型偏好"""
        config = _load_config()
        return config.get("selected_model", "") or config.get("provider", {}).get("default_model", "")

    def save_custom_api_base(self, model_id: str, api_base: str) -> dict:
        """保存自定义 API Base URL（允许用户覆写任意模型的 API 端点）"""
        config = _load_config()
        if "custom_api_bases" not in config:
            config["custom_api_bases"] = {}
        config["custom_api_bases"][model_id] = api_base
        _save_config(config)
        return {"success": True, "message": f"✅ {model_id} 的 API 地址已设为 {api_base}"}

    def get_custom_api_base(self, model_id: str) -> str:
        """获取用户自定义的 API Base URL"""
        config = _load_config()
        return config.get("custom_api_bases", {}).get(model_id, "")

    def get_all_custom_api_bases(self) -> dict[str, str]:
        """获取所有自定义 API Base URL"""
        config = _load_config()
        return config.get("custom_api_bases", {})

    def recommend(self, task_type: str = "coding") -> tuple[str, str]:
        """
        智能推荐最佳可用模型。

        优先级: 用户手动选择 > 配置默认 > 按优先级排序

        Args:
            task_type: "coding" | "chat" | "reasoning" | "vision" | "cheap"

        Returns:
            (model_id, provider_name)
        """
        self.auto_detect()

        if not self._detected:
            return (DEFAULT_FREE_MODEL, "deepseek")

        # 1. 用户已手动选择 → 优先使用
        user_model = self.load_model_preference()
        if user_model:
            info = ALL_MODELS.get(user_model)
            if info and info.provider in self._detected:
                return (user_model, info.provider)

        # 2. 按优先级排序可用提供商，跳过黑名单
        available = []
        for provider, defs in PROVIDER_DEFS.items():
            if provider in self._detected:
                key = self._detected[provider]
                if key in ModelManager._blocked_keys:
                    continue
                available.append(
                    (defs["priority"], provider, defs["recommended_model"])
                )

        if not available:
            return (DEFAULT_FREE_MODEL, "deepseek")

        available.sort(key=lambda x: x[0])

        # 根据任务类型推荐
        if task_type == "cheap":
            for _, provider, model in available:
                if provider == "glm":
                    return (model, provider)
            return (available[0][2], available[0][1])

        if task_type == "reasoning":
            if "deepseek" in self._detected:
                return ("deepseek-reasoner", "deepseek")
            return (available[0][2], available[0][1])

        if task_type == "vision":
            if "glm" in self._detected:
                return ("glm-4v-flash", "glm")
            return (available[0][2], available[0][1])

        # 默认: coding — 按优先级返回
        return (available[0][2], available[0][1])

    # ── 内部 ──

    def _get_features(self, info: ModelInfo) -> list[str]:
        features = []
        if info.supports_fim:
            features.append("FIM补全")
        if info.supports_tools:
            features.append("工具调用")
        if info.supports_reasoning:
            features.append("深度推理")
        if info.supports_vision:
            features.append("视觉识别")
        if info.supports_cache:
            features.append("缓存加速")
        return features


# 全局单例
_instance: ModelManager | None = None


def get_model_manager() -> ModelManager:
    """获取全局 ModelManager 实例"""
    global _instance
    if _instance is None:
        _instance = ModelManager()
        _instance.load_blocked_keys()
        _instance.bootstrap_keys()
    return _instance
