"""
PyCoder - Python 开发者原生的 AI 编程 IDE (桌面版)
"""

__version__ = "0.5.0"

import sys

# =====================================================
# Windows 终端 GBK 编码兼容：强制 UTF-8 输出
# =====================================================
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

# =====================================================
# 环境标记：强制子进程 UTF-8 管道，防止 GBK decode 崩溃
# =====================================================
import os

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# =====================================================
# Monkey-patch subprocess: text=True 时默认 errors='replace'
# 防止 Windows 上 GBK 解码崩溃（全项目一次性修复）
# =====================================================
import subprocess as _subprocess

_orig_popen_init = _subprocess.Popen.__init__


def _patched_popen_init(self, args, **kwargs):
    # 当开启了 text=True 或 universal_newlines=True 且未显式指定 errors 时
    if kwargs.get("universal_newlines") or kwargs.get("text"):
        if "errors" not in kwargs and "encoding" not in kwargs:
            kwargs["errors"] = "replace"
    _orig_popen_init(self, args, **kwargs)


_subprocess.Popen.__init__ = _patched_popen_init
