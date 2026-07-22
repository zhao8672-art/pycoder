"""统一异常类 — 阶段 2 架构升级

提供项目级业务异常基类，便于 ErrorMiddleware 统一处理。

层级：
- PyCoderError (基类)
  - ValidationError (参数校验失败 → 400)
  - NotFoundError (资源不存在 → 404)
  - PermissionError (权限不足 → 403)
  - ConflictError (资源冲突 → 409)
  - RateLimitError (限流 → 429)
  - ExternalServiceError (外部服务失败 → 502)
  - ConfigurationError (配置错误 → 500)
  - DependencyError (依赖未就绪 → 503)
"""
from __future__ import annotations

from typing import Any


class PyCoderError(Exception):
    """PyCoder 项目基类异常

    所有业务异常应继承自此类，ErrorMiddleware 会捕获并转换为统一 JSON 响应。
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    default_message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 响应"""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(PyCoderError):
    """参数校验失败"""

    status_code = 400
    error_code = "VALIDATION_ERROR"
    default_message = "Invalid input parameters"


class NotFoundError(PyCoderError):
    """资源不存在"""

    status_code = 404
    error_code = "NOT_FOUND"
    default_message = "Resource not found"


class PermissionDeniedError(PyCoderError):
    """权限不足"""

    status_code = 403
    error_code = "PERMISSION_DENIED"
    default_message = "Permission denied"


class ConflictError(PyCoderError):
    """资源冲突（如重复创建、版本冲突）"""

    status_code = 409
    error_code = "CONFLICT"
    default_message = "Resource conflict"


class RateLimitError(PyCoderError):
    """触发限流"""

    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    default_message = "Too many requests"


class ExternalServiceError(PyCoderError):
    """外部服务（LLM API / Docker / GitHub 等）调用失败"""

    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"
    default_message = "External service call failed"


class ConfigurationError(PyCoderError):
    """配置错误（如 API Key 缺失、配置文件损坏）"""

    status_code = 500
    error_code = "CONFIGURATION_ERROR"
    default_message = "Configuration error"


class DependencyError(PyCoderError):
    """依赖未就绪（如 Docker 未启动、数据库未连接）"""

    status_code = 503
    error_code = "DEPENDENCY_UNAVAILABLE"
    default_message = "Required dependency is not available"


__all__ = [
    "PyCoderError",
    "ValidationError",
    "NotFoundError",
    "PermissionDeniedError",
    "ConflictError",
    "RateLimitError",
    "ExternalServiceError",
    "ConfigurationError",
    "DependencyError",
]
