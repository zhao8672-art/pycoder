"""LSP 工具能力注册 — 将 LSP 客户端注册为 PyCoder 能力

提供 6 个 LSP 能力:
    - tools.lsp.completion       代码补全
    - tools.lsp.definition       定义跳转
    - tools.lsp.hover            悬停提示
    - tools.lsp.references       引用查找
    - tools.lsp.document_symbol  文档符号
    - tools.lsp.diagnostics      诊断信息

所有能力均为 READ_ONLY 权限 (只读分析，无副作用)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
)
from pycoder.capabilities.degradation import wrap_handler
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.lsp.client import LSPClient, LSPClientConfig

_CT = CapabilityCategory.EDITOR

# 全局 LSP 客户端单例 (按工作区分)
_clients: dict[str, LSPClient] = {}


async def _get_client(workspace: str = "") -> LSPClient:
    """获取或创建工作区对应的 LSP 客户端"""
    workspace = workspace or str(Path.cwd())
    if workspace not in _clients:
        config = LSPClientConfig(workspace=workspace)
        client = LSPClient(config)
        await client.start()
        try:
            await client.initialize()
        except Exception:
            # 初始化失败时返回未初始化的客户端，调用方处理降级
            pass
        _clients[workspace] = client
    return _clients[workspace]


# ── 处理器实现 ────────────────────────────────────────────


async def _handle_completion(params: dict, context: dict) -> dict:
    """代码补全"""
    client = await _get_client(params.get("workspace", ""))
    if not client.is_initialized:
        return {"success": False, "error": "LSP 服务器未初始化 (可能未安装 pyright)"}
    items = await client.completion(
        params["file_path"],
        int(params["line"]),
        int(params["character"]),
    )
    return {
        "success": True,
        "items": [item.to_dict() for item in items],
        "count": len(items),
    }


async def _handle_definition(params: dict, context: dict) -> dict:
    """定义跳转"""
    client = await _get_client(params.get("workspace", ""))
    if not client.is_initialized:
        return {"success": False, "error": "LSP 服务器未初始化"}
    locations = await client.definition(
        params["file_path"],
        int(params["line"]),
        int(params["character"]),
    )
    return {
        "success": True,
        "locations": [loc.to_dict() for loc in locations],
        "count": len(locations),
    }


async def _handle_hover(params: dict, context: dict) -> dict:
    """悬停提示"""
    client = await _get_client(params.get("workspace", ""))
    if not client.is_initialized:
        return {"success": False, "error": "LSP 服务器未初始化"}
    hover = await client.hover(
        params["file_path"],
        int(params["line"]),
        int(params["character"]),
    )
    if hover is None:
        return {"success": True, "hover": None}
    return {"success": True, "hover": hover.to_dict()}


async def _handle_references(params: dict, context: dict) -> dict:
    """引用查找"""
    client = await _get_client(params.get("workspace", ""))
    if not client.is_initialized:
        return {"success": False, "error": "LSP 服务器未初始化"}
    include_decl = params.get("include_declaration", True)
    locations = await client.references(
        params["file_path"],
        int(params["line"]),
        int(params["character"]),
        include_declaration=include_decl,
    )
    return {
        "success": True,
        "references": [loc.to_dict() for loc in locations],
        "count": len(locations),
    }


async def _handle_document_symbol(params: dict, context: dict) -> dict:
    """文档符号"""
    client = await _get_client(params.get("workspace", ""))
    if not client.is_initialized:
        return {"success": False, "error": "LSP 服务器未初始化"}
    symbols = await client.document_symbol(params["file_path"])
    return {
        "success": True,
        "symbols": [s.to_dict() for s in symbols],
        "count": len(symbols),
    }


async def _handle_diagnostics(params: dict, context: dict) -> dict:
    """诊断信息 (通过 did_open 触发后等待 publishDiagnostics 通知)"""
    client = await _get_client(params.get("workspace", ""))
    if not client.is_initialized:
        return {"success": False, "error": "LSP 服务器未初始化"}
    # did_open 触发服务器推送诊断
    text = params.get("text", "")
    if text:
        await client.did_open(params["file_path"], text)
        # 等待诊断推送 (简化: 短暂等待)
        import asyncio

        await asyncio.sleep(0.5)
    return {
        "success": True,
        "note": "诊断通过 publishDiagnostics 通知异步推送，需订阅事件流",
    }


# ── Schema 定义 ───────────────────────────────────────────

_POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "文件路径"},
        "line": {"type": "integer", "description": "行号 (0-based)"},
        "character": {"type": "integer", "description": "列号 (0-based)"},
        "workspace": {"type": "string", "default": "", "description": "工作区路径 (默认当前目录)"},
    },
    "required": ["file_path", "line", "character"],
}


def register(registry: Any) -> None:
    """向能力总线注册 LSP 工具能力"""

    def _reg(
        cap_id: str, name: str, desc: str, schema: dict, handler: Any
    ) -> None:
        registry.register(
            CapabilityDefinition(
                id=cap_id,
                name=name,
                description=desc,
                permission=TOOL_PERMISSIONS[cap_id],
                category=_CT,
                execution=ExecutionMode.ASYNC,
                side_effects=[SideEffect.PROCESS],
                schema=schema,
                tags=["lsp", "editor", "language"],
            ),
            handler=wrap_handler(handler),
        )

    _reg(
        "tools.lsp.completion",
        "代码补全",
        "获取指定位置的代码补全建议 (基于 LSP 协议，需 pyright 已安装)",
        _POSITION_SCHEMA,
        _handle_completion,
    )
    _reg(
        "tools.lsp.definition",
        "定义跳转",
        "获取符号定义位置 (跳转到定义)",
        _POSITION_SCHEMA,
        _handle_definition,
    )
    _reg(
        "tools.lsp.hover",
        "悬停提示",
        "获取悬停位置的文档/类型提示",
        _POSITION_SCHEMA,
        _handle_hover,
    )
    _reg(
        "tools.lsp.references",
        "引用查找",
        "查找符号的所有引用位置",
        {
            "type": "object",
            "properties": {
                **_POSITION_SCHEMA["properties"],
                "include_declaration": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否包含声明处",
                },
            },
            "required": ["file_path", "line", "character"],
        },
        _handle_references,
    )
    _reg(
        "tools.lsp.document_symbol",
        "文档符号",
        "获取文件中所有符号 (类/函数/变量) 的结构树",
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "workspace": {"type": "string", "default": ""},
            },
            "required": ["file_path"],
        },
        _handle_document_symbol,
    )
    _reg(
        "tools.lsp.diagnostics",
        "诊断信息",
        "获取文件的诊断信息 (错误/警告)，需先 did_open 文件",
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "text": {"type": "string", "default": "", "description": "文件内容 (触发诊断)"},
                "workspace": {"type": "string", "default": ""},
            },
            "required": ["file_path"],
        },
        _handle_diagnostics,
    )
