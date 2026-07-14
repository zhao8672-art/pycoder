"""
文件操作工具 — read_file, write_file, list_files, create_directory, delete_file
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.degradation import wrap_handler
from pycoder.capabilities.permissions import TOOL_PERMISSIONS


def register(registry: Any) -> None:
    """注册所有文件操作工具"""
    _reg(registry, "tools.file.read", "读取文件",
         "从工作区读取文件内容。path 相对于工作区根目录",
         {"path": {"type": "string", "description": "文件路径"}},
         ["path"], _handle_read_file)

    _reg(registry, "tools.file.write", "写入文件",
         "向工作区写入文件（覆盖或新建）。path 相对于工作区根目录",
         {"path": {"type": "string", "description": "文件路径"},
          "content": {"type": "string", "description": "文件内容"}},
         ["path", "content"], _handle_write_file)

    _reg(registry, "tools.file.list", "列出目录",
         "列出工作区指定目录下的文件和子目录",
         {"path": {"type": "string", "description": "目录路径", "default": "."}},
         [], _handle_list_files)

    _reg(registry, "tools.file.create_directory", "创建目录",
         "在工作区创建目录（可递归）",
         {"path": {"type": "string", "description": "目录路径"}},
         ["path"], _handle_create_directory)

    _reg(registry, "tools.file.delete", "删除文件",
         "删除工作区中的文件或目录（递归）",
         {"path": {"type": "string", "description": "文件或目录路径"}},
         ["path"], _handle_delete_file)


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid, name=name, description=desc,
            permission=TOOL_PERMISSIONS.get(cid),
            execution=ExecutionMode.SYNC,
            side_effects=_infer_side(cid),
            schema={"type": "object", "properties": schema,
                    "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


def _infer_side(cid: str) -> list:
    if ".read" in cid or ".list" in cid:
        return [SideEffect.FILE_READ]
    if ".delete" in cid:
        return [SideEffect.FILE_DELETE]
    return [SideEffect.FILE_WRITE]


async def _handle_read_file(params: dict, context: dict) -> dict:
    from pycoder.server.routers.files import get_workspace_root
    work_dir = Path(get_workspace_root())
    target = (work_dir / params.get("path", "")).resolve()
    if not target.is_relative_to(work_dir):
        return {"success": False, "error": "路径穿越拒绝"}
    if not target.exists():
        return {"success": False, "error": f"文件不存在: {params.get('path')}"}
    content = target.read_text(encoding="utf-8")
    return {"success": True, "path": params["path"],
            "content": content, "size": len(content.encode())}


async def _handle_write_file(params: dict, context: dict) -> dict:
    from pycoder.server.routers.files import get_workspace_root
    work_dir = Path(get_workspace_root())
    target = (work_dir / params["path"]).resolve()
    if not target.is_relative_to(work_dir):
        return {"success": False, "error": "路径穿越拒绝"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(params["content"], encoding="utf-8")
    return {"success": True, "path": params["path"],
            "size": len(params["content"].encode())}


async def _handle_list_files(params: dict, context: dict) -> dict:
    from pycoder.server.routers.files import get_workspace_root
    work_dir = Path(get_workspace_root())
    target = (work_dir / params.get("path", ".")).resolve()
    if not target.is_relative_to(work_dir):
        return {"success": False, "error": "路径穿越拒绝"}
    if not target.exists():
        return {"success": False, "error": f"路径不存在: {params.get('path')}"}
    items = []
    for entry in sorted(target.iterdir()):
        items.append({"name": entry.name, "is_dir": entry.is_dir(),
                       "size": entry.stat().st_size if entry.is_file() else 0})
    return {"success": True, "path": params.get("path", "."),
            "items": items, "count": len(items)}


async def _handle_create_directory(params: dict, context: dict) -> dict:
    from pycoder.server.routers.files import get_workspace_root
    work_dir = Path(get_workspace_root())
    target = (work_dir / params["path"]).resolve()
    if not target.is_relative_to(work_dir):
        return {"success": False, "error": "路径穿越拒绝"}
    target.mkdir(parents=True, exist_ok=True)
    return {"success": True, "path": params["path"]}


async def _handle_delete_file(params: dict, context: dict) -> dict:
    import shutil
    from pycoder.server.routers.files import get_workspace_root
    work_dir = Path(get_workspace_root())
    target = (work_dir / params["path"]).resolve()
    if not target.is_relative_to(work_dir):
        return {"success": False, "error": "路径穿越拒绝"}
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"success": True, "path": params["path"]}
