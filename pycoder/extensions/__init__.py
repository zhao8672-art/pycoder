"""扩展系统 — 可插拔的 PyCoder 功能扩展（像 VS Code 一样的扩展管理）"""

from pycoder.extensions.commands import (
    CommandPalette,
    get_command_palette,
    register_builtin_commands,
)
from pycoder.extensions.contributions import (
    CommandContribution,
    CommandRegistry,
    ExtensionContributions,
    KeybindingContribution,
    SettingContribution,
    SettingsRegistry,
    get_command_registry,
    get_settings_registry,
    register_extension_contributions,
    unregister_extension_contributions,
)
from pycoder.extensions.host import (
    ExtensionAPI,
    ExtensionHostManager,
    ExtensionSandbox,
    get_extension_host,
)
from pycoder.extensions.manager import ExtensionManager
from pycoder.extensions.marketplace import (
    force_refresh,
    get_cache_status,
    get_seed_extensions,
    search_extensions,
)
from pycoder.extensions.packaging import (
    PACKAGE_EXT,
    pack,
    pack_installed,
    scaffold,
    unpack,
    validate_manifest,
)

__all__ = [
    # 市场/搜索
    "search_extensions",
    "get_seed_extensions",
    # 管理器
    "ExtensionManager",
    # 贡献模型
    "CommandContribution",
    "SettingContribution",
    "KeybindingContribution",
    "ExtensionContributions",
    "CommandRegistry",
    "SettingsRegistry",
    "get_command_registry",
    "get_settings_registry",
    "register_extension_contributions",
    "unregister_extension_contributions",
    # 扩展主机/沙箱
    "ExtensionHostManager",
    "ExtensionSandbox",
    "ExtensionAPI",
    "get_extension_host",
    # 打包
    "pack",
    "unpack",
    "validate_manifest",
    "scaffold",
    "pack_installed",
    "PACKAGE_EXT",
    # 命令面板
    "CommandPalette",
    "get_command_palette",
    "register_builtin_commands",
]
