"""智能 IO 模块 — 大文件智能读取与索引"""
from __future__ import annotations

from typing import Any

from pycoder.io.chunk_cache import ChunkCache
from pycoder.io.file_indexer import FileIndex, FileIndexer, SymbolDef
from pycoder.io.smart_reader import SmartReader

__all__ = [
    "FileIndexer", "FileIndex", "SymbolDef", "SmartReader", "ChunkCache",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册智能文件读取与索引能力"""
    from pathlib import Path

    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    reader = SmartReader(Path.cwd())

    def _smart_read(params: dict, ctx: dict) -> dict:
        result = reader.read_smart(
            file_path=params["file_path"],
            max_tokens=params.get("max_tokens"),
            chunk_index=params.get("chunk_index", 0),
            start_line=params.get("start_line"),
            end_line=params.get("end_line"),
        )
        return result

    def _preview_file(params: dict, ctx: dict) -> dict:
        overview = reader.get_overview(params["file_path"])
        return overview

    def _search_symbol(params: dict, ctx: dict) -> dict:
        from pycoder.io.file_indexer import FileIndexer
        indexer = FileIndexer()
        full_path = Path.cwd() / params["file_path"]
        index = indexer.index_file(full_path)
        if not index:
            return {"error": "文件不存在或不可读"}
        symbol_name = params["symbol_name"]
        matches = [s for s in index.symbols if symbol_name.lower() in s.name.lower()]
        return {
            "file_path": params["file_path"],
            "symbol_name": symbol_name,
            "matches": [{"name": s.name, "kind": s.kind, "start_line": s.start_line, "end_line": s.end_line} for s in matches],
        }

    registry.register(
        CapabilityDefinition(
            id="io.smart_read",
            name="智能读取文件",
            description="智能读取大文件，支持自动分段、按需加载和符号定位",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                    "max_tokens": {"type": "integer", "description": "最大 token 预算"},
                    "chunk_index": {"type": "integer", "description": "分段索引"},
                    "start_line": {"type": "integer", "description": "起始行号"},
                    "end_line": {"type": "integer", "description": "结束行号"},
                },
                "required": ["file_path"],
            },
            tags=["io", "read", "smart", "file", "大文件"],
        ),
        handler=_smart_read,
    )

    registry.register(
        CapabilityDefinition(
            id="io.preview_file",
            name="预览文件",
            description="预览文件概览（符号表+前N行），用于快速了解文件结构",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                },
                "required": ["file_path"],
            },
            tags=["io", "preview", "file", "preview", "预览"],
        ),
        handler=_preview_file,
    )

    registry.register(
        CapabilityDefinition(
            id="io.search_symbol",
            name="搜索符号",
            description="在文件中搜索符号定义（函数、类、变量等）",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                    "symbol_name": {"type": "string", "description": "符号名称"},
                },
                "required": ["file_path", "symbol_name"],
            },
            tags=["io", "search", "symbol", "搜索", "符号"],
        ),
        handler=_search_symbol,
    )
