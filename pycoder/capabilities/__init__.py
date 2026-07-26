"""
能力模块 — Pycoder V2 核心功能实现

按功能域组织：
- editor/: 代码编辑、LSP、重构、调试等编辑器能力
- system/: 文件操作、Shell执行、Git、包管理等系统能力
- self_evo/: 代码分析、自我修复、自部署等自进化能力
- lifecycle/: 项目生命周期编排能力（新增）
- gateway/: 多平台消息网关能力（新增）
- memory/: 长期记忆与上下文管理能力（新增）
- extension/: 扩展系统管理能力（新增）
- observability/: 可观测性与监控能力（新增）
"""

from pycoder.capabilities.editor import register_editor_capabilities
from pycoder.capabilities.self_evo import register_self_evo_capabilities
from pycoder.capabilities.system import register_system_capabilities

# 新增能力域
from pycoder.capabilities.lifecycle import register_lifecycle_capabilities
from pycoder.capabilities.gateway import register_gateway_capabilities
from pycoder.capabilities.memory import register_memory_capabilities
from pycoder.capabilities.extension import register_extension_capabilities
from pycoder.capabilities.observability import register_observability_capabilities

__all__ = [
    # 既有能力域
    "register_editor_capabilities",
    "register_system_capabilities",
    "register_self_evo_capabilities",
    # 新增能力域
    "register_lifecycle_capabilities",
    "register_gateway_capabilities",
    "register_memory_capabilities",
    "register_extension_capabilities",
    "register_observability_capabilities",
]
