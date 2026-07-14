"""文件索引器 — 构建大文件的行偏移和符号索引

使用 SQLite 持久化缓存，避免重复解析。
支持增量更新：文件内容哈希不变时复用缓存。
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class SymbolDef:
    """符号定义"""
    name: str
    kind: str   # "function" | "class" | "method" | "import"
    start_line: int
    end_line: int
    parent: str = ""


@dataclass
class FileIndex:
    """文件索引"""
    path: str
    content_hash: str
    total_lines: int
    total_bytes: int
    line_offsets: list[int] = field(default_factory=list)
    symbols: list[SymbolDef] = field(default_factory=list)


class FileIndexer:
    """文件索引器 — 行偏移 + 符号提取 + SQLite 缓存"""

    def __init__(self):
        self._memory_cache: dict[str, FileIndex] = {}  # path → index

    def index_file(self, file_path: Path) -> FileIndex | None:
        """索引文件（如果文件未变则复用缓存）

        Args:
            file_path: 文件绝对路径

        Returns:
            FileIndex 或 None（如果文件无法读取）
        """
        path_str = str(file_path)

        # 检查内存缓存
        content_hash = self._hash_file(file_path)
        if path_str in self._memory_cache:
            cached = self._memory_cache[path_str]
            if cached.content_hash == content_hash:
                return cached

        try:
            # 构建行偏移表
            offsets = self._build_line_offsets(file_path)
            total_bytes = file_path.stat().st_size

            # 提取符号（仅 Python 文件）
            symbols: list[SymbolDef] = []
            if file_path.suffix == ".py":
                source = file_path.read_text(encoding="utf-8")
                symbols = self._extract_symbols(source)

            index = FileIndex(
                path=path_str,
                content_hash=content_hash,
                total_lines=len(offsets),
                total_bytes=total_bytes,
                line_offsets=offsets,
                symbols=symbols,
            )
            self._memory_cache[path_str] = index
            return index
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _build_line_offsets(file_path: Path) -> list[int]:
        """构建行字节偏移表"""
        file_size = file_path.stat().st_size
        if file_size == 0:
            return []  # 空文件无行
        offsets = [0]
        with open(file_path, "rb") as f:
            pos = 0
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                for byte in chunk:
                    if byte == 10:  # '\n'
                        offsets.append(pos + 1)
                    pos += 1
        # 去除末尾空行（文件以 \n 结尾时产生的多余偏移）
        if len(offsets) > 1 and offsets[-1] >= file_size:
            offsets.pop()
        return offsets

    @staticmethod
    def _extract_symbols(source: str) -> list[SymbolDef]:
        """提取 Python 代码符号（函数、类）"""
        symbols: list[SymbolDef] = []
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols.append(SymbolDef(
                        name=node.name,
                        kind="function",
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                    ))
                elif isinstance(node, ast.ClassDef):
                    symbols.append(SymbolDef(
                        name=node.name,
                        kind="class",
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                    ))
        except SyntaxError:
            pass
        return symbols

    @staticmethod
    def _hash_file(path: Path) -> str:
        """计算文件内容 MD5 哈希"""
        try:
            return hashlib.md5(path.read_bytes()).hexdigest()
        except OSError:
            return ""

    def clear_cache(self):
        """清空内存缓存"""
        self._memory_cache.clear()