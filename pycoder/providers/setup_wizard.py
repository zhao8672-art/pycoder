"""
API Key 配置向导 — 精简版，完全委托给 ModelManager

提供向后兼容的 API，所有核心逻辑统一到 model_manager.py。
"""

from pycoder.providers.auth import PROVIDER_DEFS, get_model_manager


def get_api_key(provider: str) -> str:
    """获取指定提供商的 API Key（环境变量 → 配置文件）"""
    mgr = get_model_manager()
    mgr.auto_detect()
    return mgr.get_key(provider)


def set_api_key(provider: str, api_key: str, set_default: bool = True) -> dict:
    """设置 API Key 并持久化"""
    mgr = get_model_manager()
    return mgr.save_key(provider, api_key, set_default)


def get_setup_guide(provider: str = None) -> str:
    """生成配置指南"""
    mgr = get_model_manager()
    return mgr.format_setup_guide(provider)


def check_all_keys() -> dict:
    """检查所有 Key 状态"""
    mgr = get_model_manager()
    raw = mgr.check_all()
    result = {}
    for provider, configured in raw.items():
        defs = PROVIDER_DEFS.get(provider, {})
        result[provider] = {
            "name": defs.get("name", provider),
            "configured": configured,
            "key_preview": f"...{mgr.get_key(provider)[-4:]}" if configured else "N/A",
            "env_var": defs.get("env_vars", [""])[0],
        }
    return result


def format_status() -> str:
    """格式化显示 Key 状态"""
    mgr = get_model_manager()
    return mgr.format_status()
