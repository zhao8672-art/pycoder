"""搜索工具 — search, quick_open"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.EDITOR


def register(registry: Any) -> None:
    _reg(
        registry,
        "tools.search.text",
        "文本搜索",
        "在项目中搜索文本。mode=semantic 使用向量语义搜索（需先索引）",
        {
            "query": {"type": "string", "description": "搜索关键词"},
            "mode": {
                "type": "string",
                "enum": ["keyword", "semantic"],
                "default": "keyword",
                "description": "搜索模式: keyword=关键词, semantic=语义",
            },
            "include_pattern": {"type": "string", "default": "**/*.py"},
            "max_results": {"type": "number", "default": 20},
        },
        ["query"],
        _handle_search,
    )

    _reg(
        registry,
        "tools.search.quick_open",
        "快捷打开",
        "快捷文件搜索（类似 VS Code Ctrl+P），按文件名模糊匹配",
        {
            "query": {"type": "string", "default": ""},
            "max_results": {"type": "number", "default": 15},
        },
        [],
        _handle_quick_open,
    )


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid,
            name=name,
            description=desc,
            category=_CT,
            permission=TOOL_PERMISSIONS.get(cid),
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={"type": "object", "properties": schema, "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


async def _handle_search(params: dict, context: dict) -> dict:
    query = params.get("query", "")
    include_pattern = params.get("include_pattern", "**/*.py")
    max_results = params.get("max_results", 20)
    results = []
    root = Path.cwd()
    for f in list(root.rglob(include_pattern))[:100]:
        if "__pycache__" in str(f) or "node_modules" in str(f):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(content.split("\n"), 1):
                if query.lower() in line.lower():
                    results.append(
                        {"file": str(f.relative_to(root)), "line": i, "text": line.strip()[:200]}
                    )
                    if len(results) >= max_results:
                        break
        except (OSError, UnicodeDecodeError):
            continue
        if len(results) >= max_results:
            break
    return {"success": True, "results": results, "total": len(results)}


async def _handle_quick_open(params: dict, context: dict) -> dict:
    query = params.get("query", "").lower()
    max_results = params.get("max_results", 15)
    results = []
    for f in list(Path.cwd().rglob("*"))[:500]:
        if any(kw in str(f) for kw in ("__pycache__", "node_modules", ".git")):
            continue
        if f.is_file() and f.suffix in (".py", ".ts", ".tsx", ".js", ".md", ".json", ".toml"):
            rel = str(f.relative_to(Path.cwd()))
            if not query or query in rel.lower():
                results.append({"path": rel, "name": f.name, "size": f.stat().st_size})
                if len(results) >= max_results:
                    break
    return {"success": True, "results": results, "total": len(results)}
