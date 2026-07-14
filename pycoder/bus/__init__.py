"""
统一能力总线 — Pycoder V2 架构核心
所有 AI 与编辑器模块的通信通过此总线进行。

用法:
    from pycoder.bus import capability_bus

    # 调用能力
    result = await capability_bus.call("editor.code.read", {"path": "main.py"})

    # 流式调用
    async for event in capability_bus.stream("system.shell.execute", {"cmd": "npm test"}):
        print(event.data)
"""

from pycoder.bus.monitor import BusMonitor, CallTrace
from pycoder.bus.protocol import GRPCAdapter, InternalAdapter, MCPAdapter, ProtocolAdapter
from pycoder.bus.registry import CapabilityDefinition, CapabilityRegistry
from pycoder.bus.router import IntelligentRouter, RouteDecision
from pycoder.bus.transformer import InputTransformer, OutputTransformer

__all__ = [
    "CapabilityRegistry",
    "CapabilityDefinition",
    "IntelligentRouter",
    "RouteDecision",
    "ProtocolAdapter",
    "MCPAdapter",
    "GRPCAdapter",
    "InternalAdapter",
    "BusMonitor",
    "CallTrace",
    "InputTransformer",
    "OutputTransformer",
]
