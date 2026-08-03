"""
错误码定义模块

所有错误码集中在此定义，便于统一管理和维护。
错误码格式: PYC-XXXX (模块前缀-编号)

主要接口:
    - ErrorCode: 错误码枚举 (str Enum)
    - ErrorCodeInfo: 错误码详情 dataclass
    - ERROR_CODES: 枚举到详情的映射字典
    - get_error_info: 查找错误码详情
    - to_api_response: 生成 API 响应字典
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


# ════════════════════════════════════════════════════════
# 错误码枚举
# ════════════════════════════════════════════════════════


class ErrorCode(str, Enum):
    """统一错误码枚举。

    继承 ``str`` 使枚举成员本身即为字符串值，可直接用于字典键与字符串拼接；
    重写 ``__str__`` 使 ``str(ErrorCode.XXX)`` 返回 ``"PYC-XXXX"`` 而非
    默认的 ``"ErrorCode.XXX"``，便于序列化到 API 响应与日志中。
    """

    def __str__(self) -> str:
        # 返回 "PYC-XXXX" 字符串值，而非默认的 "ErrorCode.MEMBER"
        return self.value

    # ── 通用错误 (PYC-0xxx / PYC-1xxx) ──────────────────────
    UNKNOWN = "PYC-0000"
    INVALID_INPUT = "PYC-1001"
    FILE_INVALID_PATH = "PYC-1002"
    TIMEOUT = "PYC-1003"
    NOT_FOUND = "PYC-1004"
    PERMISSION_DENIED = "PYC-1005"
    INTERNAL_ERROR = "PYC-1006"
    CONFLICT = "PYC-1007"
    RATE_LIMITED = "PYC-1008"

    # ── LLM 相关 (PYC-2xxx) ────────────────────────────────
    LLM_PROVIDER_ERROR = "PYC-2000"
    LLM_RATE_LIMIT = "PYC-2001"
    LLM_CONTEXT_TOO_LONG = "PYC-2002"
    LLM_INVALID_RESPONSE = "PYC-2003"
    LLM_QUOTA_EXCEEDED = "PYC-2004"
    LLM_MODEL_NOT_FOUND = "PYC-2005"

    # ── 工具相关 (PYC-3xxx) ────────────────────────────────
    TOOL_NOT_FOUND = "PYC-3000"
    TOOL_EXECUTION_FAILED = "PYC-3001"
    TOOL_TIMEOUT = "PYC-3002"
    TOOL_INVALID_PARAMS = "PYC-3003"

    # ── 文件相关 (PYC-4xxx) ────────────────────────────────
    FILE_NOT_FOUND = "PYC-4000"
    FILE_READ_ERROR = "PYC-4001"
    FILE_WRITE_ERROR = "PYC-4002"
    FILE_PERMISSION_DENIED = "PYC-4003"

    # ── Shell 相关 (PYC-5xxx) ─────────────────────────────
    SHELL_DANGEROUS_COMMAND = "PYC-5000"
    SHELL_TIMEOUT = "PYC-5001"
    SHELL_NONZERO_EXIT = "PYC-5002"

    # ── 网络相关 (PYC-6xxx) ────────────────────────────────
    NETWORK_UNREACHABLE = "PYC-6000"
    NETWORK_TIMEOUT = "PYC-6001"
    HTTP_ERROR = "PYC-6002"

    # ── LSP 相关 (PYC-7xxx) ───────────────────────────────
    LSP_SERVER_UNAVAILABLE = "PYC-7000"
    LSP_TIMEOUT = "PYC-7001"
    LSP_INVALID_DIAGNOSTIC = "PYC-7002"

    # ── 沙箱相关 (PYC-8xxx) ───────────────────────────────
    SANDBOX_VIOLATION = "PYC-8000"
    SANDBOX_TIMEOUT = "PYC-8001"
    SANDBOX_OOM = "PYC-8002"

    # ── 认证相关 (PYC-9xxx) ────────────────────────────────
    AUTH_INVALID_KEY = "PYC-9000"
    AUTH_EXPIRED = "PYC-9001"
    AUTH_INSUFFICIENT = "PYC-9002"
    AUTH_REQUIRED = "PYC-9003"

    # ── 自演化相关 (PYC-91xx) ──────────────────────────────
    SELF_EVO_ROLLBACK_FAILED = "PYC-9100"
    SELF_EVO_INVALID_PATCH = "PYC-9101"
    SELF_EVO_POLICY_DENIED = "PYC-9102"


# ════════════════════════════════════════════════════════
# 错误码详情
# ════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ErrorCodeInfo:
    """错误码详情。

    Attributes:
        code: 对应的 ErrorCode 枚举成员
        http_status: HTTP 状态码 (100-599)
        message_zh: 中文错误描述
        message_en: 英文错误描述
        category: 错误分类 (通用/LLM/工具/文件/Shell/网络/LSP/Sandbox/Auth/Self-Evo)
    """

    code: ErrorCode
    http_status: int
    message_zh: str
    message_en: str
    category: str


# ════════════════════════════════════════════════════════
# 错误码映射表
# ════════════════════════════════════════════════════════

# 以 (http_status, message_zh, message_en, category) 形式定义所有详情，
# 再统一组装为 ErrorCodeInfo，保证枚举成员与字典条目一一对应。
_ERROR_SPECS: dict[ErrorCode, tuple[int, str, str, str]] = {
    # ── 通用 ───────────────────────────────────────────────
    ErrorCode.UNKNOWN: (500, "未知错误", "Unknown error", "通用"),
    ErrorCode.INVALID_INPUT: (400, "无效的输入", "Invalid input", "通用"),
    ErrorCode.FILE_INVALID_PATH: (400, "无效的文件路径", "Invalid file path", "通用"),
    ErrorCode.TIMEOUT: (504, "操作超时", "Operation timeout", "通用"),
    ErrorCode.NOT_FOUND: (404, "资源未找到", "Resource not found", "通用"),
    ErrorCode.PERMISSION_DENIED: (403, "权限被拒绝", "Permission denied", "通用"),
    ErrorCode.INTERNAL_ERROR: (500, "内部错误", "Internal error", "通用"),
    ErrorCode.CONFLICT: (409, "资源冲突", "Resource conflict", "通用"),
    ErrorCode.RATE_LIMITED: (429, "请求过于频繁", "Too many requests", "通用"),
    # ── LLM ────────────────────────────────────────────────
    ErrorCode.LLM_PROVIDER_ERROR: (502, "LLM 服务提供者错误", "LLM provider error", "LLM"),
    ErrorCode.LLM_RATE_LIMIT: (429, "LLM 请求速率超限", "LLM request rate limit exceeded", "LLM"),
    ErrorCode.LLM_CONTEXT_TOO_LONG: (413, "LLM 上下文过长", "LLM context too long", "LLM"),
    ErrorCode.LLM_INVALID_RESPONSE: (502, "LLM 返回无效响应", "LLM invalid response", "LLM"),
    ErrorCode.LLM_QUOTA_EXCEEDED: (402, "LLM 配额已超限", "LLM quota exceeded", "LLM"),
    ErrorCode.LLM_MODEL_NOT_FOUND: (404, "LLM 模型未找到", "LLM model not found", "LLM"),
    # ── 工具 ───────────────────────────────────────────────
    ErrorCode.TOOL_NOT_FOUND: (404, "工具未找到", "Tool not found", "工具"),
    ErrorCode.TOOL_EXECUTION_FAILED: (500, "工具执行失败", "Tool execution failed", "工具"),
    ErrorCode.TOOL_TIMEOUT: (504, "工具执行超时", "Tool execution timeout", "工具"),
    ErrorCode.TOOL_INVALID_PARAMS: (400, "工具参数无效", "Invalid tool parameters", "工具"),
    # ── 文件 ───────────────────────────────────────────────
    ErrorCode.FILE_NOT_FOUND: (404, "文件未找到", "File not found", "文件"),
    ErrorCode.FILE_READ_ERROR: (500, "文件读取失败", "File read error", "文件"),
    ErrorCode.FILE_WRITE_ERROR: (500, "文件写入失败", "File write error", "文件"),
    ErrorCode.FILE_PERMISSION_DENIED: (403, "文件权限被拒绝", "File permission denied", "文件"),
    # ── Shell ──────────────────────────────────────────────
    ErrorCode.SHELL_DANGEROUS_COMMAND: (403, "危险的 Shell 命令", "Dangerous shell command", "Shell"),
    ErrorCode.SHELL_TIMEOUT: (504, "Shell 执行超时", "Shell execution timeout", "Shell"),
    ErrorCode.SHELL_NONZERO_EXIT: (500, "Shell 非零退出", "Shell non-zero exit", "Shell"),
    # ── 网络 ───────────────────────────────────────────────
    ErrorCode.NETWORK_UNREACHABLE: (503, "网络不可达", "Network unreachable", "网络"),
    ErrorCode.NETWORK_TIMEOUT: (504, "网络请求超时", "Network timeout", "网络"),
    ErrorCode.HTTP_ERROR: (502, "HTTP 请求错误", "HTTP error", "网络"),
    # ── LSP ────────────────────────────────────────────────
    ErrorCode.LSP_SERVER_UNAVAILABLE: (503, "LSP 服务器不可用", "LSP server unavailable", "LSP"),
    ErrorCode.LSP_TIMEOUT: (504, "LSP 请求超时", "LSP timeout", "LSP"),
    ErrorCode.LSP_INVALID_DIAGNOSTIC: (500, "LSP 诊断信息无效", "LSP invalid diagnostic", "LSP"),
    # ── Sandbox ───────────────────────────────────────────
    ErrorCode.SANDBOX_VIOLATION: (403, "沙箱违规操作", "Sandbox violation", "Sandbox"),
    ErrorCode.SANDBOX_TIMEOUT: (504, "沙箱执行超时", "Sandbox timeout", "Sandbox"),
    ErrorCode.SANDBOX_OOM: (507, "沙箱内存不足", "Sandbox out of memory", "Sandbox"),
    # ── Auth ───────────────────────────────────────────────
    ErrorCode.AUTH_INVALID_KEY: (401, "无效的 API Key", "Invalid API key", "Auth"),
    ErrorCode.AUTH_EXPIRED: (401, "认证已过期", "Authentication expired", "Auth"),
    ErrorCode.AUTH_INSUFFICIENT: (403, "权限不足", "Insufficient permissions", "Auth"),
    ErrorCode.AUTH_REQUIRED: (401, "需要认证", "Authentication required", "Auth"),
    # ── Self-Evo ───────────────────────────────────────────
    ErrorCode.SELF_EVO_ROLLBACK_FAILED: (500, "自演化回滚失败", "Self-evolution rollback failed", "Self-Evo"),
    ErrorCode.SELF_EVO_INVALID_PATCH: (400, "自演化补丁无效", "Invalid self-evolution patch", "Self-Evo"),
    ErrorCode.SELF_EVO_POLICY_DENIED: (403, "自演化策略拒绝", "Self-evolution policy denied", "Self-Evo"),
}

ERROR_CODES: dict[ErrorCode, ErrorCodeInfo] = {
    code: ErrorCodeInfo(
        code=code,
        http_status=http_status,
        message_zh=message_zh,
        message_en=message_en,
        category=category,
    )
    for code, (http_status, message_zh, message_en, category) in _ERROR_SPECS.items()
}


# ════════════════════════════════════════════════════════
# 查找与响应生成函数
# ════════════════════════════════════════════════════════


def get_error_info(code: ErrorCode) -> ErrorCodeInfo:
    """根据错误码枚举成员查找详情。

    Args:
        code: ErrorCode 枚举成员

    Returns:
        对应的 ErrorCodeInfo 详情对象

    Raises:
        TypeError: 当 ``code`` 不是 :class:`ErrorCode` 类型时
    """
    if not isinstance(code, ErrorCode):
        raise TypeError("expected ErrorCode")
    return ERROR_CODES[code]


def to_api_response(
    code: ErrorCode,
    detail: str | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """生成标准化的 API 错误响应字典。

    Args:
        code: ErrorCode 枚举成员
        detail: 额外的错误细节，可选
        lang: 消息语言，``"zh"`` 返回中文，``"en"`` 返回英文

    Returns:
        包含 ``error`` / ``message`` / ``detail`` / ``http_status`` / ``category``
        五个字段的字典
    """
    info = get_error_info(code)
    message = info.message_zh if lang == "zh" else info.message_en
    return {
        "error": str(code),
        "message": message,
        "detail": detail,
        "http_status": info.http_status,
        "category": info.category,
    }


# ════════════════════════════════════════════════════════
# 向后兼容：旧的字符串常量与映射表
# ════════════════════════════════════════════════════════
# 以下常量保留以兼容旧代码，新代码应使用 ErrorCode 枚举。
# 与枚举成员同名的常量已对齐到新的枚举值，避免值不一致。

# 认证相关
AUTH_INVALID_KEY = ErrorCode.AUTH_INVALID_KEY.value
AUTH_EXPIRED_KEY = "PYC-9001"
AUTH_MISSING_KEY = "PYC-9002"
AUTH_INVALID_TOKEN = "PYC-9003"
AUTH_EXPIRED_TOKEN = "PYC-9004"

# 请求相关
REQUEST_INVALID = "PYC-1000"
REQUEST_MISSING_PARAM = "PYC-1001"
REQUEST_INVALID_FORMAT = "PYC-1002"

# 服务器相关
SERVER_INTERNAL_ERROR = "PYC-2000"
SERVER_UNAVAILABLE = "PYC-2001"
SERVER_TIMEOUT = "PYC-2002"

# 数据库相关
DB_CONNECTION_ERROR = "PYC-3000"
DB_QUERY_ERROR = "PYC-3001"
DB_MIGRATION_ERROR = "PYC-3002"

# 文件相关
FILE_NOT_FOUND = ErrorCode.FILE_NOT_FOUND.value
FILE_PERMISSION_DENIED = ErrorCode.FILE_PERMISSION_DENIED.value
FILE_READ_ERROR = ErrorCode.FILE_READ_ERROR.value
FILE_WRITE_ERROR = ErrorCode.FILE_WRITE_ERROR.value

# 工具执行相关
TOOL_EXECUTION_FAILED = ErrorCode.TOOL_EXECUTION_FAILED.value
TOOL_NOT_FOUND = ErrorCode.TOOL_NOT_FOUND.value
TOOL_TIMEOUT = ErrorCode.TOOL_TIMEOUT.value

# 模型/LLM 相关
MODEL_NOT_FOUND = "PYC-6000"
MODEL_RATE_LIMIT = "PYC-6001"
MODEL_CONTEXT_OVERFLOW = "PYC-6002"
MODEL_API_ERROR = "PYC-6003"

# 配置相关
CONFIG_NOT_FOUND = "PYC-7000"
CONFIG_INVALID = "PYC-7001"

# 网络相关
NETWORK_ERROR = "PYC-8000"
NETWORK_TIMEOUT = ErrorCode.NETWORK_TIMEOUT.value

# 旧的错误码到中文消息的映射表 (str -> str)
ERROR_CODE_MAP: dict[str, str] = {
    AUTH_INVALID_KEY: "无效的 API Key",
    AUTH_EXPIRED_KEY: "API Key 已过期",
    AUTH_MISSING_KEY: "缺少 API Key",
    AUTH_INVALID_TOKEN: "无效的 Token",
    AUTH_EXPIRED_TOKEN: "Token 已过期",
    REQUEST_INVALID: "无效的请求",
    REQUEST_MISSING_PARAM: "缺少必需参数",
    REQUEST_INVALID_FORMAT: "请求格式无效",
    SERVER_INTERNAL_ERROR: "服务器内部错误",
    SERVER_UNAVAILABLE: "服务器不可用",
    SERVER_TIMEOUT: "服务器超时",
    DB_CONNECTION_ERROR: "数据库连接错误",
    DB_QUERY_ERROR: "数据库查询错误",
    DB_MIGRATION_ERROR: "数据库迁移错误",
    FILE_NOT_FOUND: "文件不存在",
    FILE_PERMISSION_DENIED: "文件权限被拒绝",
    FILE_READ_ERROR: "文件读取错误",
    FILE_WRITE_ERROR: "文件写入错误",
    TOOL_EXECUTION_FAILED: "工具执行失败",
    TOOL_NOT_FOUND: "工具不存在",
    TOOL_TIMEOUT: "工具执行超时",
    MODEL_NOT_FOUND: "模型不存在",
    MODEL_RATE_LIMIT: "模型速率限制",
    MODEL_CONTEXT_OVERFLOW: "模型上下文溢出",
    MODEL_API_ERROR: "模型 API 错误",
    CONFIG_NOT_FOUND: "配置不存在",
    CONFIG_INVALID: "配置无效",
    NETWORK_ERROR: "网络错误",
    NETWORK_TIMEOUT: "网络超时",
}
