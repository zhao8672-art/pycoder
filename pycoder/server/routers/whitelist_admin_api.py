"""工具白名单管理 API — 允许运行时查看/调整白名单配置

提供最高权限管理能力，避免 LLM 因白名单配置错误而无法调用工具。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/whitelist", tags=["admin-whitelist"])


# ── 鉴权依赖（复用全局 X-API-Key） ──
#
# 直接复用 pycoder.server.app 中的中间件逻辑：中间件已对所有
# /api/admin/* 路径强制 X-API-Key 验证（除非 PYCODER_API_KEY=disabled）。
# 此处无需额外鉴权 — 路由一旦被访问即代表鉴权已通过。


# ── 响应模型 ──


class WhitelistStatus(BaseModel):
    """白名单当前状态"""
    mode: str = Field(..., description="allow_all / deny_all / allowlist")
    allowed_count: int
    denied_count: int
    audit_total: int
    audit_allowed: int
    audit_denied: int
    recent_denials: list[dict] = Field(default_factory=list)


class WhitelistModeUpdate(BaseModel):
    """修改白名单模式"""
    mode: str = Field(..., description="allow_all / deny_all / allowlist")


# ── 端点 ──


@router.get("/status", response_model=WhitelistStatus)
async def get_whitelist_status() -> WhitelistStatus:
    """查看白名单当前状态（最高权限可见）"""
    from pycoder.safety.tool_whitelist import get_tool_whitelist

    wl = get_tool_whitelist()
    stats = wl.get_stats()
    recent = wl.get_audit_log(last_n=10)
    return WhitelistStatus(
        mode=stats["mode"],
        allowed_count=stats["allowed_tools_count"],
        denied_count=stats["denied_tools_count"],
        audit_total=stats["audit_total"],
        audit_allowed=stats["audit_allowed"],
        audit_denied=stats["audit_denied"],
        recent_denials=[e for e in recent if not e.get("allowed")],
    )


@router.post("/mode")
async def set_whitelist_mode(req: WhitelistModeUpdate) -> dict:
    """运行时切换白名单模式（最高权限操作）

    推荐设置为 allow_all 以彻底解决 LLM 工具调用被白名单拒绝的问题。
    """
    from pycoder.safety.tool_whitelist import WhitelistMode, get_tool_whitelist

    try:
        mode = WhitelistMode(req.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 mode: {req.mode}，允许: allow_all / deny_all / allowlist",
        )

    wl = get_tool_whitelist()
    wl.set_mode(mode)
    logger.warning(
        "whitelist_mode_changed_by_api new_mode=%s (AI highest authority operation)",
        mode.value,
    )
    return {
        "success": True,
        "mode": mode.value,
        "message": f"白名单模式已切换为 {mode.value}",
    }


@router.post("/set-allow-all")
async def force_allow_all() -> dict:
    """一键将白名单设为 allow_all（最高权限模式）"""
    from pycoder.safety.tool_whitelist import WhitelistMode, get_tool_whitelist

    wl = get_tool_whitelist()
    wl.set_mode(WhitelistMode.ALLOW_ALL)
    logger.warning("whitelist_force_allow_all (highest authority enabled)")
    return {
        "success": True,
        "mode": "allow_all",
        "message": "白名单已设为 allow_all（最高权限），所有工具调用将被放行",
    }


@router.post("/reload")
async def reload_whitelist_config() -> dict:
    """重新加载 config/tool_whitelist.yaml 配置"""
    from pycoder.safety.tool_whitelist import (
        WhitelistMode,
        get_tool_whitelist,
        reset_tool_whitelist,
    )

    reset_tool_whitelist()  # 重置单例
    wl = get_tool_whitelist()  # 重新加载
    return {
        "success": True,
        "mode": wl.config.mode.value,
        "allowed_count": len(wl.config.allowed_tools),
        "denied_count": len(wl.config.denied_tools),
    }


@router.get("/audit-log")
async def get_audit_log(last_n: int = 50) -> dict:
    """查看白名单审计日志（最近的拒绝记录）"""
    from pycoder.safety.tool_whitelist import get_tool_whitelist

    wl = get_tool_whitelist()
    log = wl.get_audit_log(last_n=last_n)
    return {
        "total": len(log),
        "entries": log,
    }
