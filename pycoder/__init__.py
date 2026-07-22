"""
PyCoder - Python 开发者原生的 AI 编程 IDE (桌面版)
"""

__version__ = "0.5.0"

# =====================================================
# 编码兼容初始化：仅设置 stdout/stderr 编码
# =====================================================
# 说明：sys.stdout.reconfigure 仅影响 Python 进程内的 stdout 编码，
# 不修改全局状态，且只在 Win32 平台生效，是安全的导入期操作。
# 子进程 UTF-8 环境变量（PYTHONUTF8 / PYTHONIOENCODING）和 Popen
# 兼容补丁已统一移至 pycoder._compat.popen.install_compat()，由
# pycoder/__main__.py 和 pycoder.server.app 在启动时显式调用。
# 这样 import pycoder 不再产生任何全局副作用，可测试性更好。
import sys

if sys.platform.startswith("win32"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def _install_subprocess_compat() -> None:
    """懒加载安装 subprocess 兼容补丁。

    阶段 0 改动：从原 __init__ 的导入期副作用拆出，改为首次需要时调用。
    调用方：pycoder/__main__.py（CLI 启动时）、pycoder.server.app.lifespan（服务启动时）。
    """
    try:
        from pycoder._compat.popen import install_compat
    except ImportError:
        return
    install_compat()
