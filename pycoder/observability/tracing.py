"""OpenTelemetry 分布式追踪集成

提供轻量级的链路追踪能力，所有方法均为条件加载：
- opentelemetry-sdk 未安装时降级到 NoOpTracer，不抛错
- 不设置 OTEL_EXPORTER_OTLP_ENDPOINT 时不发送任何数据
- 与现有 StructuredLogger 集成，自动注入 trace_id/span_id

设计原则:
1. 零侵入: 业务代码无需修改，通过装饰器/instrument 自动埋点
2. 渐进式: 默认 NoOp，安装 OTel 后自动启用
3. 可观测: trace_id 自动注入到结构化日志
4. 可控: 通过环境变量 OTEL_ENABLED=1 启用

快速开始:
    # 1. 安装依赖
    pip install opentelemetry-sdk opentelemetry-exporter-otlp

    # 2. 启用追踪（控制台输出）
    OTEL_ENABLED=1 OTEL_CONSOLE_EXPORTER=1 python -m pycoder.server.app

    # 3. 启用追踪 + OTLP 上报（Jaeger/Tempo/Grafana Cloud 等）
    OTEL_ENABLED=1 \\
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \\
    python -m pycoder.server.app

    # 4. 在业务代码中使用（无需修改已用 @traced 装饰的函数）
    from pycoder.observability.tracing import traced, span, get_current_trace_id

    @traced("my_operation", attributes={"kind": "custom"})
    async def my_function(...):
        # 日志自动带上 trace_id（通过 structured_log 桥接）
        log.info("processing")
        ...

    # 手动 span
    with span("manual_op") as s:
        s.set_attribute("key", "value")
        ...

环境变量:
    OTEL_ENABLED=1                    启用追踪（默认禁用）
    OTEL_EXPORTER_OTLP_ENDPOINT=URL   OTLP HTTP 端点（如 http://localhost:4318）
    OTEL_CONSOLE_EXPORTER=1           同时输出 spans 到 stdout（调试用）

已埋点的关键业务流程:
    - chat_bridge.chat / chat_stream  LLM 调用主入口
    - chat_bridge_tools.execute_tool_call  工具调用分发
    - ws_handler_v2._handle_chat_v2   WebSocket 聊天处理
    - skills_market.{install,uninstall,rate_skill,sync_from_remote}  技能市场
    - lifecycle.orchestrator.run      项目生命周期编排
"""

from __future__ import annotations

import logging
import os
import contextvars
import functools
import inspect
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

# ── OpenTelemetry 可选导入 ──────────────────────────────
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    trace = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False
    logger.info("opentelemetry-sdk 未安装，链路追踪降级为 NoOp")

# ── 上下文变量（trace_id/span_id 注入日志）──
_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="",
)
_SPAN_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "span_id", default="",
)


def get_current_trace_id() -> str:
    """获取当前上下文的 trace_id（用于日志注入）"""
    return _TRACE_ID.get()


def get_current_span_id() -> str:
    """获取当前上下文的 span_id（用于日志注入）"""
    return _SPAN_ID.get()


@dataclass
class TracingConfig:
    """追踪配置"""

    service_name: str = "pycoder"
    service_version: str = "0.1.0"
    deployment_env: str = "development"
    enabled: bool = field(default_factory=lambda: os.environ.get("OTEL_ENABLED", "0") == "1")
    exporter_endpoint: str = field(
        default_factory=lambda: os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    )
    console_exporter: bool = field(
        default_factory=lambda: os.environ.get("OTEL_CONSOLE_EXPORTER", "0") == "1"
    )


class NoOpSpan:
    """NoOp Span（OTel 不可用时使用）"""

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass

    def end(self) -> None:
        pass


class NoOpTracer:
    """NoOp Tracer（OTel 不可用时使用）"""

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: dict | None = None,
    ) -> NoOpSpan:
        return NoOpSpan()

    def start_span(
        self,
        name: str,
        *,
        attributes: dict | None = None,
    ) -> NoOpSpan:
        return NoOpSpan()


class TracingManager:
    """追踪管理器 — 单例

    用法:
        tracer = get_tracer()
        with tracer.start_as_current_span("my_operation") as span:
            span.set_attribute("key", "value")
            ...
    """

    _instance: "TracingManager | None" = None
    _initialized: bool = False

    def __new__(cls) -> "TracingManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._config = TracingConfig()
        # 委托给 _setup 完成实际初始化（_setup 不会重建 _config）
        self._tracer: Any = NoOpTracer()
        self._provider: Any = None
        self._initialized = True
        self._setup()

    def _setup(self) -> None:
        """初始化追踪器"""
        if not self._config.enabled:
            logger.debug("tracing_disabled set OTEL_ENABLED=1 to enable")
            return

        if not _OTEL_AVAILABLE:
            logger.warning(
                "tracing_requested_but_otel_not_installed "
                "pip install opentelemetry-sdk opentelemetry-exporter-otlp"
            )
            return

        try:
            resource = Resource.create(
                {
                    "service.name": self._config.service_name,
                    "service.version": self._config.service_version,
                    "deployment.environment": self._config.deployment_env,
                }
            )
            provider = TracerProvider(resource=resource)

            # 配置 exporter
            exporters: list = []
            if self._config.exporter_endpoint:
                exporters.append(
                    BatchSpanProcessor(
                        OTLPSpanExporter(endpoint=self._config.exporter_endpoint)
                    )
                )
            if self._config.console_exporter:
                exporters.append(BatchSpanProcessor(ConsoleSpanExporter()))

            if not exporters:
                # 默认使用 Console exporter
                exporters.append(BatchSpanProcessor(ConsoleSpanExporter()))

            for exp in exporters:
                provider.add_span_processor(exp)

            trace.set_tracer_provider(provider)
            self._provider = provider
            self._tracer = trace.get_tracer("pycoder")
            logger.info(
                "tracing_initialized service=%s env=%s endpoint=%s",
                self._config.service_name,
                self._config.deployment_env,
                self._config.exporter_endpoint or "console",
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("tracing_init_failed error=%s", e)
            self._tracer = NoOpTracer()

    @property
    def tracer(self) -> Any:
        """获取 tracer 实例"""
        return self._tracer

    @property
    def is_enabled(self) -> bool:
        """追踪是否启用"""
        return isinstance(self._tracer, NoOpTracer) is False

    @property
    def config(self) -> TracingConfig:
        return self._config

    def reconfigure(self, **kwargs: Any) -> None:
        """重新配置追踪器（运行时切换配置）

        注意：不重置 _initialized 标志，避免下次 TracingManager() 调用
        通过 __init__ 用全新的 TracingConfig() 覆盖用户的修改。
        """
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)
        # 重置内部状态后重新初始化（不重建 _config）
        self._tracer = NoOpTracer()
        self._provider = None
        self._setup()

    def shutdown(self) -> None:
        """关闭追踪器，刷新待发送的 spans"""
        if self._provider is not None:
            try:
                self._provider.shutdown()
                logger.debug("tracing_shutdown_ok")
            except (OSError, RuntimeError) as e:
                logger.warning("tracing_shutdown_failed error=%s", e)


