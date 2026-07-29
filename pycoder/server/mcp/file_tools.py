"""文件操作 MCP 工具注册"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_all(registry: Any) -> None:
    """注册所有文件操作工具"""
    _register_file_read(registry)
    _register_file_write(registry)
    _register_file_list(registry)
    _register_file_delete(registry)
    _register_file_copy(registry)
    _register_file_move(registry)
    _register_file_search(registry)
    _register_directory_operations(registry)
    _register_file_info(registry)
    _register_file_permissions(registry)


def _register_file_read(registry: Any) -> None:
    """注册文件读取工具"""
    registry.register(
        name="file_read",
        description="读取指定路径的文件内容",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "encoding": {"type": "string", "description": "文件编码，默认 utf-8"},
                "start_line": {"type": "integer", "description": "起始行号（可选）"},
                "end_line": {"type": "integer", "description": "结束行号（可选）"},
            },
            "required": ["path"],
        },
        handler=_handle_file_read,
    )


def _register_file_write(registry: Any) -> None:
    """注册文件写入工具"""
    registry.register(
        name="file_write",
        description="写入内容到指定路径的文件，自动创建父目录",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"},
                "encoding": {"type": "string", "description": "文件编码，默认 utf-8"},
                "append": {"type": "boolean", "description": "是否追加到文件末尾"},
            },
            "required": ["path", "content"],
        },
        handler=_handle_file_write,
    )


def _register_file_list(registry: Any) -> None:
    """注册文件列表工具"""
    registry.register(
        name="file_list",
        description="列出指定目录的内容",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
                "recursive": {"type": "boolean", "description": "是否递归列出子目录"},
                "pattern": {"type": "string", "description": "文件模式过滤，如 *.py"},
                "max_results": {"type": "integer", "description": "最大结果数，默认 100"},
            },
            "required": ["path"],
        },
        handler=_handle_file_list,
    )


def _register_file_delete(registry: Any) -> None:
    """注册文件删除工具"""
    registry.register(
        name="file_delete",
        description="删除指定路径的文件或空目录",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要删除的文件或目录路径"},
                "recursive": {"type": "boolean", "description": "是否递归删除目录内容"},
            },
            "required": ["path"],
        },
        handler=_handle_file_delete,
    )


def _register_file_copy(registry: Any) -> None:
    """注册文件复制工具"""
    registry.register(
        name="file_copy",
        description="复制文件或目录到目标路径",
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源路径"},
                "destination": {"type": "string", "description": "目标路径"},
                "overwrite": {"type": "boolean", "description": "是否覆盖已存在的目标"},
            },
            "required": ["source", "destination"],
        },
        handler=_handle_file_copy,
    )


def _register_file_move(registry: Any) -> None:
    """注册文件移动工具"""
    registry.register(
        name="file_move",
        description="移动文件或目录到目标路径",
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源路径"},
                "destination": {"type": "string", "description": "目标路径"},
                "overwrite": {"type": "boolean", "description": "是否覆盖已存在的目标"},
            },
            "required": ["source", "destination"],
        },
        handler=_handle_file_move,
    )


def _register_file_search(registry: Any) -> None:
    """注册文件搜索工具"""
    registry.register(
        name="file_search",
        description="在目录中搜索匹配模式的文件",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "搜索根目录"},
                "pattern": {"type": "string", "description": "文件 glob 模式，如 **/*.py"},
                "max_results": {"type": "integer", "description": "最大结果数，默认 50"},
            },
            "required": ["path", "pattern"],
        },
        handler=_handle_file_search,
    )


def _register_directory_operations(registry: Any) -> None:
    """注册目录操作工具"""
    registry.register(
        name="directory_create",
        description="创建目录（包括父目录）",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要创建的目录路径"},
            },
            "required": ["path"],
        },
        handler=_handle_directory_create,
    )


def _register_file_info(registry: Any) -> None:
    """注册文件信息工具"""
    registry.register(
        name="file_info",
        description="获取文件或目录的详细信息",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件或目录路径"},
            },
            "required": ["path"],
        },
        handler=_handle_file_info,
    )


def _register_file_permissions(registry: Any) -> None:
    """注册文件权限工具"""
    registry.register(
        name="file_permissions",
        description="获取或设置文件权限",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "mode": {"type": "string", "description": "权限模式，如 644（可选，不传则读取）"},
            },
            "required": ["path"],
        },
        handler=_handle_file_permissions,
    )


# ── 处理器实现 ──


async def _handle_file_read(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件读取"""
    path = Path(params["path"])
    if not path.exists():
        return {"success": False, "error": f"文件不存在: {path}"}

    encoding = params.get("encoding", "utf-8")
    try:
        content = path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return {"success": False, "error": f"无法使用 {encoding} 编码读取文件"}

    start_line = params.get("start_line")
    end_line = params.get("end_line")
    if start_line is not None or end_line is not None:
        lines = content.split("\n")
        start = (start_line or 1) - 1
        end = end_line or len(lines)
        content = "\n".join(lines[start:end])

    return {
        "success": True,
        "content": content,
        "path": str(path),
        "size": path.stat().st_size,
        "lines": content.count("\n") + 1,
    }


