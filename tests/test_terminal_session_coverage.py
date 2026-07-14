"""terminal_session 模块覆盖率测试 — 持久化终端会话管理

覆盖 pycoder.server.terminal_session:
- TerminalSession: run / set_env / export_env / get_history
- TerminalSessionManager: create / get / list_sessions / run / cleanup
- get_terminal_manager 单例

测试策略：mock subprocess.run（在 run() 内导入），隔离 cwd 解析逻辑。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import pycoder.server.terminal_session as ts_mod
from pycoder.server.terminal_session import (
    TerminalSession,
    TerminalSessionManager,
    get_terminal_manager,
)


# ══════════════════════════════════════════════════════════
# TerminalSession 初始化
# ══════════════════════════════════════════════════════════


class TestTerminalSessionInit:
    def test_init_captures_cwd_and_env(self):
        s = TerminalSession("sid")
        assert s.id == "sid"
        assert s.cwd  # 当前工作目录
        assert isinstance(s.env, dict)
        assert "PATH" in s.env or len(s.env) > 0
        assert s.history == []
        assert s.created_at > 0
        assert s.last_active > 0


# ══════════════════════════════════════════════════════════
# TerminalSession.run
# ══════════════════════════════════════════════════════════


class TestRun:
    def test_run_success(self, monkeypatch):
        s = TerminalSession("s1")
        mock_proc = MagicMock(returncode=0, stdout="hello\n", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = s.run("echo hi")
        assert result["success"] is True
        assert result["output"] == "hello\n"
        assert result["exit_code"] == 0
        assert result["cwd"] == s.cwd

    def test_run_failure(self, monkeypatch):
        s = TerminalSession("s1")
        mock_proc = MagicMock(returncode=1, stdout="", stderr="err msg")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = s.run("false")
        assert result["success"] is False
        assert result["error"] == "err msg"
        assert result["exit_code"] == 1

    def test_run_timeout(self, monkeypatch):
        s = TerminalSession("s1")

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=60)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        result = s.run("sleep 100")
        assert result["success"] is False
        assert "超时" in result["error"]

    def test_run_general_exception(self, monkeypatch):
        s = TerminalSession("s1")

        def raise_exc(*a, **k):
            raise ValueError("oops")

        monkeypatch.setattr(subprocess, "run", raise_exc)
        result = s.run("anything")
        assert result["success"] is False
        assert "oops" in result["error"]

    def test_run_cd_relative(self, monkeypatch, tmp_path):
        s = TerminalSession("s1")
        s.cwd = str(tmp_path)
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run("cd subdir")
        assert s.cwd == str(tmp_path / "subdir")

    def test_run_cd_parent(self, monkeypatch, tmp_path):
        s = TerminalSession("s1")
        s.cwd = str(tmp_path / "deep")
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run("cd ..")
        assert s.cwd == str(tmp_path)

    def test_run_cd_absolute(self, monkeypatch, tmp_path):
        """测试 cd 到绝对路径（使用平台原生绝对路径）"""
        s = TerminalSession("s1")
        s.cwd = str(tmp_path)
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        # 使用 tmp_path 作为绝对路径目标，确保跨平台兼容
        abs_target = str(tmp_path / "abs_target")
        (tmp_path / "abs_target").mkdir(exist_ok=True)
        s.run(f"cd {abs_target}")
        assert s.cwd == abs_target

    def test_run_cd_double_quoted(self, monkeypatch, tmp_path):
        s = TerminalSession("s1")
        s.cwd = str(tmp_path)
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run('cd "my dir"')
        assert s.cwd == str(tmp_path / "my dir")

    def test_run_cd_single_quoted(self, monkeypatch, tmp_path):
        s = TerminalSession("s1")
        s.cwd = str(tmp_path)
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run("cd 'my dir2'")
        assert s.cwd == str(tmp_path / "my dir2")

    def test_run_records_history(self, monkeypatch):
        s = TerminalSession("s1")
        mock_proc = MagicMock(returncode=0, stdout="output", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run("echo hi")
        assert len(s.history) == 1
        assert s.history[0]["command"] == "echo hi"
        assert s.history[0]["output"] == "output"

    def test_run_updates_last_active(self, monkeypatch):
        s = TerminalSession("s1")
        old_active = s.last_active
        time.sleep(0.01)
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run("echo")
        assert s.last_active > old_active

    def test_run_truncates_output(self, monkeypatch):
        s = TerminalSession("s1")
        long_out = "x" * 6000
        long_err = "y" * 1500
        mock_proc = MagicMock(returncode=0, stdout=long_out, stderr=long_err)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = s.run("cmd")
        assert len(result["output"]) == 5000
        assert len(result["error"]) == 1000

    def test_run_history_output_truncated(self, monkeypatch):
        """history 中的 output 字段限制为 200 字符"""
        s = TerminalSession("s1")
        long_out = "x" * 300
        mock_proc = MagicMock(returncode=0, stdout=long_out, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        s.run("cmd")
        assert len(s.history[-1]["output"]) == 200


# ══════════════════════════════════════════════════════════
# set_env / export_env / get_history
# ══════════════════════════════════════════════════════════


class TestSetEnv:
    def test_set_env(self):
        s = TerminalSession("s1")
        s.set_env("FOO", "bar")
        assert s.env["FOO"] == "bar"

    def test_set_env_overrides(self):
        s = TerminalSession("s1")
        s.set_env("X", "1")
        s.set_env("X", "2")
        assert s.env["X"] == "2"


class TestExportEnv:
    def test_export_env(self):
        s = TerminalSession("s1")
        s.env = {"A": "1", "B": "2"}
        exported = s.export_env()
        assert "export A=1" in exported
        assert "export B=2" in exported

    def test_export_env_empty(self):
        s = TerminalSession("s1")
        s.env = {}
        assert s.export_env() == ""

    def test_export_env_multiline(self):
        s = TerminalSession("s1")
        s.env = {"X": "y"}
        exported = s.export_env()
        assert exported == "export X=y"


class TestGetHistory:
    def test_default_limit(self, monkeypatch):
        s = TerminalSession("s1")
        mock_proc = MagicMock(returncode=0, stdout="o", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        for i in range(25):
            s.run(f"cmd{i}")
        history = s.get_history()
        assert len(history) == 20  # 默认 limit=20

    def test_custom_limit(self, monkeypatch):
        s = TerminalSession("s1")
        mock_proc = MagicMock(returncode=0, stdout="o", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        for i in range(10):
            s.run(f"cmd{i}")
        history = s.get_history(limit=5)
        assert len(history) == 5
        # 应返回最后 5 条
        assert history[-1]["command"] == "cmd9"

    def test_empty_history(self):
        s = TerminalSession("s1")
        assert s.get_history() == []


# ══════════════════════════════════════════════════════════
# TerminalSessionManager
# ══════════════════════════════════════════════════════════


class TestManagerCreate:
    def test_create_with_id(self):
        m = TerminalSessionManager()
        s = m.create("mysession")
        assert s.id == "mysession"
        assert "mysession" in m._sessions

    def test_create_without_id_generates_id(self):
        m = TerminalSessionManager()
        s = m.create("")
        assert s.id  # 自动生成
        assert len(s.id) > 0

    def test_create_returns_new_instance(self):
        m = TerminalSessionManager()
        s1 = m.create("a")
        s2 = m.create("b")
        assert s1 is not s2


class TestManagerGet:
    def test_get_existing(self):
        m = TerminalSessionManager()
        m.create("x")
        s = m.get("x")
        assert s is not None
        assert s.id == "x"

    def test_get_nonexistent_under_limit_auto_creates(self):
        """会话数 < 10 时，get 不存在的会话会自动创建"""
        m = TerminalSessionManager()
        s = m.get("new")
        assert s is not None
        assert s.id == "new"
        assert "new" in m._sessions

    def test_get_nonexistent_at_limit_returns_none(self):
        """会话数达 10 时，get 不存在的会话返回 None"""
        m = TerminalSessionManager()
        for i in range(10):
            m.create(f"session{i}")
        s = m.get("new")
        assert s is None


class TestManagerListSessions:
    def test_list_empty(self):
        m = TerminalSessionManager()
        assert m.list_sessions() == []

    def test_list_returns_session_metadata(self):
        m = TerminalSessionManager()
        m.create("a")
        m.create("b")
        sessions = m.list_sessions()
        assert len(sessions) == 2
        ids = [s["id"] for s in sessions]
        assert set(ids) == {"a", "b"}
        # 验证字段
        for s in sessions:
            assert "cwd" in s
            assert "history_count" in s
            assert "created_at" in s


class TestManagerRun:
    def test_run_with_existing_session(self, monkeypatch):
        m = TerminalSessionManager()
        m.create("s1")
        mock_proc = MagicMock(returncode=0, stdout="o", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = m.run("s1", "echo hi")
        assert result["success"] is True

    def test_run_auto_creates_session(self, monkeypatch):
        """run 不存在的会话时通过 get 自动创建"""
        m = TerminalSessionManager()
        mock_proc = MagicMock(returncode=0, stdout="o", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = m.run("new_session", "echo hi")
        assert result["success"] is True
        assert "new_session" in m._sessions

    def test_run_creates_session_at_limit(self, monkeypatch):
        """会话数达 10 时，run 仍能通过 fallback 创建会话"""
        m = TerminalSessionManager()
        for i in range(10):
            m.create(f"session{i}")
        mock_proc = MagicMock(returncode=0, stdout="o", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = m.run("brand_new", "echo hi")
        assert result["success"] is True
        assert "brand_new" in m._sessions


class TestManagerCleanup:
    def test_cleanup_removes_old_sessions(self):
        m = TerminalSessionManager()
        s = m.create("old")
        s.last_active = time.time() - 7200  # 2 小时前
        m.cleanup(max_age=3600)
        assert "old" not in m._sessions

    def test_cleanup_keeps_recent_sessions(self):
        m = TerminalSessionManager()
        s = m.create("recent")
        s.last_active = time.time()  # 当前
        m.cleanup(max_age=3600)
        assert "recent" in m._sessions

    def test_cleanup_with_custom_max_age(self):
        m = TerminalSessionManager()
        s = m.create("mid")
        s.last_active = time.time() - 100  # 100 秒前
        # max_age=50 应清除，max_age=200 应保留
        m.cleanup(max_age=50)
        assert "mid" not in m._sessions

    def test_cleanup_empty_manager(self):
        m = TerminalSessionManager()
        m.cleanup()  # 不应抛异常


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_terminal_manager_singleton(self, monkeypatch):
        monkeypatch.setattr(ts_mod, "_terminal_mgr", None)
        m1 = get_terminal_manager()
        m2 = get_terminal_manager()
        assert m1 is m2

    def test_returns_terminal_session_manager(self, monkeypatch):
        monkeypatch.setattr(ts_mod, "_terminal_mgr", None)
        assert isinstance(get_terminal_manager(), TerminalSessionManager)
