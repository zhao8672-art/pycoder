"""
MCP Tool 注册表 — 向后兼容 Shim

⚠️ 此模块已弃用。所有功能已迁移到 pycoder/capabilities/tools/
保留此文件仅为向后兼容，通过 V2 引擎委托实现所有功能。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

from pycoder.server.log import log

warnings.warn(
    "mcp_tools 已弃用，所有工具注册已迁移到 capabilities/tools/",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass
class MCPToolDef:
    """单个 MCP Tool 定义"""

    name: str
    description: str
    input_schema: dict
    handler: callable = None


@dataclass
class MCPCallResult:
    """MCP 调用结果"""

    success: bool
    output: Any = None
    error: str = ""
    tool: str = ""


_builtin_tools: dict[str, MCPToolDef] = {}


def list_builtin_tools() -> list[dict]:
    """委托 V2 引擎列出所有内置 MCP Tool"""
    from pycoder.server.app import get_v2_engine

    v2 = get_v2_engine()
    if not v2:
        return []
    tools = []
    for cap in v2.registry.list_all():
        if cap.id.startswith("tools.") or cap.id.startswith("v1."):
            tools.append(
                {
                    "name": cap.id.replace("tools.", "").replace("v1.", ""),
                    "description": cap.description,
                    "input_schema": cap.schema or {"type": "object", "properties": {}},
                    "source": "v2_bus",
                }
            )
    return tools


async def call_builtin_tool(name: str, args: dict) -> MCPCallResult:
    """通过 V2 引擎调用内置工具"""
    from pycoder.server.app import get_v2_engine

    v2 = get_v2_engine()
    if not v2:
        return MCPCallResult(success=False, error="V2 引擎未初始化", tool=name)
    candidate_ids = [f"tools.{name}", f"v1.{name}", name]
    for cid in candidate_ids:
        try:
            result = v2.registry.call(cid, args)
            if result and getattr(result, "success", False):
                return MCPCallResult(
                    success=True,
                    output=getattr(result, "data", result),
                    tool=name,
                )
        except Exception:
            continue
    return MCPCallResult(success=False, error=f"工具 {name} 未注册", tool=name)


class MCPClientManager:
    """管理外部 MCP Server 连接"""

    def __init__(self):
        self._servers: dict[str, Any] = {}

    @property
    def connected_servers(self) -> list[str]:
        return list(self._servers.keys())

    async def connect_stdio(self, name: str, command: str, *args: str) -> bool:
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            params = StdioServerParameters(command=command, args=list(args))
            read, write = await stdio_client(params)
            session = await ClientSession(read, write).__aenter__()
            await session.initialize()
            self._servers[name] = {"session": session, "read": read, "write": write}
            return True
        except Exception as e:
            log.warning("mcp_connect_stdio_failed", name=name, error=str(e))
            return False

    async def connect_sse(self, name: str, url: str) -> bool:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client

            read, write = await sse_client(url)
            session = await ClientSession(read, write).__aenter__()
            await session.initialize()
            self._servers[name] = {"session": session, "read": read, "write": write}
            return True
        except Exception as e:
            log.warning("mcp_connect_sse_failed", name=name, error=str(e))
            return False

    async def disconnect(self, name: str) -> bool:
        server = self._servers.pop(name, None)
        if server:
            try:
                await server["session"].__aexit__(None, None, None)
            except Exception:
                pass
            return True
        return False

    async def list_remote_tools(self, server_name: str) -> list[dict]:
        server = self._servers.get(server_name)
        if not server:
            return []
        try:
            tools = await server["session"].list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema or {},
                    "server": server_name,
                }
                for t in tools.tools
            ]
        except Exception as e:
            log.warning("mcp_list_remote_failed", server=server_name, error=str(e))
            return []

    async def call_remote_tool(self, server_name: str, tool_name: str, args: dict) -> MCPCallResult:
        server = self._servers.get(server_name)
        if not server:
            return MCPCallResult(
                success=False, error=f"Server {server_name} 未连接", tool=tool_name
            )
        try:
            result = await server["session"].call_tool(tool_name, args)
            return MCPCallResult(success=True, output=result.content, tool=tool_name)
        except Exception as e:
            return MCPCallResult(success=False, error=str(e), tool=tool_name)


_mcp_client_manager: MCPClientManager | None = None


def get_mcp_client_manager() -> MCPClientManager:
    """获取全局 MCP 客户端管理器"""
    global _mcp_client_manager
    if _mcp_client_manager is None:
        _mcp_client_manager = MCPClientManager()
    return _mcp_client_manager
