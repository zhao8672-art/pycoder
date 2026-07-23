"""
国际化 (i18n) 模块 — 多语言提示词和消息翻译

架构:
  1. 翻译文件存储在 pycoder/i18n/locales/ 目录
  2. 支持中文 (zh-CN) 和英文 (en-US)
  3. 通过 get_text() 函数获取翻译文本
  4. 自动检测系统语言或使用环境变量 PYCODER_LANG

用法:
  from pycoder.i18n import get_text, set_language

  set_language("zh-CN")
  msg = get_text("task.start", name="my_task")
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOCALES_DIR = Path(__file__).parent / "locales"
_CURRENT_LANG = os.environ.get("PYCODER_LANG", "zh-CN")
_TRANSLATIONS: dict[str, dict[str, str]] = {}

# ── 加载翻译文件 ──


def _load_translations() -> None:
    """加载所有翻译文件"""
    global _TRANSLATIONS
    if _TRANSLATIONS:
        return

    if not _LOCALES_DIR.exists():
        _LOCALES_DIR.mkdir(parents=True, exist_ok=True)

    for lang_file in _LOCALES_DIR.glob("*.json"):
        lang_code = lang_file.stem
        try:
            data = json.loads(lang_file.read_text(encoding="utf-8"))
            _TRANSLATIONS[lang_code] = _flatten_dict(data)
            logger.debug("加载翻译文件: %s (%d 条)", lang_code, len(_TRANSLATIONS[lang_code]))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("翻译文件 %s 加载失败: %s", lang_file, e)


def _flatten_dict(d: dict, prefix: str = "") -> dict[str, str]:
    """将嵌套字典展平为点分隔的键"""
    result: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_dict(v, key))
        elif isinstance(v, str):
            result[key] = v
    return result


# ── 公开 API ──


def set_language(lang: str) -> None:
    """设置当前语言

    Args:
        lang: 语言代码 (zh-CN / en-US)
    """
    global _CURRENT_LANG
    _CURRENT_LANG = lang
    logger.info("语言切换: %s", lang)


def get_language() -> str:
    """获取当前语言"""
    return _CURRENT_LANG


def get_text(key: str, default: str = "", **kwargs: Any) -> str:
    """获取翻译文本

    Args:
        key: 翻译键（点分隔，如 "task.start"）
        default: 默认文本（当翻译不存在时）
        **kwargs: 模板变量

    Returns:
        翻译后的文本
    """
    _load_translations()

    # 尝试当前语言
    if _CURRENT_LANG in _TRANSLATIONS:
        text = _TRANSLATIONS[_CURRENT_LANG].get(key)
        if text is not None:
            return text.format(**kwargs) if kwargs else text

    # 回退到英文
    if _CURRENT_LANG != "en-US" and "en-US" in _TRANSLATIONS:
        text = _TRANSLATIONS["en-US"].get(key)
        if text is not None:
            return text.format(**kwargs) if kwargs else text

    # 回退到默认值
    return default.format(**kwargs) if default and kwargs else default or key


# 快捷别名
_ = get_text
t = get_text


# ── 内置翻译数据 ──

_BUILTIN_TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "task.start": "任务 [{name}] 开始执行",
        "task.complete": "任务 [{name}] 已完成",
        "task.fail": "任务 [{name}] 执行失败: {error}",
        "pipeline.phase.intake": "阶段 1: 任务接入与需求解析",
        "pipeline.phase.design": "阶段 2: 架构设计与技术选型",
        "pipeline.phase.decompose": "阶段 3: 任务 DAG 拆解与调度规划",
        "pipeline.phase.env_setup": "阶段 4: 环境初始化与前置准备",
        "pipeline.phase.develop": "阶段 5: 迭代开发 + 自测提交",
        "pipeline.phase.test": "阶段 6: 全量测试 + 问题闭环",
        "pipeline.phase.deploy": "阶段 7: 部署验证与交付验收",
        "pipeline.phase.review": "阶段 8: 文档沉淀 + 自动复盘",
        "pipeline.done": "流水线执行完成",
        "pipeline.failed": "流水线执行失败",
        "quality.gate.passed": "质量门禁 L{level} 通过",
        "quality.gate.failed": "质量门禁 L{level} 未通过: {reason}",
        "auth.login_success": "登录成功",
        "auth.login_failed": "登录失败: {reason}",
        "auth.token_expired": "Token 已过期，请重新登录",
        "search.no_results": "未找到相关结果",
        "search.results_found": "找到 {count} 条结果",
        "error.unknown": "未知错误",
        "error.network": "网络连接失败",
        "error.timeout": "操作超时",
        "error.permission": "权限不足",
        "success": "操作成功",
        "cancel": "取消",
        "confirm": "确认",
        "save": "保存",
        "delete": "删除",
        "edit": "编辑",
        "create": "创建",
        "refresh": "刷新",
        "loading": "加载中...",
        "no_data": "暂无数据",
    },
    "en-US": {
        "task.start": "Task [{name}] started",
        "task.complete": "Task [{name}] completed",
        "task.fail": "Task [{name}] failed: {error}",
        "pipeline.phase.intake": "Phase 1: Task Intake & Requirement Analysis",
        "pipeline.phase.design": "Phase 2: Architecture Design & Tech Selection",
        "pipeline.phase.decompose": "Phase 3: Task DAG Decomposition & Scheduling",
        "pipeline.phase.env_setup": "Phase 4: Environment Setup & Preparation",
        "pipeline.phase.develop": "Phase 5: Iterative Development & Self-Test",
        "pipeline.phase.test": "Phase 6: Full Testing & Issue Resolution",
        "pipeline.phase.deploy": "Phase 7: Deployment Verification & Delivery",
        "pipeline.phase.review": "Phase 8: Documentation & Auto Retrospective",
        "pipeline.done": "Pipeline execution completed",
        "pipeline.failed": "Pipeline execution failed",
        "quality.gate.passed": "Quality Gate L{level} passed",
        "quality.gate.failed": "Quality Gate L{level} failed: {reason}",
        "auth.login_success": "Login successful",
        "auth.login_failed": "Login failed: {reason}",
        "auth.token_expired": "Token expired, please login again",
        "search.no_results": "No results found",
        "search.results_found": "Found {count} results",
        "error.unknown": "Unknown error",
        "error.network": "Network connection failed",
        "error.timeout": "Operation timed out",
        "error.permission": "Permission denied",
        "success": "Operation successful",
        "cancel": "Cancel",
        "confirm": "Confirm",
        "save": "Save",
        "delete": "Delete",
        "edit": "Edit",
        "create": "Create",
        "refresh": "Refresh",
        "loading": "Loading...",
        "no_data": "No data available",
    },
}


def _ensure_builtin_locales() -> None:
    """确保内置翻译文件存在"""
    _LOCALES_DIR.mkdir(parents=True, exist_ok=True)
    for lang, translations in _BUILTIN_TRANSLATIONS.items():
        locale_file = _LOCALES_DIR / f"{lang}.json"
        if not locale_file.exists():
            # 重建嵌套结构
            nested: dict[str, Any] = {}
            for key, value in translations.items():
                parts = key.split(".")
                current = nested
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
            locale_file.write_text(
                json.dumps(nested, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("创建内置翻译文件: %s", locale_file)


# 初始化时创建内置翻译
_ensure_builtin_locales()