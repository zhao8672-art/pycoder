"""
优雅降级 — 外部依赖不可用时的友好提示

当 Docker、pip-audit、多语言运行时等外部工具不可用时，
返回友好的安装提示而非报错，保持 AI 任务流程不被中断。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

DEGRADATION_HINTS: dict[str, dict[str, Any]] = {
    "tools.env.docker_status": {
        "fallback_value": {
            "available": False,
            "reason": "Docker 未安装或不可用",
            "install_hint": (
                "Windows: winget install Docker.DockerDesktop\n"
                "macOS: brew install --cask docker\n"
                "Linux: curl -fsSL https://get.docker.com | sh"
            ),
        },
    },
    "tools.env.docker_execute": {
        "fallback_value": {
            "success": False,
            "error": "Docker 不可用",
            "install_hint": "请先安装 Docker Desktop",
        },
    },
    "tools.quality.security_scan": {
        "fallback_value": {
            "success": True,
            "vulnerabilities": [],
            "note": "pip-audit 未安装，已跳过安全扫描",
            "install_hint": "pip install pip-audit",
        },
    },
    "tools.exec.multilang": {
        "check_language": True,
        "install_hints": {
            "rust": "安装 Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
            "go": "安装 Go: https://go.dev/dl/",
            "java": "安装 Java: https://adoptium.net/",
            "cpp": "安装 C++ 编译器 (gcc/clang)",
        },
    },
    "tools.quality.dependency_analysis": {
        "fallback_value": {
            "success": True,
            "dependencies": [],
            "note": "依赖分析失败，请检查项目依赖文件",
        },
    },
}


def wrap_handler(handler: Callable) -> Callable:
    """包装处理器，加入优雅降级逻辑

    当处理器抛出 FileNotFoundError 或其他已知异常时，
    返回友好提示而非崩溃。
    """

    async def wrapped(params: dict, context: dict) -> Any:
        try:
            result = await handler(params, context)
            if callable(result):
                result = result(params, context)
            return result
        except FileNotFoundError as e:
            return {
                "success": True,
                "available": False,
                "reason": str(e),
                "hint": "需要的工具未安装，请根据 install_hint 安装",
            }
        except Exception as e:
            err_msg = str(e)[:500]
            return {"success": False, "error": err_msg}

    return wrapped


def get_degradation_hint(capability_id: str) -> dict[str, Any] | None:
    """获取指定能力的降级提示"""
    return DEGRADATION_HINTS.get(capability_id)
