"""
Prompt loader - reads system prompts from JSON with i18n support.
"""

from __future__ import annotations

import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_PROMPTS_FILE = _PROMPTS_DIR / "system_prompts.json"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        with open(_PROMPTS_FILE, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def get_prompt(name: str, lang: str = "zh") -> str:
    """Get a system prompt by name and language.

    Args:
        name: Prompt key (e.g. 'hermes', 'chat_default', 'code_review')
        lang: Language code ('zh' or 'en', default 'zh')

    Returns:
        The prompt string, or empty string if not found.
    """
    data = _load()
    versions = data.get("versions", {})
    lang_dict = versions.get(lang, {})
    prompt = lang_dict.get(name, "")
    if not prompt:
        # Fallback to root-level string
        prompt = data.get(name, "")
    return prompt


def reload():
    """Force reload prompts from disk (for hot-reload)."""
    global _cache
    _cache = None
    _load()


def get_prompt_with_cache_rules(name: str, lang: str = "zh") -> str:
    """获取已注入缓存优化规则的 prompt。

    与 `get_prompt()` 相同但自动从 `pycoder.prompts.cache_rules` 追加缓存规则。
    所有 Agent 级别的 system prompt 应优先使用此函数。

    Args:
        name: Prompt key (e.g. 'hermes', 'unified_entry')
        lang: Language code ('zh' or 'en')

    Returns:
        含缓存优化规则的完整 system prompt
    """
    from pycoder.prompts.cache_rules import inject_cache_rules

    return inject_cache_rules(get_prompt(name, lang), lang)
