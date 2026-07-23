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
# 第二部分: app_lifecycle.py 模块测试
# ══════════════════════════════════════════════════════════


class TestAppLifecycle:
    """测试 pycoder/server/app_lifecycle.py 应用生命周期"""

    def test_get_uptime_positive(self):
        """get_uptime 返回正数（秒）"""
        from pycoder.server.app_lifecycle import get_uptime

        uptime = get_uptime()
        assert uptime >= 0

    def test_get_uptime_increases(self):
        """get_uptime 随时间增加"""
        import time

        from pycoder.server.app_lifecycle import get_uptime

        t1 = get_uptime()
        time.sleep(0.01)
        t2 = get_uptime()
        assert t2 >= t1

    def test_get_health_info_ok(self):
        """get_health_info 返回 status=ok"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert info["status"] == "ok"

    def test_get_health_info_contains_version(self):
        """get_health_info 包含版本号"""
        from pycoder import __version__
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert info["version"] == __version__

    def test_get_health_info_contains_python(self):
        """get_health_info 包含 Python 版本"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert info["python"] == "3.14.0"

    def test_get_health_info_contains_pid(self):
        """get_health_info 包含 pid"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert "pid" in info
        assert isinstance(info["pid"], int)

    def test_get_health_info_contains_uptime(self):
        """get_health_info 包含 uptime"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert "server_uptime_seconds" in info
        assert isinstance(info["server_uptime_seconds"], float)

    def test_run_server_calls_uvicorn(self, monkeypatch):
        """run_server 调用 uvicorn.run"""
        mock_run = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run)

        from pycoder.server.app_lifecycle import run_server

        # 避免 _check_upgrade_on_startup 副作用
        monkeypatch.setattr(
            "pycoder.server.app_lifecycle._check_upgrade_on_startup",
            lambda: None,
        )

        run_server(host="0.0.0.0", port=1234, reload=True)
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 1234
        assert call_kwargs["reload"] is True

    def test_run_server_defaults(self, monkeypatch):
        """run_server 使用默认参数"""
        mock_run = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run)
        monkeypatch.setattr(
            "pycoder.server.app_lifecycle._check_upgrade_on_startup",
            lambda: None,
        )

        from pycoder.server.app_lifecycle import run_server

        run_server()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 8423
        assert call_kwargs["reload"] is False

    def test_check_upgrade_on_startup_no_module(self, monkeypatch):
        """_check_upgrade_on_startup 在 auto_upgrade 模块不存在时静默失败"""
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", None)

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        # 不应抛出异常
        _check_upgrade_on_startup()

    def test_check_upgrade_on_startup_import_error(self, monkeypatch):
        """_check_upgrade_on_startup ImportError 时不崩溃"""
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "auto_upgrade" in name:
                raise ImportError("No module named auto_upgrade")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()  # 不应抛出异常

    def test_check_upgrade_on_startup_failed_status(self, monkeypatch, capsys):
        """_check_upgrade_on_startup 处理 failed 状态"""
        mock_check = MagicMock(return_value={"status": "failed"})
        monkeypatch.setattr(
            "pycoder.server.auto_upgrade.check_pending_on_startup",
            mock_check,
        )
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", MagicMock())
        monkeypatch.setattr(
            sys.modules["pycoder.server.auto_upgrade"],
            "check_pending_on_startup",
            mock_check,
        )

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()
        captured = capsys.readouterr()
        assert "升级恢复失败" in captured.out

    def test_check_upgrade_on_startup_resumed_status(self, monkeypatch, capsys):
        """_check_upgrade_on_startup 处理 resumed_and_completed 状态"""
        mock_check = MagicMock(return_value={"status": "resumed_and_completed"})
        monkeypatch.setattr(
            "pycoder.server.auto_upgrade.check_pending_on_startup",
            mock_check,
        )
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", MagicMock())
        monkeypatch.setattr(
            sys.modules["pycoder.server.auto_upgrade"],
            "check_pending_on_startup",
            mock_check,
        )

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()
        captured = capsys.readouterr()
        assert "升级已恢复并完成" in captured.out

    def test_check_upgrade_on_startup_exception(self, monkeypatch, capsys):
        """_check_upgrade_on_startup 异常时打印警告但不崩溃"""
        mock_check = MagicMock(side_effect=RuntimeError("测试异常"))
        monkeypatch.setattr(
            "pycoder.server.auto_upgrade.check_pending_on_startup",
            mock_check,
        )
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", MagicMock())
        monkeypatch.setattr(
            sys.modules["pycoder.server.auto_upgrade"],
            "check_pending_on_startup",
            mock_check,
        )

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()
        captured = capsys.readouterr()
        assert "升级检测跳过" in captured.out
        assert "测试异常" in captured.out


