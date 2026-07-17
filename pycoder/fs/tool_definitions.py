"""
AI 可调用的文件系统工具注册表

工具:
  - fs_read     读取文件（支持工作区外授权路径）
  - fs_write    写入文件
  - fs_list     列出目录
  - fs_search   搜索文件
  - fs_info     文件元数据
"""

from __future__ import annotations

FS_TOOLS: list[dict] = [
    {
        "name": "fs_read",
        "description": (
            "读取文件内容。支持工作区外路径，格式: fs://别名/路径。"
            "例如 fs://documents/readme.md"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_write",
        "description": "写入文件内容（仅限有写入权限的路径）",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "fs_list",
        "description": "列出目录中的文件和子目录",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_search",
        "description": "递归搜索文件，支持通配符，如 **/*.py",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式"},
                "root": {"type": "string", "description": "搜索根目录（可选）"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "fs_info",
        "description": "获取文件或目录的元数据（大小/类型/权限/修改时间）",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "路径"},
            },
            "required": ["path"],
        },
    },
]


async def execute_fs_read(path: str) -> dict:
    from pycoder.fs.unified_ops import UnifiedFileOps
    return await UnifiedFileOps().read_file(path)


async def execute_fs_write(path: str, content: str) -> dict:
    from pycoder.fs.unified_ops import UnifiedFileOps
    return await UnifiedFileOps().write_file(path, content)


async def execute_fs_list(path: str) -> dict:
    from pycoder.fs.unified_ops import UnifiedFileOps
    return await UnifiedFileOps().list_dir(path)


async def execute_fs_search(pattern: str, root: str = "") -> dict:
    from pycoder.fs.unified_ops import UnifiedFileOps
    return await UnifiedFileOps().search_files(pattern, root)


async def execute_fs_info(path: str) -> dict:
    from pycoder.fs.unified_ops import UnifiedFileOps
    return await UnifiedFileOps().get_info(path)
