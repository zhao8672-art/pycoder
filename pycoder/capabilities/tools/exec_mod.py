"""代码执行工具 — execute_python, execute_code, execute_multilang, debug_python, profile_python"""

from __future__ import annotations

import asyncio
import subprocess as sp
import sys
import tempfile
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (CapabilityCategory, CapabilityDefinition,
                                  ExecutionMode, SideEffect)
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.SYSTEM


def register(registry: Any) -> None:
    _reg(registry, "tools.exec.python", "执行Python",
         "在沙箱中安全执行 Python 代码并返回结果",
         {"code": {"type": "string"}, "timeout": {"type": "number", "default": 30}},
         ["code"], _handle_execute_python)

    _reg(registry, "tools.exec.code", "执行代码",
         "安全执行多语言代码（Python/JavaScript/Shell，自动检测）",
         {"code": {"type": "string"}, "language": {"type": "string", "default": ""},
          "timeout": {"type": "number", "default": 30}},
         ["code"], _handle_execute_code)

    _reg(registry, "tools.exec.multilang", "多语言执行",
         "在沙箱中编译并运行多语言代码（Java/Go/Rust/C/C++/JS/TS/Bash）",
         {"language": {"type": "string"}, "code": {"type": "string"},
          "timeout": {"type": "number", "default": 30}},
         ["language", "code"], _handle_execute_multilang)

    _reg(registry, "tools.exec.debug_python", "调试Python",
         "带断点支持的 Python 代码执行和调试",
         {"code": {"type": "string"}, "breakpoints": {"type": "array"},
          "timeout": {"type": "number", "default": 30}},
         ["code"], _handle_debug_python)

    _reg(registry, "tools.exec.profile_python", "性能分析",
         "用 cProfile 分析 Python 代码性能，返回热点函数和调用链",
         {"code": {"type": "string"}, "sort_by": {"type": "string", "default": "cumtime"},
          "timeout": {"type": "number", "default": 30}},
         ["code"], _handle_profile_python)

    # list_languages — 只读工具
    registry.register(
        CapabilityDefinition(
            id="tools.env.languages", name="列出语言运行时",
            description="列出系统中所有可用的编程语言运行时",
            permission=TOOL_PERMISSIONS["tools.env.languages"],
            category=_CT,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            schema={"type": "object", "properties": {}},
            tags=["languages", "runtime"],
        ),
        handler=wrap_handler(_handle_list_languages),
    )


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid, name=name, description=desc,
            category=_CT,
            permission=TOOL_PERMISSIONS.get(cid),
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS],
            schema={"type": "object", "properties": schema, "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


async def _handle_execute_python(params: dict, context: dict) -> dict:
    from pycoder.server.routers.code_exec import _run_in_subprocess
    result = await asyncio.to_thread(
        _run_in_subprocess, params["code"], params.get("timeout", 30))
    return {"success": result.success, "stdout": result.stdout,
            "stderr": result.stderr, "execution_time": result.execution_time}


def _mkres(success, output="", error="", language=""):
    return {"success": success, "output": (output or "")[:2000],
            "error": (error or "")[:1000], "language": language}


async def _handle_execute_code(params: dict, context: dict) -> dict:
    code = params["code"]
    language = params.get("language", "")
    timeout = params.get("timeout", 30)

    if not language:
        from pycoder.python.multilang_executor import list_available
        available = list_available()
        lang = "python" if "python" in available else (available[0] if available else "python")
        language = lang

    try:
        if language == "python":
            r = sp.run(["python", "-c", code], capture_output=True,
                       text=True, timeout=timeout)
            return _mkres(r.returncode == 0, r.stdout, r.stderr, language)
        if language == "javascript":
            r = sp.run(["node", "-e", code], capture_output=True,
                       text=True, timeout=timeout)
            return _mkres(r.returncode == 0, r.stdout, r.stderr, language)
        if language == "shell":
            tf = tempfile.NamedTemporaryFile(mode="w", suffix=".sh",
                                             delete=False, encoding="utf-8")
            tf.write(code)
            tf.close()
            try:
                r = sp.run(["bash", tf.name], capture_output=True,
                           text=True, timeout=timeout)
                return _mkres(r.returncode == 0, r.stdout, r.stderr, language)
            finally:
                Path(tf.name).unlink(missing_ok=True)
    except sp.TimeoutExpired:
        return _mkres(False, error=f"超时 ({timeout}s)", language=language)
    except FileNotFoundError:
        return _mkres(False, error=f"运行时未找到: {language}", language=language)
    return {"success": False, "error": f"不支持: {language}"}


async def _handle_execute_multilang(params: dict, context: dict) -> dict:
    from pycoder.python.multilang_executor import execute_multilang
    return await execute_multilang(
        params["language"], params["code"], params.get("timeout", 30))


async def _handle_debug_python(params: dict, context: dict) -> dict:
    code = params["code"]
    breakpoints = params.get("breakpoints", [])
    if breakpoints:
        lines = code.split("\n")
        for bp in sorted(breakpoints, reverse=True):
            if 0 <= bp - 1 < len(lines):
                indent = " " * (len(lines[bp - 1]) - len(lines[bp - 1].lstrip()))
                lines.insert(bp - 1, f"{indent}import pdb; pdb.set_trace()")
        code = "\n".join(lines)
    from pycoder.server.routers.code_exec import _run_in_subprocess
    result = await asyncio.to_thread(
        _run_in_subprocess, code, params.get("timeout", 30))
    return {"success": result.success, "output": result.stdout,
            "stderr": result.stderr, "error": result.error_message}


async def _handle_profile_python(params: dict, context: dict) -> dict:
    profile_script = (
        "import cProfile, pstats, io\n"
        "pr = cProfile.Profile()\npr.enable()\n"
        f"try:\n{chr(10).join('    ' + line for line in params['code'].split(chr(10)))}\n"
        "except Exception as e:\n    print(f'ERROR: {e}')\n"
        "pr.disable()\ns = io.StringIO()\n"
        f"ps = pstats.Stats(pr, stream=s).sort_stats('{params.get('sort_by','cumtime')}')\n"
        "ps.print_stats(20)\nprint(s.getvalue())"
    )
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    tf.write(profile_script)
    tf.close()
    try:
        r = sp.run([sys.executable, tf.name], capture_output=True,
                   text=True, timeout=params.get("timeout", 30))
        Path(tf.name).unlink(missing_ok=True)
        return {"success": r.returncode == 0, "profile": r.stdout[:3000]}
    except sp.TimeoutExpired:
        Path(tf.name).unlink(missing_ok=True)
        return {"success": False, "error": "分析超时"}


async def _handle_list_languages(params: dict, context: dict) -> dict:
    from pycoder.python.multilang_executor import list_available
    available = list_available()
    return {"success": True, "languages": available, "count": len(available)}
