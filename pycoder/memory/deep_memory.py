"""
深度记忆系统 — Codex 4级 & Hermes 4层风格记忆架构

实现四级渐进式记忆，覆盖从会话到跨项目的完整知识生命周期：
- Level 1: WorkingMemory   — 会话级滑动窗口（临时）
- Level 2: IterationMemory — 特性级迭代追踪（SQLite + FTS5）
- Level 3: ProjectMemory   — 项目级知识图谱（ChromaDB 向量存储）
- Level 4: GlobalMemory    — 用户级偏好模式（跨项目持久化）

ChromaDB 为可选依赖，未安装时自动回退到纯 SQLite 模式。

注意：此文件已拆分为多个模块，此处仅为向后兼容的导出层。
实际实现位于：
- deep_memory_models.py: 数据模型
- working_memory.py: Level 1
- iteration_memory.py: Level 2
- project_memory.py: Level 3
- global_memory.py: Level 4
- deep_memory_system.py: 编排器
- deep_memory_capabilities.py: 能力注册
"""

from __future__ import annotations

from pathlib import Path

# 能力注册
from pycoder.memory.deep_memory_capabilities import register_capabilities

# 数据模型
from pycoder.memory.deep_memory_models import (
    _CHROMA_AVAILABLE,
    MemoryContext,
    MemoryEntry,
    MemoryStats,
    _estimate_tokens,
    _now_iso,
)

# 编排器
from pycoder.memory.deep_memory_system import DeepMemorySystem
from pycoder.memory.global_memory import GlobalMemory
from pycoder.memory.iteration_memory import IterationMemory
from pycoder.memory.project_memory import ProjectMemory

# 四级记忆实现
from pycoder.memory.working_memory import WorkingMemory

# 单例管理
_deep_memory_instance: DeepMemorySystem | None = None


def get_deep_memory(
    project_root: Path | None = None,
    global_dir: Path | None = None,
) -> DeepMemorySystem:
    """获取 DeepMemorySystem 单例

    Args:
        project_root: 项目根路径，首次调用时设置
        global_dir: 全局记忆存储目录

    Returns:
        DeepMemorySystem 实例
    """
    global _deep_memory_instance
    if _deep_memory_instance is None:
        _deep_memory_instance = DeepMemorySystem(
            project_root=project_root or Path.cwd(),
            global_dir=global_dir,
        )
    return _deep_memory_instance


def reset_deep_memory() -> None:
    """重置深度记忆实例（用于测试）"""
    global _deep_memory_instance
    _deep_memory_instance = None


__all__ = [
    # 数据模型
    "MemoryEntry",
    "MemoryContext",
    "MemoryStats",
    # 四级记忆
    "WorkingMemory",
    "IterationMemory",
    "ProjectMemory",
    "GlobalMemory",
    # 编排器
    "DeepMemorySystem",
    # 单例管理
    "get_deep_memory",
    "reset_deep_memory",
    # 能力注册
    "register_capabilities",
    # 辅助
    "_CHROMA_AVAILABLE",
    "_estimate_tokens",
    "_now_iso",
]
