"""
执行任务卡死修复的验证测试

根因：终端 WebSocket 读取线程因阻塞系统调用（pty.read(blocking=True) /
os.read / readline）永久卡住，客户端断连后线程泄漏，积累后耗尽默认
ThreadPoolExecutor，导致整个服务器所有 run_in_executor / asyncio.to_thread
调用排队等待 → 服务器假死。code_exec 的 subprocess.run 在孙进程持有管道时
communicate() 永久挂起，同样耗尽线程池。

本测试验证修复效果：
1. _kill_process_tree 能杀死整个进程树（含孙进程），释放管道
2. _run_in_subprocess 超时后及时返回，不永久挂起
3. _run_in_subprocess 正常代码仍可执行（回归）
4. 终端会话注册表可观测
5. 终端读取循环可在 stop_event 设置后及时退出（非阻塞读取修复的核心）
6. 终端读取专用线程池有界且独立
7. ws_handler_v2 空闲超时常量已配置
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


# ──────────────────────────────────────────────────────────────
# 辅助：跨平台进程存活检查
# ──────────────────────────────────────────────────────────────
def _pid_exists(pid: int) -> bool:
    """检查 PID 是否仍在运行（跨平台）。"""
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in r.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _wait_for(predicate, timeout=10.0, interval=0.1):
    """轮询等待谓词为真，超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ──────────────────────────────────────────────────────────────
# 1. _kill_process_tree：进程树级强杀（释放管道，防止 communicate 挂起）
# ──────────────────────────────────────────────────────────────
def test_kill_process_tree_kills_grandchildren(tmp_path):
    """验证 _kill_process_tree 能杀死子进程及其孙进程。

    孙进程继承 stdout 管道是 communicate() 永久挂起的根因；只有杀死整个
    进程树才能释放管道、让 communicate 返回。
    """
    from pycoder.server.routers.code_exec import _kill_process_tree

    grandchild_pid_file = tmp_path / "gcpid.txt"
    # 子进程：启动一个孙进程（sleep 60s）并记录其 PID，然后自己 sleep
    child_script = (
        "import subprocess, sys, time\n"
        "gc = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(60)'],\n"
        "    stdout=subprocess.PIPE, stderr=subprocess.PIPE,\n"
        ")\n"
        f"open(r'{grandchild_pid_file}', 'w').write(str(gc.pid))\n"
        "time.sleep(60)\n"
    )
    # 必须用独立进程组，便于 taskkill /T 识别进程树
    creationflags = 0x00000200 | 0x08000000 if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        start_new_session=(sys.platform != "win32"),
    )
    try:
        # 等待孙进程 PID 写入文件
        assert _wait_for(lambda: grandchild_pid_file.exists(), timeout=5), \
            "孙进程 PID 未记录"
        gc_pid = int(grandchild_pid_file.read_text().strip())

        # 确认子进程与孙进程都存活
        assert _pid_exists(proc.pid), "子进程未运行"
        assert _wait_for(lambda: _pid_exists(gc_pid), timeout=3), "孙进程未运行"

        # 执行进程树强杀
        _kill_process_tree(proc)

        # 验证子进程与孙进程都被杀死
        assert _wait_for(lambda: proc.poll() is not None, timeout=5), \
            "子进程未被杀死"
        assert _wait_for(lambda: not _pid_exists(gc_pid), timeout=5), \
            "孙进程未被杀死（管道将保持打开 → communicate 会永久挂起）"
    finally:
        if proc.poll() is None:
            _kill_process_tree(proc)


def test_kill_process_tree_handles_already_dead_process():
    """验证对已退出进程调用 _kill_process_tree 不抛异常。"""
    from pycoder.server.routers.code_exec import _kill_process_tree

    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait(timeout=5)
    # 不应抛异常
    _kill_process_tree(proc)


def test_kill_process_tree_handles_none():
    """验证对 None 调用 _kill_process_tree 不抛异常。"""
    from pycoder.server.routers.code_exec import _kill_process_tree

    _kill_process_tree(None)


