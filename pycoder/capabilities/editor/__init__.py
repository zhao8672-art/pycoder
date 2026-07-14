"""
编辑器能力域

提供代码编辑、LSP智能、重构、格式化、调试和预览能力。
所有能力通过统一能力总线注册。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)
from pycoder.bus.transformer import InputTransformer, OutputTransformer

logger = logging.getLogger(__name__)


def register_editor_capabilities(registry: Any) -> None:
    """
    向总线注册所有编辑器能力

    Args:
        registry: CapabilityRegistry 实例
    """
    _register_code_operations(registry)
    _register_lsp_operations(registry)
    _register_refactor_operations(registry)
    _register_format_operations(registry)
    _register_preview_operations(registry)


def _register_code_operations(registry: Any) -> None:
    """注册代码读写能力"""

    # ── 读取文件 ──
    registry.register(
        CapabilityDefinition(
            id="editor.code.read",
            name="读取代码文件",
            description="读取指定路径的源代码文件内容，返回带行号的文本",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "start_line": {"type": "integer", "description": "起始行号（可选）"},
                    "end_line": {"type": "integer", "description": "结束行号（可选）"},
                },
                "required": ["path"],
            },
            tags=["read", "file", "读取", "文件"],
        ),
        handler=_read_file,
    )

    # ── 写入文件 ──
    registry.register(
        CapabilityDefinition(
            id="editor.code.write",
            name="写入代码文件",
            description="将内容写入指定路径的文件，会覆盖现有内容",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            rollback_support=True,
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                },
                "required": ["path", "content"],
            },
            tags=["write", "file", "写入", "文件", "保存"],
        ),
        handler=_write_file,
    )

    # ── 创建文件 ──
    registry.register(
        CapabilityDefinition(
            id="editor.code.create",
            name="创建新文件",
            description="在指定路径创建新文件，自动创建父目录",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            rollback_support=True,
            tags=["create", "new", "file", "创建", "新建"],
        ),
        handler=_create_file,
    )

    # ── 删除文件 ──
    registry.register(
        CapabilityDefinition(
            id="editor.code.delete",
            name="删除文件",
            description="删除指定路径的文件或空目录",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_DELETE],
            rollback_support=True,
            tags=["delete", "remove", "file", "删除"],
        ),
        handler=_delete_file,
    )

    # ── 内容搜索 ──
    registry.register(
        CapabilityDefinition(
            id="editor.code.search",
            name="代码搜索",
            description="在项目中搜索包含指定文本的文件，支持正则表达式",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索文本或正则表达式"},
                    "path": {"type": "string", "description": "搜索目录（可选，默认项目根目录）"},
                    "file_pattern": {"type": "string", "description": "文件模式过滤，如 *.py"},
                    "case_sensitive": {"type": "boolean", "description": "是否区分大小写"},
                    "max_results": {"type": "integer", "description": "最大结果数，默认 50"},
                },
                "required": ["query"],
            },
            tags=["search", "grep", "find", "搜索", "查找"],
        ),
        handler=_search_code,
    )


def _register_lsp_operations(registry: Any) -> None:
    """注册 LSP 能力"""
    registry.register(
        CapabilityDefinition(
            id="editor.lsp.diagnostics",
            name="代码诊断",
            description="获取当前文件的诊断信息（错误、警告、提示）",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            tags=["lsp", "diagnostics", "error", "诊断", "错误"],
        ),
        handler=_get_diagnostics,
    )


def _register_refactor_operations(registry: Any) -> None:
    """注册重构能力"""
    registry.register(
        CapabilityDefinition(
            id="editor.refactor.rename",
            name="重命名符号",
            description="重命名一个符号（变量、函数、类等）及其所有引用",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            side_effects=[SideEffect.FILE_WRITE],
            tags=["refactor", "rename", "重构", "重命名"],
        ),
        handler=_rename_symbol,
    )


def _register_format_operations(registry: Any) -> None:
    """注册格式化能力"""
    registry.register(
        CapabilityDefinition(
            id="editor.format.apply",
            name="格式化代码",
            description="使用项目配置的格式化工具格式化代码文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            side_effects=[SideEffect.FILE_WRITE],
            tags=["format", "beautify", "格式化"],
        ),
        handler=_format_code,
    )


def _register_preview_operations(registry: Any) -> None:
    """注册预览能力"""
    registry.register(
        CapabilityDefinition(
            id="editor.preview.html",
            name="预览 HTML",
            description="在编辑器中预览 HTML 文件",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            tags=["preview", "html", "预览"],
        ),
        handler=_preview_html,
    )


# ── 处理器实现 ────────────────────────────


async def _read_file(params: dict[str, Any], context: dict[str, Any]) -> str:
    """读取文件内容"""
    path = InputTransformer.normalize_path(params["path"])
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    content = file_path.read_text(encoding="utf-8", errors="replace")
    start_line = params.get("start_line")
    end_line = params.get("end_line")

    if start_line is not None or end_line is not None:
        lines = content.split("\n")
        start = (start_line or 1) - 1
        end = end_line or len(lines)
        content = "\n".join(lines[start:end])

    return OutputTransformer.format_file_content(content)


async def _write_file(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """写入文件内容"""
    path = InputTransformer.normalize_path(params["path"])
    content = params["content"]

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    existed = file_path.exists()
    file_path.write_text(content, encoding="utf-8")

    return {
        "path": str(file_path),
        "existed_before": existed,
        "size_bytes": file_path.stat().st_size,
        "lines": content.count("\n") + 1,
    }


async def _create_file(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """创建新文件"""
    path = InputTransformer.normalize_path(params.get("path", ""))
    content = params.get("content", "")

    file_path = Path(path)
    if file_path.exists():
        raise FileExistsError(f"文件已存在: {path}")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")

    return {
        "path": str(file_path),
        "created": True,
    }


async def _delete_file(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """删除文件"""
    path = InputTransformer.normalize_path(params["path"])
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    file_path.unlink()
    return {"path": str(file_path), "deleted": True}


async def _search_code(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """代码搜索"""
    import fnmatch
    import re

    query = params["query"]
    search_path = Path(params.get("path", "."))
    file_pattern = params.get("file_pattern", "*")
    case_sensitive = params.get("case_sensitive", False)
    max_results = params.get("max_results", 50)

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query, flags)

    results: list[dict[str, Any]] = []

    for file_path in search_path.rglob("*"):
        if not file_path.is_file():
            continue
        if not fnmatch.fnmatch(file_path.name, file_pattern):
            continue
        if len(results) >= max_results:
            break

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(content.split("\n"), 1):
                if pattern.search(line):
                    results.append({
                        "file": str(file_path.relative_to(search_path)),
                        "line": i,
                        "content": line.strip()[:200],
                    })
                    if len(results) >= max_results:
                        break
        except (OSError, UnicodeDecodeError):
            continue

    return {
        "query": query,
        "matches": len(results),
        "results": results,
    }


async def _get_diagnostics(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """获取诊断信息（委托给 LSP 服务）"""
    return {"diagnostics": [], "message": "LSP 诊断委托给语言服务器"}


async def _rename_symbol(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """重命名符号（委托给 LSP）"""
    return {"message": "重命名委托给 LSP 服务"}


async def _format_code(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """格式化代码"""
    path = InputTransformer.normalize_path(params.get("path", ""))
    return {"path": path, "message": "格式化委托给外部格式化工具"}


async def _preview_html(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """预览 HTML"""
    path = InputTransformer.normalize_path(params.get("path", ""))
    return {"path": path, "message": "HTML 预览委托给前端"}
