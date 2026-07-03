"""
代码执行沙箱 — 安全地运行 Python 代码片段

端点:
    POST /api/code/exec  — 执行 Python 代码
    POST /api/code/install  — 安装临时依赖

安全措施:
    - 受限的 globals/locals（禁用危险内置函数）
    - 超时限制（默认 10 秒）
    - 内存限制模拟
    - 禁止访问文件系统、网络、进程
"""

from __future__ import annotations

import io
import sys
import time
import traceback
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from typing import Optional

# ─── Pre-execution scanners (defense layer) ───
import re

SCAN_PATTERNS = [
    (re.compile(r'__import__\s*\('), "blocked: __import__ usage"),
    (re.compile(r'\.__subclasses__\s*\(\)'), "blocked: subclass traversal"),
    (re.compile(r'getattr\s*\(.*__[a-z]'), "blocked: dunder attr access"),
    (re.compile(r'compile\s*\(("|\')'), "blocked: compile() usage"),
]


def pre_scan_code(code: str) -> list[str]:
    """Static pre-scan for dangerous patterns. Returns violations list."""
    violations = []
    for pattern, label in SCAN_PATTERNS:
        if pattern.search(code):
            violations.append(label)
    return violations


IMPORT_SCAN = re.compile(
    r'(?:^|\n)\s*(?:from\s+(\S+)\s+import|import\s+(\S+))',
    re.MULTILINE,
)


def scan_banned_imports(code: str) -> list[str]:
    """Scan for banned module imports. Returns blocked module names."""
    blocked = []
    for match in IMPORT_SCAN.finditer(code):
        mod = (match.group(1) or match.group(2)).split(".")[0].strip()
        if mod in BANNED_MODULES:
            blocked.append(mod)
    return blocked


from fastapi import APIRouter, HTTPException, Request
from pycoder.server.log import log
from pydantic import BaseModel

router = APIRouter()


# ── 配置 ──────────────────────────────────────────────────
DEFAULT_TIMEOUT = 10  # 秒
MAX_OUTPUT_LENGTH = 10000  # 最大输出字符数
MAX_MEMORY_MB = 128  # 最大内存（模拟）


# ── 受限环境 ──────────────────────────────────────────────
# 禁用这些内置函数和模块
BANNED_BUILTINS = {
    "open", "file", "compile", "eval", "exec", "reload",
    "__import__", "input", "print",  # print 被重定向输出
    "breakpoint", "help",  # 交互式功能
}

# 受限模块
BANNED_MODULES = {
    "os", "sys", "subprocess", "socket", "urllib", "http",
    "requests", "aiohttp", "httpx", "websockets",
    "threading", "multiprocessing", "concurrent",
    "ctypes", "cffi", "winreg", "msvcrt",
    "resource", "signal", "ptrace",
    "importlib", "pkgutil", "zipimport",
    "gc", "sysconfig",
    "pathlib", "glob", "fnmatch",
    "shutil", "tempfile",
    "sqlite3", "dbm", "anydbm",
    "marshal", "yaml",
    "html", "urllib", "http", "cgi",
    "webbrowser", "curses", "tty", "termios",
    "fcntl", "grp", "pwd", "spwd",
    "tarfile", "zipfile",
}
