"""io 模块测试 — 文件索引、智能读取、分段缓存"""
from __future__ import annotations

import pytest
from pathlib import Path

from pycoder.io.file_indexer import FileIndexer, FileIndex, SymbolDef
from pycoder.io.smart_reader import SmartReader
from pycoder.io.chunk_cache import ChunkCache


class TestFileIndexer:
    def test_index_python_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("""import os

def hello():
    return "world"

class MyClass:
    def method(self):
        pass
""")
        indexer = FileIndexer()
        index = indexer.index_file(f)
        assert index is not None
        assert "hello" in {s.name for s in index.symbols}
        assert "MyClass" in {s.name for s in index.symbols}
        assert index.total_lines > 0
        assert index.total_bytes > 0

    def test_index_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        indexer = FileIndexer()
        index = indexer.index_file(f)
        assert index is not None
        assert index.total_lines == 0
        assert index.symbols == []

    def test_index_non_python_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        indexer = FileIndexer()
        index = indexer.index_file(f)
        assert index is not None
        assert index.total_lines == 3
        assert index.symbols == []  # 非 Python 文件不提取符号

    def test_index_nonexistent_file(self):
        indexer = FileIndexer()
        index = indexer.index_file(Path("/nonexistent/file.py"))
        assert index is None

    def test_cache_reuse(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo(): pass\n")
        indexer = FileIndexer()
        idx1 = indexer.index_file(f)
        idx2 = indexer.index_file(f)
        assert idx1 is idx2  # 同一对象，说明缓存命中

    def test_cache_invalidated_on_change(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo(): pass\n")
        indexer = FileIndexer()
        idx1 = indexer.index_file(f)
        f.write_text("def bar(): pass\n")
        idx2 = indexer.index_file(f)
        assert idx1 is not idx2  # 文件变化后缓存失效

    def test_line_offsets_correct(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\n")
        indexer = FileIndexer()
        index = indexer.index_file(f)
        assert index is not None
        assert index.total_lines == 3
        assert len(index.line_offsets) == 3


class TestSmartReader:
    def test_read_entire_small_file(self, tmp_path):
        f = tmp_path / "small.py"
        f.write_text("def hello():\n    return 'world'\n")
        reader = SmartReader(workspace=tmp_path)
        result = reader.read_smart("small.py")
        assert "hello" in result["content"]
        assert result["total_lines"] > 0

    def test_read_with_line_range(self, tmp_path):
        f = tmp_path / "test.py"
        lines = [f"line{i}" for i in range(1, 101)]
        f.write_text("\n".join(lines) + "\n")
        reader = SmartReader(workspace=tmp_path)
        result = reader.read_smart("test.py", start_line=10, end_line=15)
        assert "line10" in result["content"]
        assert "line15" in result["content"]
        assert result["start_line"] == 10
        assert result["end_line"] == 15

    def test_read_nonexistent_file(self, tmp_path):
        reader = SmartReader(workspace=tmp_path)
        result = reader.read_smart("nonexistent.py")
        assert "error" in result

    def test_get_overview(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("""import os

def main():
    pass

class App:
    def run(self):
        pass
""")
        reader = SmartReader(workspace=tmp_path)
        overview = reader.get_overview("test.py")
        assert "total_lines" in overview
        assert "preview" in overview
        assert len(overview["symbols"]) > 0
        symbol_names = {s["name"] for s in overview["symbols"]}
        assert "main" in symbol_names
        assert "App" in symbol_names

    def test_find_symbol(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("""def foo():
    x = 1

def bar():
    y = 2

def baz():
    z = 3
""")
        reader = SmartReader(workspace=tmp_path)
        result = reader.find_symbol("test.py", "bar", context_lines=0)
        assert "bar" in result["content"]
        assert result["symbol"]["name"] == "bar"

    def test_find_symbol_not_found(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo(): pass\n")
        reader = SmartReader(workspace=tmp_path)
        result = reader.find_symbol("test.py", "nonexistent")
        assert "error" in result

    def test_chunked_read_large_file(self, tmp_path):
        f = tmp_path / "large.py"
        # 生成约 2000 行文件
        lines = [f"def func_{i}(): return {i}" for i in range(2000)]
        f.write_text("\n".join(lines) + "\n")
        reader = SmartReader(workspace=tmp_path)
        result = reader.read_smart("large.py", max_tokens=500)
        assert "chunk_index" in result
        assert "total_chunks" in result
        assert result["total_chunks"] > 1  # 应该被分成多段
        assert result["has_more"] is True


class TestChunkCache:
    def test_set_and_get(self):
        cache = ChunkCache(max_bytes=1024 * 1024)
        cache.set("key1", "hello world")
        assert cache.get("key1") == "hello world"

    def test_miss_returns_none(self):
        cache = ChunkCache()
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self):
        cache = ChunkCache(max_bytes=100)
        cache.set("a", "x" * 60)
        cache.set("b", "y" * 60)
        # a 应该被淘汰
        assert cache.get("a") is None
        assert cache.get("b") is not None

    def test_clear(self):
        cache = ChunkCache()
        cache.set("k", "v")
        cache.clear()
        assert cache.get("k") is None
        assert cache.size_bytes == 0

    def test_entry_count(self):
        cache = ChunkCache()
        cache.set("a", "1")
        cache.set("b", "2")
        assert cache.entry_count == 2

    def test_lru_move_on_access(self, tmp_path):
        cache = ChunkCache(max_bytes=100)
        cache.set("a", "x" * 30)
        cache.set("b", "y" * 30)
        cache.set("c", "z" * 30)
        # 访问 a 后，它应该最近被使用
        cache.get("a")
        cache.set("d", "w" * 50)
        # a 不应被淘汰，b 应被淘汰
        assert cache.get("a") is not None
        assert cache.get("b") is None