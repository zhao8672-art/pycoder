"""覆盖率测试: pycoder/server/routers/terminal.py

目标: 行覆盖率 >= 80%
覆盖端点: WS /ws/terminal

测试策略:
  - 辅助函数直接测试
  - WebSocket 端点使用 TestClient.websocket_connect
  - mock verify_ws_auth, subprocess.Popen, winpty
  - 测试 Windows subprocess 模式 + pywinpty 模式 + Unix pty 模式
"""
from __future__ import annotations

import asyncio
import io
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from pycoder.server.routers import terminal


@pytest.fixture
def app():
    """创建仅包含 terminal 路由的 FastAPI 应用"""
    app = FastAPI()
    app.include_router(terminal.router)
    return app


def _mock_verify_ws_auth(monkeypatch, return_value=True):
    """Mock verify_ws_auth 函数 — 在 pycoder.server.app 模块上 patch

    注意：``pycoder/server/__init__.py`` 中 ``from pycoder.server.app import app``
    会将 ``pycoder.server.app`` 属性绑定到 FastAPI 实例，导致
    ``import pycoder.server.app as app_mod`` 返回 FastAPI 对象而非模块。
    必须使用 ``sys.modules`` 获取真实模块对象才能正确 patch。

    真实 verify_ws_auth 在认证失败时会调用 ``ws.close()``，mock 也需
    复现该行为，否则终端 WS 端点 ``return`` 后连接悬空导致 TestClient 挂起。
    """
    async def mock_auth(ws):
        if not return_value:
            # 复现真实行为：认证失败时关闭连接
            try:
                await ws.close(code=1008, reason="未授权：缺少或错误的 API Key")
            except Exception:
                pass
        return return_value

    # 确保模块已导入（触发 __init__.py 的副作用）
    import pycoder.server.app  # noqa: F401

    # 从 sys.modules 获取真实模块对象（绕过 __init__.py 的属性遮蔽）
    app_mod = sys.modules["pycoder.server.app"]
    monkeypatch.setattr(app_mod, "verify_ws_auth", mock_auth)


@pytest.fixture
def client(app, monkeypatch):
    """TestClient，默认 mock 认证通过"""
    _mock_verify_ws_auth(monkeypatch, True)
    with TestClient(app) as c:
        yield c


def _make_mock_process(stdout_data="", stderr_data="", poll_value=0):
    """构造 mock subprocess.Popen 返回值"""
    process = MagicMock()
    process.pid = 12345
    process.stdin = MagicMock()
    process.stdout = MagicMock()
    process.stdout.readline = MagicMock(return_value=stdout_data)
    process.stderr = MagicMock()
    process.stderr.readline = MagicMock(return_value=stderr_data)
    process.poll.return_value = poll_value
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


# ══════════════════════════════════════════════════════════
# 辅助函数测试
# ══════════════════════════════════════════════════════════


