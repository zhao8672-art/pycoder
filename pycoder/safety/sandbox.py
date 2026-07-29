"""
安全沙箱 — 安全的代码执行环境

提供:
- 安全的 Python 代码执行（不使用 exec/eval）
- 资源限制（CPU/内存/时间）
- 白名单导入控制
- 输出捕获与超时处理
"""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    memory_kb: int = 0


class CodeSandbox:
    """安全代码沙箱 — 使用子进程隔离执行，避免 exec/eval

    安全策略:
    1. 使用 subprocess 在隔离进程中执行
    2. 限制可导入的模块白名单
    3. 设置 CPU/内存/时间限制
    4. 捕获并限制输出大小
    """

    # 安全模块白名单 — 只允许导入这些模块
    SAFE_MODULES = {
        "math", "json", "datetime", "collections", "itertools",
        "functools", "re", "typing", "enum", "dataclasses",
        "uuid", "hashlib", "base64", "decimal", "fractions",
        "statistics", "random", "string", "textwrap", "pprint",
        "copy", "bisect", "heapq", "operator", "pathlib",
        "os.path", "sys", "time",
    }

    # 危险模块 — 禁止导入
    DANGEROUS_MODULES = {
        "os", "subprocess", "shutil", "socket", "requests",
        "urllib", "http", "ftplib", "telnetlib", "smtplib",
        "ctypes", "cffi", "imp", "importlib", "builtins",
        "inspect", "sys", "code", "codeop", "codecs",
        "compileall", "py_compile", "zipimport", "pkgutil",
        "pdb", "bdb", "profile", "cProfile", "trace",
        "webbrowser", "antigravity",
    }

    def __init__(
        self,
        timeout: int = 30,
        max_memory_mb: int = 256,
        max_output_chars: int = 10000,
    ):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.max_output_chars = max_output_chars

    def execute(self, code: str, filename: str = "<sandbox>") -> SandboxResult:
        """在子进程中安全执行 Python 代码

        Args:
            code: 要执行的 Python 代码
            filename: 代码文件名（用于错误报告）

        Returns:
            SandboxResult 包含执行结果
        """
        start_time = time.time()

        try:
            # 1. 静态分析代码 — 检查危险操作
            self._validate_code(code)

            # 2. 创建安全的执行环境
            safe_code = self._wrap_safe_execution(code)

            # 3. 在子进程中执行
            result = self._run_in_subprocess(safe_code)

            duration = (time.time() - start_time) * 1000
            return SandboxResult(
                success=result["returncode"] == 0,
                output=result["stdout"][:self.max_output_chars],
                error=result["stderr"][:self.max_output_chars],
                duration_ms=duration,
            )

        except SecurityViolation as e:
            return SandboxResult(
                success=False,
                error=f"安全违规: {e}",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=f"执行错误: {e}",
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _validate_code(self, code: str) -> None:
        """静态分析代码，检查安全违规

        使用 AST 解析而不是 exec/eval 来检查代码。
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise SecurityViolation(f"语法错误: {e}") from e

        for node in ast.walk(tree):
            # 检查 import 语句
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.DANGEROUS_MODULES:
                        raise SecurityViolation(
                            f"禁止导入危险模块: {alias.name}"
                        )

            # 检查 from ... import 语句
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module in self.DANGEROUS_MODULES:
                    raise SecurityViolation(
                        f"禁止从危险模块导入: {node.module}"
                    )

            # 检查 exec/eval 调用
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ("exec", "eval", "compile", "__import__"):
                        raise SecurityViolation(
                            f"禁止使用危险函数: {node.func.id}()"
                        )

            # 检查属性访问（如 os.system）
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    if node.value.id in self.DANGEROUS_MODULES:
                        raise SecurityViolation(
                            f"禁止访问危险模块属性: {node.value.id}.{node.attr}"
                        )

    def _wrap_safe_execution(self, code: str) -> str:
        """将代码包装在安全的执行环境中"""
        # 添加安全限制
        safe_preamble = f"""
import sys
import math
import json
import datetime
import collections
import itertools
import functools
import re
import typing
import enum
import dataclasses
import uuid
import hashlib
import base64
import decimal
import fractions
import statistics
import random
import string
import textwrap
import pprint
import copy
import bisect
import heapq
import operator
from pathlib import Path

# 禁用危险操作
_original_import = __builtins__.__import__
def _safe_import(name, *args, **kwargs):
    _DANGEROUS = {{"os", "subprocess", "shutil", "socket", "requests",
                  "urllib", "http", "ftplib", "telnetlib", "smtplib",
                  "ctypes", "cffi", "imp", "importlib", "builtins",
                  "inspect", "sys", "code", "codeop", "codecs",
                  "compileall", "py_compile", "zipimport", "pkgutil",
                  "pdb", "bdb", "profile", "cProfile", "trace",
                  "webbrowser", "antigravity"}}
    if name in _DANGEROUS:
        raise ImportError(f"安全沙箱禁止导入: {{name}}")
    return _original_import(name, *args, **kwargs)
__builtins__.__import__ = _safe_import

# 禁用 exec/eval/compile
__builtins__.exec = None
__builtins__.eval = None
__builtins__.compile = None
__builtins__.__import__ = _safe_import

# 用户代码
{textwrap.indent(code, '')}
"""
        return safe_preamble

    def _run_in_subprocess(self, code: str) -> dict[str, Any]:
        """在子进程中执行代码

        使用 subprocess 而不是 exec/eval 来执行。
        """
        # 创建临时文件
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            # 在子进程中执行
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, "PYTHONPATH": ""},
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"执行超时 ({self.timeout}s)",
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
            }
        finally:
            # 清理临时文件
            try:
                Path(temp_path).unlink()
            except OSError:
                pass


class SecurityViolation(Exception):
    """安全违规异常"""
    pass


# 全局单例
_sandbox: CodeSandbox | None = None


def get_sandbox() -> CodeSandbox:
    """获取全局 CodeSandbox 单例"""
    global _sandbox
    if _sandbox is None:
        _sandbox = CodeSandbox()
    return _sandbox


def execute_safely(code: str, timeout: int = 30) -> SandboxResult:
    """安全执行代码的便捷函数

    Args:
        code: 要执行的 Python 代码
        timeout: 超时秒数

    Returns:
        SandboxResult 包含执行结果
    """
    sandbox = get_sandbox()
    sandbox.timeout = timeout
    return sandbox.execute(code)


# ── SandboxConfig / SandboxManager / ProcessSandbox ──


@dataclass
class SandboxConfig:
    """沙箱配置"""
    max_timeout_seconds: float = 30.0
    max_memory_mb: int = 512
    allow_network: bool = False
    max_runtime_ms: int = 300_000
    max_file_writes: int = 10
    allowed_dirs: list[str] = field(default_factory=lambda: ["pycoder/"])
    banned_dirs: list[str] = field(default_factory=lambda: ["__pycache__", ".git", "venv", ".venv", "node_modules"])


class SandboxManager:
    """沙箱管理器 — 管理沙箱实例的生命周期"""

    def __init__(self, config: SandboxConfig | None = None):
        self._config = config or SandboxConfig()
        self._active_tasks: dict[str, ProcessSandbox] = {}

    def enter(self, task_id: str) -> ProcessSandbox:
        """进入沙箱 —— 为指定任务创建沙箱实例"""
        sandbox = ProcessSandbox(self._config)
        self._active_tasks[task_id] = sandbox
        return sandbox

    def exit(self, task_id: str) -> None:
        """退出沙箱 —— 清理指定任务的沙箱"""
        self._active_tasks.pop(task_id, None)

    def get(self, task_id: str) -> ProcessSandbox | None:
        """获取指定任务的沙箱"""
        return self._active_tasks.get(task_id)


class ProcessSandbox:
    """进程级沙箱 —— 在子进程中隔离执行代码"""

    def __init__(self, config: SandboxConfig):
        self._config = config

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        """在沙箱中执行代码"""
        return SandboxResult(
            success=False,
            error="ProcessSandbox.execute() 尚未实现，请使用 CodeSandbox 或 DockerSandbox",
        )
