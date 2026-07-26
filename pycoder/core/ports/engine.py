"""Engine 端口 — V2 Engine 的 Protocol 抽象

将 bus 层对 server.app.get_v2_engine 的直接依赖
替换为 Protocol 依赖，消除 P→C 违规。

演进策略（ADR-002）：旧路径保留
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EngineProtocol(Protocol):
    """V2 Engine 协议"""

    @property
    def registry(self) -> Any:
        """能力注册表"""
        ...


# ── 工厂函数 ──────────────────────────────────

_engine_getter: Callable[[], EngineProtocol | None] | None = None


def register_engine_getter(getter: Callable[[], EngineProtocol | None]) -> None:
    """注册 Engine 获取函数（由 server 层在启动时调用）

    Args:
        getter: 返回 Engine 实例的可调用对象
    """
    global _engine_getter
    _engine_getter = getter


def get_engine() -> EngineProtocol | None:
    """获取 V2 Engine 实例

    使用注册的获取函数。若未注册则返回 None。

    Returns:
        EngineProtocol 实例，不可用时返回 None
    """
    if _engine_getter is not None:
        return _engine_getter()

    return None
