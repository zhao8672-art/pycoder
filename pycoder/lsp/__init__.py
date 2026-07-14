"""多语言 LSP 模块 — 统一管理多语言 LSP 服务器"""
from __future__ import annotations

from typing import Any

from pycoder.lsp.lsp_manager import LSPManager, LSPServerConfig, LSPStatus
from pycoder.lsp.diagnostics import DiagnosticsAggregator, AggregatedDiagnostic

__all__ = [
    "LSPManager", "LSPServerConfig", "LSPStatus",
    "DiagnosticsAggregator", "AggregatedDiagnostic",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册多语言 LSP 能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    from pathlib import Path
    manager = LSPManager(Path.cwd())

    def _start_language(params: dict, ctx: dict) -> dict:
        from asyncio import run
        success = run(manager.start(params["language"]))
        return {"success": success, "language": params["language"]}

    def _stop_language(params: dict, ctx: dict) -> dict:
        manager.stop(params["language"])
        return {"success": True, "language": params["language"]}

    def _get_status(params: dict, ctx: dict) -> dict:
        status = manager.get_status()
        return {"status": status}

    def _get_language_for_file(params: dict, ctx: dict) -> dict:
        lang = manager.get_language_for_file(params["file_path"])
        return {"language": lang}

    def _list_supported(params: dict, ctx: dict) -> dict:
        langs = manager.list_supported_languages()
        return {"supported": langs}

    def _scan_diagnostics(params: dict, ctx: dict) -> dict:
        diag = DiagnosticsAggregator(manager)
        if "file_path" in params:
            errors = diag.scan_file(params["file_path"])
            return {"errors": [e.to_dict() for e in errors], "file_path": params["file_path"]}
        else:
            all_errors = diag.scan_workspace(Path(params.get("workspace_path", ".")))
            return {"errors": [e.to_dict() for e in all_errors]}

    registry.register(
        CapabilityDefinition(
            id="lsp.start",
            name="启动 LSP 服务器",
            description="为指定语言启动 LSP 服务器",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS],
            schema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "语言标识符 (python/typescript/java/cpp/go)"},
                },
                "required": ["language"],
            },
            tags=["lsp", "language", "start", "语言服务器"],
        ),
        handler=_start_language,
    )

    registry.register(
        CapabilityDefinition(
            id="lsp.stop",
            name="停止 LSP 服务器",
            description="停止指定语言的 LSP 服务器",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS],
            schema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "语言标识符"},
                },
                "required": ["language"],
            },
            tags=["lsp", "stop", "语言服务器"],
        ),
        handler=_stop_language,
    )

    registry.register(
        CapabilityDefinition(
            id="lsp.status",
            name="获取 LSP 状态",
            description="获取所有 LSP 服务器的运行状态",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["lsp", "status", "状态"],
        ),
        handler=_get_status,
    )

    registry.register(
        CapabilityDefinition(
            id="lsp.detect_language",
            name="检测文件语言",
            description="根据文件扩展名检测语言",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                },
                "required": ["file_path"],
            },
            tags=["lsp", "detect", "language", "检测"],
        ),
        handler=_get_language_for_file,
    )

    registry.register(
        CapabilityDefinition(
            id="lsp.list_supported",
            name="列出支持的语言",
            description="列出所有支持的语言及其文件扩展名",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={"type": "object", "properties": {}},
            tags=["lsp", "list", "supported", "支持"],
        ),
        handler=_list_supported,
    )

    registry.register(
        CapabilityDefinition(
            id="lsp.diagnostics",
            name="扫描诊断",
            description="扫描文件或工作区收集诊断信息（错误、警告）",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径（指定则只扫描单个文件）"},
                    "workspace_path": {"type": "string", "description": "工作区路径（不指定文件时扫描整个工作区）"},
                },
            },
            tags=["lsp", "diagnostics", "errors", "diagnostic", "诊断"],
        ),
        handler=_scan_diagnostics,
    )