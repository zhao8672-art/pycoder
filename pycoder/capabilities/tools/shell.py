"""Shell 工具 — run_terminal

集成 P0-1 跨平台命令翻译：自动将 Linux/Mac 风格命令翻译为 Windows 等价命令。
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler
from pycoder.core.shell_translator import (
    detect_platform,
    translate_to_current_platform,
)

_CT = CapabilityCategory.SYSTEM


def register(registry: Any) -> None:
    registry.register(
        CapabilityDefinition(
            id="tools.shell.run_terminal",
            name="终端命令",
            description="在终端中执行 shell 命令并获取输出和退出码（自动跨平台翻译）",
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
                    "translate": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否自动跨平台翻译（默认 true）",
                    },
                },
                "required": ["command"],
            },
            tags=["shell", "terminal", "执行", "跨平台"],
        ),
        handler=wrap_handler(_handle_run_terminal),
    )


async def _handle_run_terminal(params: dict, context: dict) -> dict:
    cmd = params["command"]
    timeout = params.get("timeout", 30)
    cwd = params.get("cwd") or str(Path.cwd())
    enable_translate = params.get("translate", True)

    # P0-1 跨平台命令翻译：在执行前自动翻译到当前平台
    translation_info = None
    if enable_translate:
        try:
            result = translate_to_current_platform(cmd)
            if result.changed:
                cmd = result.translated
                translation_info = {
                    "translated": True,
                    "from": result.source_platform,
                    "to": result.target_platform,
                    "mappings": result.mappings_applied,
                    "original": result.original,
                }
        except Exception as e:  # 翻译失败时不影响原命令执行
            translation_info = {"translated": False, "error": str(e)}

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
            "translation": translation_info,
        }
    except sp.TimeoutExpired:
        return {"success": False, "error": f"命令超时 ({timeout}s)", "exit_code": -1, "translation": translation_info}
    except Exception as e:
        return {"success": False, "error": str(e), "exit_code": -1, "translation": translation_info}
