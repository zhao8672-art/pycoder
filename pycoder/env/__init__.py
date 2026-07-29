"""
环境能力注册模块 — 将环境检测能力注册到 V2 能力总线

能力清单:
    env.check.docker       — 检查 Docker 可用性
    env.check.python       — 检查 Python 环境
    env.check.node         — 检查 Node.js 环境
    env.check.git          — 检查 Git 可用性
    env.check.languages    — 检查多语言运行时
    env.system.info        — 获取系统信息
    env.system.resources   — 获取系统资源使用情况
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_capabilities(registry: Any) -> None:
    """注册所有环境检测能力到 V2 能力总线"""
    _register_env_check_capabilities(registry)
    _register_system_capabilities(registry)


def _register_env_check_capabilities(registry: Any) -> None:
    """注册环境检测类能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    # Docker 检测
    registry.register(
        CapabilityDefinition(
            id="env.check.docker",
            name="检查 Docker",
            description="检查 Docker 是否安装并可用",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["docker", "container", "环境"],
        ),
        handler=_check_docker,
    )

    # Python 环境检测
    registry.register(
        CapabilityDefinition(
            id="env.check.python",
            name="检查 Python 环境",
            description="检查 Python 版本、路径和可用包",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["python", "环境"],
        ),
        handler=_check_python,
    )

    # Node.js 环境检测
    registry.register(
        CapabilityDefinition(
            id="env.check.node",
            name="检查 Node.js",
            description="检查 Node.js 是否安装并可用",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["node", "javascript", "环境"],
        ),
        handler=_check_node,
    )

    # Git 检测
    registry.register(
        CapabilityDefinition(
            id="env.check.git",
            name="检查 Git",
            description="检查 Git 是否安装并可用",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["git", "vcs", "环境"],
        ),
        handler=_check_git,
    )

    # 多语言运行时检测
    registry.register(
        CapabilityDefinition(
            id="env.check.languages",
            name="检查多语言运行时",
            description="检查系统中可用的编程语言运行时",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["languages", "runtime", "环境"],
        ),
        handler=_check_languages,
    )


def _register_system_capabilities(registry: Any) -> None:
    """注册系统信息类能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    # 系统信息
    registry.register(
        CapabilityDefinition(
            id="env.system.info",
            name="系统信息",
            description="获取操作系统、架构、主机名等系统信息",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["system", "info", "os"],
        ),
        handler=_get_system_info,
    )

    # 系统资源
    registry.register(
        CapabilityDefinition(
            id="env.system.resources",
            name="系统资源",
            description="获取 CPU、内存、磁盘等系统资源使用情况",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["resources", "cpu", "memory", "disk"],
        ),
        handler=_get_system_resources,
    )


# ── 处理器实现 ────────────────────────────


async def _check_docker(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检查 Docker 可用性"""
    try:
        import subprocess

        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return {"available": True, "version": version}
        return {"available": False, "reason": "Docker 命令返回非零退出码"}
    except FileNotFoundError:
        return {"available": False, "reason": "Docker 未安装"}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "Docker 命令超时"}
    except Exception as e:
        return {"available": False, "reason": str(e)}


async def _check_python(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检查 Python 环境"""
    import sys
    import platform

    return {
        "version": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "packages": len(sys.modules),
    }


async def _check_node(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检查 Node.js 环境"""
    try:
        import subprocess

        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return {"available": True, "version": result.stdout.strip()}
        return {"available": False, "reason": "Node.js 命令返回非零退出码"}
    except FileNotFoundError:
        return {"available": False, "reason": "Node.js 未安装"}
    except Exception as e:
        return {"available": False, "reason": str(e)}


async def _check_git(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检查 Git 环境"""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return {"available": True, "version": result.stdout.strip()}
        return {"available": False, "reason": "Git 命令返回非零退出码"}
    except FileNotFoundError:
        return {"available": False, "reason": "Git 未安装"}
    except Exception as e:
        return {"available": False, "reason": str(e)}


async def _check_languages(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检查多语言运行时"""
    import subprocess

    languages = {}
    checks = {
        "python": ["python3", "--version"],
        "node": ["node", "--version"],
        "java": ["java", "-version"],
        "go": ["go", "version"],
        "rust": ["rustc", "--version"],
    }

    for lang, cmd in checks.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                languages[lang] = result.stdout.strip() or result.stderr.strip()
            else:
                languages[lang] = None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            languages[lang] = None

    return {"available_languages": [k for k, v in languages.items() if v], "versions": languages}


async def _get_system_info(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """获取系统信息"""
    import platform
    import os

    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "cwd": os.getcwd(),
        "pid": os.getpid(),
    }


async def _get_system_resources(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """获取系统资源使用情况"""
    import os
    import psutil

    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "cpu": {
            "percent": cpu_percent,
            "count": psutil.cpu_count(),
            "count_logical": psutil.cpu_count(logical=True),
        },
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "process": {
            "pid": os.getpid(),
            "memory_mb": psutil.Process().memory_info().rss / 1024 / 1024,
        },
    }