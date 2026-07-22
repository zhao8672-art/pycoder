"""
系统能力域

提供文件操作、Shell执行、Git操作、包管理和环境检测能力。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)


def register_system_capabilities(registry: Any) -> None:
    """向总线注册所有系统能力"""
    _register_file_operations(registry)
    _register_shell_operations(registry)
    _register_git_operations(registry)
    _register_package_operations(registry)


def _register_file_operations(registry: Any) -> None:
    """注册文件操作能力"""

    registry.register(
        CapabilityDefinition(
            id="system.file.list",
            name="列出目录",
            description="列出指定目录下的文件和子目录",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认当前目录"},
                    "recursive": {"type": "boolean", "description": "是否递归"},
                    "pattern": {"type": "string", "description": "文件名过滤模式"},
                    "max_depth": {"type": "integer", "description": "最大递归深度"},
                },
            },
            tags=["ls", "dir", "list", "目录", "列表"],
        ),
        handler=_list_directory,
    )

    registry.register(
        CapabilityDefinition(
            id="system.file.watch",
            name="监听文件变化",
            description="设置文件系统监听，在文件变化时接收通知",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.STREAM,
            tags=["watch", "monitor", "监听"],
        ),
        stream_handler=_watch_files,
    )


def _register_shell_operations(registry: Any) -> None:
    """注册 Shell 操作能力"""

    registry.register(
        CapabilityDefinition(
            id="system.shell.execute",
            name="执行 Shell 命令",
            description="在项目环境中执行 Shell 命令并返回输出",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.FILE_WRITE],
            timeout_ms=120000,
            schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "cwd": {"type": "string", "description": "工作目录"},
                    "env": {"type": "object", "description": "额外的环境变量"},
                },
                "required": ["command"],
            },
            tags=["shell", "bash", "执行", "命令", "运行"],
        ),
        handler=_execute_shell,
    )


def _register_git_operations(registry: Any) -> None:
    """注册 Git 操作能力"""

    registry.register(
        CapabilityDefinition(
            id="system.git.status",
            name="Git 状态（已弃用）",
            description="⚠️ 已弃用，请使用 tools.git.status",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            deprecated=True,
            deprecated_message="请使用 tools.git.status",
            side_effects=[SideEffect.NONE],
            tags=["git", "status", "状态"],
        ),
        handler=_git_status,
    )

    registry.register(
        CapabilityDefinition(
            id="system.git.diff",
            name="Git 差异",
            description="查看工作区的详细变更差异",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            tags=["git", "diff", "差异", "变更"],
        ),
        handler=_git_diff,
    )

    registry.register(
        CapabilityDefinition(
            id="system.git.commit",
            name="Git 提交",
            description="提交暂存的变��到 Git 仓库",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "提交信息"},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要提交的文件",
                    },
                },
                "required": ["message"],
            },
            tags=["git", "commit", "提交"],
        ),
        handler=_git_commit,
    )

    registry.register(
        CapabilityDefinition(
            id="system.git.push",
            name="Git 推送",
            description="将本地提交推送到远程仓库",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.NETWORK],
            tags=["git", "push", "推送"],
        ),
        handler=_git_push,
    )


def _register_package_operations(registry: Any) -> None:
    """注册包管理能力"""

    registry.register(
        CapabilityDefinition(
            id="system.package.install",
            name="安装包",
            description="安装 Python 或 Node.js 包到项目环境",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            side_effects=[SideEffect.NETWORK, SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要安装的包名列表",
                    },
                    "manager": {"type": "string", "description": "包管理器: pip / npm / poetry"},
                    "dev": {"type": "boolean", "description": "是否安装为开发依赖"},
                },
                "required": ["packages"],
            },
            tags=["install", "package", "pip", "npm", "安装"],
        ),
        handler=_install_package,
    )

    registry.register(
        CapabilityDefinition(
            id="system.package.list",
            name="列出已安装包",
            description="列出项目已安装的依赖包及版本",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            tags=["list", "package", "包", "依赖"],
        ),
        handler=_list_packages,
    )

    registry.register(
        CapabilityDefinition(
            id="system.env.detect",
            name="环境检测",
            description="检测项目的 Python/Node 环境和依赖",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            tags=["env", "detect", "环境", "检测"],
        ),
        handler=_detect_environment,
    )


# ── 处理器实现 ────────────────────────────


async def _list_directory(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """列出目录内容"""
    path = Path(params.get("path", "."))
    recursive = params.get("recursive", False)
    pattern = params.get("pattern")

    if not path.exists():
        raise FileNotFoundError(f"目录不存在: {path}")

    items: list[dict[str, Any]] = []

    if recursive:
        for item in sorted(path.rglob("*")):
            if pattern and not item.match(pattern):
                continue
            items.append(
                {
                    "name": item.name,
                    "path": str(item.relative_to(path)),
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
            )
    else:
        for item in sorted(path.iterdir()):
            if pattern and not item.match(pattern):
                continue
            items.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
            )

    return {
        "path": str(path.absolute()),
        "count": len(items),
        "items": items[:200],  # 限制返回数量
    }


async def _watch_files(params: dict[str, Any], context: dict[str, Any]):
    """监听文件变化（占位）"""
    from pycoder.bus.protocol import CapabilityEvent

    yield CapabilityEvent(
        trace_id=context.get("trace_id", ""),
        event_type="done",
        message="文件监听为占位实现",
    )


async def _execute_shell(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """执行 Shell 命令"""
    command = params["command"]
    cwd = params.get("cwd", os.getcwd())

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, **(params.get("env") or {})},
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=params.get("timeout", 120),
        )

        return {
            "exit_code": process.returncode,
            "success": process.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace")[:10000],
            "stderr": stderr.decode("utf-8", errors="replace")[:5000],
        }

    except TimeoutError:
        return {"exit_code": -1, "success": False, "error": "命令执行超时"}


async def _git_status(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Git 状态"""
    import subprocess

    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"status": result.stdout, "has_changes": bool(result.stdout.strip())}


