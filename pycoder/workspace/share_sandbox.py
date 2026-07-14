"""共享沙箱 — 安全跨工作区文件访问

在沙箱隔离的前提下，通过路径白名单 + 边界检查实现安全跨工作区读写。
只读共享直接读取，读写共享使用 copy-on-write 临时层。
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pycoder.workspace.workspace_registry import ShareLevel, WorkspaceRegistry


class ShareSandbox:
    """跨工作区共享沙箱

    用法:
        sandbox = ShareSandbox(registry)
        content = sandbox.read_file("ws_a", "ws_b", "src/main.py")
        sandbox.write_file("ws_a", "ws_b", "src/main.py", "new content")
        sandbox.commit_changes("ws_b")
    """

    def __init__(self, registry: WorkspaceRegistry):
        self._registry = registry
        self._temp_layers: dict[str, Path] = {}

    def read_file(self, caller_ws: str, target_ws: str, rel_path: str) -> str:
        """从目标工作区只读读取文件

        Args:
            caller_ws: 调用方工作区 ID
            target_ws: 目标工作区 ID
            rel_path: 相对路径

        Returns:
            文件内容

        Raises:
            PermissionError: 权限不足
            FileNotFoundError: 文件不存在
        """
        target = self._registry.get(target_ws)
        if not target:
            raise PermissionError(f"工作区 {target_ws} 未注册")

        if target.share_level == ShareLevel.NONE:
            raise PermissionError(f"工作区 {target_ws} 未开启共享")

        if caller_ws not in target.allowed_workspaces:
            raise PermissionError(f"工作区 {caller_ws} 无权访问 {target_ws}")

        if not self._is_path_allowed(rel_path, target.shared_paths):
            raise PermissionError(f"路径 {rel_path} 不在共享白名单中")

        full_path = Path(target.path) / rel_path
        resolved = full_path.resolve()
        ws_root = Path(target.path).resolve()

        if not resolved.is_relative_to(ws_root):
            raise PermissionError("路径逃逸检测：拒绝访问工作区外文件")

        if not resolved.is_file():
            raise FileNotFoundError(f"文件不存在: {rel_path}")

        return resolved.read_text(encoding="utf-8")

    def write_file(self, caller_ws: str, target_ws: str, rel_path: str,
                   content: str) -> None:
        """向目标工作区写入（copy-on-write 临时层）

        Args:
            caller_ws: 调用方工作区 ID
            target_ws: 目标工作区 ID
            rel_path: 相对路径
            content: 新内容
        """
        target = self._registry.get(target_ws)
        if not target:
            raise PermissionError(f"工作区 {target_ws} 未注册")

        if target.share_level != ShareLevel.READ_WRITE:
            raise PermissionError(f"工作区 {target_ws} 未开启读写共享")

        if caller_ws not in target.allowed_workspaces:
            raise PermissionError(f"工作区 {caller_ws} 无权访问 {target_ws}")

        if not self._is_path_allowed(rel_path, target.shared_paths):
            raise PermissionError(f"路径 {rel_path} 不在共享白名单中")

        if target_ws not in self._temp_layers:
            self._temp_layers[target_ws] = Path(
                tempfile.mkdtemp(prefix="ws_share_")
            )

        layer_path = self._temp_layers[target_ws] / rel_path
        layer_path.parent.mkdir(parents=True, exist_ok=True)
        layer_path.write_text(content, encoding="utf-8")

    def commit_changes(self, target_ws: str) -> list[str]:
        """将临时层变更合并到目标工作区

        Returns:
            已合并的文件路径列表
        """
        if target_ws not in self._temp_layers:
            return []

        target = self._registry.get(target_ws)
        if not target:
            return []

        merged = []
        temp_dir = self._temp_layers[target_ws]
        ws_root = Path(target.path)

        for temp_file in temp_dir.rglob("*"):
            if temp_file.is_file():
                rel = temp_file.relative_to(temp_dir)
                dest = ws_root / rel
                shutil.copy2(temp_file, dest)
                merged.append(str(rel))

        # 清理临时层
        shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_layers.pop(target_ws, None)
        return merged

    def rollback_changes(self, target_ws: str) -> None:
        """丢弃临时层变更"""
        if target_ws in self._temp_layers:
            shutil.rmtree(self._temp_layers[target_ws], ignore_errors=True)
            self._temp_layers.pop(target_ws, None)

    @staticmethod
    def _is_path_allowed(rel_path: str, allowed: list[str]) -> bool:
        if not allowed:
            return True  # 空列表 = 允许全部
        return any(
            rel_path == p.rstrip("/") or rel_path.startswith(p)
            for p in allowed
        )
