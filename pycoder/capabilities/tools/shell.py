"""Shell 工具 — run_terminal"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.SYSTEM


def register(registry: Any) -> None:
    registry.register(
        CapabilityDefinition(
            id="tools.shell.run_terminal",
            name="终端命令",
            description="在终端中执行 shell 命令并获取输出和退出码",
            permission=TOOL_PERMISSIONS["tools.shell.run_terminal"],
            category=_CT,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "number", "default": 30},
                    "cwd": {"type": "string", "default": ""},
                },
                "required": ["command"],
            },
            tags=["shell", "terminal", "执行"],
        ),
        handler=wrap_handler(_handle_run_terminal),
    )


async def _handle_run_terminal(params: dict, context: dict) -> dict:
    cmd = params["command"]
    timeout = params.get("timeout", 30)
    cwd = params.get("cwd") or str(Path.cwd())
    try:
        import sys as _sys

        if _sys.platform == "win32":
            proc = sp.run(
                ["powershell.exe", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        else:
            proc = sp.run(
                ["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:8000],
            "stderr": proc.stderr[:4000],
            "cwd": cwd,
        }
    except sp.TimeoutExpired:
        return {"success": False, "error": f"命令超时 ({timeout}s)", "exit_code": -1}
    except Exception as e:
        return {"success": False, "error": str(e), "exit_code": -1}
