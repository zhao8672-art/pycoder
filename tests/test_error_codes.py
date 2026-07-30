"""统一错误码字典测试"""
from __future__ import annotations

import pytest

from pycoder.core.error_codes import (
    ERROR_CODES,
    ErrorCode,
    ErrorCodeInfo,
    get_error_info,
    to_api_response,
)

# ════════════════════════════════════════════════════════
# 枚举与字典完整性测试
# ════════════════════════════════════════════════════════


class TestErrorCodeEnum:
    """ErrorCode 枚举测试"""

    def test_minimum_codes_count(self) -> None:
        """至少 40 个错误码"""
        assert len(ErrorCode) >= 40

    def test_codes_are_strings(self) -> None:
        """所有错误码是字符串值"""
        for code in ErrorCode:
            assert isinstance(code, str)
            assert code.startswith("PYC-")

    def test_code_format(self) -> None:
        """错误码格式为 PYC-XXXX 或 PYC-XXXXX"""
        for code in ErrorCode:
            val = str(code)
            # PYC-10000 之类的 5 位数也允许
            assert val.startswith("PYC-")
            tail = val[4:]
            assert tail.isdigit()
            assert 4 <= len(tail) <= 5

    def test_all_codes_have_entries(self) -> None:
        """所有枚举成员在 ERROR_CODES 中都有对应项"""
        for code in ErrorCode:
            assert code in ERROR_CODES

    def test_all_entries_have_required_fields(self) -> None:
        """所有 ErrorCodeInfo 字段已填写"""
        for code, info in ERROR_CODES.items():
            assert isinstance(info, ErrorCodeInfo)
            assert info.code == code
            assert 100 <= info.http_status < 600
            assert info.message_zh.strip()
            assert info.message_en.strip()
            assert info.category in {
                "通用",
                "LLM",
                "工具",
                "文件",
                "Shell",
                "网络",
                "LSP",
                "Sandbox",
                "Auth",
                "Self-Evo",
            }

    def test_category_mapping(self) -> None:
        """错误码分类正确"""
        assert ERROR_CODES[ErrorCode.UNKNOWN].category == "通用"
        assert ERROR_CODES[ErrorCode.LLM_RATE_LIMIT].category == "LLM"
        assert ERROR_CODES[ErrorCode.TOOL_NOT_FOUND].category == "工具"
        assert ERROR_CODES[ErrorCode.FILE_NOT_FOUND].category == "文件"
        assert ERROR_CODES[ErrorCode.SHELL_TIMEOUT].category == "Shell"
        assert ERROR_CODES[ErrorCode.NETWORK_TIMEOUT].category == "网络"
        assert ERROR_CODES[ErrorCode.LSP_TIMEOUT].category == "LSP"
        assert ERROR_CODES[ErrorCode.SANDBOX_TIMEOUT].category == "Sandbox"
        assert ERROR_CODES[ErrorCode.AUTH_EXPIRED].category == "Auth"
        assert ERROR_CODES[ErrorCode.SELF_EVO_ROLLBACK_FAILED].category == "Self-Evo"


class TestErrorCodeCoverage:
    """覆盖所有声明的错误码"""

    def test_required_general_codes(self) -> None:
        for c in [
            ErrorCode.UNKNOWN,
            ErrorCode.INVALID_INPUT,
            ErrorCode.TIMEOUT,
            ErrorCode.NOT_FOUND,
            ErrorCode.PERMISSION_DENIED,
            ErrorCode.INTERNAL_ERROR,
        ]:
            assert c in ERROR_CODES

    def test_required_llm_codes(self) -> None:
        for c in [
            ErrorCode.LLM_PROVIDER_ERROR,
            ErrorCode.LLM_RATE_LIMIT,
            ErrorCode.LLM_CONTEXT_TOO_LONG,
            ErrorCode.LLM_INVALID_RESPONSE,
            ErrorCode.LLM_QUOTA_EXCEEDED,
        ]:
            assert c in ERROR_CODES

    def test_required_tool_codes(self) -> None:
        for c in [
            ErrorCode.TOOL_NOT_FOUND,
            ErrorCode.TOOL_EXECUTION_FAILED,
            ErrorCode.TOOL_TIMEOUT,
            ErrorCode.TOOL_INVALID_PARAMS,
        ]:
            assert c in ERROR_CODES

    def test_required_file_codes(self) -> None:
        for c in [
            ErrorCode.FILE_NOT_FOUND,
            ErrorCode.FILE_READ_ERROR,
            ErrorCode.FILE_WRITE_ERROR,
            ErrorCode.FILE_PERMISSION_DENIED,
        ]:
            assert c in ERROR_CODES

    def test_required_shell_codes(self) -> None:
        for c in [
            ErrorCode.SHELL_DANGEROUS_COMMAND,
            ErrorCode.SHELL_TIMEOUT,
            ErrorCode.SHELL_NONZERO_EXIT,
        ]:
            assert c in ERROR_CODES

    def test_required_network_codes(self) -> None:
        for c in [
            ErrorCode.NETWORK_UNREACHABLE,
            ErrorCode.NETWORK_TIMEOUT,
            ErrorCode.HTTP_ERROR,
        ]:
            assert c in ERROR_CODES

    def test_required_lsp_codes(self) -> None:
        for c in [
            ErrorCode.LSP_SERVER_UNAVAILABLE,
            ErrorCode.LSP_TIMEOUT,
            ErrorCode.LSP_INVALID_DIAGNOSTIC,
        ]:
            assert c in ERROR_CODES

    def test_required_sandbox_codes(self) -> None:
        for c in [
            ErrorCode.SANDBOX_VIOLATION,
            ErrorCode.SANDBOX_TIMEOUT,
            ErrorCode.SANDBOX_OOM,
        ]:
            assert c in ERROR_CODES

    def test_required_auth_codes(self) -> None:
        for c in [
            ErrorCode.AUTH_INVALID_KEY,
            ErrorCode.AUTH_EXPIRED,
            ErrorCode.AUTH_INSUFFICIENT,
        ]:
            assert c in ERROR_CODES

    def test_required_self_evo_codes(self) -> None:
        for c in [
            ErrorCode.SELF_EVO_ROLLBACK_FAILED,
            ErrorCode.SELF_EVO_INVALID_PATCH,
        ]:
            assert c in ERROR_CODES


