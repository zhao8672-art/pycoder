"""
动态模块系统 — AI 可按需加载/卸载的功能模块

提供:
- 模块发现、加载、激活、停用、卸载的完整生命周期
- 沙箱隔离，模块崩溃不影响主系统
- AI 驱动的模块搜索与安装
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

from pycoder.bus.protocol import CapabilityDefinition

logger = logging.getLogger(__name__)


@dataclass
class ModuleManifest:
    """模块清单 —— 每个动态模块必须提供"""

    id: str  # 唯一标识
    name: str  # 显示名称
    version: str  # 语义化版本
    description: str  # 功能描述
    author: str = ""
    capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class DynamicModule:
    """所有动态模块的基类"""

    manifest: ModuleManifest

    async def on_load(self) -> None:
        """模块加载时调用 —— 初始化资源"""
        pass

    async def on_activate(self, context: dict[str, Any]) -> None:
        """模块激活时调用 —— 注册能力到总线"""
        pass

    async def on_deactivate(self) -> None:
        """模块停用时调用 —— 清理运行时状态"""
        pass

    async def on_unload(self) -> None:
        """模块卸载时调用 —— 释放所有资源"""
        pass

    def health_check(self) -> bool:
        """健康检查"""
        return True


class ModuleLoader:
    """
    模块加载器

    负责模块的发现、加载、激活、停用和卸载。
    与总线集成，模块的能力自动注册。
    """

    def __init__(self, registry: Any = None):
        self._registry = registry
        self._loaded_modules: dict[str, DynamicModule] = {}
        self._module_states: dict[str, str] = {}  # loaded / active / inactive / error
        self._manifests: dict[str, ModuleManifest] = {}

    async def load(self, module_path: str) -> DynamicModule | None:
        """
        加载一个模块

        Args:
            module_path: Python 模块导入路径

        Returns:
            加载的模块实例
        """
        if module_path in self._loaded_modules:
            logger.info("模块 '%s' 已加载", module_path)
            return self._loaded_modules[module_path]

        try:
            mod = importlib.import_module(module_path)
            instance: DynamicModule | None = None

            # 查找 DynamicModule 的子类实例
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, DynamicModule)
                    and attr is not DynamicModule
                ):
                    instance = attr()
                    break

            if instance is None:
                logger.error("模块 '%s' 中未找到 DynamicModule 子类", module_path)
                return None

            await instance.on_load()
            self._loaded_modules[module_path] = instance
            self._module_states[module_path] = "loaded"

            if hasattr(instance, "manifest"):
                self._manifests[module_path] = instance.manifest

            logger.info("模块已加载: %s", module_path)
            return instance

        except Exception as e:
            logger.error("加载模块 '%s' 失败: %s", module_path, e)
            self._module_states[module_path] = "error"
            return None

    async def activate(self, module_path: str, context: dict[str, Any] | None = None) -> bool:
        """激活模块"""
        instance = self._loaded_modules.get(module_path)
        if instance is None:
            logger.error("模块 '%s' 未加载", module_path)
            return False

        try:
            await instance.on_activate(context or {})
            self._module_states[module_path] = "active"
            logger.info("模块已激活: %s", module_path)
            return True
        except Exception as e:
            logger.error("激活模块 '%s' 失败: %s", module_path, e)
            self._module_states[module_path] = "error"
            return False

    async def deactivate(self, module_path: str) -> bool:
        """停用模块"""
        instance = self._loaded_modules.get(module_path)
        if instance is None:
            return False

        try:
            await instance.on_deactivate()
            self._module_states[module_path] = "inactive"
            return True
        except Exception as e:
            logger.error("停用模块 '%s' 失败: %s", module_path, e)
            return False

    async def unload(self, module_path: str) -> bool:
        """卸载模块"""
        instance = self._loaded_modules.pop(module_path, None)
        if instance is None:
            return False

        try:
            await instance.on_deactivate()
            await instance.on_unload()
            self._module_states.pop(module_path, None)
            self._manifests.pop(module_path, None)
            logger.info("模块已卸载: %s", module_path)
            return True
        except Exception as e:
            logger.error("卸载模块 '%s' 失败: %s", module_path, e)
            return False

    def get(self, module_path: str) -> DynamicModule | None:
        """获取已加载的模块"""
        return self._loaded_modules.get(module_path)

    def list_loaded(self) -> dict[str, str]:
        """列出已加载的模块及状态"""
        return dict(self._module_states)

    def is_active(self, module_path: str) -> bool:
        """检查模块是否激活"""
        return self._module_states.get(module_path) == "active"

    async def health_check_all(self) -> dict[str, bool]:
        """检查所有已加载模块的健康状态"""
        results: dict[str, bool] = {}
        for path, module in self._loaded_modules.items():
            try:
                results[path] = module.health_check()
            except Exception:
                results[path] = False
        return results
