"""统一错误处理模块

提供标准化的错误响应格式，符合 api_path_specification.md 规范
"""
from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


# 标准错误码
class ErrorCode:
    """标准错误码常量"""
    # 4xx 客户端错误
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"

    # 5xx 服务器错误
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"

    # 业务错误
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    AUTH_FAILED = "AUTH_FAILED"
    LLM_ERROR = "LLM_ERROR"
    EXEC_ERROR = "EXEC_ERROR"
    GIT_ERROR = "GIT_ERROR"
    SKILL_ERROR = "SKILL_ERROR"
    EVOLUTION_ERROR = "EVOLUTION_ERROR"


def _now_iso() -> str:
    """返回 ISO 格式时间戳"""
    return datetime.now(timezone.utc).isoformat()


def make_error_response(
    code: str,
    message: str,
    status_code: int = 500,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """构造标准错误响应"""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id or str(uuid.uuid4()),
            },
            "timestamp": _now_iso(),
        },
    )


def make_success_response(
    data: Any = None,
    message: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """构造标准成功响应"""
    return {
        "success": True,
        "data": data,
        "message": message,
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": _now_iso(),
    }


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """处理 HTTPException"""
    # 映射 HTTP 状态码到错误码
    code_map = {
        400: ErrorCode.BAD_REQUEST,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.CONFLICT,
        422: ErrorCode.VALIDATION_ERROR,
        429: ErrorCode.RATE_LIMITED,
        500: ErrorCode.INTERNAL_ERROR,
        503: ErrorCode.SERVICE_UNAVAILABLE,
    }
    code = code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    return make_error_response(
        code=code,
        message=str(exc.detail) if exc.detail else "请求失败",
        status_code=exc.status_code,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError | ValidationError
) -> JSONResponse:
    """处理请求体验证错误"""
    errors = exc.errors() if hasattr(exc, "errors") else []
    # 简化错误信息，避免泄露内部细节
    details = [
        {
            "field": ".".join(str(loc) for loc in err.get("loc", [])),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in errors[:10]  # 最多返回 10 个错误
    ]
    return make_error_response(
        code=ErrorCode.VALIDATION_ERROR,
        message="请求参数验证失败",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details={"errors": details},
    )


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """处理未捕获的异常"""
    logger.exception(
        "unhandled_exception path=%s method=%s",
        request.url.path,
        request.method,
    )
    # 生产环境不暴露详细错误信息
    return make_error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message="服务器内部错误",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={
            "exception_type": type(exc).__name__,
            "path": request.url.path,
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """注册全局错误处理器到 FastAPI 应用"""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    logger.info("error_handlers_registered")
