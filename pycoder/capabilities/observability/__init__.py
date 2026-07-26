"""可观测性能力域 — 将 observability/ 包装为 V2 能力

能力清单：
    observability.trace.query    — 查询调用链路
    observability.metrics.snapshot — 获取指标快照
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_observability_capabilities() -> None:
    """注册可观测性域能力到 V2 能力总线"""
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
            id="observability.trace.query",
            category=CapabilityCategory.SYSTEM,
            description="查询调用链路记录",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_trace_query,
        ))

        registry.register(CapabilityDefinition(
            id="observability.metrics.snapshot",
            category=CapabilityCategory.SYSTEM,
            description="获取系统指标快照",
            execution_mode=ExecutionMode.SYNC,
            side_effects={SideEffect.NONE},
            trust_level=TrustLevel.READ_ONLY,
            handler=_handle_metrics_snapshot,
        ))

        logger.info("observability_capabilities_registered: count=2")
    except Exception as e:
        logger.warning("observability_capabilities_register_failed: %s", e)


async def _handle_trace_query(args: dict[str, Any]) -> dict[str, Any]:
    """处理 observability.trace.query"""
    from pycoder.bus.monitor import BusMonitor
    monitor = BusMonitor.get_instance()
    traces = monitor.query_traces(
        trace_id=args.get("trace_id"),
        limit=args.get("limit", 50),
    )
    return {"success": True, "traces": traces}


async def _handle_metrics_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    """处理 observability.metrics.snapshot"""
    from pycoder.bus.monitor import BusMonitor
    monitor = BusMonitor.get_instance()
    stats = monitor.get_stats()
    return {"success": True, "metrics": stats}
