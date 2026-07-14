"""
能力模块 — Pycoder V2 核心功能实现

按功能域组织：
- editor/: 代码编辑、LSP、重构、调试等编辑器能力
- system/: 文件操作、Shell执行、Git、包管理等系统能力
- self_evo/: 代码分析、自我修复、自部署等自进化能力
"""

from pycoder.capabilities.editor import register_editor_capabilities
from pycoder.capabilities.self_evo import register_self_evo_capabilities
from pycoder.capabilities.system import register_system_capabilities

__all__ = [
    "register_editor_capabilities",
    "register_system_capabilities",
    "register_self_evo_capabilities",
]
