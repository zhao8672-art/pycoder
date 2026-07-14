"""
PyCoder 自我学习进化引擎 — 向后兼容重导出

已迁移至 V2 能力模块: pycoder.capabilities.self_evo.learning
"""

# 从 V2 路径重导出所有内容，保持完全向后兼容
from pycoder.capabilities.self_evo.learning.__init__ import *  # noqa: F401 F403

# 暴露私有模块级变量（测试需要）
from pycoder.capabilities.self_evo.learning.__init__ import (
    _engine,
    _format_top_errors,
    _pattern_extractor_instance,
)
