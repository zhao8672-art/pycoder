"""
优雅降级模块测试

覆盖:
  - DEGRADATION_HINTS: 预定义降级提示的完整性
  - get_degradation_hint: 获取指定能力的降级提示
  - wrap_handler: 包装处理器，正常执行
  - wrap_handler: 捕获 FileNotFoundError 返回友好提示
  - wrap_handler: 捕获通用 Exception 返回错误信息
  - wrap_handler: 处理返回可调用对象的结果
  - wrap_handler: 错误消息截断
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pycoder.capabilities.degradation import (
    DEGRADATION_HINTS,
    get_degradation_hint,
    wrap_handler,
)


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


async def _success_handler(params: dict, context: dict) -> dict:
    """成功的处理器"""
    return {"success": True, "data": params.get("key", "default")}


async def _error_handler(params: dict, context: dict) -> dict:
    """抛出 FileNotFoundError 的处理器"""
    raise FileNotFoundError("未找到 docker")


async def _generic_error_handler(params: dict, context: dict) -> dict:
    """抛出通用异常的处理器"""
    raise ValueError("参数错误")


# ══════════════════════════════════════════════════════════
# DEGRADATION_HINTS 测试
# ══════════════════════════════════════════════════════════


class TestDegradationHints:
    """预定义降级提示"""

    def test_docker_status_hint_exists(self):
        """Docker 状态降级提示存在"""
        hint = DEGRADATION_HINTS.get("tools.env.docker_status")
        assert hint is not None
        assert "fallback_value" in hint
        assert hint["fallback_value"]["available"] is False
        assert "install_hint" in hint["fallback_value"]

    def test_docker_execute_hint_exists(self):
        """Docker 执行降级提示存在"""
        hint = DEGRADATION_HINTS.get("tools.env.docker_execute")
        assert hint is not None
        assert hint["fallback_value"]["success"] is False
        assert "Docker" in hint["fallback_value"]["error"]

    def test_security_scan_hint_exists(self):
        """安全扫描降级提示存在"""
        hint = DEGRADATION_HINTS.get("tools.quality.security_scan")
        assert hint is not None
        assert hint["fallback_value"]["success"] is True
        assert "pip-audit" in hint["fallback_value"]["install_hint"]

    def test_multilang_hint_exists(self):
        """多语言降级提示存在"""
        hint = DEGRADATION_HINTS.get("tools.exec.multilang")
        assert hint is not None
        assert hint["check_language"] is True
        assert "rust" in hint["install_hints"]
        assert "go" in hint["install_hints"]
        assert "java" in hint["install_hints"]
        assert "cpp" in hint["install_hints"]

    def test_dependency_analysis_hint_exists(self):
        """依赖分析降级提示存在"""
        hint = DEGRADATION_HINTS.get("tools.quality.dependency_analysis")
        assert hint is not None
        assert hint["fallback_value"]["success"] is True
        assert hint["fallback_value"]["dependencies"] == []


# ══════════════════════════════════════════════════════════
# get_degradation_hint 测试
# ══════════════════════════════════════════════════════════


class TestGetDegradationHint:
    """获取降级提示"""

    def test_get_existing_hint(self):
        """获取存在的降级提示"""
        hint = get_degradation_hint("tools.env.docker_status")
        assert hint is not None
        assert "fallback_value" in hint

    def test_get_nonexistent_hint(self):
        """获取不存在的降级提示返回 None"""
        hint = get_degradation_hint("tools.nonexistent.capability")
        assert hint is None

    def test_get_empty_string(self):
        """空字符串返回 None"""
        hint = get_degradation_hint("")
        assert hint is None


# ══════════════════════════════════════════════════════════
# wrap_handler 测试
# ══════════════════════════════════════════════════════════


class TestWrapHandler:
    """包装处理器"""

    @pytest.mark.asyncio
    async def test_wrap_success_handler(self):
        """包装成功的处理器"""
        wrapped = wrap_handler(_success_handler)
        result = await wrapped({"key": "hello"}, {"trace_id": "123"})
        assert result == {"success": True, "data": "hello"}

    @pytest.mark.asyncio
    async def test_wrap_handler_with_empty_params(self):
        """包装处理器，空参数"""
        wrapped = wrap_handler(_success_handler)
        result = await wrapped({}, {})
        assert result == {"success": True, "data": "default"}

    @pytest.mark.asyncio
    async def test_wrap_handler_file_not_found_error(self):
        """包装处理器，捕获 FileNotFoundError"""
        wrapped = wrap_handler(_error_handler)
        result = await wrapped({}, {})
        assert result["success"] is True
        assert result["available"] is False
        assert "未找到 docker" in result["reason"]
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_wrap_handler_generic_exception(self):
        """包装处理器，捕获通用异常"""
        wrapped = wrap_handler(_generic_error_handler)
        result = await wrapped({}, {})
        assert result["success"] is False
        assert "参数错误" in result["error"]

    @pytest.mark.asyncio
    async def test_wrap_handler_with_mock(self):
        """使用 mock 验证包装逻辑"""
        mock_handler = AsyncMock(return_value={"success": True, "result": "ok"})
        wrapped = wrap_handler(mock_handler)

        params = {"path": "test.py"}
        context = {"trace_id": "abc"}
        result = await wrapped(params, context)

        assert result == {"success": True, "result": "ok"}
        mock_handler.assert_called_once_with(params, context)

    @pytest.mark.asyncio
    async def test_wrap_handler_result_is_callable(self):
        """处理器返回可调用对象时，自动调用它"""
        async def handler(params, context):
            # 返回一个可调用对象
            def inner(p, c):
                return {"called": True, "inner_params": p}
            return inner

        wrapped = wrap_handler(handler)
        result = await wrapped({"test": 1}, {"ctx": "x"})
        assert result["called"] is True
        assert result["inner_params"] == {"test": 1}

    @pytest.mark.asyncio
    async def test_wrap_handler_long_error_message_truncated(self):
        """长错误消息被截断到 500 字符"""
        long_msg = "x" * 1000
        async def handler(params, context):
            raise RuntimeError(long_msg)

        wrapped = wrap_handler(handler)
        result = await wrapped({}, {})
        assert result["success"] is False
        assert len(result["error"]) <= 500

    @pytest.mark.asyncio
    async def test_wrap_handler_preserves_exception_in_error(self):
        """异常消息被保留在 error 字段中"""
        async def handler(params, context):
            raise ConnectionError("网络连接失败")

        wrapped = wrap_handler(handler)
        result = await wrapped({}, {})
        assert result["success"] is False
        assert "网络连接失败" in result["error"]