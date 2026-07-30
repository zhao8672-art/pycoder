"""统一错误码字典 — 前后端、跨服务通用错误标识

设计原则:
    1. 每个错误码对应一个稳定的字符串标识 (StrEnum)
    2. 按业务域分段 (通用/LLM/工具/文件/Shell/网络/LSP/Sandbox/Auth/Self-Evo)
    3. 提供 HTTP 状态码、中文/英文消息、类别等元数据
    4. 通过 get_error_info / to_api_response 统一查询与响应生成

用法:
    from pycoder.core.error_codes import ErrorCode, get_error_info, to_api_response

    info = get_error_info(ErrorCode.LLM_RATE_LIMIT)
    response = to_api_response(ErrorCode.LLM_RATE_LIMIT, detail="try later")
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """统一错误码枚举 (字符串值)"""

    # ── 通用 (1000-1099) ──
    UNKNOWN = "PYC-1000"
    INVALID_INPUT = "PYC-1001"
    TIMEOUT = "PYC-1002"
    NOT_FOUND = "PYC-1003"
    PERMISSION_DENIED = "PYC-1004"
    INTERNAL_ERROR = "PYC-1005"
    CONFLICT = "PYC-1006"
    RATE_LIMITED = "PYC-1007"
    DEPENDENCY_UNAVAILABLE = "PYC-1008"

    # ── LLM (2000-2099) ──
    LLM_PROVIDER_ERROR = "PYC-2000"
    LLM_RATE_LIMIT = "PYC-2001"
    LLM_CONTEXT_TOO_LONG = "PYC-2002"
    LLM_INVALID_RESPONSE = "PYC-2003"
    LLM_QUOTA_EXCEEDED = "PYC-2004"
    LLM_AUTH_FAILED = "PYC-2005"
    LLM_MODEL_NOT_FOUND = "PYC-2006"

    # ── 工具 (3000-3099) ──
    TOOL_NOT_FOUND = "PYC-3000"
    TOOL_EXECUTION_FAILED = "PYC-3001"
    TOOL_TIMEOUT = "PYC-3002"
    TOOL_INVALID_PARAMS = "PYC-3003"
    TOOL_PERMISSION_DENIED = "PYC-3004"

    # ── 文件 (4000-4099) ──
    FILE_NOT_FOUND = "PYC-4000"
    FILE_READ_ERROR = "PYC-4001"
    FILE_WRITE_ERROR = "PYC-4002"
    FILE_PERMISSION_DENIED = "PYC-4003"
    FILE_TOO_LARGE = "PYC-4004"
    FILE_INVALID_PATH = "PYC-4005"

    # ── Shell (5000-5099) ──
    SHELL_DANGEROUS_COMMAND = "PYC-5000"
    SHELL_TIMEOUT = "PYC-5001"
    SHELL_NONZERO_EXIT = "PYC-5002"
    SHELL_EXECUTION_ERROR = "PYC-5003"

    # ── 网络 (6000-6099) ──
    NETWORK_UNREACHABLE = "PYC-6000"
    NETWORK_TIMEOUT = "PYC-6001"
    HTTP_ERROR = "PYC-6002"
    NETWORK_DNS_ERROR = "PYC-6003"

    # ── LSP (7000-7099) ──
    LSP_SERVER_UNAVAILABLE = "PYC-7000"
    LSP_TIMEOUT = "PYC-7001"
    LSP_INVALID_DIAGNOSTIC = "PYC-7002"
    LSP_INIT_FAILED = "PYC-7003"

    # ── Sandbox (8000-8099) ──
    SANDBOX_VIOLATION = "PYC-8000"
    SANDBOX_TIMEOUT = "PYC-8001"
    SANDBOX_OOM = "PYC-8002"
    SANDBOX_INIT_FAILED = "PYC-8003"

    # ── Auth (9000-9099) ──
    AUTH_INVALID_KEY = "PYC-9000"
    AUTH_EXPIRED = "PYC-9001"
    AUTH_INSUFFICIENT = "PYC-9002"
    AUTH_REQUIRED = "PYC-9003"

    # ── Self-Evo (10000-10099) ──
    SELF_EVO_ROLLBACK_FAILED = "PYC-10000"
    SELF_EVO_INVALID_PATCH = "PYC-10001"
    SELF_EVO_ENGINE_ERROR = "PYC-10002"
    SELF_EVO_POLICY_DENIED = "PYC-10003"


@dataclass(frozen=True)
class ErrorCodeInfo:
    """错误码元信息"""

    code: ErrorCode
    http_status: int
    message_zh: str
    message_en: str
    category: str


# ── HTTP 状态码默认值 ──
_DEFAULT_HTTP_STATUS = {
    "通用": 500,
    "LLM": 502,
    "工具": 500,
    "文件": 400,
    "Shell": 500,
    "网络": 502,
    "LSP": 500,
    "Sandbox": 500,
    "Auth": 401,
    "Self-Evo": 500,
}

# ── 分类重写 (基于具体语义) ──
_HTTP_STATUS_OVERRIDE: dict[ErrorCode, int] = {
    ErrorCode.UNKNOWN: 500,
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.LLM_PROVIDER_ERROR: 502,
    ErrorCode.LLM_RATE_LIMIT: 429,
    ErrorCode.LLM_CONTEXT_TOO_LONG: 413,
    ErrorCode.LLM_INVALID_RESPONSE: 502,
    ErrorCode.LLM_QUOTA_EXCEEDED: 402,
    ErrorCode.LLM_AUTH_FAILED: 401,
    ErrorCode.LLM_MODEL_NOT_FOUND: 404,
    ErrorCode.TOOL_NOT_FOUND: 404,
    ErrorCode.TOOL_EXECUTION_FAILED: 500,
    ErrorCode.TOOL_TIMEOUT: 504,
    ErrorCode.TOOL_INVALID_PARAMS: 400,
    ErrorCode.TOOL_PERMISSION_DENIED: 403,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.FILE_READ_ERROR: 500,
    ErrorCode.FILE_WRITE_ERROR: 500,
    ErrorCode.FILE_PERMISSION_DENIED: 403,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.FILE_INVALID_PATH: 400,
    ErrorCode.SHELL_DANGEROUS_COMMAND: 403,
    ErrorCode.SHELL_TIMEOUT: 504,
    ErrorCode.SHELL_NONZERO_EXIT: 500,
    ErrorCode.SHELL_EXECUTION_ERROR: 500,
    ErrorCode.NETWORK_UNREACHABLE: 502,
    ErrorCode.NETWORK_TIMEOUT: 504,
    ErrorCode.HTTP_ERROR: 502,
    ErrorCode.NETWORK_DNS_ERROR: 502,
    ErrorCode.LSP_SERVER_UNAVAILABLE: 503,
    ErrorCode.LSP_TIMEOUT: 504,
    ErrorCode.LSP_INVALID_DIAGNOSTIC: 500,
    ErrorCode.LSP_INIT_FAILED: 500,
    ErrorCode.SANDBOX_VIOLATION: 403,
    ErrorCode.SANDBOX_TIMEOUT: 504,
    ErrorCode.SANDBOX_OOM: 500,
    ErrorCode.SANDBOX_INIT_FAILED: 503,
    ErrorCode.AUTH_INVALID_KEY: 401,
    ErrorCode.AUTH_EXPIRED: 401,
    ErrorCode.AUTH_INSUFFICIENT: 403,
    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.SELF_EVO_ROLLBACK_FAILED: 500,
    ErrorCode.SELF_EVO_INVALID_PATCH: 400,
    ErrorCode.SELF_EVO_ENGINE_ERROR: 500,
    ErrorCode.SELF_EVO_POLICY_DENIED: 403,
}


def _category_of(code: ErrorCode) -> str:
    """根据错误码枚举值推断类别"""
    val = str(code)
    # 5 位数 (10000+) 优先于 1 位数前缀匹配, 避免 PYC-1xxxx 被误判为 通用
    if val.startswith("PYC-1"):
        tail = val[len("PYC-"):]
        # tail 5 位 → Self-Evo (10xxx); tail 4 位 → 通用 (1xxx)
        if len(tail) == 5:
            return "Self-Evo"
        return "通用"
    if val.startswith("PYC-2"):
        return "LLM"
    if val.startswith("PYC-3"):
        return "工具"
    if val.startswith("PYC-4"):
        return "文件"
    if val.startswith("PYC-5"):
        return "Shell"
    if val.startswith("PYC-6"):
        return "网络"
    if val.startswith("PYC-7"):
        return "LSP"
    if val.startswith("PYC-8"):
        return "Sandbox"
    if val.startswith("PYC-9"):
        return "Auth"
    return "Self-Evo"


# ── 错误码 → 描述映射 ──
_ERROR_DESCRIPTIONS: dict[ErrorCode, tuple[str, str]] = {
    # 通用
    ErrorCode.UNKNOWN: ("未知错误", "Unknown error"),
    ErrorCode.INVALID_INPUT: ("参数无效", "Invalid input"),
    ErrorCode.TIMEOUT: ("操作超时", "Operation timeout"),
    ErrorCode.NOT_FOUND: ("资源不存在", "Resource not found"),
    ErrorCode.PERMISSION_DENIED: ("权限不足", "Permission denied"),
    ErrorCode.INTERNAL_ERROR: ("内部错误", "Internal server error"),
    ErrorCode.CONFLICT: ("资源冲突", "Resource conflict"),
    ErrorCode.RATE_LIMITED: ("请求过于频繁", "Rate limited"),
    ErrorCode.DEPENDENCY_UNAVAILABLE: ("依赖不可用", "Dependency unavailable"),
    # LLM
    ErrorCode.LLM_PROVIDER_ERROR: ("LLM 提供商错误", "LLM provider error"),
    ErrorCode.LLM_RATE_LIMIT: ("LLM 速率限制", "LLM rate limit exceeded"),
    ErrorCode.LLM_CONTEXT_TOO_LONG: ("LLM 上下文过长", "LLM context too long"),
    ErrorCode.LLM_INVALID_RESPONSE: ("LLM 响应无效", "LLM invalid response"),
    ErrorCode.LLM_QUOTA_EXCEEDED: ("LLM 配额耗尽", "LLM quota exceeded"),
    ErrorCode.LLM_AUTH_FAILED: ("LLM 认证失败", "LLM authentication failed"),
    ErrorCode.LLM_MODEL_NOT_FOUND: ("LLM 模型不存在", "LLM model not found"),
    # 工具
    ErrorCode.TOOL_NOT_FOUND: ("工具不存在", "Tool not found"),
    ErrorCode.TOOL_EXECUTION_FAILED: ("工具执行失败", "Tool execution failed"),
    ErrorCode.TOOL_TIMEOUT: ("工具执行超时", "Tool execution timeout"),
    ErrorCode.TOOL_INVALID_PARAMS: ("工具参数无效", "Tool invalid parameters"),
    ErrorCode.TOOL_PERMISSION_DENIED: ("工具权限不足", "Tool permission denied"),
    # 文件
    ErrorCode.FILE_NOT_FOUND: ("文件不存在", "File not found"),
    ErrorCode.FILE_READ_ERROR: ("文件读取错误", "File read error"),
    ErrorCode.FILE_WRITE_ERROR: ("文件写入错误", "File write error"),
    ErrorCode.FILE_PERMISSION_DENIED: ("文件权限不足", "File permission denied"),
    ErrorCode.FILE_TOO_LARGE: ("文件过大", "File too large"),
    ErrorCode.FILE_INVALID_PATH: ("文件路径无效", "Invalid file path"),
    # Shell
    ErrorCode.SHELL_DANGEROUS_COMMAND: ("危险命令被拒绝", "Dangerous command rejected"),
    ErrorCode.SHELL_TIMEOUT: ("Shell 命令超时", "Shell command timeout"),
    ErrorCode.SHELL_NONZERO_EXIT: ("Shell 命令返回非零", "Shell command non-zero exit"),
    ErrorCode.SHELL_EXECUTION_ERROR: ("Shell 执行错误", "Shell execution error"),
    # 网络
    ErrorCode.NETWORK_UNREACHABLE: ("网络不可达", "Network unreachable"),
    ErrorCode.NETWORK_TIMEOUT: ("网络超时", "Network timeout"),
    ErrorCode.HTTP_ERROR: ("HTTP 请求错误", "HTTP error"),
    ErrorCode.NETWORK_DNS_ERROR: ("DNS 解析失败", "DNS resolution failed"),
    # LSP
    ErrorCode.LSP_SERVER_UNAVAILABLE: ("LSP 服务不可用", "LSP server unavailable"),
    ErrorCode.LSP_TIMEOUT: ("LSP 请求超时", "LSP timeout"),
    ErrorCode.LSP_INVALID_DIAGNOSTIC: ("LSP 诊断无效", "LSP invalid diagnostic"),
    ErrorCode.LSP_INIT_FAILED: ("LSP 初始化失败", "LSP initialization failed"),
    # Sandbox
    ErrorCode.SANDBOX_VIOLATION: ("沙箱违规", "Sandbox violation"),
    ErrorCode.SANDBOX_TIMEOUT: ("沙箱超时", "Sandbox timeout"),
    ErrorCode.SANDBOX_OOM: ("沙箱内存耗尽", "Sandbox out of memory"),
    ErrorCode.SANDBOX_INIT_FAILED: ("沙箱初始化失败", "Sandbox initialization failed"),
    # Auth
    ErrorCode.AUTH_INVALID_KEY: ("API Key 无效", "Invalid API key"),
    ErrorCode.AUTH_EXPIRED: ("凭证已过期", "Credential expired"),
    ErrorCode.AUTH_INSUFFICIENT: ("权限不足", "Insufficient permissions"),
    ErrorCode.AUTH_REQUIRED: ("需要认证", "Authentication required"),
    # Self-Evo
    ErrorCode.SELF_EVO_ROLLBACK_FAILED: ("自我进化回滚失败", "Self-evol rollout rollback failed"),
    ErrorCode.SELF_EVO_INVALID_PATCH: ("自我进化补丁无效", "Self-evol invalid patch"),
    ErrorCode.SELF_EVO_ENGINE_ERROR: ("自我进化引擎错误", "Self-evol engine error"),
    ErrorCode.SELF_EVO_POLICY_DENIED: ("自我进化策略拒绝", "Self-evol policy denied"),
}


# ── 构建 ERROR_CODES 字典 ──
def _build_error_codes() -> dict[ErrorCode, ErrorCodeInfo]:
    codes: dict[ErrorCode, ErrorCodeInfo] = {}
    for code in ErrorCode:
        if code not in _ERROR_DESCRIPTIONS:
            raise RuntimeError(f"missing description for {code}")
        zh, en = _ERROR_DESCRIPTIONS[code]
        http_status = _HTTP_STATUS_OVERRIDE.get(code, _DEFAULT_HTTP_STATUS[_category_of(code)])
        codes[code] = ErrorCodeInfo(
            code=code,
            http_status=http_status,
            message_zh=zh,
            message_en=en,
            category=_category_of(code),
        )
    return codes


ERROR_CODES: dict[ErrorCode, ErrorCodeInfo] = _build_error_codes()


def get_error_info(code: ErrorCode) -> ErrorCodeInfo:
    """查询错误码元信息

    Args:
        code: 错误码枚举值

    Returns:
        ErrorCodeInfo; 若 code 不在字典中, 返回基于默认值构造的 info (不抛错)

    Raises:
        TypeError: code 不是 ErrorCode 类型
    """
    if not isinstance(code, ErrorCode):
        raise TypeError(f"expected ErrorCode, got {type(code).__name__}")
    if code in ERROR_CODES:
        return ERROR_CODES[code]
    category = _category_of(code)
    return ErrorCodeInfo(
        code=code,
        http_status=_HTTP_STATUS_OVERRIDE.get(code, _DEFAULT_HTTP_STATUS[category]),
        message_zh=str(code),
        message_en=str(code),
        category=category,
    )


def to_api_response(
    code: ErrorCode,
    detail: str | None = None,
    lang: str = "zh",
) -> dict:
    """生成标准 API 错误响应

    Args:
        code: 错误码枚举值
        detail: 可选的详细描述 (会覆盖默认 message)
        lang: 语言 ("zh" / "en"), 默认中文

    Returns:
        形如 {
            "error": "PYC-2001",
            "message": "...",
            "detail": "...",
            "http_status": 429,
            "category": "LLM",
        }
    """
    info = get_error_info(code)
    base_message = info.message_zh if lang == "zh" else info.message_en
    return {
        "error": str(info.code),
        "message": base_message,
        "detail": detail,
        "http_status": info.http_status,
        "category": info.category,
    }


__all__ = [
    "ErrorCode",
    "ErrorCodeInfo",
    "ERROR_CODES",
    "get_error_info",
    "to_api_response",
]
