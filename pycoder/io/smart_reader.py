"""智能文件读取器 — 自动分段、按需加载、符号定位

替代当前 read_file 的手动分段读取模式。
支持：
- 自动分段：根据 token 预算自动切分
- 按需加载：指定行范围精确读取
- 内容概览：符号表 + 前 N 行预览
- 符号定位：搜索符号名 → 返回其所在代码区域
"""
from __future__ import annotations

from pathlib import Path

from pycoder.io.file_indexer import FileIndexer, FileIndex
from pycoder.io.chunk_cache import ChunkCache


class SmartReader:
    """智能文件读取器"""

    MAX_CHUNK_TOKENS = 8000   # 单段最大 token 数（约 2000 行）
    PREVIEW_LINES = 50        # 概览时预览行数

    def __init__(self, workspace: Path,
                 indexer: FileIndexer | None = None,
                 cache: ChunkCache | None = None):
        self._workspace = workspace
        self._indexer = indexer or FileIndexer()
        self._cache = cache or ChunkCache()

    def read_smart(self, file_path: str, max_tokens: int | None = None,
                   chunk_index: int = 0,
                   start_line: int | None = None,
                   end_line: int | None = None) -> dict:
        """智能读取文件

        Args:
            file_path: 相对于工作区的文件路径
            max_tokens: 最大 token 预算（用于自动分段，默认 8000）
            chunk_index: 分段索引（从 0 开始）
            start_line: 起始行号（1-based，按需加载模式）
            end_line: 结束行号（1-based）

        Returns:
            dict: {
                "content": str,         文件内容
                "total_lines": int,     总行数
                "chunk_index": int,     当前分段索引
                "total_chunks": int,    总分段数
                "has_more": bool,       是否有更多分段
                "symbols": list[dict],  符号表
            }
        """
        full_path = self._workspace / file_path
        index = self._indexer.index_file(full_path)
        if not index:
            return {"error": "无法索引文件，请检查文件是否存在且可读"}

        max_tokens = max_tokens or self.MAX_CHUNK_TOKENS

        # 按需加载：指定行范围
        if start_line is not None:
            return self._read_lines(index, full_path, start_line, end_line)

        # 自动分段：根据 token 预算
        return self._read_chunked(index, full_path, max_tokens, chunk_index)

    def get_overview(self, file_path: str) -> dict:
        """获取文件概览（符号表 + 前 N 行预览）

        Args:
            file_path: 相对于工作区的文件路径

        Returns:
            dict: {
                "file_path": str,
                "total_lines": int,
                "total_bytes": int,
                "symbols": list[dict],
                "preview": str,
            }
        """
        full_path = self._workspace / file_path
        index = self._indexer.index_file(full_path)
        if not index:
            return {"error": "无法索引文件"}

        preview = self._read_lines(index, full_path, 1, self.PREVIEW_LINES)
        return {
            "file_path": file_path,
            "total_lines": index.total_lines,
            "total_bytes": index.total_bytes,
            "symbols": [
                {"name": s.name, "kind": s.kind,
                 "start_line": s.start_line, "end_line": s.end_line}
                for s in index.symbols
            ],
            "preview": preview["content"],
        }

    def find_symbol(self, file_path: str, symbol_name: str,
                    context_lines: int = 20) -> dict:
        """定位符号并返回其所在代码区域

        Args:
            file_path: 相对于工作区的文件路径
            symbol_name: 符号名称（函数名/类名）
            context_lines: 返回符号前后的上下文行数

        Returns:
            dict: 包含 content 和 symbol 信息，或 error
        """
        full_path = self._workspace / file_path
        index = self._indexer.index_file(full_path)
        if not index:
            return {"error": "无法索引文件"}

        for sym in index.symbols:
            if sym.name == symbol_name:
                start = max(1, sym.start_line - context_lines)
                end = min(index.total_lines, sym.end_line + context_lines)
                result = self._read_lines(index, full_path, start, end)
                result["symbol"] = {
                    "name": sym.name,
                    "kind": sym.kind,
                    "start_line": sym.start_line,
                    "end_line": sym.end_line,
                }
                return result

        return {"error": f"未找到符号: {symbol_name}"}

    def _read_lines(self, index: FileIndex, path: Path,
                    start: int, end: int | None = None) -> dict:
        """精确读取指定行范围（1-based）"""
        end = end or index.total_lines
        start = max(1, start)
        end = min(index.total_lines, end)

        if index.total_lines == 0:
            return {
                "content": "",
                "total_lines": 0,
                "start_line": 0,
                "end_line": 0,
                "has_more": False,
            }

        offset_start = index.line_offsets[start - 1]
        offset_end = (
            index.line_offsets[end]
            if end < len(index.line_offsets)
            else index.total_bytes
        )

        # 尝试缓存
        cache_key = f"{index.path}:{start}:{end}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return {
                "content": cached,
                "total_lines": index.total_lines,
                "start_line": start,
                "end_line": end,
                "has_more": end < index.total_lines,
            }

        with open(path, "rb") as f:
            f.seek(offset_start)
            content = f.read(offset_end - offset_start).decode(
                "utf-8", errors="replace"
            )

        self._cache.set(cache_key, content)
        return {
            "content": content,
            "total_lines": index.total_lines,
            "start_line": start,
            "end_line": end,
            "has_more": end < index.total_lines,
        }

    def _read_chunked(self, index: FileIndex, path: Path,
                      max_tokens: int, chunk_index: int = 0) -> dict:
        """按 token 预算自动分段读取"""
        # 估算每行平均 token 数
        avg_bytes_per_line = index.total_bytes / max(index.total_lines, 1)
        avg_tokens_per_line = max(avg_bytes_per_line / 4, 1)
        lines_per_chunk = max(1, int(max_tokens / avg_tokens_per_line))

        total_chunks = max(
            1,
            (index.total_lines + lines_per_chunk - 1) // lines_per_chunk,
        )
        start = chunk_index * lines_per_chunk + 1
        end = min(start + lines_per_chunk - 1, index.total_lines)

        result = self._read_lines(index, path, start, end)
        result["chunk_index"] = chunk_index
        result["total_chunks"] = total_chunks
        result["symbols"] = [
            {"name": s.name, "kind": s.kind,
             "start_line": s.start_line, "end_line": s.end_line}
            for s in index.symbols
        ]
        return result