"""
统一响应解析器 — 一次解析所有 LLM 输出格式

支持格式（按优先级）:
  1. JSON tool_calls 数组: {"tool_calls": [{"name":"read_file","params":{...}}]}
  2. JSON 单工具: {"name":"write_file","params":{...}}
  3. ReAct JSON: {"thought":"...","action":"read_file","action_input":{...}}
  4. FILE: 代码块: ```FILE:path\ncode\n```
  5. 内联代码块: ```python:path\ncode\n```
  6. 完成信号: "完成", "done", "总结:"
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 解析结果类型
# ══════════════════════════════════════════════════════════

TOOL_WRITE = {"write_file", "patch_file", "create_file", "overwrite_file"}
TOOL_READ = {"read_file", "search_code", "list_files", "git_diff", "git_log"}
TOOL_EXEC = {"run_command", "run_terminal", "execute_python"}
TOOL_GIT = {"git_add", "git_commit", "git_push", "git_status", "git_branch"}
TOOL_PACKAGE = {"install_package", "search_package", "ensure_tool", "install_deps"}
TOOL_AGENT = {"list_agent_configs"}

ALL_TOOLS = TOOL_WRITE | TOOL_READ | TOOL_EXEC | TOOL_GIT | TOOL_PACKAGE | TOOL_AGENT

WRITE_TOOLS = TOOL_WRITE
READ_TOOLS = TOOL_READ | TOOL_GIT | TOOL_AGENT


@dataclass
class ParsedResponse:
    """统一解析结果"""

    tool_calls: list[dict]  # [{"name", "params"}, ...]
    file_blocks: list[dict]  # [{"path", "content", "language"}, ...]
    completion: bool  # 是否为完成信号
    summary: str  # 如果 completion=True，这是总结文本
    raw: str  # 原始 LLM 输出
    errors: list[str]  # 解析过程中的警告/错误


# ══════════════════════════════════════════════════════════
# 完成信号模式
# ══════════════════════════════════════════════════════════

_COMPLETION_PATTERNS = [
    re.compile(r"^完成[！!。.]?"),
    re.compile(r"^总结[：:].*"),
    re.compile(r"^所有任务已完成"),
    re.compile(r"^任务完成"),
    re.compile(r"^done[.!]?$", re.IGNORECASE),
    re.compile(r"^all tasks? (are )?complete", re.IGNORECASE),
    re.compile(r"^finished[.!]?$", re.IGNORECASE),
    re.compile(r"^\u2705"),  # ✅ 开头
    re.compile(r"已完成所有任务"),
    re.compile(r"没有更多的工具需要调用"),
]

_SHORT_COMPLETION = {"完成", "done", "ok", "finished", "complete", "已全部完成"}


# ══════════════════════════════════════════════════════════
# JSON 工具调用 Schema 校验
# ══════════════════════════════════════════════════════════

TOOL_CALLS_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["name", "params"],
            },
        },
    },
    "required": ["tool_calls"],
}

REACT_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string"},
        "action_input": {"type": "object"},
    },
    "required": ["thought", "action", "action_input"],
}


# ══════════════════════════════════════════════════════════
# 统一解析器
# ══════════════════════════════════════════════════════════


def parse_response(text: str) -> ParsedResponse:
    """统一解析 LLM 响应，返回结构化的解析结果"""
    text = text.strip()
    result = ParsedResponse(
        raw=text,
        tool_calls=[],
        file_blocks=[],
        completion=False,
        summary="",
        errors=[],
    )

    if not text:
        return result

    # 1. 检测完成信号
    is_comp, summary = _detect_completion(text)
    if is_comp:
        result.completion = True
        result.summary = summary or text[:200]
        return result

    # 2. 解析 JSON 工具调用
    result.tool_calls = _extract_json_tool_calls(text)

    # 3. 解析 FILE: 代码块 (```FILE:path)
    result.file_blocks.extend(_extract_file_blocks(text))

    # 4. 解析内联代码块 (```python:path)
    if not result.tool_calls:
        inline_blocks = _extract_inline_code_blocks(text)
        result.file_blocks.extend(inline_blocks)

    return result


def _detect_completion(text: str) -> tuple[bool, str]:
    """检测 LLM 是否在表示任务完成"""
    lines = text.strip().split("\n")
    first_line = lines[0].strip() if lines else ""

    # 多行模式匹配
    for pattern in _COMPLETION_PATTERNS:
        m = pattern.match(text.strip())
        if m:
            return True, m.string[:300]

    # 短词匹配
    if first_line.lower().rstrip(".!") in _SHORT_COMPLETION:
        return True, text[:300]

    # 无工具调用 + 总结性语句
    has_json = bool(re.search(r'"tool_calls"|\{"name"|\{"thought"', text))
    has_file = bool(re.search(r"```(FILE|python|[a-z]+):", text))
    if not has_json and not has_file:
        summary_words = ["总结", "完成", "结果", "输出", "done", "summary", "conclusion"]
        for w in summary_words:
            if w in first_line.lower():
                return True, text[:300]

    return False, ""


def _extract_json_tool_calls(text: str) -> list[dict]:
    """从文本中提取 JSON 格式的工具调用"""
    calls: list[dict] = []

    # 策略 1: 找 Markdown 代码块中的 JSON
    json_blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    for block in json_blocks:
        calls.extend(_parse_json_block(block.strip()))
        if calls:
            return calls  # 找到就返回

    # 策略 2: 裸 JSON（第一个 { 到最后一个 }）
    calls = _parse_bare_json(text)
    if calls:
        return calls

    # 策略 3: 兼容单工具格式 {"name": "...", "params": {...}}
    calls = _parse_single_tool(text)
    if calls:
        return calls

    # 策略 4: ReAct 格式 {"thought": "...", "action": "...", "action_input": {...}}
    calls = _parse_react_format(text)
    if calls:
        return calls

    return []


def _parse_json_block(block: str) -> list[dict]:
    """解析一个 JSON 代码块"""
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return []

    # tool_calls 数组格式
    if isinstance(data, dict) and "tool_calls" in data:
        tcs = data["tool_calls"]
        if isinstance(tcs, list):
            validated = []
            for tc in tcs:
                if isinstance(tc, dict) and "name" in tc and "params" in tc:
                    validated.append({"name": tc["name"], "params": tc.get("params", {})})
            return validated

    # 单工具格式（JSON 块中）
    if isinstance(data, dict) and "name" in data:
        return [{"name": data["name"], "params": data.get("params", {})}]

    # 数组格式（直接是工具数组）
    if isinstance(data, list):
        validated = []
        for item in data:
            if isinstance(item, dict) and "name" in item:
                validated.append({"name": item["name"], "params": item.get("params", {})})
        return validated

    return []


def _parse_bare_json(text: str) -> list[dict]:
    """解析裸 JSON"""
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
        return []

    candidate = text[brace_start : brace_end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict) and "tool_calls" in data:
        tcs = data["tool_calls"]
        if isinstance(tcs, list):
            return [
                {"name": tc["name"], "params": tc.get("params", {})}
                for tc in tcs
                if isinstance(tc, dict) and "name" in tc
            ]

    if isinstance(data, dict) and "name" in data:
        return [{"name": data["name"], "params": data.get("params", {})}]

    return []


def _parse_single_tool(text: str) -> list[dict]:
    """兼容单工具格式: 直接输出 {"name":"read_file","params":{...}}"""
    m = re.search(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"params"\s*:', text)
    if not m:
        return []

    brace_start = text.find("{", m.start())
    brace_end = text.rfind("}")
    if brace_end <= brace_start:
        return []

    try:
        data = json.loads(text[brace_start : brace_end + 1])
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict) and "name" in data:
        return [{"name": data["name"], "params": data.get("params", {})}]
    return []


def _parse_react_format(text: str) -> list[dict]:
    """解析 ReAct 格式: {"thought":"...","action":"read_file","action_input":{...}}"""
    m = re.search(r'\{\s*"thought"\s*:', text)
    if not m:
        return []

    brace_start = text.find("{", m.start())
    brace_end = text.rfind("}")
    if brace_end <= brace_start:
        return []

    try:
        data = json.loads(text[brace_start : brace_end + 1])
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict) and "action" in data and "thought" in data:
        action = data["action"]
        if action and action.upper() != "FINISH" and action != "finish":
            return [
                {
                    "name": action,
                    "params": data.get("action_input", {}),
                    "_react_thought": data.get("thought", ""),
                }
            ]
    return []


def _extract_file_blocks(text: str) -> list[dict]:
    """解析 ```FILE:path\ncode\n``` 格式"""
    blocks: list[dict] = []
    pattern = re.compile(r"```FILE:(.+?)\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        if path and content:
            blocks.append(
                {
                    "path": path,
                    "content": content,
                    "language": "",
                    "source": "file-block",
                }
            )
    return blocks


def _extract_inline_code_blocks(text: str) -> list[dict]:
    """解析 ```language:path\ncode\n``` 格式"""
    blocks: list[dict] = []
    # 格式: ```python:path/to/file.py\ncode\n``` 或 ```python\n# path:path/to/file.py\ncode\n```
    pattern = re.compile(r"```(\w+):([^\n]+)\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(text):
        language = m.group(1)
        path = m.group(2).strip()
        content = m.group(3)
        if path and content:
            blocks.append(
                {
                    "path": path,
                    "content": content,
                    "language": language,
                    "source": "inline-block",
                }
            )

    # 补充: 检测 FILE 标记的代码块
    fp = r"```(\w+)\n.*?(?:#\s*file:\s*([^\n]+)"
    fp += r"|//\s*file:\s*([^\n]+)).*?\n(.*?)```"
    file_pattern = re.compile(fp, re.DOTALL)
    for m in file_pattern.finditer(text):
        language = m.group(1)
        path = m.group(2) or m.group(3) or ""
        content = m.group(4)
        if path and content:
            blocks.append(
                {
                    "path": path.strip(),
                    "content": content,
                    "language": language,
                    "source": "inline-block",
                }
            )

    return blocks


def is_tool_name_valid(name: str) -> bool:
    """检查工具名是否在已知工具集中"""
    return name in ALL_TOOLS or name.startswith("pycoder.") or name.startswith("_")


def validate_tool_call(tc: dict) -> tuple[bool, str]:
    """校验单个工具调用"""
    name = tc.get("name", "")
    params = tc.get("params", {})
    if not name:
        return False, "工具名称为空"
    if not isinstance(params, dict):
        return False, f"工具 '{name}' 的参数必须是对象"
    return True, ""
