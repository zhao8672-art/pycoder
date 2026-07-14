"""
PyCoder 自动升级 — 向后兼容重导出

已迁移至 V2 能力模块: pycoder.capabilities.self_evo.upgrade
"""

import sys
from types import ModuleType

from pycoder.capabilities.self_evo.upgrade import *  # noqa: F401 F403

_v2 = sys.modules["pycoder.capabilities.self_evo.upgrade"]


class _ShimModule(ModuleType):
    """模块代理：属性访问和修改自动同步到 V2 模块。

    解决问题：当测试通过 monkeypatch.setattr(au, "PENDING_FILE", ...) 修改
    本模块的属性时，V2 模块中的函数仍引用 V2 模块自身的常量（而非本模块的副本），
    导致 monkeypatch 不生效。本类通过 __setattr__ 将属性修改同步到 V2 模块，
    通过 __getattr__ 将未在本地定义的属性访问委托给 V2 模块。
    """

    def __getattr__(self, name: str):
        """将未在本地定义的属性访问委托给 V2 模块。

        处理私有属性（如 _sp, _create_snapshot, _compare_versions 等），
        这些属性不会被 `from ... import *` 导入。
        """
        return getattr(_v2, name)

    def __setattr__(self, name: str, value) -> None:
        """将属性修改同步到 V2 模块，确保 monkeypatch 生效。

        测试通过 monkeypatch.setattr(au, attr, val) 修改属性时，
        本方法会同步修改 V2 模块中的同名属性，使 V2 模块内的函数能感知变更。
        特殊属性（以 __ 开头）不同步，避免干扰模块初始化。
        """
        if not name.startswith("__"):
            try:
                setattr(_v2, name, value)
            except AttributeError:
                pass
        super().__setattr__(name, value)


# 替换当前模块的类，使 __getattr__ / __setattr__ 生效
sys.modules[__name__].__class__ = _ShimModule