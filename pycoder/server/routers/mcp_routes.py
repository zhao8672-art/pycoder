"""
MCP 工具生态 REST API
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/mcp/marketplace")
async def mcp_marketplace():
    """列出 MCP 模板市场"""
    from pycoder.server.mcp_store import MCP_MARKETPLACE
    return {
        "marketplace": [
            {"id": k, **v}
            for k, v in MCP_MARKETPLACE.items()
        ]
    }


@router.post("/api/mcp/servers")
async def mcp_save_server(req: dict):
    """保存 MCP 服务器配置"""
    from pycoder.server.mcp_store import get_mcp_store
    store = get_mcp_store()
    ok = store.save_server(
        name=req.get("name", ""),
        server_type=req.get("type", "stdio"),
        command=req.get("command", ""),
        url=req.get("url", ""),
        env_vars=req.get("env_vars", {}),
        auto_connect=req.get("auto_connect", False),
    )
    return {"success": ok}


@router.get("/api/mcp/servers")
async def mcp_list_servers():
    """列出已配置的 MCP 服务器"""
    from pycoder.server.mcp_store import get_mcp_store
    store = get_mcp_store()
    return {"servers": store.list_servers()}


@router.delete("/api/mcp/servers/{name}")
async def mcp_delete_server(name: str):
    """删除 MCP 服务器配置"""
    from pycoder.server.mcp_store import get_mcp_store
    store = get_mcp_store()
    return {"success": store.delete_server(name)}


@router.get("/api/mcp/audit")
async def mcp_audit_log(limit: int = 50):
    """获取 MCP 调用审计日志"""
    from pycoder.server.mcp_store import get_mcp_store
    store = get_mcp_store()
    return {"audit": store.get_audit_log(limit)}
