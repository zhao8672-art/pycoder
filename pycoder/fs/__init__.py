"""文件系统扩展模块 — 突破工作区限制，支持跨目录授权访问

架构:
  PathMapper ── 路径别名映射 (fs://documents → C:/Users/xxx/Documents)
  PermissionPolicy ── 读写权限 + 白名单 + 路径穿越防护
  UnifiedFileOps ── 统一文件操作接口
"""

from __future__ import annotations

from pycoder.fs.path_mapper import PathMapper, PathEntry, get_mapper
from pycoder.fs.unified_ops import UnifiedFileOps
from pycoder.fs.tool_definitions import FS_TOOLS

__all__ = [
    "PathMapper",
    "PathEntry",
    "get_mapper",
    "UnifiedFileOps",
    "FS_TOOLS",
]
