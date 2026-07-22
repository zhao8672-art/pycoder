"""环境工具 — python_env, docker_status, docker_execute"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS

_logger = logging.getLogger('pycoder.capabilities.tools.env')
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.SYSTEM


def register(registry: Any) -> None:
    _reg(
        registry,
        "tools.env.python",
        "Python 环境",
        "扫描并列出所有可用的 Python 虚拟环境和版本信息",
        {},
        [],
        _handle_python_env,
    )

    _reg(
        registry,
        "tools.env.docker_status",
        "Docker 状态",
        "检查 Docker 执行后端的可用性和状态",
        {},
        [],
        _handle_docker_status,
    )

    _reg(
        registry,
        "tools.env.docker_execute",
        "Docker 执行",
        "在隔离的 Docker 容器中安全执行 Python 代码",
        {"code": {"type": "string"}, "timeout": {"type": "number", "default": 30}},
        ["code"],
        _handle_docker_execute,
    )


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid,
            name=name,
            description=desc,
            permission=TOOL_PERMISSIONS.get(cid),
            category=_CT,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE if "status" in cid else SideEffect.PROCESS],
            schema={"type": "object", "properties": schema, "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


async def _handle_python_env(params: dict, context: dict) -> dict:
    envs = []
    venv = os.environ.get("VIRTUAL_ENV", "")
    if venv:
        envs.append({"name": "current", "path": venv, "type": "venv", "active": True})
    cwd = Path(os.getcwd())
    for name in (".venv", "venv", "env"):
        p = cwd / name
        if p.exists():
            envs.append({"name": name, "path": str(p), "type": "venv", "active": venv == str(p)})
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    return {
        "success": True,
        "environments": envs,
        "python_path": sys.executable,
        "python_version": v,
    }


async def _handle_docker_status(params: dict, context: dict) -> dict:
    try:
        from pycoder.server.docker_backend import get_docker_backend

        backend = get_docker_backend()
        return await backend.get_status()
    except Exception as e:
        _logger.warning("silently_swallowed: {err}", exc_info=False)
        return {
            "available": False,
            "reason": "Docker 未安装或不可用",
            "install_hint": "winget install Docker.DockerDesktop",
        }


async def _handle_docker_execute(params: dict, context: dict) -> dict:
    from pycoder.server.docker_backend import get_docker_backend

    backend = get_docker_backend()
    if not backend.is_available:
        return {"success": False, "error": "Docker 不可用"}
    result = await backend.execute(params["code"], timeout=params.get("timeout", 30))
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }
