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
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


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
        """持续读取终端输出并推送到 WebSocket"""
        try:
            if use_pty:
                if _is_windows():
                    loop = asyncio.get_running_loop()
                    while True:
                        try:
                            data = await loop.run_in_executor(None, lambda: pty.read(blocking=True))
                        except (OSError, RuntimeError) as e:
                            logger.debug("terminal_pty_read_failed error=%s", e)
                            break
                        if not data:
                            break

                        try:
                            await websocket.send_json(
                                {
                                    "type": "output",
                                    "data": data,
                                    "has_color": True,
                                }
                            )
                        except Exception as e:
                            logger.debug("terminal_ws_send_failed error=%s", e)
                            break
                else:
                    loop = asyncio.get_running_loop()
                    while True:
                        try:
                            data = await loop.run_in_executor(
                                None, lambda: os.read(master_fd, 4096)
                            )
                        except OSError:
                            break
                        if not data:
                            break
                        text = data.decode("utf-8", errors="replace")
                        try:
                            await websocket.send_json(
                                {
                                    "type": "output",
                                    "data": text,
                                    "has_color": True,
                                }
                            )
                        except Exception as e:
                            logger.debug("terminal_ws_send_failed error=%s", e)
                            break
            else:
                loop = asyncio.get_running_loop()
                while True:
                    try:
                        stdout_data = await loop.run_in_executor(None, process.stdout.readline)
                        stderr_data = await loop.run_in_executor(None, process.stderr.readline)
                    except (OSError, ValueError) as e:
                        logger.debug("terminal_process_read_failed error=%s", e)
                        break

                    if stdout_data:
                        try:
                            await websocket.send_json(
                                {
                                    "type": "output",
                                    "data": stdout_data,
                                    "has_color": False,
                                }
                            )
                        except Exception as e:
                            logger.debug("terminal_ws_send_failed error=%s", e)
                            break

                    if stderr_data:
                        try:
                            await websocket.send_json(
                                {
                                    "type": "output",
                                    "data": stderr_data,
                                    "has_color": False,
                                }
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
                    {
                        "type": "error",
                        "message": f"输出读取错误: {e}",
                    }
                )
            except Exception as send_err:
                logger.debug("terminal_ws_error_send_failed error=%s", send_err)

    reader_task = asyncio.create_task(_read_output())

    try:
        while True:
            data = await websocket.receive_json()

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
        if reader_task:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass

        if _is_windows():
            if pty:
                try:
                    pty.close()
                except (OSError, RuntimeError) as e:
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
