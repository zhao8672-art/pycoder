"""浏览器增强模块 — MCP 浏览器工具优化"""
from __future__ import annotations

from typing import Any

from pycoder.browser.browser_pool import BrowserPool, BrowserInstance
from pycoder.browser.proxy_manager import ProxyCacheManager
from pycoder.browser.access_control import BrowserAccessControl, BrowserAccessPolicy

__all__ = [
    "BrowserPool", "BrowserInstance", "ProxyCacheManager",
    "BrowserAccessControl", "BrowserAccessPolicy",
    "register_capabilities",
]


def register_capabilities(registry: Any) -> None:
    """向能力总线注册浏览器增强能力"""
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    acl = BrowserAccessControl()
    cache = ProxyCacheManager()

    def _check_url_access(params: dict, ctx: dict) -> dict:
        ok, reason = acl.check_url(params["url"])
        return {"allowed": ok, "reason": reason}

    def _check_rate_limit(params: dict, ctx: dict) -> dict:
        from urllib.parse import urlparse
        parsed = urlparse(params["url"])
        domain = parsed.netloc or parsed.hostname or ""
        allowed = acl.check_rate_limit(domain)
        return {"allowed": allowed}

    def _set_access_policy(params: dict, ctx: dict) -> dict:
        from pycoder.browser.access_control import BrowserAccessPolicy
        acl._policy = BrowserAccessPolicy(
            allowed_domains=params.get("allowed_domains", acl._policy.allowed_domains),
            blocked_domains=params.get("blocked_domains", acl._policy.blocked_domains),
            max_requests_per_minute=params.get("max_requests_per_minute", acl._policy.max_requests_per_minute),
            block_private_ips=params.get("block_private_ips", acl._policy.block_private_ips),
        )
        return {"success": True}

    def _get_cache(params: dict, ctx: dict) -> dict:
        cached = cache.get(params["url"]) if hasattr(cache, 'get') else None
        return {"cached": cached is not None, "content": cached}

    def _set_cache(params: dict, ctx: dict) -> dict:
        if hasattr(cache, 'set'):
            cache.set(params["url"], params["content"])
        return {"success": True}

    registry.register(
        CapabilityDefinition(
            id="browser.check_url",
            name="检查 URL 访问权限",
            description="检查指定 URL 是否允许访问，返回权限检查结果和拒绝原因",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要检查的 URL"},
                },
                "required": ["url"],
            },
            tags=["browser", "url", "access", "安全检查"],
        ),
        handler=_check_url_access,
    )

    registry.register(
        CapabilityDefinition(
            id="browser.check_rate_limit",
            name="检查速率限制",
            description="检查指定域名的请求速率是否超过限制",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要检查的 URL"},
                },
                "required": ["url"],
            },
            tags=["browser", "rate_limit", "限流"],
        ),
        handler=_check_rate_limit,
    )

    registry.register(
        CapabilityDefinition(
            id="browser.set_policy",
            name="设置访问策略",
            description="配置浏览器访问策略（白名单、黑名单、速率限制等）",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.STATE_CHANGE],
            schema={
                "type": "object",
                "properties": {
                    "allowed_domains": {"type": "array", "items": {"type": "string"}},
                    "blocked_domains": {"type": "array", "items": {"type": "string"}},
                    "max_requests_per_minute": {"type": "integer"},
                    "block_private_ips": {"type": "boolean"},
                },
            },
            tags=["browser", "policy", "配置"],
        ),
        handler=_set_access_policy,
    )

    registry.register(
        CapabilityDefinition(
            id="browser.cache.get",
            name="获取缓存内容",
            description="从代理缓存中获取已缓存的 URL 内容",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[],
            schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "缓存键 URL"},
                },
                "required": ["url"],
            },
            tags=["browser", "cache", "缓存"],
        ),
        handler=_get_cache,
    )

    registry.register(
        CapabilityDefinition(
            id="browser.cache.set",
            name="设置缓存内容",
            description="将内容写入代理缓存",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.WORKSPACE_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.STATE_CHANGE],
            schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "缓存键 URL"},
                    "content": {"type": "string", "description": "缓存内容"},
                },
                "required": ["url", "content"],
            },
            tags=["browser", "cache", "缓存"],
        ),
        handler=_set_cache,
    )