"""
OAuth2 认证 API 路由 — 第三方登录端点

端点:
  GET  /api/auth/oauth2/providers              — 列出可用 OAuth2 提供商
  GET  /api/auth/oauth2/login/{provider}       — 发起 OAuth2 登录
  GET  /api/auth/oauth2/callback/{provider}    — OAuth2 回调处理
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from pycoder.server.auth.oauth2 import get_oauth2_manager

router = APIRouter(prefix="/api/auth/oauth2", tags=["auth-oauth2"])


@router.get("/providers")
async def list_providers():
    """列出可用的 OAuth2 提供商"""
    manager = get_oauth2_manager()
    return {"providers": manager.list_providers()}


@router.get("/login/{provider}")
async def oauth2_login(provider: str):
    """发起 OAuth2 登录 — 重定向到提供商授权页"""
    manager = get_oauth2_manager()
    url = manager.generate_authorize_url(provider)
    if not url:
        raise HTTPException(
            status_code=404,
            detail=f"OAuth2 提供商未配置: {provider}",
        )
    return RedirectResponse(url=url)


@router.get("/callback/{provider}")
async def oauth2_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
):
    """OAuth2 回调处理 — 交换 token 并返回 JWT"""
    manager = get_oauth2_manager()
    result = await manager.handle_callback(provider, code, state)

    if "error" in result:
        raise HTTPException(
            status_code=400,
            detail=result.get("message", result["error"]),
        )

    return result