# ════════════════════════════════════════════════════════
# get_error_info 查找函数测试
# ════════════════════════════════════════════════════════


class TestGetErrorInfo:
    """get_error_info 查找函数测试"""

    def test_lookup_known_code(self) -> None:
        info = get_error_info(ErrorCode.LLM_RATE_LIMIT)
        assert info.code == ErrorCode.LLM_RATE_LIMIT
        assert info.http_status == 429
        assert info.category == "LLM"
        assert "速率" in info.message_zh or "rate" in info.message_en.lower()

    def test_invalid_input_returns_400(self) -> None:
        info = get_error_info(ErrorCode.INVALID_INPUT)
        assert info.http_status == 400

    def test_not_found_returns_404(self) -> None:
        info = get_error_info(ErrorCode.FILE_NOT_FOUND)
        assert info.http_status == 404

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError, match="expected ErrorCode"):
            get_error_info("PYC-1000")  # type: ignore[arg-type]

    def test_consistent_with_dict(self) -> None:
        """get_error_info 返回的对象与字典中的对象等价"""
        for code in ErrorCode:
            via_fn = get_error_info(code)
            via_dict = ERROR_CODES[code]
            assert via_fn == via_dict


# ════════════════════════════════════════════════════════
# to_api_response 测试
# ════════════════════════════════════════════════════════


class TestToApiResponse:
    """to_api_response 响应生成函数测试"""

    def test_basic_response(self) -> None:
        resp = to_api_response(ErrorCode.LLM_RATE_LIMIT)
        assert resp["error"] == "PYC-2001"
        assert resp["http_status"] == 429
        assert resp["category"] == "LLM"
        assert resp["message"]  # 默认中文非空
        assert resp["detail"] is None

    def test_response_with_detail(self) -> None:
        resp = to_api_response(ErrorCode.TIMEOUT, detail="请求耗时 30s")
        assert resp["detail"] == "请求耗时 30s"

    def test_english_message(self) -> None:
        resp = to_api_response(ErrorCode.TIMEOUT, lang="en")
        assert resp["message"] == "Operation timeout"

    def test_chinese_default(self) -> None:
        resp = to_api_response(ErrorCode.TIMEOUT)
        assert resp["message"] == "操作超时"

    def test_response_contains_all_fields(self) -> None:
        resp = to_api_response(ErrorCode.FILE_NOT_FOUND)
        assert set(resp.keys()) == {"error", "message", "detail", "http_status", "category"}

    def test_auth_response_status(self) -> None:
        resp = to_api_response(ErrorCode.AUTH_INVALID_KEY)
        assert resp["http_status"] == 401
        assert resp["category"] == "Auth"

    def test_shell_dangerous_command_status(self) -> None:
        resp = to_api_response(ErrorCode.SHELL_DANGEROUS_COMMAND)
        assert resp["http_status"] == 403

    def test_quota_exceeded_status(self) -> None:
        resp = to_api_response(ErrorCode.LLM_QUOTA_EXCEEDED)
        assert resp["http_status"] == 402

    def test_error_code_string_value(self) -> None:
        """error 字段是错误码的字符串值"""
        for code in [ErrorCode.UNKNOWN, ErrorCode.LLM_PROVIDER_ERROR, ErrorCode.SELF_EVO_ROLLBACK_FAILED]:
            resp = to_api_response(code)
            assert resp["error"] == str(code)


# ════════════════════════════════════════════════════════
# 一致性测试
# ════════════════════════════════════════════════════════


class TestErrorCodeConsistency:
    """错误码与 HTTP 状态码的一致性"""

    @pytest.mark.parametrize(
        "code,expected_status",
        [
            (ErrorCode.INVALID_INPUT, 400),
            (ErrorCode.FILE_INVALID_PATH, 400),
            (ErrorCode.SELF_EVO_INVALID_PATCH, 400),
            (ErrorCode.NOT_FOUND, 404),
            (ErrorCode.LLM_MODEL_NOT_FOUND, 404),
            (ErrorCode.AUTH_REQUIRED, 401),
            (ErrorCode.AUTH_EXPIRED, 401),
            (ErrorCode.PERMISSION_DENIED, 403),
            (ErrorCode.SANDBOX_VIOLATION, 403),
            (ErrorCode.SELF_EVO_POLICY_DENIED, 403),
            (ErrorCode.CONFLICT, 409),
            (ErrorCode.RATE_LIMITED, 429),
            (ErrorCode.LLM_RATE_LIMIT, 429),
            (ErrorCode.TIMEOUT, 504),
            (ErrorCode.SHELL_TIMEOUT, 504),
            (ErrorCode.NETWORK_TIMEOUT, 504),
            (ErrorCode.SANDBOX_TIMEOUT, 504),
        ],
    )
    def test_http_status_consistency(self, code: ErrorCode, expected_status: int) -> None:
        assert get_error_info(code).http_status == expected_status
