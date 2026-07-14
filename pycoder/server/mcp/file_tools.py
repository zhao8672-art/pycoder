"""
MCP 文件操作工具集 — 从 mcp_tools.py 抽取
"""

from __future__ import annotations


def register_all(register_fn):
    """注册所有文件操作工具"""

    async def _handle_write_file(args: dict) -> dict:
        from pycoder.server.routers.files import get_workspace_root

        work_dir = get_workspace_root()
        file_path = args.get("path", "")
        content = args.get("content", "")
        if not file_path:
            return {"success": False, "error": "path 不能为空"}
        if not content:
            return {"success": False, "error": "content 不能为空"}
        try:
            target = (work_dir / file_path).resolve()
            if not target.is_relative_to(work_dir):
                return {"success": False, "error": "路径穿越拒绝"}
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {
                "success": True,
                "path": file_path,
                "size": len(content.encode("utf-8")),
                "message": f"文件已写入: {file_path} ({len(content.encode('utf-8'))} 字节)",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    register_fn(
        name="write_file",
        description="向当前工作区写入文件（覆盖或新建），自动创建父目录。path 是相对于工作区的路径",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对于工作区根目录）"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        },
        handler=_handle_write_file,
    )

    async def _handle_read_file(args: dict) -> dict:
        from pycoder.server.routers.files import get_workspace_root

        work_dir = get_workspace_root()
        file_path = args.get("path", "")
        if not file_path:
            return {"success": False, "error": "path 不能为空"}
        try:
            target = (work_dir / file_path).resolve()
            if not target.is_relative_to(work_dir):
                return {"success": False, "error": "路径穿越拒绝"}
            if not target.exists():
                return {"success": False, "error": f"文件不存在: {file_path}"}
            if target.is_dir():
                return {"success": False, "error": f"是目录不是文件: {file_path}"}
            content = target.read_text(encoding="utf-8")
            return {
                "success": True,
                "path": file_path,
                "content": content,
                "size": len(content.encode("utf-8")),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    register_fn(
        name="read_file",
        description="从当前工作区读取文件内容",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对于工作区根目录）"},
            },
            "required": ["path"],
        },
        handler=_handle_read_file,
    )

    async def _handle_list_files(args: dict) -> dict:
        from pycoder.server.routers.files import get_workspace_root

        work_dir = get_workspace_root()
        dir_path = args.get("path", ".")
        try:
            target = (work_dir / dir_path).resolve()
            if not target.is_relative_to(work_dir):
                return {"success": False, "error": "路径穿越拒绝"}
            if not target.exists():
                return {"success": False, "error": f"路径不存在: {dir_path}"}
            if not target.is_dir():
                return {"success": False, "error": f"不是目录: {dir_path}"}
            items = []
            for entry in sorted(target.iterdir()):
                items.append(
                    {
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size if entry.is_file() else 0,
                    }
                )
            return {"success": True, "path": dir_path, "items": items, "count": len(items)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    register_fn(
        name="list_files",
        description="列出工作区指定目录下的文件和子目录",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径（相对于工作区根目录）",
                    "default": ".",
                },
            },
        },
        handler=_handle_list_files,
    )

    async def _handle_delete_file(args: dict) -> dict:
        import shutil

        from pycoder.server.routers.files import get_workspace_root

        work_dir = get_workspace_root()
        file_path = args.get("path", "")
        if not file_path:
            return {"success": False, "error": "path 不能为空"}
        try:
            target = (work_dir / file_path).resolve()
            if not target.is_relative_to(work_dir):
                return {"success": False, "error": "路径穿越拒绝"}
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return {"success": True, "path": file_path, "message": f"已删除: {file_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    register_fn(
        name="delete_file",
        description="删除工作区中的文件或目录（递归删除）",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件或目录路径"},
            },
            "required": ["path"],
        },
        handler=_handle_delete_file,
    )

    async def _handle_create_directory(args: dict) -> dict:
        from pycoder.server.routers.files import get_workspace_root

        work_dir = get_workspace_root()
        dir_path = args.get("path", "")
        if not dir_path:
            return {"success": False, "error": "path 不能为空"}
        try:
            target = (work_dir / dir_path).resolve()
            if not target.is_relative_to(work_dir):
                return {"success": False, "error": "路径穿越拒绝"}
            target.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": dir_path, "message": f"目录已创建: {dir_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    register_fn(
        name="create_directory",
        description="在当前工作区创建目录（可递归创建多层目录）",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
            },
            "required": ["path"],
        },
        handler=_handle_create_directory,
    )

    async def _handle_run_terminal(args: dict) -> dict:
        cmd = args.get("command", "")
        timeout = args.get("timeout", 30)
        cwd = args.get("cwd", None)
        if not cmd:
            return {"success": False, "error": "command 不能为空"}
        try:
            import subprocess as _sp
            import sys

            from pycoder.server.routers.files import get_workspace_root

            work_dir = cwd or str(get_workspace_root())
            if sys.platform == "win32":
                proc = _sp.run(
                    ["powershell.exe", "-Command", cmd],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=work_dir,
                )
            else:
                proc = _sp.run(
                    ["bash", "-c", cmd],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=work_dir,
                )
            return {
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:8000],
                "stderr": proc.stderr[:4000],
                "cwd": work_dir,
            }
        except _sp.TimeoutExpired:
            return {"success": False, "error": f"命令超时 ({timeout}s)", "exit_code": -1}
        except Exception as e:
            return {"success": False, "error": str(e), "exit_code": -1}

    register_fn(
        name="run_terminal",
        description="在终端中执行 shell 命令并获取输出和退出码",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {"type": "number", "description": "超时秒数", "default": 30},
                "cwd": {"type": "string", "description": "工作目录(可选)", "default": ""},
            },
            "required": ["command"],
        },
        handler=_handle_run_terminal,
    )
