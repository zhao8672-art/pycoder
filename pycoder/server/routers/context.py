"""
@上下文引用系统 — 文件/符号/依赖/Web 搜索

为 AIPanel 的 @mention 功能提供后端 API:
  @file:path     → 读取文件内容
  @symbol:name   → 搜索项目符号
  @dep:name      → 搜索依赖信息
  @web:query     → 网页搜索
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/context")

WORKSPACE = Path(os.environ.get("PYCODER_WORKSPACE", os.getcwd())).resolve()


@router.get("/file")
async def get_file_context(path: str = Query(...)):
    """读取指定文件内容作为上下文"""
    full_path = (WORKSPACE / path).resolve()
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not full_path.is_relative_to(WORKSPACE):
        return {"error": "路径越界", "content": ""}
    if not full_path.exists():
        return {"error": "文件不存在", "content": ""}
    if full_path.is_dir():
        return {"error": "不能引用目录", "content": ""}
    if full_path.stat().st_size > 200_000:  # 200KB 上限
        return {"error": "文件过大（超过 200KB）", "content": ""}
    content = full_path.read_text(encoding="utf-8")
    return {
        "content": content,
        "path": str(full_path),
        "language": _guess_lang(full_path.suffix),
        "size": full_path.stat().st_size,
    }


@router.get("/symbols")
async def search_symbols(q: str = Query(...)):
    """搜索项目中的符号（函数/类/变量）"""
    try:
        from pycoder.python.project_context import get_symbol_index

        index = get_symbol_index(WORKSPACE)
        results = index.search(q, limit=15)
        return {
            "symbols": [
                {
                    "name": r.name,
                    "file": r.file,
                    "line": r.line,
                    "kind": r.kind,
                }
                for r in results
            ]
        }
    except ImportError:
        return {"symbols": [], "error": "project_context 模块未就绪"}
    except Exception as e:
        return {"symbols": [], "error": str(e)}


@router.get("/deps")
async def get_dep_context(q: str = Query("")):
    """搜索项目依赖信息"""
    try:
        from pycoder.python.dep_analyzer import get_dep_analyzer

        analyzer = get_dep_analyzer(WORKSPACE)
        deps = analyzer.get_all_deps()
        if q:
            q_lower = q.lower()
            deps = [
                d
                for d in deps
                if q_lower in d.get("name", "").lower() or q_lower in d.get("package", "").lower()
            ]
        return {"dependencies": deps[:20]}
    except ImportError:
        return {"dependencies": [], "error": "dep_analyzer 模块未就绪"}
    except Exception as e:
        return {"dependencies": [], "error": str(e)}


@router.get("/web")
async def search_web(q: str = Query(...)):
    """通过 MCP 搜索网页（需要联网）"""
    try:
        from pycoder.server.mcp_tools import call_builtin_tool

        result = await call_builtin_tool("web_search", {"query": q})
        if result and result.success:
            return {"results": result.output or []}
        return {"results": [], "error": "web_search 工具不可用"}
    except Exception as e:
        return {"results": [], "error": str(e)}


def _guess_lang(suffix: str) -> str:
    """根据文件后缀返回 Monaco 语言 ID"""
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".css": "css",
        ".html": "html",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sql": "sql",
        ".sh": "shell",
        ".bash": "shell",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".swift": "swift",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".vue": "html",
        ".svelte": "html",
        ".xml": "xml",
        ".env": "text",
        ".gitignore": "text",
        ".dockerfile": "dockerfile",
        ".txt": "text",
    }
    return mapping.get(suffix.lower(), "text")