async def _git_diff(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Git 差异"""
    import subprocess

    result = subprocess.run(
        ["git", "diff", "--stat"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    result2 = subprocess.run(
        ["git", "diff"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "stat": result.stdout,
        "diff": result2.stdout[:10000],
    }


async def _git_commit(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Git 提交"""
    import subprocess

    message = params["message"]
    cmd = ["git", "add"]
    if params.get("files"):
        cmd.extend(params["files"])
    else:
        cmd.append("-A")

    subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
        timeout=30,
    )

    return {
        "success": result.returncode == 0,
        "output": result.stdout + result.stderr,
    }


async def _git_push(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Git 推送"""
    import subprocess

    result = subprocess.run(
        ["git", "push"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "success": result.returncode == 0,
        "output": result.stdout + result.stderr,
    }


async def _install_package(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """安装包"""
    import subprocess

    packages = params["packages"]
    manager = params.get("manager", "pip")

    if manager == "pip":
        cmd = ["pip", "install"] + packages
    elif manager == "npm":
        cmd = ["npm", "install"] + packages
        if params.get("dev"):
            cmd.insert(2, "--save-dev")
    else:
        cmd = ["pip", "install"] + packages

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return {
        "success": result.returncode == 0,
        "output": result.stdout[-2000:] + result.stderr[-2000:],
    }


async def _list_packages(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """列出已安装包"""
    import subprocess

    result = subprocess.run(
        ["pip", "list", "--format=json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    import json

    try:
        packages = json.loads(result.stdout)
        return {"count": len(packages), "packages": packages[:100]}
    except json.JSONDecodeError:
        return {"count": 0, "packages": [], "error": "解析失败"}


async def _detect_environment(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检测项目环境"""
    import sys

    return {
        "python_version": sys.version,
        "executable": sys.executable,
        "platform": sys.platform,
        "cwd": os.getcwd(),
    }
