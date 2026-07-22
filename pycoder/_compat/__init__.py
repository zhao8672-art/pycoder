"""pycoder._compat — 兼容性补丁包

放任何"必须在运行时打"的运行时补丁。**不**在导入时执行副作用。
实际补丁实现位于 `pycoder._compat.popen.install_compat()`，
仅在 CLI/服务启动时显式调用，避免污染 import 期全局状态。
"""
from __future__ import annotations