async def _handle_file_write(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件写入"""
    path = Path(params["path"])
    content = params["content"]
    encoding = params.get("encoding", "utf-8")
    append = params.get("append", False)

    path.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if append else "w"
    with open(path, mode, encoding=encoding) as f:
        f.write(content)

    return {
        "success": True,
        "path": str(path),
        "size": path.stat().st_size,
        "lines": content.count("\n") + 1,
        "appended": append,
    }


async def _handle_file_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件列表"""
    path = Path(params["path"])
    if not path.exists():
        return {"success": False, "error": f"目录不存在: {path}"}
    if not path.is_dir():
        return {"success": False, "error": f"路径不是目录: {path}"}

    recursive = params.get("recursive", False)
    pattern = params.get("pattern", "*")
    max_results = params.get("max_results", 100)

    files = []
    if recursive:
        for f in path.rglob(pattern):
            if len(files) >= max_results:
                break
            files.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "is_dir": f.is_dir(),
                    "size": f.stat().st_size if f.is_file() else 0,
                }
            )
    else:
        for f in path.glob(pattern):
            if len(files) >= max_results:
                break
            files.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "is_dir": f.is_dir(),
                    "size": f.stat().st_size if f.is_file() else 0,
                }
            )

    return {
        "success": True,
        "files": files,
        "total": len(files),
        "path": str(path),
    }


async def _handle_file_delete(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件删除"""
    path = Path(params["path"])
    if not path.exists():
        return {"success": False, "error": f"路径不存在: {path}"}

    recursive = params.get("recursive", False)

    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            if recursive:
                import shutil

                shutil.rmtree(path)
            else:
                path.rmdir()

        return {"success": True, "path": str(path), "deleted": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _handle_file_copy(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件复制"""
    source = Path(params["source"])
    destination = Path(params["destination"])
    overwrite = params.get("overwrite", False)

    if not source.exists():
        return {"success": False, "error": f"源路径不存在: {source}"}
    if destination.exists() and not overwrite:
        return {"success": False, "error": f"目标已存在且未设置覆盖: {destination}"}

    try:
        import shutil

        if source.is_file():
            shutil.copy2(source, destination)
        else:
            shutil.copytree(source, destination, dirs_exist_ok=overwrite)

        return {"success": True, "source": str(source), "destination": str(destination)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _handle_file_move(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件移动"""
    source = Path(params["source"])
    destination = Path(params["destination"])
    overwrite = params.get("overwrite", False)

    if not source.exists():
        return {"success": False, "error": f"源路径不存在: {source}"}
    if destination.exists() and not overwrite:
        return {"success": False, "error": f"目标已存在且未设置覆盖: {destination}"}

    try:
        if overwrite and destination.exists():
            if destination.is_file():
                destination.unlink()
            else:
                import shutil

                shutil.rmtree(destination)

        source.rename(destination)
        return {"success": True, "source": str(source), "destination": str(destination)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _handle_file_search(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件搜索"""
    path = Path(params["path"])
    pattern = params["pattern"]
    max_results = params.get("max_results", 50)

    if not path.exists():
        return {"success": False, "error": f"目录不存在: {path}"}

    files = []
    for f in path.glob(pattern):
        if len(files) >= max_results:
            break
        files.append(
            {
                "name": f.name,
                "path": str(f),
                "is_dir": f.is_dir(),
                "size": f.stat().st_size if f.is_file() else 0,
            }
        )

    return {
        "success": True,
        "files": files,
        "total": len(files),
        "pattern": pattern,
    }


async def _handle_directory_create(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理目录创建"""
    path = Path(params["path"])
    path.mkdir(parents=True, exist_ok=True)
    return {"success": True, "path": str(path), "created": True}


async def _handle_file_info(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理文件信息"""
    path = Path(params["path"])
    if not path.exists():
        return {"success": False, "error": f"路径不存在: {path}"}

    stat = path.stat()
    return {
        "success": True,
        "path": str(path),
        "name": path.name,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "created": stat.st_ctime,
        "permissions": oct(stat.st_mode)[-3:],
    }


async def _handle_file_permissions(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理文件权限"""
    path = Path(params["path"])
    if not path.exists():
        return {"success": False, "error": f"路径不存在: {path}"}

    if "mode" in params:
        mode = int(params["mode"], 8)
        path.chmod(mode)
        return {"success": True, "path": str(path), "mode": params["mode"]}
    else:
        stat = path.stat()
        return {
            "success": True,
            "path": str(path),
            "mode": oct(stat.st_mode)[-3:],
        }