# ── 全局单例 ────────────────────────────────────────────

def get_tracer() -> Any:
    """获取全局 tracer 实例

    Returns:
        OTel Tracer 或 NoOpTracer
    """
    return TracingManager().tracer


def get_tracing_manager() -> TracingManager:
    """获取 TracingManager 单例"""
    return TracingManager()


# ── 装饰器：自动埋点 ────────────────────────────────────

def traced(
    name: str | None = None,
    *,
    attributes: dict | None = None,
    record_exception: bool = True,
) -> Callable[[Callable], Callable]:
    """函数装饰器：自动创建 span

    Args:
        name: span 名称（默认使用 函数名）
        attributes: 静态属性
        record_exception: 是否自动记录异常

    用法:
        @traced("my_operation", attributes={"kind": "custom"})
        async def my_function(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__}.{func.__name__}"

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                # 注入静态属性
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                # 注入上下文 trace_id 到 contextvar
                _inject_trace_context(span)

                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    if record_exception:
                        span.record_exception(e)
                    raise

        @functools.wraps(func)
        async def async_gen_wrapper(*args: Any, **kwargs: Any) -> Any:
            """异步生成器包装：在 span 内 yield 每个事件"""
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as s:
                if attributes:
                    for k, v in attributes.items():
                        s.set_attribute(k, v)
                _inject_trace_context(s)

                start = time.perf_counter()
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                    s.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                    s.set_status(Status(StatusCode.OK))
                except Exception as e:
                    s.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                    s.set_status(Status(StatusCode.ERROR, str(e)))
                    if record_exception:
                        s.record_exception(e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                _inject_trace_context(span)

                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    if record_exception:
                        span.record_exception(e)
                    raise

        if inspect.isasyncgenfunction(func):
            return async_gen_wrapper
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


@contextmanager
def span(
    name: str,
    *,
    attributes: dict | None = None,
) -> Iterator[Any]:
    """上下文管理器：手动创建 span

    用法:
        with span("my_operation", attributes={"key": "value"}) as s:
            s.set_attribute("custom", 42)
            ...
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                s.set_attribute(k, v)
        _inject_trace_context(s)
        yield s


def _inject_trace_context(current_span: Any) -> None:
    """注入 trace_id/span_id 到 ContextVar（供日志使用）

    同时同步到 structured_log 模块的 contextvars，确保 StructuredLogger
    输出的日志自动带上 trace_id/span_id 字段。
    """
    if not _OTEL_AVAILABLE or isinstance(current_span, NoOpSpan):
        return
    try:
        ctx = current_span.get_span_context()
        if ctx and ctx.is_valid:
            trace_id = f"{ctx.trace_id:032x}"
            span_id = f"{ctx.span_id:016x}"
            _TRACE_ID.set(trace_id)
            _SPAN_ID.set(span_id)
            # 同步到 structured_log 模块的 contextvars
            try:
                from pycoder.observability import structured_log as _slog

                _slog._trace_id_var.set(trace_id)
                _slog._span_id_var.set(span_id)
            except ImportError:
                pass
    except (AttributeError, ValueError):
        pass


# ── 便捷方法 ────────────────────────────────────────────

def is_available() -> bool:
    """OpenTelemetry SDK 是否可用"""
    return _OTEL_AVAILABLE


def is_enabled() -> bool:
    """追踪是否启用"""
    return TracingManager().is_enabled


def status() -> dict[str, Any]:
    """获取追踪状态（供健康检查/调试使用）"""
    mgr = TracingManager()
    return {
        "otel_available": _OTEL_AVAILABLE,
        "enabled": mgr.is_enabled,
        "service_name": mgr.config.service_name,
        "deployment_env": mgr.config.deployment_env,
        "exporter_endpoint": mgr.config.exporter_endpoint or "(none)",
        "console_exporter": mgr.config.console_exporter,
        "current_trace_id": get_current_trace_id(),
        "current_span_id": get_current_span_id(),
    }


__all__ = [
    "TracingConfig",
    "TracingManager",
    "NoOpSpan",
    "NoOpTracer",
    "get_tracer",
    "get_tracing_manager",
    "get_current_trace_id",
    "get_current_span_id",
    "traced",
    "span",
    "is_available",
    "is_enabled",
    "status",
]
