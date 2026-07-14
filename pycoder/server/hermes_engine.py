"""
Hermes structured task engine (simplified shim).
保留 _execute_hermes_write 供 ws_handler.py 和 ws_handler_v2.py 调用。
"""

from __future__ import annotations


async def _execute_hermes_write(file_path: str, file_content: str) -> dict:
    """执行文件写入 (kept for backward compatibility)"""
    from pycoder.server.routers.files import get_workspace_root

    try:
        root = get_workspace_root()
        target = (root / file_path).resolve()
        if not target.is_relative_to(root):
            return {"path": file_path, "success": False, "error": "路径穿越拒绝"}
        target.parent.mkdir(parents=True, exist_ok=True)
        if not file_content:
            if target.exists():
                file_content = target.read_text(encoding="utf-8")
            else:
                return {
                    "path": file_path,
                    "success": False,
                    "error": "file_content为空且文件不存在",
                }
        target.write_text(file_content, encoding="utf-8")
        return {"path": file_path, "success": True, "size": len(file_content.encode("utf-8"))}
    except Exception as e:
        return {"path": file_path, "success": False, "error": str(e)}