# ──────────────────────────────────────────────────────────────
# 2. _run_in_subprocess：超时及时返回（不永久挂起）
# ──────────────────────────────────────────────────────────────
def test_run_in_subprocess_timeout_returns_promptly():
    """超时代码应在 ~timeout+缓冲 内返回 TimeoutError，而非永久挂起。

    这是修复的核心回归测试：旧版 subprocess.run 在孙进程持有管道时
    communicate() 永久挂起；新版 Popen + _kill_process_tree 确保及时返回。
    """
    from pycoder.server.routers.code_exec import _run_in_subprocess

    # 沙箱剥离 __import__，用户代码无法 import；用无导入的无限循环
    # （不需要任何内置模块，纯语句）跑过 timeout
    code = "i = 0\nwhile True:\n    i += 1\n"
    timeout = 5
    t0 = time.time()
    result = _run_in_subprocess(code, timeout=timeout)
    elapsed = time.time() - t0

    assert result.error_type == "TimeoutError", \
        f"期望 TimeoutError，实际 {result.error_type}: {result.error_message}"
    # 应在 timeout + 进程树强杀缓冲(10s) 内返回，而非 120s
    assert elapsed < timeout + 15, \
        f"超时返回耗时 {elapsed:.1f}s，疑似进程树强杀失败导致 communicate 挂起"


def test_run_in_subprocess_normal_code_succeeds():
    """正常代码仍可执行并返回输出（回归测试）。"""
    from pycoder.server.routers.code_exec import _run_in_subprocess

    code = "print('hello pycoder')\n"
    result = _run_in_subprocess(code, timeout=15)

    assert result.success, f"执行失败: {result.error_type}: {result.error_message}"
    assert "hello pycoder" in result.stdout


def test_run_in_subprocess_security_violation_short_circuits():
    """安全违规代码不启动子进程，直接返回 SecurityViolation。"""
    from pycoder.server.routers.code_exec import _run_in_subprocess

    # subprocess 在 BANNED_MODULES 中
    code = "import subprocess\nsubprocess.run(['ls'])\n"
    result = _run_in_subprocess(code, timeout=10)

    assert not result.success
    assert result.error_type == "BannedImport"


# ──────────────────────────────────────────────────────────────
# 3. 外层看门狗 asyncio.wait_for 兜底
# ──────────────────────────────────────────────────────────────
async def test_outer_watchdog_wait_for_fires_on_unresponsive_thread():
    """模拟路由层 asyncio.wait_for 兜底：当 to_thread 内部挂起时，
    外层 wait_for 在 hard_timeout 后触发 TimeoutError，保证请求返回。"""
    # 模拟 _run_in_subprocess 挂起（永不返回）
    def hanging_worker():
        time.sleep(60)

    hard_timeout = 1.0
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            asyncio.to_thread(hanging_worker), timeout=hard_timeout
        )


# ──────────────────────────────────────────────────────────────
# 4. 终端会话注册表（可观测性）
# ──────────────────────────────────────────────────────────────
def test_terminal_session_registry_list_and_pop():
    """验证终端会话注册表可注册、列出、清理（用于排查卡死）。"""
    from pycoder.server.routers.terminal import (
        _TERMINAL_SESSIONS,
        list_terminal_sessions,
    )

    _TERMINAL_SESSIONS.clear()
    _TERMINAL_SESSIONS["s1"] = {
        "started_at": time.time(),
        "shell": "powershell.exe",
        "pid": 1234,
        "remote": "127.0.0.1",
    }
    sessions = list_terminal_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "s1"
    assert sessions[0]["pid"] == 1234
    assert "uptime_sec" in sessions[0]

    _TERMINAL_SESSIONS.pop("s1", None)
    assert list_terminal_sessions() == []


