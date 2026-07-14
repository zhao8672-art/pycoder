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

    modules = [
        ("files", files),
        ("search", search),
        ("exec_mod", exec_mod),
        ("quality", quality),
        ("git", git),
        ("shell", shell),
        ("env", env),
        ("testing", testing),
        ("marketplace", marketplace),
        ("agent", agent),
    ]

    for name, mod in modules:
        try:
            mod.register(registry)
        except Exception as e:
            import logging
            import traceback

            logging.getLogger(__name__).error(
                "tools_registration_failed module=%s error=%s trace=%s",
                name,
                e,
                traceback.format_exc(),
            )
            raise

    return registry.count - count_before
