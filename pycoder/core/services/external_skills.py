"""外部技能采集器 — P 层抽象

将原本位于 pycoder.server.skills_external_sources 的采集函数
下沉到 P 层（core.services.external_skills），消除 D→C 违规。

演进策略（ADR-002）：旧路径保留并标记 @deprecated
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pycoder.core.services.log import log

# ── 技能采集器注册 ──────────────────────────────

_fetch_impl: Callable[[], tuple[list[Any], dict[str, Any]]] | None = None


def register_skills_fetcher(
    fetcher: Callable[[], tuple[list[Any], dict[str, Any]]],
) -> None:
    """注册外部技能采集器（由 server 层在启动时调用）

    Args:
        fetcher: 返回 (skills 列表, 状态字典) 的可调用对象
    """
    global _fetch_impl
    _fetch_impl = fetcher


def fetch_all_external_skills() -> tuple[list[Any], dict[str, Any]]:
    """从所有外部数据源采集技能

    Returns:
        (skills 列表, 各数据源状态)

    Note:
        若未注册采集器（_fetch_impl 为 None），返回空列表。
        server 层应在启动时调用 register_skills_fetcher()。
    """
    if _fetch_impl is not None:
        return _fetch_impl()
    log.warning("外部技能采集器未注册，返回空列表")
    return [], {"error": "not available"}


# ── Agent 角色数据 ──────────────────────────────

_roles_getter: Callable[[], dict[str, Any]] | None = None


def register_roles_getter(getter: Callable[[], dict[str, Any]]) -> None:
    """注册 Agent 角色获取函数（由 server 层在启动时调用）"""
    global _roles_getter
    _roles_getter = getter


def get_agent_roles() -> dict[str, Any]:
    """获取 Agent 角色定义

    Returns:
        Agent 角色字典，未注册时返回空字典
    """
    if _roles_getter is not None:
        return _roles_getter()
    return {}
