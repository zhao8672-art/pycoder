"""代码执行路由 — 沙箱内执行 Python/多语言代码"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from pycoder.server.auth import require_api_key
from pycoder.server.permission_policy import check_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/code-exec", tags=["code-exec"])


# ──────────────────────────────────────────────────────────
# 写范围冲突检测 — 同一工作目录禁止并发执行
# 借鉴 LoopX task_lease 的写范围冲突检测思路：并发执行若写同一目录
# 可能互相覆盖文件，执行前先"认领" working_dir，冲突则拒绝。
# ──────────────────────────────────────────────────────────

_active_exec_dirs: set[str] = set()
_active_exec_dirs_lock = asyncio.Lock()


async def _try_lock_working_dir(working_dir: str) -> bool:
    """尝试认领工作目录的执行权。返回 False 表示已被其他执行占用（冲突）。"""
    async with _active_exec_dirs_lock:
        if working_dir in _active_exec_dirs:
            return False
        _active_exec_dirs.add(working_dir)
        return True


async def _unlock_working_dir(working_dir: str) -> None:
    """释放工作目录的执行权。"""
    async with _active_exec_dirs_lock:
        _active_exec_dirs.discard(working_dir)


# ──────────────────────────────────────────────────────────
# 沙箱配置 — 供 app._create_sandbox 与 rest_routes 共用
# ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SandboxConfig:
    """子进程沙箱配置（只读）"""

    default_timeout: int = 30
    max_timeout: int = 120
    max_output_chars: int = 10000


_sandbox_config = SandboxConfig()


# ──────────────────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────────────────


class CodeExecRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 30
    working_dir: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    stdin: str | None = None
    max_output_chars: int = 10000


class CodeExecResponse(BaseModel):
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    error: str | None = None


# ──────────────────────────────────────────────────────────
# 子路由：各语言执行器
# ──────────────────────────────────────────────────────────


async def _run_python(code: str, working_dir: str, env: dict, timeout: int) -> dict:
    """执行 Python 代码"""
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        cmd = [sys.executable, script_path]
        proc_env = {**os.environ, **env}
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _run_sync,
                cmd,
                working_dir,
                proc_env,
                timeout,
            ),
            timeout=timeout + 5,
        )
        return result
    finally:
        Path(script_path).unlink(missing_ok=True)


async def _run_shell(cmd: str, working_dir: str, env: dict, timeout: int) -> dict:
    """执行 Shell 命令"""
    proc_env = {**os.environ, **env}
    return await asyncio.wait_for(
        asyncio.to_thread(
            _run_sync,
            cmd,
            working_dir,
            proc_env,
            timeout,
        ),
        timeout=timeout + 5,
    )


async def _run_node(code: str, working_dir: str, env: dict, timeout: int) -> dict:
    """执行 Node.js 代码"""
    with tempfile.NamedTemporaryFile(
        suffix=".js", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        cmd = ["node", script_path]
        proc_env = {**os.environ, **env}
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _run_sync,
                cmd,
                working_dir,
                proc_env,
                timeout,
            ),
            timeout=timeout + 5,
        )
        return result
    finally:
        Path(script_path).unlink(missing_ok=True)


def _run_sync(cmd: list[str], working_dir: str, env: dict, timeout: int) -> dict:
    """同步执行命令（供 asyncio.to_thread 调用）"""
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = (time.perf_counter() - start) * 1000
        return {
            "stdout": proc.stdout[:10000],
            "stderr": proc.stderr[:5000],
            "exit_code": proc.returncode,
            "duration_ms": round(duration_ms, 1),
        }
    except subprocess.TimeoutExpired:
        duration_ms = (time.perf_counter() - start) * 1000
        return {
            "stdout": "",
            "stderr": f"执行超时（{timeout}s）",
            "exit_code": -1,
            "duration_ms": round(duration_ms, 1),
        }
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -2,
            "duration_ms": round(duration_ms, 1),
        }


# ──────────────────────────────────────────────────────────
# 主执行入口
# ──────────────────────────────────────────────────────────


async def _run_in_subprocess(req: CodeExecRequest) -> CodeExecResponse:
    """统一执行入口：根据 language 分发到对应执行器"""
    working_dir = req.working_dir or os.getcwd()
    try:
        Path(working_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        working_dir = tempfile.gettempdir()

    dispatch = {
        "python": lambda: _run_python(req.code, working_dir, req.env, req.timeout),
        "shell": lambda: _run_shell(req.code, working_dir, req.env, req.timeout),
        "node": lambda: _run_node(req.code, working_dir, req.env, req.timeout),
    }

    executor = dispatch.get(req.language)
    if not executor:
        return CodeExecResponse(
            success=False,
            error=f"不支持的语言: {req.language}，支持: {', '.join(dispatch.keys())}",
        )

    # 写范围冲突检测：同一工作目录禁止并发执行，避免相互覆盖文件
    if not await _try_lock_working_dir(working_dir):
        return CodeExecResponse(
            success=False,
            error=f"工作目录正被其他执行占用（写范围冲突），请等待完成后再试: {working_dir}",
        )

    try:
        result = await asyncio.wait_for(executor(), timeout=req.timeout + 10)
    except asyncio.TimeoutError:
        return CodeExecResponse(
            success=False,
            error=f"执行超时（{req.timeout}s）",
            duration_ms=float(req.timeout) * 1000,
        )
    except Exception as e:
        logger.exception("code_exec_failed language=%s error=%s", req.language, e)
        return CodeExecResponse(success=False, error=str(e))
    finally:
        await _unlock_working_dir(working_dir)

    return CodeExecResponse(
        success=result.get("exit_code", -1) == 0,
        stdout=result.get("stdout", "")[: req.max_output_chars],
        stderr=result.get("stderr", "")[: req.max_output_chars],
        exit_code=result.get("exit_code", -1),
        duration_ms=result.get("duration_ms", 0.0),
    )


# ──────────────────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────────────────


@router.post("/execute", response_model=CodeExecResponse)
@require_api_key
@check_permission("tools.exec.python")
async def execute_code(req: CodeExecRequest) -> CodeExecResponse:
    """在沙箱中执行代码"""
    return await _run_in_subprocess(req)


@router.post("/execute/multilang", response_model=CodeExecResponse)
@require_api_key
@check_permission("tools.exec.multilang")
async def execute_multilang(req: CodeExecRequest) -> CodeExecResponse:
    """执行多语言代码（python/shell/node）"""
    return await _run_in_subprocess(req)