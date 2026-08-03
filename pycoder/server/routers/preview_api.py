"""F7 实时预览 API — dev-server 探测 / 静态 HTML / 反向代理 / reload 推送

端点:
    GET  /api/preview/detect  — 探测工作区 dev-server（端口/框架/运行状态）
    POST /api/preview/start   — 启动文件监听（body: {"path": 可选}）
    POST /api/preview/stop    — 停止文件监听
    GET  /api/preview/status  — 监听状态
    GET  /api/preview/static  — 静态 HTML 模式：输出工作区文件内容（供 iframe/srcDoc）
    GET  /api/preview/proxy   — 反向代理 dev-server，规避跨域（?path=/&port=5173）
    WS   /ws/preview          — 文件变更 reload 事件推送

安全:
    - 静态文件读取复用 files 路由的 _safe_path，禁止路径穿越
    - 代理目标强制 127.0.0.1 + 端口白名单区间，避免 SSRF 外联
    - WebSocket 走 verify_ws_auth 统一鉴权
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from pycoder.server.routers.files import _safe_path, get_workspace_root
from pycoder.server.services.preview_manager import (
    detect_dev_server,
    get_preview_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/preview", tags=["preview"])
ws_router = APIRouter(tags=["websocket"])

# 代理仅允许回环地址 + 常见 dev-server 端口区间，防止 SSRF
_PROXY_HOST = "127.0.0.1"
_PROXY_PORT_MIN = 1024
_PROXY_PORT_MAX = 65535
_PROXY_TIMEOUT = 15.0

# 代理响应中需要剔除的 hop-by-hop / 长度类头（由 httpx/starlette 重新处理）
_STRIP_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "content-encoding",
    "content-length",
    "te",
    "trailer",
    "upgrade",
}


class PreviewStartRequest(BaseModel):
    """启动监听请求体"""

    path: str | None = Field(default=None, description="监听目录（默认工作区根）")


def _resolve_watch_dir(path: str | None) -> Path:
    """解析监听目录：默认工作区根；相对路径按工作区内解析并校验"""
    if not path:
        return Path(get_workspace_root())
    return _safe_path(path)


@router.get("/detect")
async def detect() -> dict:
    """探测工作区 dev-server 与静态 HTML 入口"""
    workspace = Path(get_workspace_root())
    info = await asyncio.to_thread(detect_dev_server, workspace)
    return info.to_dict()


@router.post("/start")
async def start_watch(req: PreviewStartRequest | None = None) -> dict:
    """启动文件变更监听（变更防抖后通过 /ws/preview 推送 reload）"""
    manager = get_preview_manager()
    watch_dir = _resolve_watch_dir(req.path if req else None)
    result = await asyncio.to_thread(manager.start_watcher, watch_dir)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "启动监听失败"))
    return {**result, **manager.status()}


@router.post("/stop")
async def stop_watch() -> dict:
    """停止文件变更监听并清理线程"""
    manager = get_preview_manager()
    result = await asyncio.to_thread(manager.stop_watcher)
    return {**result, **manager.status()}


@router.get("/status")
async def preview_status() -> dict:
    """预览监听状态"""
    return get_preview_manager().status()


@router.get("/static")
async def static_preview(path: str = Query(..., description="工作区内文件路径")) -> Response:
    """静态 HTML 模式：读取工作区文件并以正确 Content-Type 返回

    前端 iframe 可直接加载（同源 + X-API-Key 场景外建议用 srcDoc）。
    """
    target = _safe_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    try:
        content = target.read_bytes()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}") from e
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return Response(content=content, media_type=media_type)


def _create_async_client(*, timeout: float = _PROXY_TIMEOUT) -> httpx.AsyncClient:
    """创建代理用 httpx 客户端（独立为工厂便于测试替换）"""
    return httpx.AsyncClient(follow_redirects=True, timeout=timeout)


@router.get("/proxy")
async def proxy(
    path: str = Query(default="/", description="dev-server 上的请求路径"),
    port: int = Query(..., description="dev-server 端口"),
) -> Response:
    """反向代理本机 dev-server 内容（仅 GET，规避前端跨域）"""
    if not (_PROXY_PORT_MIN <= port <= _PROXY_PORT_MAX):
        raise HTTPException(status_code=400, detail=f"端口不合法: {port}")
    if not path.startswith("/"):
        path = "/" + path
    target = f"http://{_PROXY_HOST}:{port}{path}"

    client = _create_async_client()
    try:
        resp = await client.get(target)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"dev-server 不可达: {e}") from e

    headers = {
        name: value for name, value in resp.headers.items() if name.lower() not in _STRIP_HEADERS
    }
    media_type = resp.headers.get("content-type")
    content = resp.content
    status_code = resp.status_code
    await client.aclose()
    return Response(content=content, status_code=status_code, headers=headers, media_type=media_type)


@ws_router.websocket("/ws/preview")
async def preview_ws(ws: WebSocket) -> None:
    """推送文件变更 reload 事件

    协议:
        - 服务端 → 客户端: {"type": "reload", "changed": [...], "count": n, "ts": ...}
        - 客户端 → 服务端: "ping" → 回 {"type": "pong"}
    """
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return
    await ws.accept()

    manager = get_preview_manager()
    queue = manager.subscribe()
    try:
        while True:
            # 同时等待 reload 事件与客户端消息（用于检测断开/心跳）
            get_task = asyncio.ensure_future(queue.get())
            recv_task = asyncio.ensure_future(ws.receive_text())
            done, pending = await asyncio.wait(
                {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

            if get_task in done and not get_task.cancelled():
                exc = get_task.exception()
                if exc is None:
                    await ws.send_json(get_task.result())

            if recv_task in done and not recv_task.cancelled():
                exc = recv_task.exception()
                if exc is not None:
                    break  # 客户端断开
                text = recv_task.result()
                if text == "ping":
                    await ws.send_json({"type": "pong"})
                elif text == "stop":
                    # 客户端主动结束
                    break
    except WebSocketDisconnect:
        pass
    except RuntimeError as e:
        logger.debug("preview_ws_closed: %s", e)
    finally:
        manager.unsubscribe(queue)
