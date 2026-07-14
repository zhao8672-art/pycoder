"""
V2 工具能力总入口 — 一次性注册所有工具
"""

from __future__ import annotations

from typing import Any


def register_all_tools(registry: Any) -> int:
    """向总线注册所有 V1 迁移过来的工具能力

    Args:
        registry: V2 CapabilityRegistry 实例

    Returns:
        注册的工具总数
    """
    # 延迟导入避免循环依赖
    from pycoder.capabilities.tools import (
        agent,
        env,
        exec_mod,
        files,
        git,
        marketplace,
        quality,
        search,
        shell,
        testing,
    )

    count_before = registry.count

    files.register(registry)
    search.register(registry)
    exec_mod.register(registry)
    quality.register(registry)
    git.register(registry)
    shell.register(registry)
    env.register(registry)
    testing.register(registry)
    marketplace.register(registry)
    agent.register(registry)

    return registry.count - count_before
