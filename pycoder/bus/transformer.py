"""
输入输出转换器 — 在 AI 和模块之间转换数据格式

确保 AI 发出的指令能被模块理解，模块返回的数据能被 AI 消费。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InputTransformer:
    """
    输入转换器 —— 将 AI 的自然语言或结构化指令转换为模块可执行的参数

    场景:
    - AI 说 "读取 main.py" → 转换为 {"path": "main.py"}
    - AI 说 "在 app/models.py 第 50 行后添加 User 模型" → 转换为结构化的编辑指令
    """

    @staticmethod
    def normalize_path(path: str, workspace_root: str = ".") -> str:
        """规范化文件路径 —— 将相对路径转为绝对路径"""
        p = Path(path)
        if p.is_absolute():
            return str(p)
        return str(Path(workspace_root) / p)

    @staticmethod
    def extract_paths(params: dict[str, Any]) -> list[str]:
        """从参数中提取所有文件路径"""
        paths: list[str] = []
        for key in ("path", "file", "file_path", "source", "target"):
            if key in params and isinstance(params[key], str):
                paths.append(params[key])
        if "paths" in params and isinstance(params["paths"], list):
            paths.extend(p for p in params["paths"] if isinstance(p, str))
        if "files" in params and isinstance(params["files"], list):
            paths.extend(str(f) for f in params["files"] if isinstance(f, (str, Path)))
        return paths

    @staticmethod
    def sanitize_shell_command(cmd: str) -> tuple[bool, str]:
        """
        清理和检查 Shell 命令

        Returns:
            (is_safe, sanitized_command)
        """
        dangerous_patterns = [
            "rm -rf /", "rm -rf ~", "rm -rf .",
            ":(){ :|:& };:",  # fork bomb
            "> /dev/sda", "dd if=",
            "chmod 777 /", "chown -R",
            "mkfs.", "format c:",
        ]

        for pattern in dangerous_patterns:
            if pattern.lower() in cmd.lower():
                return False, f"命令包含危险模式: {pattern}"

        return True, cmd

    @staticmethod
    def coerce_to_type(value: Any, target_type: type) -> Any:
        """将值强制转换为目标类型"""
        try:
            if target_type is bool:
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on")
                return bool(value)
            if target_type is int:
                return int(value)
            if target_type is float:
                return float(value)
            if target_type is str:
                return str(value)
            if target_type is list:
                if isinstance(value, list):
                    return value
                return [value]
            return value
        except (ValueError, TypeError):
            return value

    @staticmethod
    def expand_template(template: str, variables: dict[str, Any]) -> str:
        """展开模板字符串中的变量"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"${{{key}}}", str(value))
            result = result.replace(f"${key}", str(value))
        return result


class OutputTransformer:
    """
    输出转换器 —— 将模块的原始输出转换为 AI 友好格式

    场景:
    - 大文件内容 → 截断 + 行号 + 高亮关键部分
    - 错误堆栈 → 提取关键信息 + 建议修复
    - 命令输出 → 结构化解析
    """

    @staticmethod
    def format_file_content(
        content: str,
        *,
        max_lines: int = 500,
        show_line_numbers: bool = True,
        highlight_ranges: list[tuple[int, int]] | None = None,
    ) -> str:
        """格式化文件内容为 AI 友好格式"""
        lines = content.split("\n")
        total = len(lines)

        if total <= max_lines:
            # 全部返回
            if show_line_numbers:
                return "\n".join(f"{i+1:>6}| {line}" for i, line in enumerate(lines))
            return content

        # 截断：取首尾各一半
        half = max_lines // 2
        head = lines[:half]
        tail = lines[-half:]

        parts = []
        if show_line_numbers:
            parts.append("--- 文件开头 ---")
            parts.extend(f"{i+1:>6}| {line}" for i, line in enumerate(head))
            parts.append(f"... (省略 {total - max_lines} 行) ...")
            parts.extend(f"{total - half + i + 1:>6}| {line}" for i, line in enumerate(tail))
            parts.append(f"--- 文件结尾 (共 {total} 行) ---")
        else:
            parts.append("--- 文件开头 ---")
            parts.extend(head)
            parts.append(f"... (省略 {total - max_lines} 行) ...")
            parts.extend(tail)
            parts.append(f"--- 文件结尾 (共 {total} 行) ---")

        return "\n".join(parts)

    @staticmethod
    def format_error(error: Exception) -> dict[str, Any]:
        """格式化异常为结构化信息"""
        import traceback

        tb_lines = traceback.format_exception(type(error), error, error.__traceback__)

        return {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": "".join(tb_lines[-5:]),  # 只保留最后 5 帧
            "full_traceback": "".join(tb_lines),
        }

    @staticmethod
    def format_command_output(
        output: str,
        exit_code: int,
        *,
        max_lines: int = 200,
    ) -> dict[str, Any]:
        """格式化命令输出"""
        lines = output.split("\n")
        truncated = len(lines) > max_lines

        return {
            "exit_code": exit_code,
            "success": exit_code == 0,
            "output": "\n".join(lines[:max_lines]) if truncated else output,
            "lines_count": len(lines),
            "truncated": truncated,
            "first_error": OutputTransformer._extract_first_error(output) if exit_code != 0 else None,
        }

    @staticmethod
    def format_diff(diff_text: str) -> dict[str, Any]:
        """格式化 Git diff 输出"""
        stats = {"files_changed": 0, "insertions": 0, "deletions": 0}

        for line in diff_text.split("\n"):
            if line.startswith("+++ ") or line.startswith("--- "):
                if not line.endswith("/dev/null"):
                    stats["files_changed"] += 1
            elif line.startswith("+") and not line.startswith("+++"):
                stats["insertions"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                stats["deletions"] += 1

        # 除以 2 因为每个文件有 +++ 和 --- 两行
        stats["files_changed"] = stats["files_changed"] // 2

        return {
            "summary": f"{stats['files_changed']} 个文件变更, +{stats['insertions']} -{stats['deletions']}",
            "stats": stats,
            "diff": diff_text[:5000],  # 限制大小
        }

    @staticmethod
    def format_list_result(
        items: list[Any],
        *,
        item_name: str = "条目",
        max_items: int = 50,
    ) -> str:
        """格式化列表结果"""
        if not items:
            return f"没有找到{item_name}"

        lines = [f"找到 {len(items)} 个{item_name}:"]
        for i, item in enumerate(items[:max_items]):
            lines.append(f"  {i+1}. {item}")

        if len(items) > max_items:
            lines.append(f"  ... 还有 {len(items) - max_items} 个条目")

        return "\n".join(lines)

    @staticmethod
    def to_json_safe(obj: Any) -> Any:
        """将对象转换为 JSON 安全格式"""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        if isinstance(obj, (list, tuple)):
            return [OutputTransformer.to_json_safe(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): OutputTransformer.to_json_safe(v) for k, v in obj.items()}
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return {k: OutputTransformer.to_json_safe(v) for k, v in obj.__dict__.items()
                    if not k.startswith("_")}
        return str(obj)

    @staticmethod
    def _extract_first_error(output: str) -> str | None:
        """从命令输出中提取第一个错误信息"""
        error_indicators = ["Error:", "error:", "ERROR:", "FATAL:", "Traceback", "Caused by:"]
        for line in output.split("\n"):
            for indicator in error_indicators:
                if indicator in line:
                    return line.strip()
        # 取最后 5 行作为可能的错误信息
        last_lines = output.strip().split("\n")[-5:]
        return "\n".join(last_lines) if last_lines else None
