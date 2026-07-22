"""性能监控中间件 — 阶段 3 架构升级

检测慢请求，输出结构化日志，便于性能分析。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

_logger = logging.getLogger("pycoder.server.middleware.perf")


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """性能监控中间件

    行为：
        1. 记录每个请求的耗时
        2. 慢请求（> SLOW_THRESHOLD_MS）记录 WARNING
        3. 添加 X-Response-Time 响应头
        4. 忽略健康检查路径

    阈值：
        - 警告阈值: 1000ms (1s)
        - 严重阈值: 5000ms (5s)
    """

    SLOW_THRESHOLD_MS = 1000.0
    CRITICAL_THRESHOLD_MS = 5000.0

    def _should_track(self, path: str) -> bool:
        """跳过不需要监控的路径"""
        skip_prefixes = ("/api/health", "/ws/", "/docs", "/openapi.json", "/_")
        return not any(path.startswith(p) for p in skip_prefixes)

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path

        if not self._should_track(path):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0

        # 添加响应时间头
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"

        # 慢请求日志
        if duration_ms >= self.CRITICAL_THRESHOLD_MS:
            _logger.warning(
                "CRITICAL_SLOW_REQUEST: %s %s duration=%.1fms status=%d",
                request.method,
                path,
                duration_ms,
                response.status_code,
            )
        elif duration_ms >= self.SLOW_THRESHOLD_MS:
            _logger.info(
                "SLOW_REQUEST: %s %s duration=%.1fms status=%d",
                request.method,
                path,
                duration_ms,
                response.status_code,
            )

        return response


__all__ = ["PerformanceMonitoringMiddleware"]
