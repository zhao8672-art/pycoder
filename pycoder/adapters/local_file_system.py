"""P1-4: LocalFileSystem — 包装 pathlib 实现 FileSystem 端口

将现有的文件操作适配为符合 FileSystem Protocol 的实现，并强制路径校验。
"""

from __future__ import annotations

from pathlib import Path


class LocalFileSystem:
    """FileSystem 适配器 — 包装 pathlib，强制路径在工作区内

    用法：
        fs = LocalFileSystem(workspace=Path("/workspace"))
        content = fs.read_text("src/app.py")  # 自动校验路径
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.resolve()

    def safe_path(self, path: str | Path) -> Path:
        """校验路径在工作区内，返回绝对路径

        Raises:
            ValueError: 路径逃逸工作区时
        """
        target = (self._workspace / path).resolve()
        # 必须在 workspace 内（或就是 workspace 本身）
        if target != self._workspace and self._workspace not in target.parents:
            raise ValueError(f"路径逃逸工作区: {path} → {target}（工作区: {self._workspace}）")
        return target

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str:
        target = self.safe_path(path)
        return target.read_text(encoding=encoding)

    def write_text(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> None:
        target = self.safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)

    def list_files(
        self,
        path: str | Path = ".",
        pattern: str = "*",
    ) -> list[Path]:
        target = self.safe_path(path)
        return sorted(target.glob(pattern))

    def exists(self, path: str | Path) -> bool:
        target = self.safe_path(path)
        return target.exists()
