"""错误处理中间件 — 阶段 2 架构升级

将所有 PyCoderError 及其子类统一转换为 JSON 响应，避免泄露内部堆栈。
同时捕获未预期异常，记录 ERROR 日志并返回 500。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pycoder.core.errors import PyCoderError

_logger = logging.getLogger("pycoder.server.middleware.error")


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """统一错误处理中间件

    行为：
        1. 捕获所有 PyCoderError 及其子类 → 返回对应 status_code + JSON
        2. 捕获未预期的 Exception → 记录 ERROR 日志 + 返回 500
        3. 在响应头添加 X-Request-ID 便于追踪
        4. 记录访问日志（method, path, status, duration_ms）
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # 生成或复用 request_id
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except PyCoderError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            _logger.warning(
                "pycoder_error: code=%s status=%d duration=%.1fms path=%s msg=%s",
                e.error_code,
                e.status_code,
                duration_ms,
                request.url.path,
                e.message,
            )
            return JSONResponse(
                status_code=e.status_code,
                content=e.to_dict(),
                headers={"X-Request-ID": request_id},
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            _logger.error(
                "unhandled_exception: path=%s method=%s duration=%.1fms err=%s",
                request.url.path,
                request.method,
                duration_ms,
                repr(e),
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )

        duration_ms = (time.perf_counter() - start) * 1000
        # 添加 request_id 头
        response.headers["X-Request-ID"] = request_id
        # 访问日志（仅非健康检查路径，避免日志爆炸）
        if not request.url.path.startswith("/api/health"):
            log_level = logging.WARNING if response.status_code >= 500 else logging.INFO
            _logger.log(
                log_level,
                "request: %s %s status=%d duration=%.1fms request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                request_id,
            )
        return response


__all__ = [
    "ErrorHandlingMiddleware",
    "PerformanceMonitoringMiddleware",
    "SecurityHeadersMiddleware",
    "ETagCacheMiddleware",
    "RateLimitMiddleware",
    "RequestBodyScannerMiddleware",
]


# 子模块导入（避免循环依赖）
from pycoder.server.middleware.perf import (  # noqa: E402
    PerformanceMonitoringMiddleware,
)
from pycoder.server.middleware.security import (  # noqa: E402
    ETagCacheMiddleware,
    RateLimitMiddleware,
    RequestBodyScannerMiddleware,
    SecurityHeadersMiddleware,
)
