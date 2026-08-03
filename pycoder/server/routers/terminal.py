"""
终端 WebSocket — Web IDE 交互式终端

端点:
    WS /ws/terminal  — 交互式终端

协议:
    客户端 → 服务器:
        {"type": "command", "data": "ls -la\\n"}
        {"type": "resize", "cols": 80, "rows": 24}
        {"type": "cd", "path": "/some/dir"}

    服务器 → 客户端:
        {"type": "output", "data": "..."}
        {"type": "exit", "code": 0}
        {"type": "error", "message": "..."}
        {"type": "cwd", "path": "/current/dir"}
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 终端读取专用线程池 ──
# 独立于默认 ThreadPoolExecutor：即使某个读取线程因阻塞系统调用未能立即退出，
# 也不会耗尽全局线程池导致整个服务器假死（这是终端任务卡死的主因）。
# 非阻塞读取已从根本上消除长期阻塞，专用池作为额外隔离兜底。
_TERMINAL_EXECUTOR = ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="pty-reader"
)

# ── 终端会话注册表（观测/排查卡死）──
# session_id -> {"started_at": float, "shell": str, "pid": int|None, "remote": str}
_TERMINAL_SESSIONS: dict[str, dict] = {}

# WebSocket 空闲超时：被遗弃/半开连接在此时间无任何输入后清理，防止进程与线程长期占用。
_WS_IDLE_TIMEOUT = 3600  # 1 小时（交互式终端，用户可能长时间只看输出不输入）


def list_terminal_sessions() -> list[dict]:
    """返回活跃终端会话列表（用于观测和排查卡死）。"""
    now = time.time()
    return [
        {
            "id": sid,
            "uptime_sec": round(now - info["started_at"], 1),
            **{k: v for k, v in info.items() if k != "started_at"},
        }
        for sid, info in _TERMINAL_SESSIONS.items()
    ]


WORKSPACE_ROOT: Path = Path(
    os.environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),  # pycode/ (project root)
    )
).resolve()


def _default_shell() -> str:
    if platform.system() == "Windows":
        return "powershell.exe"
    return "/bin/bash"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _has_winpty() -> bool:
    """检查是否安装了 pywinpty"""
    try:
        import winpty  # noqa: F401

        return True
    except ImportError:
        return False


def _strip_ansi_codes(text: str) -> str:
    """移除 ANSI 颜色代码"""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _supports_color() -> bool:
    """检查当前环境是否支持颜色输出"""
    if _is_windows():
        return _has_winpty()
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    """
    交互式终端 WebSocket。

    Windows: 使用 pywinpty 创建真正的 PTY（伪终端），支持颜色
             如果 pywinpty 不可用，回退到 subprocess 模式
    Unix: 使用 pty 获取真实终端输出，支持颜色
    """
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(websocket):
        return
    await websocket.accept()

    shell = _default_shell()
    cwd = str(WORKSPACE_ROOT)

    pty = None
    reader_task = None
    process = None
    master_fd = None
    use_pty = True
    stop_event = asyncio.Event()
    session_id = uuid.uuid4().hex[:12]
    _TERMINAL_SESSIONS[session_id] = {
        "started_at": time.time(),
        "shell": shell,
        "pid": None,
        "remote": websocket.client.host if websocket.client else "unknown",
    }
    logger.info("terminal_ws_connect session=%s remote=%s", session_id, _TERMINAL_SESSIONS[session_id]["remote"])

    try:
        if _is_windows():
            if _has_winpty():
                import winpty

                pty = winpty.PTY(80, 24)
                pty.spawn(shell, cwd=cwd)

                await websocket.send_json(
                    {
                        "type": "connected",
                        "cwd": cwd,
                        "shell": shell,
                        "platform": platform.system(),
                        "color_support": True,
                        "pty_mode": True,
                    }
                )
            else:
                use_pty = False
                process = subprocess.Popen(
                    [shell, "-NoProfile"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    text=True,
                    encoding="utf-8",
                )

                await websocket.send_json(
                    {
                        "type": "connected",
                        "cwd": cwd,
                        "shell": shell,
                        "platform": platform.system(),
                        "color_support": False,
                        "pty_mode": False,
                        "warning": "pywinpty 未安装，使用 subprocess 模式（无颜色）",
                    }
                )
        else:
            master_fd, slave_fd = os.openpty()
            process = subprocess.Popen(
                [shell],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                preexec_fn=os.setsid,
            )
            os.close(slave_fd)
            # 设置 master_fd 为非阻塞，使 os.read 在无数据时立即抛 BlockingIOError，
            # 读取协程可定期让出并检查 stop_event，从根本上消除阻塞读取线程泄漏
            # （否则客户端断连时 reader 线程永久卡在 os.read → 线程池耗尽 → 服务器假死）
            import fcntl

            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            if process.pid:
                _TERMINAL_SESSIONS[session_id]["pid"] = process.pid

            await websocket.send_json(
                {
                    "type": "connected",
                    "cwd": cwd,
                    "shell": shell,
                    "platform": platform.system(),
                    "color_support": True,
                    "pty_mode": True,
                }
            )

    except ImportError:
        await websocket.send_json(
            {
                "type": "error",
                "message": "需要安装 pywinpty: pip install pywinpty",
            }
        )
        await websocket.close()
        return
    except OSError as e:
        await websocket.send_json(
            {
                "type": "error",
                "message": f"启动终端失败: {e}",
            }
        )
        await websocket.close()
        return

    async def _read_output():
        """持续读取终端输出并推送到 WebSocket（非阻塞、可取消）。

        关键：所有读取均通过 _TERMINAL_EXECUTOR 调度且非阻塞/限时，
        循环每轮检查 stop_event，确保客户端断连或会话结束时能立即退出，
        不再因阻塞 read 系统调用泄漏线程导致线程池耗尽、服务器假死。
        """
        loop = asyncio.get_running_loop()
        try:
            if use_pty:
                if _is_windows():
                    # Windows winpty: 非阻塞轮询
                    while not stop_event.is_set():
                        try:
                            data = await loop.run_in_executor(
                                _TERMINAL_EXECUTOR, lambda: pty.read(blocking=False)
                            )
                        except (OSError, RuntimeError) as e:
                            logger.debug("terminal_pty_read_failed error=%s", e)
                            break
                        except Exception as e:
                            logger.debug("terminal_pty_read_unexpected error=%s", e)
                            break
                        if data:
                            try:
                                await websocket.send_json(
                                    {"type": "output", "data": data, "has_color": True}
                                )
                            except Exception as e:
                                logger.debug("terminal_ws_send_failed error=%s", e)
                                break
                        else:
                            # 无数据，短暂让出并重新检查 stop_event
                            await asyncio.sleep(0.05)
                else:
                    # Unix master_fd 已设为非阻塞：os.read 无数据时抛 BlockingIOError
                    while not stop_event.is_set():
                        try:
                            data = await loop.run_in_executor(
                                _TERMINAL_EXECUTOR, lambda: os.read(master_fd, 4096)
                            )
                        except BlockingIOError:
                            # 无数据可读：检查进程是否退出，否则短暂让出
                            if process and process.poll() is not None:
                                # 进程已退出：尝试读取剩余输出后结束
                                try:
                                    tail = await loop.run_in_executor(
                                        _TERMINAL_EXECUTOR, lambda: os.read(master_fd, 4096)
                                    )
                                    if tail:
                                        await websocket.send_json(
                                            {
                                                "type": "output",
                                                "data": tail.decode("utf-8", errors="replace"),
                                                "has_color": True,
                                            }
                                        )
                                except (OSError, BlockingIOError):
                                    pass
                                break
                            await asyncio.sleep(0.05)
                            continue
                        except OSError:
                            break
                        if not data:
                            break
                        text = data.decode("utf-8", errors="replace")
                        try:
                            await websocket.send_json(
                                {"type": "output", "data": text, "has_color": True}
                            )
                        except Exception as e:
                            logger.debug("terminal_ws_send_failed error=%s", e)
                            break
            else:
                # 非 pty subprocess（winpty 不可用时回退）：用 wait_for 限时读取，
                # 避免 readline 永久阻塞；超时后检查 stop_event 与进程退出
                while not stop_event.is_set():
                    stdout_data = ""
                    stderr_data = ""
                    try:
                        stdout_data = await asyncio.wait_for(
                            loop.run_in_executor(_TERMINAL_EXECUTOR, process.stdout.readline),
                            timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        pass
                    except (OSError, ValueError) as e:
                        logger.debug("terminal_process_read_failed error=%s", e)
                        break

                    try:
                        stderr_data = await asyncio.wait_for(
                            loop.run_in_executor(_TERMINAL_EXECUTOR, process.stderr.readline),
                            timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        pass
                    except (OSError, ValueError) as e:
                        logger.debug("terminal_process_read_failed error=%s", e)
                        break

                    if stdout_data:
                        try:
                            await websocket.send_json(
                                {"type": "output", "data": stdout_data, "has_color": False}
                            )
                        except Exception as e:
                            logger.debug("terminal_ws_send_failed error=%s", e)
                            break

                    if stderr_data:
                        try:
                            await websocket.send_json(
                                {"type": "output", "data": stderr_data, "has_color": False}
                            )
                        except Exception as e:
                            logger.debug("terminal_ws_send_failed error=%s", e)
                            break

                    if process.poll() is not None and not stdout_data and not stderr_data:
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            try:
                await websocket.send_json(
                    {"type": "error", "message": f"输出读取错误: {e}"}
                )
            except Exception as send_err:
                logger.debug("terminal_ws_error_send_failed error=%s", send_err)

    reader_task = asyncio.create_task(_read_output())

    try:
        while True:
            # 空闲超时：被遗弃/半开连接在 _WS_IDLE_TIMEOUT 内无输入则清理，
            # 防止进程与读取线程长期占用（卡死诱因之一）
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(), timeout=_WS_IDLE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.info(
                    "terminal_ws_idle_timeout session=%s idle=%ds",
                    session_id, _WS_IDLE_TIMEOUT,
                )
                break

            msg_type = data.get("type", "")

            if msg_type == "command":
                cmd = data.get("data", "")
                try:
                    if use_pty:
                        if _is_windows():
                            pty.write(cmd)
                        else:
                            os.write(master_fd, cmd.encode("utf-8"))
                    else:
                        if process.stdin:
                            process.stdin.write(cmd)
                            process.stdin.flush()
                except (OSError, BrokenPipeError):
                    break

            elif msg_type == "input":
                raw = data.get("data", "")
                try:
                    if use_pty:
                        if _is_windows():
                            pty.write(raw)
                        else:
                            os.write(master_fd, raw.encode("utf-8"))
                    else:
                        if process.stdin:
                            process.stdin.write(raw)
                            process.stdin.flush()
                except (OSError, BrokenPipeError):
                    break

            elif msg_type == "cd":
                new_path = data.get("path", "")
                if new_path:
                    target = Path(new_path).resolve()
                    # M8: 用 is_relative_to 替代字符串前缀匹配
                    if target.is_relative_to(WORKSPACE_ROOT) or target.exists():
                        cd_cmd = f'cd "{target}"\n'
                        try:
                            if use_pty:
                                if _is_windows():
                                    pty.write(f'cd "{target}"\r\n')
                                else:
                                    os.write(master_fd, cd_cmd.encode("utf-8"))
                            else:
                                if process.stdin:
                                    process.stdin.write(f'cd "{target}"\r\n')
                                    process.stdin.flush()
                        except (OSError, BrokenPipeError):
                            break

                        await websocket.send_json(
                            {
                                "type": "cwd",
                                "path": str(target),
                            }
                        )
                    else:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": f"路径不存在或超出工作区: {new_path}",
                            }
                        )

            elif msg_type == "resize":
                cols = data.get("cols", 80)
                rows = data.get("rows", 24)
                if _is_windows() and pty:
                    pty.set_size(rows, cols)
                await websocket.send_json(
                    {
                        "type": "resize_ack",
                        "cols": cols,
                        "rows": rows,
                    }
                )

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"终端错误: {e}",
                }
            )
        except Exception as send_err:
            logger.debug("terminal_ws_error_send_failed error=%s", send_err)
    finally:
        # 先通知读取协程退出，再取消任务（非阻塞读取使其能即时响应）
        stop_event.set()
        if reader_task:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass

        if _is_windows():
            if pty:
                try:
                    # pywinpty 不同版本 API 不同，兼容处理
                    if hasattr(pty, "close"):
                        pty.close()
                    elif hasattr(pty, "terminate"):
                        pty.terminate()
                except (OSError, RuntimeError, AttributeError) as e:
                    logger.debug("terminal_pty_close_failed error=%s", e)
            elif process:
                try:
                    process.terminate()
                    await asyncio.sleep(0.5)
                    if process.poll() is None:
                        process.kill()
                except (OSError, ProcessLookupError):
                    pass
        else:
            if process and process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    await asyncio.sleep(0.5)
                    if process.poll() is None:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass

            if master_fd:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

        try:
            exit_code = 0
            if process:
                exit_code = process.poll() or 0
            await websocket.send_json(
                {
                    "type": "exit",
                    "code": exit_code,
                }
            )
        except Exception as send_err:
            logger.debug("terminal_ws_exit_send_failed error=%s", send_err)
        finally:
            _TERMINAL_SESSIONS.pop(session_id, None)
            logger.info("terminal_ws_disconnect session=%s", session_id)