# ──────────────────────────────────────────────────────────────
# 5. 终端读取循环可取消（非阻塞读取修复的核心验证）
# ──────────────────────────────────────────────────────────────
async def test_terminal_reader_loop_exits_on_stop_event():
    """验证非 pty 读取循环（wait_for + stop_event）能在 stop_event 设置后
    及时退出，而非永久阻塞在 readline 上。

    这复现了 terminal.py 中 _read_output 非 pty 分支的修复模式：
    用 asyncio.wait_for 限时读取，超时后检查 stop_event，从而避免
    阻塞系统调用导致线程泄漏、线程池耗尽、服务器假死。
    """
    # 启动一个长时间运行的子进程（stdout 不产生数据）
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stop_event = asyncio.Event()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-reader")

    async def reader_loop():
        """镜像 terminal.py _read_output 非 pty 分支的循环逻辑。"""
        loop = asyncio.get_running_loop()
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(executor, proc.stdout.readline),
                    timeout=0.2,
                )
            except asyncio.TimeoutError:
                continue
            except (OSError, ValueError):
                break
        return "exited"

    try:
        # 0.5s 后设置 stop_event
        async def stopper():
            await asyncio.sleep(0.5)
            stop_event.set()

        asyncio.create_task(stopper())
        t0 = time.time()
        # 整体兜底 5s
        result = await asyncio.wait_for(reader_loop(), timeout=5)
        elapsed = time.time() - t0

        assert result == "exited"
        # 应在 stop_event 设置后 ~0.3s 内退出（一个 wait_for 周期）
        assert elapsed < 2.0, \
            f"读取循环退出耗时 {elapsed:.1f}s，stop_event 未被及时检查（线程泄漏风险）"
    finally:
        proc.kill()
        proc.wait(timeout=5)
        executor.shutdown(wait=False)


async def test_terminal_reader_loop_exits_when_process_ends():
    """验证子进程退出后读取循环能及时退出（读到 EOF）。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", "print('done')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stop_event = asyncio.Event()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-reader2")

    async def reader_loop():
        loop = asyncio.get_running_loop()
        seen = []
        while not stop_event.is_set():
            try:
                data = await asyncio.wait_for(
                    loop.run_in_executor(executor, proc.stdout.readline),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                if proc.poll() is not None:
                    break
                continue
            if not data:
                break
            seen.append(data)
        return "".join(seen)

    try:
        t0 = time.time()
        out = await asyncio.wait_for(reader_loop(), timeout=5)
        elapsed = time.time() - t0
        assert "done" in out
        assert elapsed < 3.0
    finally:
        proc.wait(timeout=5)
        executor.shutdown(wait=False)


# ──────────────────────────────────────────────────────────────
# 6. 终端读取专用线程池有界且独立
# ──────────────────────────────────────────────────────────────
def test_terminal_executor_is_bounded_and_named():
    """验证终端读取使用独立的有界线程池，与默认 ThreadPoolExecutor 隔离，
    即使读取线程泄漏也不会耗尽全局线程池导致服务器假死。"""
    from pycoder.server.routers.terminal import _TERMINAL_EXECUTOR

    assert _TERMINAL_EXECUTOR._max_workers <= 16
    # 线程名前缀便于排查
    assert "pty-reader" in _TERMINAL_EXECUTOR._thread_name_prefix


def test_terminal_idle_timeout_configured():
    """验证终端 WebSocket 空闲超时已配置（防止半开连接永久占用）。"""
    from pycoder.server.routers.terminal import _WS_IDLE_TIMEOUT

    assert isinstance(_WS_IDLE_TIMEOUT, int)
    assert 60 <= _WS_IDLE_TIMEOUT <= 86400


# ──────────────────────────────────────────────────────────────
# 7. ws_handler_v2 空闲超时
# ──────────────────────────────────────────────────────────────
def test_ws_handler_v2_idle_timeout_configured():
    """验证聊天 WebSocket 空闲超时已配置。"""
    from pycoder.server.ws_handler_v2 import _WS_IDLE_TIMEOUT

    assert isinstance(_WS_IDLE_TIMEOUT, int)
    assert 300 <= _WS_IDLE_TIMEOUT <= 86400
