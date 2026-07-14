"""P1-4: FileSystem 端口 — 文件系统操作抽象接口

核心业务逻辑通过此接口访问文件系统，便于测试与替换实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class FileSystem(Protocol):
    """文件系统操作端口

    实现示例：LocalFileSystem（包装 pathlib）

    安全要求：
        - 所有路径必须经过校验，防止目录遍历
        - 不允许访问工作区外的文件
    """

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str:
        """读取文本文件"""
        ...

    def write_text(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> None:
        """写入文本文件"""
        ...

    def list_files(
        self,
        path: str | Path = ".",
        pattern: str = "*",
    ) -> list[Path]:
        """列出目录下的文件"""
        ...

    def exists(self, path: str | Path) -> bool:
        """检查文件是否存在"""
        ...

    def safe_path(self, path: str | Path) -> Path:
        """校验路径在工作区内，返回绝对路径

        Raises:
            ValueError: 路径逃逸工作区时
        """
        ...
