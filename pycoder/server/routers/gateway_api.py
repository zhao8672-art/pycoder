"""
多平台消息网关 API — 平台管理、消息发送、会话管理、WebSocket 实时推送
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from pycoder.gateway import MessageGateway, get_gateway
from pycoder.gateway.adapters import get_all_adapters

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 路由定义
# ═══════════════════════════════════════════════

router = APIRouter(prefix="/api/gateway", tags=["gateway"])
ws_router = APIRouter(tags=["gateway"])

# ═══════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════


class PlatformInfo(BaseModel):
    """平台信息"""

    name: str = Field(..., description="平台名称")
    status: str = Field(default="unknown", description="运行状态: running / stopped / unknown")
    adapter_loaded: bool = Field(default=False, description="适配器是否已加载")


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    platform: str = Field(..., description="目标平台名称", min_length=1)
    user_id: str = Field(..., description="目标用户 ID", min_length=1)
    content: str = Field(..., description="消息内容", min_length=1)


class SendMessageResponse(BaseModel):
    """发送消息响应"""

    success: bool = Field(..., description="是否发送成功")
    platform: str = Field(default="", description="目标平台")
    target: str = Field(default="", description="目标用户")
    message: str = Field(default="", description="结果描述")


class SessionInfo(BaseModel):
    """会话信息"""

    session_id: str = Field(..., description="会话唯一 ID")
    platform: str = Field(..., description="平台名称")
    user_id: str = Field(..., description="用户 ID")
    created_at: float = Field(default=0, description="创建时间戳")
    last_activity: float = Field(default=0, description="最后活跃时间")
    message_count: int = Field(default=0, description="消息数量")
    is_active: bool = Field(default=False, description="是否为当前活跃会话")
    context_keys: list[str] = Field(default_factory=list, description="上下文键列表")


class SessionListResponse(BaseModel):
    """会话列表响应"""

    sessions: list[SessionInfo] = Field(default_factory=list, description="会话列表")
    total: int = Field(default=0, description="会话总数")
    active_session_id: str | None = Field(default=None, description="当前活跃会话 ID")


class SessionDetailResponse(BaseModel):
    """会话详情响应"""

    session_id: str = Field(..., description="会话唯一 ID")
    platform: str = Field(..., description="平台名称")
    user_id: str = Field(..., description="用户 ID")
    created_at: float = Field(default=0, description="创建时间戳")
    last_activity: float = Field(default=0, description="最后活跃时间")
    message_count: int = Field(default=0, description="消息数量")
    is_active: bool = Field(default=False, description="是否为当前活跃会话")
    context_keys: list[str] = Field(default_factory=list, description="上下文键列表")
    messages: list[dict[str, Any]] = Field(default_factory=list, description="最近消息历史")


class SwitchSessionResponse(BaseModel):
    """切换会话响应"""

    success: bool = Field(default=True, description="是否切换成功")
    session_id: str = Field(..., description="切换后的会话 ID")
    platform: str = Field(default="", description="平台名称")
    user_id: str = Field(default="", description="用户 ID")


# ═══════════════════════════════════════════════
# 网关懒初始化辅助
# ═══════════════════════════════════════════════

_gateway: MessageGateway | None = None
_initialized = False
_ws_clients: dict[str, WebSocket] = {}  # WebSocket 客户端注册表


def _get_gateway() -> MessageGateway:
    """获取或初始化网关实例（懒加载）"""
    global _gateway, _initialized
    if _gateway is None:
        try:
            _gateway = get_gateway()
        except Exception as e:
            logger.warning("获取网关实例失败，创建新实例: %s", e)
            _gateway = MessageGateway()
    return _gateway


async def _ensure_gateway_started() -> MessageGateway:
    """确保网关已启动（注册适配器并启动）"""
    global _initialized
    gw = _get_gateway()
    if not _initialized:
        # 注册所有可用适配器
        try:
            adapters = get_all_adapters()
            for adapter in adapters:
                if adapter.platform not in gw.available_platforms:
                    gw.register_adapter(adapter)
        except Exception as e:
            logger.warning("注册适配器时出错: %s", e)

        # 启动网关
        if not gw.is_running:
            try:
                await gw.start()
            except Exception as e:
                logger.warning("启动网关时出错: %s", e)
        _initialized = True
    return gw


# ═══════════════════════════════════════════════
# REST 端点
# ═══════════════════════════════════════════════


@router.get("/platforms", response_model=list[PlatformInfo])
async def list_platforms():
    """列出所有可用平台及其状态"""
    gw = _get_gateway()
    platforms: list[PlatformInfo] = []

    # 已注册的平台
    for name in gw.available_platforms:
        adapter = gw.get_adapter(name)
        platforms.append(
            PlatformInfo(
                name=name,
                status="running" if (adapter and adapter.is_running) else "stopped",
                adapter_loaded=adapter is not None,
            )
        )

    # 尝试加载所有适配器，展示完整列表
    try:
        all_adapters = get_all_adapters()
        registered_names = set(gw.available_platforms)
        for adapter in all_adapters:
            if adapter.platform not in registered_names:
                platforms.append(
                    PlatformInfo(
                        name=adapter.platform,
                        status="not_registered",
                        adapter_loaded=True,
                    )
                )
    except Exception as e:
        logger.warning("获取适配器列表时出错: %s", e)

    return platforms


@router.post("/send", response_model=SendMessageResponse)
async def send_message(req: SendMessageRequest):
    """向指定平台的目标发送消息"""
    gw = await _ensure_gateway_started()

    if req.platform not in gw.available_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"平台 '{req.platform}' 不可用。可用平台: {gw.available_platforms}",
        )

    success = await gw.send_message(req.platform, req.user_id, req.content)
    return SendMessageResponse(
        success=success,
        platform=req.platform,
        target=req.user_id,
        message="消息已发送" if success else "消息发送失败",
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions():
    """列出所有活跃会话"""
    gw = _get_gateway()
    sm = gw._session_manager

    if sm is None:
        return SessionListResponse(sessions=[], total=0, active_session_id=None)

    sessions: list[SessionInfo] = []
    for (platform, user_id), session in sm._sessions.items():
        sessions.append(
            SessionInfo(
                session_id=session.session_id,
                platform=platform,
                user_id=user_id,
                created_at=session.created_at,
                last_activity=session.last_activity,
                message_count=len(session.messages),
                is_active=(session.session_id == sm._active_session_id),
                context_keys=list(session.context.keys()),
            )
        )

    return SessionListResponse(
        sessions=sessions,
        total=len(sessions),
        active_session_id=sm._active_session_id,
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str):
    """获取指定会话的详细信息"""
    gw = _get_gateway()
    sm = gw._session_manager

    if sm is None:
        raise HTTPException(status_code=404, detail="会话管理器尚未初始化")

    # 按 session_id 查找会话
    found_session = None
    found_key = None
    for key, session in sm._sessions.items():
        if session.session_id == session_id:
            found_session = session
            found_key = key
            break

    if found_session is None:
        raise HTTPException(status_code=404, detail=f"会话 '{session_id}' 不存在")

    return SessionDetailResponse(
        session_id=found_session.session_id,
        platform=found_key[0] if found_key else "",
        user_id=found_key[1] if found_key else "",
        created_at=found_session.created_at,
        last_activity=found_session.last_activity,
        message_count=len(found_session.messages),
        is_active=(found_session.session_id == sm._active_session_id),
        context_keys=list(found_session.context.keys()),
        messages=found_session.get_recent_messages(50),
    )


@router.post("/sessions/{session_id}/switch", response_model=SwitchSessionResponse)
async def switch_session(session_id: str):
    """切换当前活跃会话"""
    gw = _get_gateway()
    sm = gw._session_manager

    if sm is None:
        raise HTTPException(status_code=404, detail="会话管理器尚未初始化")

    # 按 session_id 查找会话
    found_session = None
    found_key = None
    for key, session in sm._sessions.items():
        if session.session_id == session_id:
            found_session = session
            found_key = key
            break

    if found_session is None:
        raise HTTPException(status_code=404, detail=f"会话 '{session_id}' 不存在")

    sm.set_active_session(session_id)
    return SwitchSessionResponse(
        success=True,
        session_id=session_id,
        platform=found_key[0] if found_key else "",
        user_id=found_key[1] if found_key else "",
    )


# ═══════════════════════════════════════════════
# WebSocket 端点
# ═══════════════════════════════════════════════


@ws_router.websocket("/ws/gateway")
async def gateway_websocket(ws: WebSocket):
    """WebSocket 端点 — 实时网关消息推送

    客户端连接后可接收：
    - 平台状态变更通知
    - 新消息到达通知
    - 会话更新通知
    """
    from pycoder.server.app import verify_ws_auth

    if not await verify_ws_auth(ws):
        return

    client_id = f"gw_{id(ws)}_{int(time.time())}"
    await ws.accept()
    _ws_clients[client_id] = ws
    logger.info("网关 WebSocket 客户端已连接: %s", client_id)

    try:
        # 发送欢迎消息
        gw = _get_gateway()
        await ws.send_json({
            "type": "connected",
            "client_id": client_id,
            "platforms": gw.available_platforms,
            "gateway_running": gw.is_running,
            "timestamp": time.time(),
        })

        # 保持连接，接收客户端消息
        while True:
            try:
                data = await ws.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "ping":
                    await ws.send_json({"type": "pong", "timestamp": time.time()})

                elif msg_type == "get_platforms":
                    gw = _get_gateway()
                    platforms_info = []
                    for name in gw.available_platforms:
                        adapter = gw.get_adapter(name)
                        platforms_info.append({
                            "name": name,
                            "status": "running" if (adapter and adapter.is_running) else "stopped",
                        })
                    await ws.send_json({
                        "type": "platforms",
                        "platforms": platforms_info,
                        "timestamp": time.time(),
                    })

                elif msg_type == "get_sessions":
                    gw = _get_gateway()
                    sm = gw._session_manager
                    sessions = []
                    if sm is not None:
                        for (platform, user_id), s in sm._sessions.items():
                            sessions.append({
                                "session_id": s.session_id,
                                "platform": platform,
                                "user_id": user_id,
                                "message_count": len(s.messages),
                                "is_active": s.session_id == sm._active_session_id,
                            })
                    await ws.send_json({
                        "type": "sessions",
                        "sessions": sessions,
                        "total": len(sessions),
                        "timestamp": time.time(),
                    })

                else:
                    await ws.send_json({
                        "type": "unknown",
                        "message": f"未知消息类型: {msg_type}",
                    })

            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as e:
                logger.warning("网关 WebSocket 消息处理出错: %s", e)
                try:
                    await ws.send_json({"type": "error", "message": str(e)})
                except Exception:
                    break

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _ws_clients.pop(client_id, None)
        logger.info("网关 WebSocket 客户端已断开: %s", client_id)


# ═══════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════


async def broadcast_gateway_event(event_type: str, data: dict[str, Any]) -> None:
    """向所有已连接的 WebSocket 客户端广播事件

    Args:
        event_type: 事件类型
        data: 事件数据
    """
    disconnected: list[str] = []
    for client_id, ws in _ws_clients.items():
        try:
            await ws.send_json({
                "type": event_type,
                "data": data,
                "timestamp": time.time(),
            })
        except Exception:
            disconnected.append(client_id)

    for cid in disconnected:
        _ws_clients.pop(cid, None)


__all__ = [
    "router",
    "ws_router",
    "broadcast_gateway_event",
    "PlatformInfo",
    "SendMessageRequest",
    "SendMessageResponse",
    "SessionInfo",
    "SessionListResponse",
    "SessionDetailResponse",
    "SwitchSessionResponse",
]