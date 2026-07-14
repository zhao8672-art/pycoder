"""Base plugin interface and registry."""

from __future__ import annotations


class BasePlugin:
    """Base class for all PyCoder plugins."""

    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    async def analyze(self, context: dict) -> dict:
        """Analyze the input context and return analysis."""
        return {}

    async def execute(self, analysis: dict) -> dict:
        """Execute based on analysis results."""
        return {}

    async def post_process(self, result: dict) -> dict:
        """Post-process execution results."""
        return result

    def match(self, message: str) -> bool:
        """Check if this plugin should handle the message."""
        return False


class PluginRegistry:
    """Plugin registry for discovering and using plugins."""

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin):
        """Register a plugin instance."""
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str):
        """Remove a plugin by name."""
        self._plugins.pop(name, None)

    def get(self, name: str) -> BasePlugin | None:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list(self) -> list[dict]:
        """List all registered plugins."""
        return [
            {"name": p.name, "description": p.description, "version": p.version}
            for p in self._plugins.values()
        ]

    def match(self, message: str) -> BasePlugin | None:
        """Find first plugin that matches the message."""
        for plugin in self._plugins.values():
            if plugin.match(message):
                return plugin
        return None

    def __len__(self) -> int:
        return len(self._plugins)
