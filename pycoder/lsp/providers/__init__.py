"""多语言 LSP Provider — 各语言 LSP 客户端封装

每个 Provider 封装对应语言的 LSP 服务器交互逻辑，
包括初始化、诊断获取、补全请求等。
"""
from __future__ import annotations

from pycoder.lsp.providers.javascript import JavaScriptProvider
from pycoder.lsp.providers.java import JavaProvider
from pycoder.lsp.providers.cpp import CppProvider
from pycoder.lsp.providers.go import GoProvider

__all__ = [
    "JavaScriptProvider", "JavaProvider", "CppProvider", "GoProvider",
]