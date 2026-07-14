"""
命令面板 — 类似 VS Code 的 Ctrl+Shift+P

功能:
  - 集中注册所有命令（内置 + 扩展贡献）
  - 命令搜索/过滤
  - 命令执行
  - 最近使用排序
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pycoder.extensions.contributions import (
    CommandContribution,
    get_command_registry,
)

logger = logging.getLogger(__name__)

# ── 最近使用记录 ──

_HISTORY_FILE = Path.home() / ".pycoder" / "command_history.json"
_MAX_HISTORY = 50


def _load_history() -> dict[str, float]:
    try:
        data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _save_history(history: dict[str, float]):
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _record_usage(command_id: str):
    history = _load_history()
    history[command_id] = time.time()
    # 只保留最近的
    if len(history) > _MAX_HISTORY:
        sorted_items = sorted(history.items(), key=lambda x: -x[1])[:_MAX_HISTORY]
        history = dict(sorted_items)
    _save_history(history)


# ── 内置命令注册 ──

_BUILTIN_COMMANDS: dict[str, Callable] = {}


def register_builtin_commands():
    """注册内置系统命令"""
    cmd_reg = get_command_registry()

    builtins = [
        CommandContribution(
            id="pycoder.help",
            title="显示帮助信息",
            category="PyCoder",
            keybinding="f1",
        ),
        CommandContribution(
            id="pycoder.reloadExtensions",
            title="重新加载所有扩展",
            category="PyCoder",
        ),
        CommandContribution(
            id="pycoder.showExtensions",
            title="显示扩展管理面板",
            category="PyCoder",
        ),
        CommandContribution(
            id="pycoder.showCommands",
            title="显示所有命令",
            category="PyCoder",
            keybinding="ctrl+shift+p",
        ),
        CommandContribution(
            id="pycoder.installExtension",
            title="安装扩展",
            category="PyCoder",
        ),
        CommandContribution(
            id="pycoder.createExtension",
            title="创建新扩展脚手架",
            category="PyCoder",
        ),
        CommandContribution(
            id="pycoder.showSettings",
            title="打开设置",
            category="PyCoder",
            keybinding="ctrl+,",
        ),
        CommandContribution(
            id="pycoder.extensionsHelp",
            title="扩展帮助",
            category="PyCoder",
        ),
    ]

    for cmd in builtins:
        cmd_reg.register(cmd)


# ── 命令面板 API ──


class CommandPalette:
    """命令面板 — 搜索和执行命令"""

    def search(self, query: str = "", limit: int = 50) -> list[dict]:
        """搜索命令，按最近使用排序"""
        cmd_reg = get_command_registry()
        results = cmd_reg.search(query)
        history = _load_history()

        # 按最近使用排序
        def sort_key(cmd: dict) -> tuple:
            last_used = history.get(cmd["id"], 0)
            is_builtin = 0 if cmd["ext_id"] else 1
            return (-last_used, is_builtin, cmd["category"], cmd["title"])

        results.sort(key=sort_key, reverse=True)
        return results[:limit]

    def execute(self, command_id: str, *args, **kwargs) -> Any:
        """执行一个命令"""
        cmd_reg = get_command_registry()
        cmd = cmd_reg.get(command_id)
        if cmd is None:
            raise KeyError(f"命令未注册: {command_id}")

        # 记录使用
        _record_usage(command_id)

        # 执行
        return cmd_reg.execute(command_id, *args, **kwargs)

    def get_all_categories(self) -> list[str]:
        """获取所有命令分类"""
        cmd_reg = get_command_registry()
        categories = set()
        for cmd in cmd_reg.list():
            if cmd.category:
                categories.add(cmd.category)
        return sorted(categories)

    def get_stats(self) -> dict:
        """获取命令统计"""
        cmd_reg = get_command_registry()
        all_cmds = cmd_reg.list()
        builtin_count = sum(1 for c in all_cmds if c.id.startswith("pycoder."))
        return {
            "total": len(all_cmds),
            "builtin": builtin_count,
            "extensions": len(all_cmds) - builtin_count,
            "categories": self.get_all_categories(),
        }


# ── 全局单例 ──

_command_palette = CommandPalette()


def get_command_palette() -> CommandPalette:
    return _command_palette
