"""扩展能力域 — 将 extensions/ 系统包装为 V2 能力

能力清单：
    extension.list.installed   — 列出已安装扩展
    extension.list.search      — 搜索扩展市场
    extension.lifecycle.activate — 激活扩展
    extension.lifecycle.deactivate — 停用扩展
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_extension_capabilities() -> None:
    """注册扩展域能力到 V2 能力总线"""
    try:
        from pycoder.bus.registry import CapabilityRegistry
        from pycoder.bus.protocol import (
            CapabilityDefinition,
            CapabilityCategory,
            ExecutionMode,
            SideEffect,
            TrustLevel,
        )

        registry = CapabilityRegistry.get_instance()

        registry.register(CapabilityDefinition(
            id="extension.list.installed",
            category=CapabilityCategory.SYSTEM,
            description="列出已安装的扩展",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_list_installed,
        ))

        registry.register(CapabilityDefinition(
            id="extension.list.search",
            category=CapabilityCategory.SYSTEM,
            description="搜索扩展市场",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NETWORK},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_search,
        ))

        logger.info("extension_capabilities_registered: count=2")
    except Exception as e:
        logger.warning("extension_capabilities_register_failed: %s", e)


async def _handle_list_installed(args: dict[str, Any]) -> dict[str, Any]:
    """处理 extension.list.installed"""
    from pycoder.extensions import ExtensionManager
    mgr = ExtensionManager()
    exts = mgr.list_installed()
    return {"success": True, "extensions": exts}


async def _handle_search(args: dict[str, Any]) -> dict[str, Any]:
    """处理 extension.list.search"""
    from pycoder.extensions import ExtensionManager
    mgr = ExtensionManager()
    results = await mgr.search(query=args.get("q", ""))
    return {"success": True, "results": results}
