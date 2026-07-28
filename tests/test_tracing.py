"""OpenTelemetry 追踪集成单元测试"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from pycoder.observability.tracing import (
    NoOpSpan,
    NoOpTracer,
    TracingConfig,
    TracingManager,
    get_current_span_id,
    get_current_trace_id,
    get_tracer,
    get_tracing_manager,
    is_available,
    is_enabled,
    span,
    status,
    traced,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前重置 TracingManager 单例"""
    TracingManager._instance = None
    TracingManager._initialized = False
    yield
    # 测试结束后优雅关闭，避免 BatchSpanProcessor 在解释器关闭时
    # 尝试写入已关闭的 stdout
    try:
        if TracingManager._instance is not None:
            TracingManager._instance.shutdown()
    except (RuntimeError, OSError, AttributeError):
        pass
    TracingManager._instance = None
    TracingManager._initialized = False


@pytest.fixture(autouse=True)
def clear_env():
    """清除 OTEL 环境变量"""
    env_keys = ["OTEL_ENABLED", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_CONSOLE_EXPORTER"]
    saved = {k: os.environ.pop(k, None) for k in env_keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


# ══════════════════════════════════════════════════════════
# TracingConfig
# ══════════════════════════════════════════════════════════


class TestTracingConfig:
    def test_default_values(self):
        cfg = TracingConfig()
        assert cfg.service_name == "pycoder"
        assert cfg.deployment_env == "development"
        assert cfg.enabled is False
        assert cfg.exporter_endpoint == ""
        assert cfg.console_exporter is False

    def test_enabled_from_env(self):
        os.environ["OTEL_ENABLED"] = "1"
        cfg = TracingConfig()
        assert cfg.enabled is True

    def test_endpoint_from_env(self):
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
        cfg = TracingConfig()
        assert cfg.exporter_endpoint == "http://localhost:4318"

    def test_console_exporter_from_env(self):
        os.environ["OTEL_CONSOLE_EXPORTER"] = "1"
        cfg = TracingConfig()
        assert cfg.console_exporter is True


# ══════════════════════════════════════════════════════════
# NoOpSpan / NoOpTracer
# ══════════════════════════════════════════════════════════


class TestNoOp:
    def test_noop_span_context_manager(self):
        s = NoOpSpan()
        with s as sp:
            sp.set_attribute("k", "v")
            sp.set_status("ok")
            sp.add_event("evt")
        s.end()  # 不抛错

    def test_noop_span_record_exception(self):
        s = NoOpSpan()
        try:
            raise ValueError("test")
        except ValueError as e:
            s.record_exception(e)  # 不抛错

    def test_noop_tracer_returns_noop_span(self):
        t = NoOpTracer()
        sp = t.start_as_current_span("op")
        assert isinstance(sp, NoOpSpan)
        sp2 = t.start_span("op2")
        assert isinstance(sp2, NoOpSpan)


# ══════════════════════════════════════════════════════════
# TracingManager
# ══════════════════════════════════════════════════════════


class TestTracingManager:
    def test_singleton(self):
        m1 = TracingManager()
        m2 = TracingManager()
        assert m1 is m2

    def test_default_disabled_returns_noop_tracer(self):
        mgr = TracingManager()
        assert isinstance(mgr.tracer, NoOpTracer)
        assert mgr.is_enabled is False

    def test_enabled_but_otel_not_installed(self):
        """如果 OTel 不可用，即使 enabled=True 也降级为 NoOp

        当 OTel 可用时，enabled=True 会启用真实 tracer。
        本测试根据运行时 OTel 可用性动态断言。
        """
        from pycoder.observability.tracing import _OTEL_AVAILABLE

        os.environ["OTEL_ENABLED"] = "1"
        mgr = TracingManager()
        if _OTEL_AVAILABLE:
            # OTel 可用 + enabled=True → 真实 tracer
            assert not isinstance(mgr.tracer, NoOpTracer)
            assert mgr.is_enabled is True
        else:
            # OTel 不可用 + enabled=True → 降级为 NoOp
            assert isinstance(mgr.tracer, NoOpTracer)

    def test_reconfigure(self):
        mgr = TracingManager()
        mgr.reconfigure(service_name="custom", deployment_env="production")
        assert mgr.config.service_name == "custom"
        assert mgr.config.deployment_env == "production"

    def test_shutdown_no_error(self):
        mgr = TracingManager()
        mgr.shutdown()  # 不抛错


# ══════════════════════════════════════════════════════════
# 全局函数
# ══════════════════════════════════════════════════════════


class TestGlobalFunctions:
    def test_get_tracer_returns_noop_when_disabled(self):
        t = get_tracer()
        assert isinstance(t, NoOpTracer)

    def test_get_tracing_manager_singleton(self):
        m1 = get_tracing_manager()
        m2 = get_tracing_manager()
        assert m1 is m2

    def test_is_available_returns_bool(self):
        assert isinstance(is_available(), bool)

    def test_is_enabled_returns_bool(self):
        assert isinstance(is_enabled(), bool)

    def test_status_returns_dict(self):
        s = status()
        assert isinstance(s, dict)
        assert "otel_available" in s
        assert "enabled" in s
        assert "service_name" in s

    def test_get_current_trace_id_empty_default(self):
        assert get_current_trace_id() == ""

    def test_get_current_span_id_empty_default(self):
        assert get_current_span_id() == ""


# ══════════════════════════════════════════════════════════
# traced 装饰器
# ══════════════════════════════════════════════════════════


class TestTracedDecorator:
    def test_sync_function_decorator(self):
        @traced("sync_op")
        def my_function(x: int) -> int:
            return x * 2

        result = my_function(21)
        assert result == 42

    def test_async_function_decorator(self):
        import asyncio

        @traced("async_op")
        async def my_async_function(x: int) -> int:
            return x * 3

        result = asyncio.run(my_async_function(14))
        assert result == 42

    def test_decorator_with_default_name(self):
        @traced()
        def my_function() -> str:
            return "ok"

        assert my_function() == "ok"

    def test_decorator_records_exception(self):
        @traced("failing_op", record_exception=True)
        def my_function() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            my_function()

    def test_decorator_no_record_exception(self):
        @traced("failing_op", record_exception=False)
        def my_function() -> None:
            raise ValueError("silent error")

        with pytest.raises(ValueError, match="silent error"):
            my_function()

    def test_decorator_preserves_function_metadata(self):
        @traced("with_metadata")
        def my_function(arg1: str, arg2: int = 5) -> str:
            """My docstring."""
            return f"{arg1}_{arg2}"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."
        assert my_function("test") == "test_5"

    def test_decorator_with_attributes(self):
        @traced("attr_op", attributes={"kind": "custom", "version": 1})
        def my_function() -> str:
            return "done"

        assert my_function() == "done"


# ══════════════════════════════════════════════════════════
# span 上下文管理器
# ══════════════════════════════════════════════════════════


class TestSpanContextManager:
    def test_span_no_attributes(self):
        with span("my_op") as s:
            assert s is not None

    def test_span_with_attributes(self):
        with span("my_op", attributes={"key": "value", "count": 42}) as s:
            assert s is not None

    def test_span_nested(self):
        with span("outer") as outer:
            with span("inner") as inner:
                assert outer is not None
                assert inner is not None

    def test_span_exception_propagates(self):
        with pytest.raises(ValueError, match="span error"):
            with span("error_op"):
                raise ValueError("span error")


# ══════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════


class TestIntegration:
    def test_decorated_function_inside_span(self):
        @traced("inner_op")
        def inner() -> str:
            return "inner_result"

        with span("outer_op"):
            result = inner()
        assert result == "inner_result"

    def test_multiple_decorated_calls(self):
        @traced("op1")
        def op1(x: int) -> int:
            return x + 1

        @traced("op2")
        def op2(x: int) -> int:
            return x * 2

        assert op1(10) == 11
        assert op2(10) == 20
        assert op1(op2(5)) == 11

    def test_status_dict_content_when_disabled(self):
        s = status()
        assert s["enabled"] is False
        assert s["service_name"] == "pycoder"
        assert s["current_trace_id"] == ""

    def test_reconfigure_takes_effect(self):
        mgr = get_tracing_manager()
        original_name = mgr.config.service_name
        mgr.reconfigure(service_name="test_service")
        s = status()
        assert s["service_name"] == "test_service"
        # 恢复
        mgr.reconfigure(service_name=original_name)


# ══════════════════════════════════════════════════════════
# 异步生成器 + reconfigure bug 修复 + structured_log 桥接
# ══════════════════════════════════════════════════════════


class TestAsyncGeneratorSupport:
    """验证 @traced 对 async generator 的支持"""

    def test_async_generator_decorator_preserves_values(self):
        """装饰 async generator 不影响 yield 的值"""
        import asyncio

        @traced("gen_op")
        async def my_gen(n: int):
            for i in range(n):
                yield i

        async def collect():
            return [x async for x in my_gen(5)]

        result = asyncio.run(collect())
        assert result == [0, 1, 2, 3, 4]

    def test_async_generator_decorator_with_attributes(self):
        """带 attributes 的 async generator 装饰器"""
        import asyncio

        @traced("gen_attr", attributes={"kind": "stream"})
        async def my_gen():
            yield "a"
            yield "b"

        async def collect():
            return [x async for x in my_gen()]

        result = asyncio.run(collect())
        assert result == ["a", "b"]

    def test_async_generator_decorator_propagates_exception(self):
        """async generator 内部异常正确传播"""
        import asyncio

        @traced("gen_err")
        async def my_gen():
            yield 1
            raise ValueError("gen failed")

        async def collect():
            return [x async for x in my_gen()]

        with pytest.raises(ValueError, match="gen failed"):
            asyncio.run(collect())


class TestReconfigurePreservesConfig:
    """验证 reconfigure 修改的配置在新的 TracingManager() 调用后保留"""

    def test_reconfigure_then_reinit_preserves_config(self):
        """reconfigure 后再次调用 TracingManager() 不应覆盖用户的修改

        这是 P2-C 修复的回归测试: 之前的 reconfigure 把 _initialized 设为 False,
        导致下次 TracingManager() 通过 __init__ 用新的 TracingConfig() 覆盖。
        """
        mgr1 = TracingManager()
        mgr1.reconfigure(service_name="custom_svc", deployment_env="staging")

        # 模拟后续代码再次获取单例
        mgr2 = TracingManager()
        assert mgr1 is mgr2
        assert mgr2.config.service_name == "custom_svc"
        assert mgr2.config.deployment_env == "staging"


class TestStructuredLogBridge:
    """验证 tracing 与 structured_log 的 trace_id 桥接"""

    def test_structured_log_imports_safely(self):
        """桥接代码不会因 structured_log 未导入而抛错"""
        from pycoder.observability import structured_log

        assert hasattr(structured_log, "_trace_id_var")
        assert hasattr(structured_log, "_span_id_var")

    def test_traced_function_does_not_break_log_context(self):
        """@traced 装饰的函数不会破坏现有 log 上下文"""
        from pycoder.observability.structured_log import (
            get_current_trace_id as slog_trace_id,
        )

        @traced("with_log_bridge")
        def my_function() -> str:
            # 函数内部访问 structured_log 的 trace_id（应为空，因为 tracing 默认禁用）
            _ = slog_trace_id()
            return "ok"

        assert my_function() == "ok"