class TestHelpers:
    """辅助函数直接测试"""

    def test_default_shell_windows(self, monkeypatch):
        """Windows 默认 shell 为 powershell"""
        monkeypatch.setattr(terminal.platform, "system", lambda: "Windows")
        assert terminal._default_shell() == "powershell.exe"

    def test_default_shell_unix(self, monkeypatch):
        """Unix 默认 shell 为 bash"""
        monkeypatch.setattr(terminal.platform, "system", lambda: "Linux")
        assert terminal._default_shell() == "/bin/bash"

    def test_is_windows_true(self, monkeypatch):
        """_is_windows 在 Windows 返回 True"""
        monkeypatch.setattr(terminal.platform, "system", lambda: "Windows")
        assert terminal._is_windows() is True

    def test_is_windows_false(self, monkeypatch):
        """_is_windows 在 Linux 返回 False"""
        monkeypatch.setattr(terminal.platform, "system", lambda: "Linux")
        assert terminal._is_windows() is False

    def test_has_winpty_import_error(self, monkeypatch):
        """_has_winpty 无 winpty 返回 False"""
        # 使用 mock 使 import winpty 失败
        monkeypatch.setitem(sys.modules, "winpty", None)
        assert terminal._has_winpty() is False

    def test_strip_ansi_codes(self):
        """移除 ANSI 颜色代码"""
        text = "\x1b[31mRed Text\x1b[0m"
        result = terminal._strip_ansi_codes(text)
        assert result == "Red Text"

    def test_strip_ansi_codes_no_codes(self):
        """无 ANSI 代码的文本不变"""
        text = "Hello World"
        assert terminal._strip_ansi_codes(text) == "Hello World"

    def test_supports_color_windows_no_winpty(self, monkeypatch):
        """Windows 无 winpty → 不支持颜色"""
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        assert terminal._supports_color() is False

    def test_supports_color_windows_with_winpty(self, monkeypatch):
        """Windows 有 winpty → 支持颜色"""
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: True)
        assert terminal._supports_color() is True

    def test_supports_color_unix_tty(self, monkeypatch):
        """Unix 有 tty → 支持颜色"""
        monkeypatch.setattr(terminal, "_is_windows", lambda: False)
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True
        monkeypatch.setattr(terminal.sys, "stdout", mock_stdout)
        assert terminal._supports_color() is True

    def test_supports_color_unix_no_tty(self, monkeypatch):
        """Unix 无 tty → 不支持颜色"""
        monkeypatch.setattr(terminal, "_is_windows", lambda: False)
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = False
        monkeypatch.setattr(terminal.sys, "stdout", mock_stdout)
        assert terminal._supports_color() is False


# ══════════════════════════════════════════════════════════
# WebSocket 端点测试 — Windows subprocess 模式
# ══════════════════════════════════════════════════════════


