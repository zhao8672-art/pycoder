"""Hermes plugin - structured coding task pipeline."""

from __future__ import annotations

import re

from pycoder.plugins.base import BasePlugin


class HermesPlugin(BasePlugin):
    """Hermes structured task pipeline: analyze -> plan -> execute -> report."""

    name = "hermes"
    description = "Structured coding task analysis and execution pipeline"
    version = "0.1.0"

    # 使用 regex 模式匹配，比精确关键词覆盖更广
    # 与 unified_entry.py 的 _TASK_PATTERNS 保持一致
    _MATCH_PATTERNS: list[tuple[str, str]] = [
        # 代码/文件修改类
        (r"修改|更改|改成|修复|添加|增加|删除|更新|优化|重构|改进", "modify"),
        (r"写一个|生成一个|创建一个|新建一个|帮我写|帮我改|帮我做|帮我.*写", "generate"),
        # 工具/命令操作类
        (r"安装|卸载|配置|设置|运行|执行|测试|调试|编译", "execute"),
        # 检查/分析类
        (r"检查|诊断|分析|查看|排查|审查|review|lint|format", "inspect"),
        # Git 操作
        (r"提交|commit|push|pull|merge|branch|stash|rebase", "git"),
        # 开发/搭建类
        (r"开发|搭建|构建|实现|设计|规划", "develop"),
        # 文件相关
        (r"\.py|\.ts|\.js|\.json|\.html|\.css|\.md|\.yaml|\.toml", "file"),
    ]

    def match(self, message: str) -> bool:
        """Match if message matches any coding-related regex pattern."""
        if len(message.strip()) < 5:
            return False
        for pattern, _category in self._MATCH_PATTERNS:
            if re.search(pattern, message):
                return True
        return False

    async def analyze(self, context: dict) -> dict:
        """Analyze the coding task request."""
        from pycoder.server.hermes_engine import _is_hermes_task, _parse_hermes_output

        message = context.get("message", "")
        analysis = _parse_hermes_output(message) if _is_hermes_task(message) else {}
        return {"analysis": analysis, "message": message}

    async def execute(self, analysis: dict) -> dict:
        """Execute the planned changes."""
        from pycoder.server.hermes_engine import _execute_hermes_write

        results = []
        files = analysis.get("files", [])
        for file_info in files:
            result = await _execute_hermes_write(
                file_info.get("path", ""), file_info.get("content", "")
            )
            results.append(result)
        return {"files_written": len(results), "results": results}
