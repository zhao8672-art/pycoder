"""
Hermes structured task engine (simplified).
_parse_hermes_output and HERMES_SYSTEM_PROMPT removed — replaced by AgentOrchestrator.
Only _execute_hermes_write is kept for file operations.
"""

from __future__ import annotations

import re


def _extract_field(section: str, field_name: str) -> str:
    """Extract field value from a structured section"""
    if not section:
        return ""
    for pat in [
        rf"\*\*{field_name}：\*\*(.+?)(?:\n|$)",
        rf"\*\*{field_name}:\*\*(.+?)(?:\n|$)",
        rf"{field_name}[:：](.+?)(?:\n|$)",
    ]:
        m = re.search(pat, section)
        if m:
            return m.group(1).strip()
    return ""


async def _execute_hermes_write(file_path: str, file_content: str) -> dict:
    """执行文件写入 (kept for compatibility)"""
    from pycoder.server.routers.files import get_workspace_root

    try:
        root = get_workspace_root()
        # 防止路径穿越 — 用 is_relative_to 替代字符串前缀匹配（M8 修复）
        target = (root / file_path).resolve()
        if not target.is_relative_to(root):
            return {"path": file_path, "success": False, "error": "路径穿越拒绝"}
        target.parent.mkdir(parents=True, exist_ok=True)
        if not file_content:
            if target.exists():
                file_content = target.read_text(encoding="utf-8")
            else:
                return {
                    "path": file_path,
                    "success": False,
                    "error": "file_content为空且文件不存在",
                }
        target.write_text(file_content, encoding="utf-8")
        return {"path": file_path, "success": True, "size": len(file_content.encode("utf-8"))}
    except Exception as e:
        return {"path": file_path, "success": False, "error": str(e)}


def _is_hermes_task(message: str) -> bool:
    """判断消息是否为 Hermes 结构化任务"""
    keywords = [
        "代码修改",
        "添加功能",
        "重构",
        "优化代码",
        "修改 bug",
        "bug修复",
        "创建文件",
        "写代码",
        "改代码",
        "新增",
        "bug",
    ]
    return any(kw in message for kw in keywords)


def _parse_hermes_output(message: str) -> dict:
    """解析 Hermes 结构化输出 — 提取 任务分析/执行计划/执行结果"""
    result: dict[str, str] = {}
    sections = {
        "goal": r"真实目的[：:](.+?)(?:\n|$|\*\*)",
        "scope": r"影响范围[：:](.+?)(?:\n|$|\*\*)",
        "priority": r"优先级[：:](.+?)(?:\n|$|\*\*)",
        "strategy": r"方案[：:](.+?)(?:\n|$|\*\*)",
    }
    for key, pattern in sections.items():
        m = re.search(pattern, message)
        if m:
            result[key] = m.group(1).strip()
    return result


__all__ = [
    "_execute_hermes_write",
    "_extract_field",
    "_is_hermes_task",
    "_parse_hermes_output",
]
