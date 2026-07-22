"""P0 兼容层 — Windows 终端 GBK 编码兼容

说明：
- 该模块原位于 pycoder/__init__.py 的导入期副作用之一
- 阶段 0 架构升级：拆出独立模块，**只在首次调用 install_compat() 时打 patch**，
  避免 import pycoder 时污染全局 subprocess 行为。
- 保留 Windows GBK 兼容：subprocess 在 text=True 时默认 errors='replace'，
  防止 GBK 解码崩溃。
"""

from __future__ import annotations

import os
import subprocess as _subprocess

# 标记是否已打 patch（避免重复打补丁）
_PATCHED = False


def _patched_popen_init(self, args, **kwargs):
    """subprocess.Popen.__init__ 包装：当 text=True 且未指定 errors/encoding 时默认 errors='replace'"""
    if kwargs.get("universal_newlines") or kwargs.get("text"):
        if "errors" not in kwargs and "encoding" not in kwargs:
            kwargs["errors"] = "replace"
    _orig_popen_init(self, args, **kwargs)


def install_compat() -> None:
    """在第一次需要时打 monkey-patch（仅一次）"""
    global _PATCHED, _orig_popen_init
    if _PATCHED:
        return
    # 同时设置环境变量（必须在 subprocess 启动前完成）
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    _orig_popen_init = _subprocess.Popen.__init__
    _subprocess.Popen.__init__ = _patched_popen_init
    _PATCHED = True


__all__ = ["install_compat"]
