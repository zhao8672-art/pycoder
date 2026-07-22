"""安全头与缓存中间件 — 阶段 3 安全强化

提供：
    1. SecurityHeadersMiddleware: 添加 CSP / X-Frame-Options / X-Content-Type-Options
    2. ETagCacheMiddleware: 自动 ETag + 条件 GET 304 支持
    3. RateLimitMiddleware: 增强版速率限制（按路径分级）
    4. RequestBodyScannerMiddleware: 请求体 shell 注入扫描 (BUG-005)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pycoder.core.security import SHELL_INJECTION_PATTERNS

_logger = logging.getLogger("pycoder.server.middleware.security")

# ── 路径分级限流配置 ─────────────────────────────────────
# 格式: (path_prefix, max_requests, window_seconds, label)
_RATE_LIMIT_TIERS = [
    ("/api/code/exec", 10, 60, "code-exec"),
    ("/api/chat", 30, 60, "chat"),
    ("/api/skills/v2/search", 60, 60, "skills-search"),
    ("/api/skills", 20, 60, "skills"),
    ("/api/agent", 30, 60, "agent"),
    ("/api/v2/evolution", 5, 300, "evolution"),
]

# 跳过请求体扫描的路径（已知安全或自定义逻辑）
_BODY_SCAN_SKIP_PATHS = (
    "/api/health",
    "/api/auth/login",
    "/api/code/exec",  # code exec 自带多层沙箱
)


class RequestBodyScannerMiddleware(BaseHTTPMiddleware):
    """请求体 Shell 注入扫描中间件 — 修复 BUG-005

    扫描 POST/PUT/PATCH 请求体中的 JSON 字符串字段，检测：
        - shell 元字符注入 (`;`, `|`, `&&`, `||`, 反引号, `$(...)` 等)
        - 路径遍历 (../)

    仅对显式标记为命令/路径字段的输入生效（不破坏普通文本消息）。

    策略：
        - 命中注入载荷 → 返回 400 + 详细错误
        - 静默放行：仅当字段名含 "message" / "content" / "description" 等明确为文本字段
    """

    # 敏感字段名（接收 shell 命令或文件路径的字段）
    _SENSITIVE_FIELD_NAMES = frozenset(
        [
            "command",
            "cmd",
            "shell_command",
            "path",
            "file_path",
            "filepath",
            "filename",
            "dir",
            "directory",
            "script",
            "exec",
            "exec_command",
            "commandline",
            "cmdline",
            "shell_cmd",
        ]
    )

    # 文本字段名（不应触发扫描）
    _TEXT_FIELD_NAMES = frozenset(
        [
            "message",
            "content",
            "text",
            "description",
            "prompt",
            "query",
            "q",
            "title",
            "name",
            "comment",
            "body",
        ]
    )

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # 仅扫描 POST/PUT/PATCH
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in _BODY_SCAN_SKIP_PATHS):
            return await call_next(request)

        # 读取 body
        try:
            body_bytes = await request.body()
        except Exception:
            return await call_next(request)

        if not body_bytes:
            return await call_next(request)

        # 解析 JSON
        try:
            body_json = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            return await call_next(request)  # 非 JSON，让 Pydantic 校验

        if not isinstance(body_json, dict):
            return await call_next(request)

        # 扫描敏感字段
        threats: list[dict[str, Any]] = []
        for key, value in _walk_fields(body_json):
            field_lower = key.lower()
            # 跳过文本字段
            if any(t in field_lower for t in self._TEXT_FIELD_NAMES):
                continue
            # 仅扫描疑似命令/路径字段
            is_sensitive = any(s in field_lower for s in self._SENSITIVE_FIELD_NAMES)
            if not is_sensitive:
                continue
            if not isinstance(value, str):
                continue
            # 执行 shell 注入检测
            for pattern in SHELL_INJECTION_PATTERNS:
                match = pattern.search(value)
                if match:
                    threats.append(
                        {
                            "field": key,
                            "pattern": pattern.pattern,
                            "matched": match.group(0),
                        }
                    )
                    break
            else:
                # 路径遍历检测
                if ".." in value and (
                    "/../" in value
                    or value.startswith("../")
                    or value.startswith("..\\")
                ):
                    threats.append(
                        {
                            "field": key,
                            "pattern": "path_traversal",
                            "matched": "..",
                        }
                    )

        if threats:
            _logger.warning(
                "shell_injection_detected: path=%s threats=%d",
                path,
                len(threats),
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": "INJECTION_DETECTED",
                    "message": "Request body contains potential injection payloads",
                    "threats": threats[:5],  # 最多暴露 5 个
                },
            )

        # 重新注入 body 供下游读取
        async def _receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
        return await call_next(request)


def _walk_fields(obj: Any, prefix: str = ""):
    """递归遍历 JSON 对象，产出 (field_path, value) 元组。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            yield from _walk_fields(v, full_key)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            full_key = f"{prefix}[{i}]"
            yield from _walk_fields(item, full_key)
    else:
        yield prefix, obj


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件 — 修复 BUG-006 / BUG-010

    添加以下安全头：
        - Content-Security-Policy: 防止 XSS
        - X-Content-Type-Options: nosniff
        - X-Frame-Options: DENY
        - Referrer-Policy: no-referrer
        - Permissions-Policy: 关闭危险能力
    """

    # API 主要返回 JSON，无需大量内联资源；CSP 使用严格策略
    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' ws: wss: http: https:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    _PERMISSIONS_POLICY = (
        "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
    )

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)

        # 仅对 API 路径添加（避免干扰静态文件）
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/ws/"):
            response.headers["Content-Security-Policy"] = self._CSP
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = self._PERMISSIONS_POLICY

        return response


class ETagCacheMiddleware(BaseHTTPMiddleware):
    """ETag + Cache-Control 中间件 — 修复 BUG-012

    行为：
        1. 对 GET 请求且响应 200 的情况自动生成 ETag（基于 body MD5）
        2. 处理 If-None-Match 条件请求 → 返回 304
        3. 为静态资源类端点添加 Cache-Control 头
    """

    # 默认缓存 TTL（秒）
    _DEFAULT_TTL = 30
    # 长缓存端点（很少变化）
    _LONG_TTL_PATHS = (
        "/api/models",
        "/api/skills",
        "/api/extensions/installed",
        "/api/extensions/recommended",
    )

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # 仅处理 GET 请求
        if request.method != "GET":
            return await call_next(request)

        response = await call_next(request)

        # 仅对成功响应添加 ETag
        if response.status_code != 200:
            return response

        # 跳过流式 / 分块响应
        if response.headers.get("transfer-encoding") == "chunked":
            return response

        # 读取 body 用于计算 ETag
        try:
            body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    body += chunk.encode("utf-8")
                else:
                    body += chunk
        except Exception:
            return response

        # 计算 ETag
        etag = hashlib.md5(body).hexdigest()
        etag_header = f'"{etag}"'

        # 检查 If-None-Match（容错：去引号比较 + 支持 W/ 弱验证）
        if_none_match = request.headers.get("If-None-Match", "")
        if if_none_match:
            # 提取所有 etag 值（去引号、忽略 W/ 弱验证前缀）
            client_tags = [t.strip() for t in if_none_match.split(",")]
            client_tags = [
                t[2:] if t.startswith("W/") else t
                for t in client_tags
            ]
            client_tags = [t.strip('"') for t in client_tags]
            if "*" in client_tags or etag in client_tags:
                # 返回 304 Not Modified
                from fastapi.responses import Response

                return Response(
                    status_code=304,
                    headers={
                        "ETag": etag_header,
                        "X-Cache": "HIT",
                    },
                )

        # 设置 Cache-Control
        path = request.url.path
        if any(path.startswith(p) for p in self._LONG_TTL_PATHS):
            cache_control = f"public, max-age={self._DEFAULT_TTL * 10}"
        else:
            cache_control = f"public, max-age={self._DEFAULT_TTL}"

        # 重新构造响应
        from fastapi.responses import Response

        return Response(
            content=body,
            status_code=response.status_code,
            headers={
                **dict(response.headers),
                "ETag": etag_header,
                "Cache-Control": cache_control,
                "X-Cache": "MISS",
            },
            media_type=response.headers.get("content-type", "application/json"),
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件（增强版）— 修复 BUG-008

    按路径分级限流：
        - /api/code/exec: 10 req/min（重资源）
        - /api/chat: 30 req/min（LLM 调用）
        - /api/agent: 30 req/min
        - /api/skills/v2/search: 60 req/min
        - /api/v2/evolution: 5 req/5min（高成本）

    其他路径：默认 120 req/min（防滥用）

    使用滑动窗口算法（精确但内存占用略高）。
    """

    _DEFAULT_RATE = 120
    _DEFAULT_WINDOW = 60

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        # IP -> (tier_label, [timestamps])
        self._buckets: dict = defaultdict(list)

    def _get_tier(self, path: str) -> tuple[int, int, str]:
        """根据路径返回 (max_requests, window_seconds, tier_label)"""
        for prefix, max_req, window, label in _RATE_LIMIT_TIERS:
            if path.startswith(prefix):
                return max_req, window, label
        return self._DEFAULT_RATE, self._DEFAULT_WINDOW, "default"

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # 跳过健康检查 / 文档 / WebSocket
        path = request.url.path
        if (
            path in ("/api/health", "/docs", "/openapi.json")
            or path.startswith("/ws/")
            or path.startswith("/_")
        ):
            return await call_next(request)

        # 跳过本地回环（Electron/CLI 自身）
        client_ip = request.client.host if request.client else "unknown"
        if client_ip in ("127.0.0.1", "::1", "localhost", "unknown"):
            # 本地请求放宽到 600 req/min（Electron 频繁轮询）
            max_req = 600
            window = 60
            label = "local-trusted"
        else:
            max_req, window, label = self._get_tier(path)

        now = time.time()
        bucket = self._buckets[client_ip]
        # 滑动窗口：清理过期时间戳
        cutoff = now - window
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

        if len(bucket) >= max_req:
            retry_after = int(window - (now - bucket[0])) + 1
            _logger.warning(
                "rate_limit_exceeded: ip=%s tier=%s path=%s count=%d limit=%d retry_after=%ds",
                client_ip,
                label,
                path,
                len(bucket),
                max_req,
                retry_after,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "请求过于频繁，请稍后重试",
                    "tier": label,
                    "limit": max_req,
                    "window_seconds": window,
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + retry_after)),
                },
            )

        bucket.append(now)

        # 添加速率限制响应头
        response = await call_next(request)
        remaining = max(0, max_req - len(bucket))
        response.headers["X-RateLimit-Limit"] = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Tier"] = label
        return response


__all__ = [
    "SecurityHeadersMiddleware",
    "ETagCacheMiddleware",
    "RateLimitMiddleware",
]
