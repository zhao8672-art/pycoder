"""PyCoder 插件系统 - 根级入口.

完整实现位于 `pycoder.plugins` 子包, 此处重导出以便根级 `import plugins` 访问.
"""

from pycoder.plugins import (
    BasePlugin,
    PluginRegistry,
)

__version__ = "0.5.0"
__all__ = [
    "BasePlugin",
    "PluginRegistry",
    "__version__",
]
