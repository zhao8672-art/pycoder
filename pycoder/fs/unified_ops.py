"""
统一文件操作 — 跨路径的读写/搜索/元数据

支持:
  - 普通路径 (工作区内)
  - fs:// 别名路径 (工作区外授权目录)
  - 递归搜索
  - 文件元数据
"""

from __future__ import annotations

import glob
import logging
import os

from pycoder.fs.path_mapper import get_mapper

logger = logging.getLogger(__name__)


class UnifiedFileOps:
    """统一文件操作"""

    def __init__(self):
        self._mapper = get_mapper()

    async def read_file(self, path: str) -> dict:
        """读取文件"""
        real_path = self._resolve(path)
        if not real_path:
            return {"success": False, "error": "路径未授权或不存在"}
        if not os.path.isfile(real_path):
            return {"success": False, "error": "文件不存在"}
        try:
            with open(real_path, encoding="utf-8") as f:
                content = f.read()
            return {
                "success": True,
                "path": real_path,
                "content": content,
                "size": len(content),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def write_file(self, path: str, content: str) -> dict:
        """写入文件（检查写入权限）"""
        real_path = self._resolve(path)
        if not real_path:
            return {"success": False, "error": "路径未授权"}
        if not self._mapper.can_write(path):
            return {"success": False, "error": "该路径无写入权限"}
        try:
            os.makedirs(os.path.dirname(real_path), exist_ok=True)
            with open(real_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "path": real_path, "size": len(content)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def list_dir(self, path: str) -> dict:
        """列出目录内容"""
        real_path = self._resolve(path) if self._is_fs_path(path) else path
        if not real_path or not os.path.isdir(real_path):
            return {"success": False, "error": "目录不存在"}
        try:
            entries = []
            for item in sorted(os.listdir(real_path)):
                full = os.path.join(real_path, item)
                entries.append({
                    "name": item,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                })
            return {"success": True, "path": real_path, "entries": entries}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def search_files(self, pattern: str, root: str = "") -> dict:
        """递归搜索文件"""
        results = []
        if root:
            roots = [self._resolve(root)] if self._is_fs_path(root) else [root]
        else:
            roots = [e.real_path for e in self._mapper.list_mappings()]
        for r in roots:
            if r and os.path.isdir(r):
                for match in glob.glob(os.path.join(r, "**", pattern), recursive=True):
                    results.append({
                        "path": match,
                        "size": os.path.getsize(match) if os.path.isfile(match) else 0,
                    })
        return {"success": True, "total": len(results), "results": results[:100]}

    async def get_info(self, path: str) -> dict:
        """获取文件/目录元数据"""
        real_path = self._resolve(path)
        if not real_path:
            return {"success": False, "error": "路径未授权"}
        if not os.path.exists(real_path):
            return {"success": False, "error": "不存在"}
        stat = os.stat(real_path)
        return {
            "success": True,
            "path": real_path,
            "type": "dir" if os.path.isdir(real_path) else "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "permissions": oct(stat.st_mode)[-3:],
        }

    def _resolve(self, path: str) -> str | None:
        """解析路径"""
        if self._is_fs_path(path):
            return self._mapper.resolve(path)
        if os.path.exists(path):
            return path
        return None

    def _is_fs_path(self, path: str) -> bool:
        return path.startswith("fs://") or path.startswith("/") and not path.startswith("//")
