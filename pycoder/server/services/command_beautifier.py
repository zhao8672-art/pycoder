"""
指令美化器 — 补齐缺失上下文，标准化用户指令

流程:
    原始输入 → 补齐框架/端口/路径 → 添加输出约束 → 标准化指令
"""

from __future__ import annotations

import re


def beautify_command(message: str, task_category: str = "chat") -> str:
    """美化并标准化用户指令。

    Args:
        message: 原始用户输入
        task_category: 任务类别 (chat / hermes / agent)

    Returns:
        标准化后的指令字符串
    """
    command = message.strip()

    if task_category == "chat":
        return _beautify_chat(command)

    elif task_category == "hermes":
        return _beautify_hermes(command)

    elif task_category == "agent":
        return _beautify_agent(command)

    return command


def _beautify_chat(message: str) -> str:
    """美化简单问答指令。"""
    return message


def _beautify_hermes(message: str) -> str:
    """美化 Hermes 结构化工作指令。"""
    # 补齐句号
    if not message.rstrip().endswith(("。", ".", "!", "！", ")", "】", ":", "：")):
        message = message.rstrip() + "。"

    # 如果涉及修改但未指定文件，添加探查提示
    if re.search(r'修改|修复|优化|重构|调整', message) and not re.search(
        r'[./]\w+\.\w{1,6}', message
    ):
        message += "\n\n请先读取相关文件了解上下文后再进行修改。"

    return message


def _beautify_agent(message: str) -> str:
    """美化 Agent 团队协作指令。"""
    # 补齐技术栈默认值
    if not re.search(r'python|react|vue|node|spring|go|rust|java|typescript|docker|k8s|mysql|postgres|redis|mongodb',
                     message, re.IGNORECASE):
        message += "\n\n默认技术约束:\n- 后端: Python 3.12+, FastAPI, Pydantic v2\n- 数据库: SQLite（开发）/ PostgreSQL（生产）\n- 编码规范: PEP 8, type hints, 中文注释"

    # 补齐交付物约束
    if "交付" not in message and "输出" not in message and "生成" not in message:
        message += "\n\n交付要求:\n- 所有文件完整可运行，不含占位符\n- 关键函数有 type hints 和文档字符串\n- 附带简要 README"

    return message


# 便捷导出
__all__ = ["beautify_command"]