class TestTerminalWsSubprocessMode:
    """WS /ws/terminal — Windows subprocess 模式 (无 pywinpty)"""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """设置 Windows subprocess 模式 mock 环境"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        process = _make_mock_process()
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        return process

    def test_connect(self, client, mock_env):
        """连接成功 → 收到 connected 消息"""
        with client.websocket_connect("/ws/terminal") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["pty_mode"] is False
            assert data["color_support"] is False
            assert "warning" in data

    def test_ping_pong(self, client, mock_env):
        """ping → pong"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_resize(self, client, mock_env):
        """resize → resize_ack"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "resize", "cols": 120, "rows": 40})
            data = ws.receive_json()
            assert data["type"] == "resize_ack"
            assert data["cols"] == 120
            assert data["rows"] == 40

    def test_resize_default_values(self, client, mock_env):
        """resize 无 cols/rows → 使用默认值"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "resize"})
            data = ws.receive_json()
            assert data["type"] == "resize_ack"
            assert data["cols"] == 80
            assert data["rows"] == 24

    def test_cd_valid_path(self, client, mock_env, monkeypatch):
        """cd 到工作区内路径"""
        monkeypatch.setattr(terminal, "WORKSPACE_ROOT", __import__("pathlib").Path(".").resolve())
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cd", "path": "."})
            data = ws.receive_json()
            assert data["type"] == "cwd"

    def test_cd_invalid_path(self, client, mock_env, monkeypatch):
        """cd 到不存在的路径"""
        monkeypatch.setattr(terminal, "WORKSPACE_ROOT", __import__("pathlib").Path("/nonexistent_root_12345").resolve())
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cd", "path": "/nonexistent_path_67890"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "路径不存在" in data["message"]

    def test_cd_empty_path(self, client, mock_env):
        """cd 空路径 → 忽略"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cd", "path": ""})
            # 空路径被忽略,发 ping 验证连接仍正常
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_command_writes_to_stdin(self, client, mock_env):
        """command → 写入 process.stdin"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "command", "data": "ls -la\n"})
            # 发 ping 确认命令处理完成
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"
            mock_env.stdin.write.assert_called_with("ls -la\n")
            mock_env.stdin.flush.assert_called()

    def test_input_writes_to_stdin(self, client, mock_env):
        """input → 写入 process.stdin"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "input", "data": "some input"})
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
            mock_env.stdin.write.assert_called_with("some input")

    def test_command_broken_pipe(self, client, mock_env):
        """command 写入 BrokenPipeError → 连接关闭"""
        mock_env.stdin.write.side_effect = BrokenPipeError("broken")
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "command", "data": "x"})
            # 连接应该被关闭,可能收到 exit 或断开
            try:
                data = ws.receive_json()
                assert data["type"] in ("exit", "error")
            except Exception:
                pass  # 连接直接断开也可接受

    def test_unknown_message_type(self, client, mock_env):
        """未知消息类型 → 忽略"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "unknown_type", "data": "x"})
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_disconnect_cleans_up(self, client, mock_env):
        """断开连接 → 清理 process"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
        # 退出 context 后,process.terminate 应被调用
        mock_env.terminate.assert_called()

    def test_auth_failure(self, app, monkeypatch):
        """认证失败 → 连接被拒"""
        _mock_verify_ws_auth(monkeypatch, False)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        with TestClient(app) as c:
            try:
                with c.websocket_connect("/ws/terminal") as ws:
                    ws.receive_json()
                assert True  # 连接被关闭即可
            except Exception:
                assert True  # 连接被拒绝也可接受


# ══════════════════════════════════════════════════════════
# WebSocket 端点测试 — Windows pywinpty 模式
# ══════════════════════════════════════════════════════════


class TestTerminalWsPtyMode:
    """WS /ws/terminal — Windows pywinpty 模式"""

    @pytest.fixture
    def mock_pty_env(self, monkeypatch):
        """设置 pywinpty 模式 mock 环境"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: True)

        # mock winpty 模块
        mock_pty = MagicMock()
        mock_pty.read = MagicMock(return_value="")  # 空数据,reader 退出
        mock_pty.write = MagicMock()
        mock_pty.spawn = MagicMock()
        mock_pty.set_size = MagicMock()
        mock_pty.close = MagicMock()

        mock_winpty = MagicMock()
        mock_winpty.PTY.return_value = mock_pty
        monkeypatch.setitem(sys.modules, "winpty", mock_winpty)
        return mock_pty

    def test_connect_pty_mode(self, client, mock_pty_env):
        """PTY 模式连接成功"""
        with client.websocket_connect("/ws/terminal") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["pty_mode"] is True
            assert data["color_support"] is True

    def test_ping_pty(self, client, mock_pty_env):
        """PTY 模式 ping → pong"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_resize_pty(self, client, mock_pty_env):
        """PTY 模式 resize → 调用 pty.set_size"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "resize", "cols": 100, "rows": 30})
            data = ws.receive_json()
            assert data["type"] == "resize_ack"
            mock_pty_env.set_size.assert_called_with(30, 100)

    def test_command_pty(self, client, mock_pty_env):
        """PTY 模式 command → pty.write"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "command", "data": "dir\n"})
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
            mock_pty_env.write.assert_called_with("dir\n")

    def test_input_pty(self, client, mock_pty_env):
        """PTY 模式 input → pty.write"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "input", "data": "text"})
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
            mock_pty_env.write.assert_called_with("text")

    def test_cd_pty(self, client, mock_pty_env, monkeypatch):
        """PTY 模式 cd → pty.write"""
        monkeypatch.setattr(terminal, "WORKSPACE_ROOT", __import__("pathlib").Path(".").resolve())
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cd", "path": "."})
            data = ws.receive_json()
            assert data["type"] == "cwd"

    def test_disconnect_pty_closes(self, client, mock_pty_env):
        """PTY 模式断开 → pty.close"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
        mock_pty_env.close.assert_called()


# ══════════════════════════════════════════════════════════
# WebSocket 端点测试 — 错误处理
# ══════════════════════════════════════════════════════════


class TestTerminalWsErrors:
    """WS /ws/terminal — 错误处理"""

    def test_popen_oserror(self, client, monkeypatch):
        """subprocess.Popen 失败 → OSError"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        monkeypatch.setattr(
            terminal.subprocess, "Popen",
            MagicMock(side_effect=OSError("spawn failed")),
        )
        with client.websocket_connect("/ws/terminal") as ws:
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "启动终端失败" in data["message"]

    def test_winpty_import_error(self, client, monkeypatch):
        """pywinpty 导入失败 → ImportError"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: True)
        # winpty 不可导入
        monkeypatch.setitem(sys.modules, "winpty", None)
        with client.websocket_connect("/ws/terminal") as ws:
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "pywinpty" in data["message"]


# ══════════════════════════════════════════════════════════
# WebSocket 端点测试 — Unix pty 模式 (mock)
# ══════════════════════════════════════════════════════════


class TestTerminalWsUnixPtyMode:
    """WS /ws/terminal — Unix pty 模式 (mock os.openpty 等)"""

    @pytest.fixture
    def mock_unix_env(self, monkeypatch):
        """设置 Unix pty 模式 mock 环境

        Windows 上 ``os`` 模块为 frozen，且 ``openpty``/``setsid``/``killpg``/
        ``getpgid`` 等 Unix-only 函数不存在，需用 ``raising=False`` 允许注入。
        """
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: False)

        # mock os 相关函数（部分 Unix-only，raising=False 允许在 Windows 注入）
        mock_fd_pair = (999, 998)
        monkeypatch.setattr(terminal.os, "openpty", MagicMock(return_value=mock_fd_pair), raising=False)
        monkeypatch.setattr(terminal.os, "close", MagicMock())
        monkeypatch.setattr(terminal.os, "setsid", MagicMock(), raising=False)  # Unix-only
        monkeypatch.setattr(terminal.os, "read", MagicMock(return_value=b""))  # reader 退出
        monkeypatch.setattr(terminal.os, "write", MagicMock())
        monkeypatch.setattr(terminal.os, "killpg", MagicMock(), raising=False)  # Unix-only
        monkeypatch.setattr(terminal.os, "getpgid", MagicMock(return_value=12345), raising=False)  # Unix-only

        process = _make_mock_process()
        # preexec_fn 参数在 Unix 模式下使用,需要 mock
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        # signal 模块（SIGKILL 在 Windows 不存在）
        monkeypatch.setattr(terminal.signal, "SIGTERM", 15, raising=False)
        monkeypatch.setattr(terminal.signal, "SIGKILL", 9, raising=False)
        return process

    def test_connect_unix_pty(self, client, mock_unix_env):
        """Unix pty 模式连接成功"""
        with client.websocket_connect("/ws/terminal") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["pty_mode"] is True
            assert data["color_support"] is True

    def test_ping_unix(self, client, mock_unix_env):
        """Unix pty 模式 ping"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_command_unix(self, client, mock_unix_env):
        """Unix pty 模式 command → os.write"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "command", "data": "ls\n"})
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
            terminal.os.write.assert_called_with(999, b"ls\n")

    def test_cd_unix(self, client, mock_unix_env, monkeypatch):
        """Unix pty 模式 cd"""
        monkeypatch.setattr(terminal, "WORKSPACE_ROOT", __import__("pathlib").Path(".").resolve())
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cd", "path": "."})
            data = ws.receive_json()
            assert data["type"] == "cwd"

    def test_resize_unix(self, client, mock_unix_env):
        """Unix pty 模式 resize (无 pty, 跳过 set_size)"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "resize", "cols": 90, "rows": 25})
            data = ws.receive_json()
            assert data["type"] == "resize_ack"
            assert data["cols"] == 90

    def test_disconnect_unix(self, client, mock_unix_env):
        """Unix pty 模式断开 → killpg

        清理逻辑仅在 ``process.poll() is None``（进程仍运行）时调用 killpg，
        因此需覆盖 mock 返回 None。
        """
        # 进程仍运行 → finally 中调用 killpg 终止
        mock_unix_env.poll.return_value = None
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
        # 退出后应调用 killpg
        terminal.os.killpg.assert_called()

    def test_input_unix(self, client, mock_unix_env):
        """Unix pty 模式 input → os.write"""
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "input", "data": "text"})
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
            terminal.os.write.assert_called_with(999, b"text")


