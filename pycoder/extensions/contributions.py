"""
扩展贡献模型 — 扩展可以贡献什么

类似 VS Code 的 contributes 机制:
  - commands    → 注册到命令面板 (Ctrl+Shift+P)
  - settings    → 声明设置项（带类型、默认值、描述）
  - keybindings → 快捷键绑定
  - views       → 自定义视图
  - menus       → 上下文菜单贡献
  - languages   → 语言支持

每个 seed 扩展在 manifest 中声明 contributes 字段。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 贡献点类型
# ──────────────────────────────────────────────


@dataclass
class CommandContribution:
    """扩展贡献的命令"""

    id: str  # 命令唯一 ID，如 pycoder.gitlens.blame
    title: str  # 显示名称（命令面板中可见）
    category: str = ""  # 分类，如 "Git"
    icon: str = ""  # 图标名
    enablement: str = ""  # 启用条件表达式
    keybinding: str = ""  # 默认快捷键


@dataclass
class SettingContribution:
    """扩展贡献的设置项"""

    id: str  # 设置项 ID，如 pycoder.gitlens.enabled
    title: str  # 设置显示名称
    description: str = ""  # 描述
    type: str = "string"  # string | boolean | number | array | object
    default: Any = None  # 默认值
    enum: list[Any] | None = None  # 枚举值列表
    scope: str = "resource"  # resource | window | machine
    minimum: float | None = None
    maximum: float | None = None


@dataclass
class KeybindingContribution:
    """扩展贡献的快捷键"""

    key: str  # 按键组合，如 ctrl+shift+g
    command: str  # 绑定的命令 ID
    when: str = ""  # 生效条件
    mac: str = ""  # macOS 专用


@dataclass
class ViewContribution:
    """扩展贡献的视图"""

    id: str  # 视图 ID
    name: str  # 视图名称
    type: str = "tree"  # tree | webview
    when: str = ""  # 显示条件


@dataclass
class MenuContribution:
    """扩展贡献的菜单项"""

    command: str  # 命令 ID
    group: str = ""  # 分组
    when: str = ""  # 条件
    icon: str = ""


@dataclass
class LanguageContribution:
    """扩展贡献的语言支持"""

    id: str  # 语言 ID
    extensions: list[str] = field(default_factory=list)  # 文件扩展名
    aliases: list[str] = field(default_factory=list)  # 别名
    configuration: str = ""  # 语言配置文件路径


@dataclass
class ExtensionContributions:
    """一个扩展的所有贡献点"""

    commands: list[CommandContribution] = field(default_factory=list)
    settings: list[SettingContribution] = field(default_factory=list)
    keybindings: list[KeybindingContribution] = field(default_factory=list)
    views: list[ViewContribution] = field(default_factory=list)
    menus: list[MenuContribution] = field(default_factory=list)
    languages: list[LanguageContribution] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.commands,
                self.settings,
                self.keybindings,
                self.views,
                self.menus,
                self.languages,
            ]
        )


# ──────────────────────────────────────────────
# 命令注册中心
# ──────────────────────────────────────────────


class CommandRegistry:
    """全局命令注册中心 — 类似 VS Code 的 commands.registerCommand"""

    def __init__(self):
        self._commands: dict[str, CommandContribution] = {}
        self._handlers: dict[str, callable] = {}
        self._extension_map: dict[str, str] = {}  # command_id → ext_id

    def register(
        self,
        cmd: CommandContribution,
        handler: callable | None = None,
        ext_id: str = "",
    ) -> None:
        """注册一个命令"""
        existing = self._commands.get(cmd.id)
        if existing:
            logger.debug(
                "command_already_registered id=%s existing_ext=%s new_ext=%s",
                cmd.id,
                self._extension_map.get(cmd.id),
                ext_id,
            )
        self._commands[cmd.id] = cmd
        if handler:
            self._handlers[cmd.id] = handler
        if ext_id:
            self._extension_map[cmd.id] = ext_id

    def execute(self, command_id: str, *args, **kwargs) -> Any:
        """执行一个命令"""
        if command_id not in self._commands:
            raise KeyError(f"命令未注册: {command_id}")
        handler = self._handlers.get(command_id)
        if handler is None:
            raise KeyError(f"命令无处理器: {command_id}")
        return handler(*args, **kwargs)

    def get(self, command_id: str) -> CommandContribution | None:
        return self._commands.get(command_id)

    def list(self, ext_id: str | None = None) -> list[CommandContribution]:
        """列出命令，可选按扩展过滤"""
        if ext_id:
            ids = {cid for cid, eid in self._extension_map.items() if eid == ext_id}
            return [self._commands[cid] for cid in ids if cid in self._commands]
        return list(self._commands.values())

    def search(self, query: str = "") -> list[dict]:
        """搜索命令（用于命令面板）"""
        results = []
        q = query.lower().strip()
        for cid, cmd in self._commands.items():
            if not q or q in cmd.title.lower() or q in cmd.id.lower() or q in cmd.category.lower():
                results.append(
                    {
                        "id": cmd.id,
                        "title": cmd.title,
                        "category": cmd.category,
                        "ext_id": self._extension_map.get(cid, ""),
                        "keybinding": cmd.keybinding,
                    }
                )
        results.sort(key=lambda x: (x["category"], x["title"]))
        return results

    def count(self) -> int:
        return len(self._commands)

    def clear_extension(self, ext_id: str) -> int:
        """卸载扩展时清除其所有命令"""
        to_remove = [cid for cid, eid in self._extension_map.items() if eid == ext_id]
        for cid in to_remove:
            self._commands.pop(cid, None)
            self._handlers.pop(cid, None)
            self._extension_map.pop(cid, None)
        return len(to_remove)


# ──────────────────────────────────────────────
# 设置注册中心
# ──────────────────────────────────────────────


class SettingsRegistry:
    """全局设置注册中心 — 管理所有扩展的设置"""

    def __init__(self):
        self._settings: dict[str, SettingContribution] = {}
        self._values: dict[str, Any] = {}  # 用户设置值
        self._extension_map: dict[str, str] = {}

    def register(self, setting: SettingContribution, ext_id: str = "") -> None:
        """注册一个设置项"""
        self._settings[setting.id] = setting
        if ext_id:
            self._extension_map[setting.id] = ext_id
        # 如果已有用户设置值，保留
        if setting.id not in self._values:
            self._values[setting.id] = setting.default

    def get(self, key: str) -> Any:
        """获取设置值"""
        if key in self._values:
            return self._values[key]
        setting = self._settings.get(key)
        return setting.default if setting else None

    def set(self, key: str, value: Any) -> bool:
        """设置值"""
        if key not in self._settings:
            return False
        setting = self._settings[key]
        # 类型校验
        if not self._validate_type(value, setting):
            logger.warning(
                "setting_type_mismatch key=%s expected=%s got=%s",
                key,
                setting.type,
                type(value).__name__,
            )
            return False
        # 枚举校验
        if setting.enum and value not in setting.enum:
            logger.warning(
                "setting_value_not_in_enum key=%s value=%s enum=%s", key, value, setting.enum
            )
            return False
        # 范围校验
        if setting.type == "number":
            if setting.minimum is not None and value < setting.minimum:
                return False
            if setting.maximum is not None and value > setting.maximum:
                return False
        self._values[key] = value
        return True

    def list_settings(self, ext_id: str | None = None) -> list[dict]:
        """列出设置项"""
        results = []
        for sid, setting in self._settings.items():
            if ext_id and self._extension_map.get(sid) != ext_id:
                continue
            results.append(
                {
                    "id": setting.id,
                    "title": setting.title,
                    "description": setting.description,
                    "type": setting.type,
                    "default": setting.default,
                    "current": self._values.get(sid, setting.default),
                    "enum": setting.enum,
                    "ext_id": self._extension_map.get(sid, ""),
                }
            )
        results.sort(key=lambda x: x["id"])
        return results

    def export_json(self) -> dict:
        """导出所有用户设置为 JSON"""
        return {k: v for k, v in self._values.items() if v is not None}

    def import_json(self, data: dict) -> int:
        """从 JSON 导入用户设置"""
        count = 0
        for k, v in data.items():
            if self.set(k, v):
                count += 1
        return count

    def clear_extension(self, ext_id: str) -> int:
        """卸载扩展时清除其所有设置"""
        to_remove = [sid for sid, eid in self._extension_map.items() if eid == ext_id]
        for sid in to_remove:
            self._settings.pop(sid, None)
            self._values.pop(sid, None)
            self._extension_map.pop(sid, None)
        return len(to_remove)

    @staticmethod
    def _validate_type(value: Any, setting: SettingContribution) -> bool:
        type_map = {
            "string": str,
            "boolean": bool,
            "number": (int, float),
            "array": list,
            "object": dict,
        }
        expected = type_map.get(setting.type)
        if expected is None:
            return True
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────

_command_registry = CommandRegistry()
_settings_registry = SettingsRegistry()


def get_command_registry() -> CommandRegistry:
    return _command_registry


def get_settings_registry() -> SettingsRegistry:
    return _settings_registry


# ──────────────────────────────────────────────
# 从 manifest 解析贡献点
# ──────────────────────────────────────────────


def parse_contributions_from_manifest(manifest: dict) -> ExtensionContributions:
    """从扩展 manifest 中解析贡献点"""
    contributes = manifest.get("contributes", {})
    if not contributes:
        return ExtensionContributions()

    contribs = ExtensionContributions()

    # commands
    for cmd in contributes.get("commands", []):
        contribs.commands.append(
            CommandContribution(
                id=cmd.get("command", ""),
                title=cmd.get("title", ""),
                category=cmd.get("category", ""),
                icon=cmd.get("icon", ""),
                enablement=cmd.get("enablement", ""),
                keybinding=cmd.get("keybinding", ""),
            )
        )

    # settings
    for s in contributes.get("settings", []):
        contribs.settings.append(
            SettingContribution(
                id=s.get("id", ""),
                title=s.get("title", ""),
                description=s.get("description", ""),
                type=s.get("type", "string"),
                default=s.get("default"),
                enum=s.get("enum"),
                scope=s.get("scope", "resource"),
            )
        )

    # keybindings
    for kb in contributes.get("keybindings", []):
        contribs.keybindings.append(
            KeybindingContribution(
                key=kb.get("key", ""),
                command=kb.get("command", ""),
                when=kb.get("when", ""),
                mac=kb.get("mac", ""),
            )
        )

    # views
    for v in contributes.get("views", []):
        contribs.views.append(
            ViewContribution(
                id=v.get("id", ""),
                name=v.get("name", ""),
                type=v.get("type", "tree"),
                when=v.get("when", ""),
            )
        )

    # menus
    for m in contributes.get("menus", []):
        contribs.menus.append(
            MenuContribution(
                command=m.get("command", ""),
                group=m.get("group", ""),
                when=m.get("when", ""),
                icon=m.get("icon", ""),
            )
        )

    # languages
    for lang in contributes.get("languages", []):
        contribs.languages.append(
            LanguageContribution(
                id=lang.get("id", ""),
                extensions=lang.get("extensions", []),
                aliases=lang.get("aliases", []),
                configuration=lang.get("configuration", ""),
            )
        )

    return contribs


def register_extension_contributions(ext_id: str, manifest: dict) -> ExtensionContributions:
    """将扩展的贡献点注册到全局注册中心"""
    contribs = parse_contributions_from_manifest(manifest)
    cmd_reg = get_command_registry()
    set_reg = get_settings_registry()

    for cmd in contribs.commands:
        cmd_reg.register(cmd, ext_id=ext_id)

    for setting in contribs.settings:
        set_reg.register(setting, ext_id=ext_id)

    return contribs


def unregister_extension_contributions(ext_id: str) -> dict:
    """卸载扩展时清除其所有贡献"""
    cmd_reg = get_command_registry()
    set_reg = get_settings_registry()
    return {
        "commands_removed": cmd_reg.clear_extension(ext_id),
        "settings_removed": set_reg.clear_extension(ext_id),
    }
