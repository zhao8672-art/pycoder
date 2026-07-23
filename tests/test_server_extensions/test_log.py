from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════
# 第一部分: log.py 模块测试
# ══════════════════════════════════════════════════════════


class TestLogModule:
    """测试 pycoder/server/log.py 日志模块"""

    def test_get_logger_returns_logger(self, monkeypatch):
        """get_logger 返回一个有效的日志对象"""
        # 确保 structlog 可用
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        import structlog

        from pycoder.server.log import get_logger

        logger = get_logger("test_logger")
        assert logger is not None

    def test_get_logger_with_custom_name(self, monkeypatch):
        """get_logger 使用自定义名称返回日志器"""
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        from pycoder.server.log import get_logger

        logger = get_logger("my_custom_module")
        assert logger is not None

    def test_get_logger_default_name(self, monkeypatch):
        """get_logger 不传名称时使用 __name__"""
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        from pycoder.server.log import get_logger

        logger = get_logger()
        assert logger is not None

    def test_log_convenience_access(self, monkeypatch):
        """log 便捷访问变量存在"""
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        from pycoder.server.log import log

        assert log is not None

    def test_get_logger_fallback_no_structlog(self, monkeypatch):
        """没有 structlog 时降级使用标准 logging"""
        import logging

        # 模拟 structlog 导入失败：在模块导入前阻止 structlog
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "structlog":
                raise ImportError("No module named structlog")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # 删除已缓存的模块并重新导入
        for key in list(sys.modules.keys()):
            if "pycoder.server.log" in key:
                del sys.modules[key]

        import pycoder.server.log as log_mod

        logger = log_mod.get_logger("fallback_test")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_none_name_fallback(self, monkeypatch):
        """get_logger(None) 降级时返回标准 logger"""
        import logging

        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "structlog":
                raise ImportError("No module named structlog")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        for key in list(sys.modules.keys()):
            if "pycoder.server.log" in key:
                del sys.modules[key]

        import pycoder.server.log as log_mod

        logger = log_mod.get_logger(None)
        assert isinstance(logger, logging.Logger)