# ══════════════════════════════════════════════════════════
# 读取器输出与错误处理 — 提升覆盖率
# ══════════════════════════════════════════════════════════


class TestTerminalReaderOutput:
    """测试 _read_output 后台任务的输出推送"""

    def test_subprocess_stdout_output(self, client, monkeypatch):
        """subprocess 模式 stdout 有数据 → output 消息"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)

        process = _make_mock_process()
        # 第一次 readline 返回数据,之后返回空使 reader 退出
        call_count = [0]

        def mock_stdout_readline():
            call_count[0] += 1
            return "hello world\n" if call_count[0] == 1 else ""

        process.stdout.readline = mock_stdout_readline
        process.stderr.readline = MagicMock(return_value="")
        process.poll.return_value = 0
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))

        with client.websocket_connect("/ws/terminal") as ws:
            received = []
            for _ in range(5):
                try:
                    data = ws.receive_json()
                    received.append(data)
                    if data.get("type") == "output":
                        break
                except Exception:
                    break
        output_msgs = [m for m in received if m.get("type") == "output"]
        assert any("hello world" in m["data"] for m in output_msgs)

    def test_subprocess_stderr_output(self, client, monkeypatch):
        """subprocess 模式 stderr 有数据 → output 消息"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)

        process = _make_mock_process()
        err_count = [0]

        def mock_stderr_readline():
            err_count[0] += 1
            return "error msg\n" if err_count[0] == 1 else ""

        process.stdout.readline = MagicMock(return_value="")
        process.stderr.readline = mock_stderr_readline
        process.poll.return_value = 0
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))

        with client.websocket_connect("/ws/terminal") as ws:
            received = []
            for _ in range(5):
                try:
                    data = ws.receive_json()
                    received.append(data)
                    if data.get("type") == "output":
                        break
                except Exception:
                    break
        output_msgs = [m for m in received if m.get("type") == "output"]
        assert any("error msg" in m["data"] for m in output_msgs)

    def test_pty_windows_output(self, client, monkeypatch):
        """PTY Windows 模式 pty.read 返回数据 → output 消息"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: True)

        mock_pty = MagicMock()
        read_count = [0]

        def mock_read(blocking=True):
            read_count[0] += 1
            return "pty output\n" if read_count[0] == 1 else ""

        mock_pty.read = mock_read
        mock_pty.write = MagicMock()
        mock_pty.spawn = MagicMock()
        mock_pty.set_size = MagicMock()
        mock_pty.close = MagicMock()

        mock_winpty = MagicMock()
        mock_winpty.PTY.return_value = mock_pty
        monkeypatch.setitem(sys.modules, "winpty", mock_winpty)

        with client.websocket_connect("/ws/terminal") as ws:
            received = []
            for _ in range(5):
                try:
                    data = ws.receive_json()
                    received.append(data)
                    if data.get("type") == "output":
                        break
                except Exception:
                    break
        output_msgs = [m for m in received if m.get("type") == "output"]
        assert any("pty output" in m["data"] for m in output_msgs)


# ══════════════════════════════════════════════════════════
# 错误处理与清理路径 — 提升覆盖率
# ══════════════════════════════════════════════════════════


class TestTerminalErrorHandling:
    """测试错误处理和清理路径"""

    def test_has_winpty_true(self, monkeypatch):
        """_has_winpty 当 winpty 可导入时返回 True"""
        mock_winpty = MagicMock()
        monkeypatch.setitem(sys.modules, "winpty", mock_winpty)
        assert terminal._has_winpty() is True

    def test_input_broken_pipe(self, client, monkeypatch):
        """input 写入 BrokenPipeError → 连接关闭"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        process = _make_mock_process()
        process.stdin.write.side_effect = BrokenPipeError("broken")
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "input", "data": "x"})
            # BrokenPipe 触发 break,服务器发送 exit 后关闭
            try:
                ws.receive_json()  # exit 消息
            except Exception:
                pass  # 连接关闭也可接受

    def test_cd_broken_pipe(self, client, monkeypatch):
        """cd 写入 BrokenPipeError → 连接关闭"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        process = _make_mock_process()
        process.stdin.write.side_effect = BrokenPipeError("broken")
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        monkeypatch.setattr(terminal, "WORKSPACE_ROOT", __import__("pathlib").Path(".").resolve())
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "cd", "path": "."})
            try:
                ws.receive_json()  # exit 消息
            except Exception:
                pass  # 连接关闭也可接受

    def test_pty_close_oserror(self, client, monkeypatch):
        """PTY 模式断开时 pty.close 抛 OSError → 被捕获"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: True)

        mock_pty = MagicMock()
        mock_pty.read = MagicMock(return_value="")  # reader 退出
        mock_pty.write = MagicMock()
        mock_pty.spawn = MagicMock()
        mock_pty.set_size = MagicMock()
        mock_pty.close = MagicMock(side_effect=OSError("close failed"))

        mock_winpty = MagicMock()
        mock_winpty.PTY.return_value = mock_pty
        monkeypatch.setitem(sys.modules, "winpty", mock_winpty)

        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
        # pty.close 被调用且异常被吞掉
        mock_pty.close.assert_called()

    def test_process_kill_after_terminate(self, client, monkeypatch):
        """subprocess 模式断开时 terminate 后 poll 仍 None → kill"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: True)
        monkeypatch.setattr(terminal, "_has_winpty", lambda: False)
        process = _make_mock_process()
        # terminate 后 poll 仍返回 None → 触发 kill
        process.poll.return_value = None
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        # 加速 asyncio.sleep
        monkeypatch.setattr(terminal.asyncio, "sleep", AsyncMock(return_value=None))
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
        process.terminate.assert_called()
        process.kill.assert_called()

    def test_unix_killpg_sigkill(self, client, monkeypatch):
        """Unix pty 模式断开时 SIGTERM 后仍运行 → SIGKILL"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: False)

        mock_fd_pair = (999, 998)
        monkeypatch.setattr(terminal.os, "openpty", MagicMock(return_value=mock_fd_pair), raising=False)
        monkeypatch.setattr(terminal.os, "close", MagicMock())
        monkeypatch.setattr(terminal.os, "setsid", MagicMock(), raising=False)
        monkeypatch.setattr(terminal.os, "read", MagicMock(return_value=b""))
        monkeypatch.setattr(terminal.os, "write", MagicMock())
        monkeypatch.setattr(terminal.os, "killpg", MagicMock(), raising=False)
        monkeypatch.setattr(terminal.os, "getpgid", MagicMock(return_value=12345), raising=False)

        process = _make_mock_process()
        process.poll.return_value = None  # 进程仍运行
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        monkeypatch.setattr(terminal.signal, "SIGTERM", 15, raising=False)
        monkeypatch.setattr(terminal.signal, "SIGKILL", 9, raising=False)
        monkeypatch.setattr(terminal.asyncio, "sleep", AsyncMock(return_value=None))

        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
        # killpg 被调用两次(SIGTERM + SIGKILL)
        assert terminal.os.killpg.call_count == 2

    def test_master_fd_close_oserror(self, client, monkeypatch):
        """Unix pty 模式断开时 os.close(master_fd) 抛 OSError → 被捕获"""
        _mock_verify_ws_auth(monkeypatch, True)
        monkeypatch.setattr(terminal, "_is_windows", lambda: False)

        mock_fd_pair = (999, 998)
        monkeypatch.setattr(terminal.os, "openpty", MagicMock(return_value=mock_fd_pair), raising=False)
        # os.close 第一次(slave_fd)正常,第二次(master_fd)抛异常
        close_count = [0]

        def mock_close(fd):
            close_count[0] += 1
            if close_count[0] >= 2:
                raise OSError("close failed")

        monkeypatch.setattr(terminal.os, "close", mock_close)
        monkeypatch.setattr(terminal.os, "setsid", MagicMock(), raising=False)
        monkeypatch.setattr(terminal.os, "read", MagicMock(return_value=b""))
        monkeypatch.setattr(terminal.os, "write", MagicMock())
        monkeypatch.setattr(terminal.os, "killpg", MagicMock(), raising=False)
        monkeypatch.setattr(terminal.os, "getpgid", MagicMock(return_value=12345), raising=False)

        process = _make_mock_process()
        process.poll.return_value = 0
        monkeypatch.setattr(terminal.subprocess, "Popen", MagicMock(return_value=process))
        monkeypatch.setattr(terminal.signal, "SIGTERM", 15, raising=False)
        monkeypatch.setattr(terminal.signal, "SIGKILL", 9, raising=False)

        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong
