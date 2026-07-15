"""
平台适配器注册表 — 管理所有消息平台适配器

每个适配器负责将特定平台的消息规范化，并与网关交互。
"""

from __future__ import annotations

import logging

from pycoder.gateway import PlatformAdapter
from pycoder.gateway.adapters.cli import CLIAdapter
from pycoder.gateway.adapters.discord import DiscordAdapter
from pycoder.gateway.adapters.slack import SlackAdapter
from pycoder.gateway.adapters.telegram import TelegramAdapter

logger = logging.getLogger(__name__)


def get_all_adapters() -> list[PlatformAdapter]:
    """获取所有可用的平台适配器实例

    Returns:
        平台适配器实例列表
    """
    adapters: list[PlatformAdapter] = []
    for cls in [TelegramAdapter, DiscordAdapter, SlackAdapter, CLIAdapter]:
        try:
            adapters.append(cls())
        except Exception as e:
            logger.warning("无法实例化适配器 %s: %s", cls.__name__, e)
    return adapters


__all__ = [
    "TelegramAdapter",
    "DiscordAdapter",
    "SlackAdapter",
    "CLIAdapter",
    "get_all_adapters",
]