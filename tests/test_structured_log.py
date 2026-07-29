"""P2-A: 统一结构化日志聚合单元测试

验证:
- StructuredLogger JSON 输出
- LogContext 上下文注入（同步 + 异步）
- 多 sink 输出
- contextvars 隔离（async 安全）
- 与标准 logging 桥接
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

from pycoder.observability.structured_log import (
    BufferSink,
    FileSink,
    LogContext,
    StructuredFormatter,
    StructuredLogger,
    add_file_sink,
    configure_sinks,
    get_current_session_id,
    get_current_span_id,
    get_current_trace_id,
    get_current_user_id,
    get_structured_logger,
    install_structured_logging,
    reset_sinks,
)


@pytest.fixture
def buffer_logger() -> tuple[StructuredLogger, BufferSink]:
    """创建带 buffer sink 的 logger（便于断言）"""
    sink = BufferSink()
    logger = StructuredLogger("test", sinks=[sink], level="DEBUG")
    return logger, sink


# ──────────────────────────────────────────────────────────────
# StructuredLogger 测试
# ──────────────────────────────────────────────────────────────


class TestStructuredLogger:
    """结构化日志器测试"""

    def test_basic_info(self, buffer_logger) -> None:
        log, sink = buffer_logger
        log.info("test_msg", key1="value1", key2=42)
        records = sink.records
        assert len(records) == 1
        r = records[0]
        assert r["msg"] == "test_msg"
        assert r["level"] == "info"
        assert r["key1"] == "value1"
        assert r["key2"] == 42
        assert r["logger"] == "test"
        assert "ts" in r

    def test_all_levels(self, buffer_logger) -> None:
        log, sink = buffer_logger
        log.debug("d")
        log.info("i")
        log.warning("w")
        log.error("e")
        log.critical("c")
        levels = [r["level"] for r in sink.records]
        assert levels == ["debug", "info", "warning", "error", "critical"]

    def test_level_filtering(self, buffer_logger) -> None:
        """低于设定级别的日志不输出"""
        log, sink = buffer_logger
        log.set_level("WARNING")
        log.debug("d")  # 被过滤
        log.info("i")  # 被过滤
        log.warning("w")  # 输出
        log.error("e")  # 输出
        assert len(sink.records) == 2

    def test_exception_logging(self, buffer_logger) -> None:
        log, sink = buffer_logger
        try:
            raise ValueError("test error")
        except ValueError:
            log.exception("op_failed", op="db")
        r = sink.records[0]
        assert r["level"] == "error"
        assert r["op"] == "db"
        assert "traceback" in r
        assert "ValueError" in r["traceback"]

    def test_complex_value_serialization(self, buffer_logger) -> None:
        """复杂值能被序列化"""
        log, sink = buffer_logger
        log.info(
            "complex",
            data={"list": [1, 2, 3], "nested": {"a": True}},
            none_val=None,
        )
        r = sink.records[0]
        assert r["data"] == {"list": [1, 2, 3], "nested": {"a": True}}
        assert r["none_val"] is None


# ──────────────────────────────────────────────────────────────
# LogContext 测试
# ──────────────────────────────────────────────────────────────


class TestLogContext:
    """日志上下文测试"""

    def test_trace_id_injection(self, buffer_logger) -> None:
        log, sink = buffer_logger
        with LogContext(trace_id="abc-123"):
            log.info("op")
        r = sink.records[0]
        assert r["trace_id"] == "abc-123"

    def test_context_cleanup_after_exit(self, buffer_logger) -> None:
        log, sink = buffer_logger
        with LogContext(trace_id="abc"):
            log.info("inside")
        log.info("outside")
        assert sink.records[0]["trace_id"] == "abc"
        assert "trace_id" not in sink.records[1]

    def test_nested_contexts(self, buffer_logger) -> None:
        log, sink = buffer_logger
        with LogContext(trace_id="outer"):
            log.info("a")
            with LogContext(span_id="inner"):
                log.info("b")
            log.info("c")
        assert sink.records[0]["trace_id"] == "outer"
        assert "span_id" not in sink.records[0]
        assert sink.records[1]["trace_id"] == "outer"
        assert sink.records[1]["span_id"] == "inner"
        assert sink.records[2]["trace_id"] == "outer"
        assert "span_id" not in sink.records[2]

    def test_all_context_fields(self, buffer_logger) -> None:
        log, sink = buffer_logger
        with LogContext(
            trace_id="t1",
            span_id="s1",
            user_id="u1",
            session_id="sess1",
        ):
            log.info("op")
        r = sink.records[0]
        assert r["trace_id"] == "t1"
        assert r["span_id"] == "s1"
        assert r["user_id"] == "u1"
        assert r["session_id"] == "sess1"

    def test_extra_fields(self, buffer_logger) -> None:
        log, sink = buffer_logger
        with LogContext(custom_field="custom_value"):
            log.info("op")
        r = sink.records[0]
        assert r["custom_field"] == "custom_value"

    def test_field_overwrite_in_log_call(self, buffer_logger) -> None:
        """日志调用时的字段覆盖上下文"""
        log, sink = buffer_logger
        with LogContext(user_id="ctx_user"):
            log.info("op", user_id="explicit_user")
        r = sink.records[0]
        assert r["user_id"] == "explicit_user"

    @pytest.mark.asyncio
    async def test_async_context_isolation(self, buffer_logger) -> None:
        """async 任务间上下文隔离"""
        log, sink = buffer_logger

        async def task(trace_id: str) -> None:
            with LogContext(trace_id=trace_id):
                await asyncio.sleep(0.01)
                log.info("op", task_name=trace_id)

        await asyncio.gather(
            task("task_a"),
            task("task_b"),
        )

        # 两条日志应该有各自的 trace_id
        trace_ids = sorted(r["trace_id"] for r in sink.records)
        assert trace_ids == ["task_a", "task_b"]


# ──────────────────────────────────────────────────────────────
# 上下文读取函数测试
# ──────────────────────────────────────────────────────────────


class TestContextGetters:
    """上下文 getter 函数测试"""

    def test_default_empty(self) -> None:
        assert get_current_trace_id() == ""
        assert get_current_span_id() == ""
        assert get_current_user_id() == ""
        assert get_current_session_id() == ""

    def test_get_inside_context(self) -> None:
        with LogContext(trace_id="t1", user_id="u1"):
            assert get_current_trace_id() == "t1"
            assert get_current_user_id() == "u1"
        # 退出后恢复
        assert get_current_trace_id() == ""


# ──────────────────────────────────────────────────────────────
# Sink 测试
# ──────────────────────────────────────────────────────────────


class TestSinks:
    """sink 测试"""

    def test_buffer_sink_max_size(self) -> None:
        sink = BufferSink(max_size=3)
        for i in range(10):
            sink.emit({"i": i})
        # 只保留最后 3 条
        assert len(sink.records) == 3
        assert sink.records[0]["i"] == 7
        assert sink.records[-1]["i"] == 9

    def test_buffer_sink_clear(self) -> None:
        sink = BufferSink()
        sink.emit({"a": 1})
        sink.clear()
        assert sink.records == []

    def test_file_sink_writes_jsonl(self, tmp_path: Path) -> None:
        path = tmp_path / "logs" / "app.jsonl"
        sink = FileSink(str(path))
        sink.emit({"msg": "first", "level": "info"})
        sink.emit({"msg": "second", "level": "error"})
        sink.flush()

        content = path.read_text(encoding="utf-8")
        lines = [json.loads(line) for line in content.strip().split("\n")]
        assert len(lines) == 2
        assert lines[0]["msg"] == "first"
        assert lines[1]["level"] == "error"

    def test_multiple_sinks(self) -> None:
        """一个 logger 同时输出到多个 sink"""
        sink1 = BufferSink()
        sink2 = BufferSink()
        log = StructuredLogger("multi", sinks=[sink1, sink2], level="DEBUG")
        log.info("broadcast")
        assert len(sink1.records) == 1
        assert len(sink2.records) == 1
        assert sink1.records[0] == sink2.records[0]


# ──────────────────────────────────────────────────────────────
# 全局配置测试
# ──────────────────────────────────────────────────────────────


class TestGlobalConfig:
    """全局 sink 配置测试"""

    def setup_method(self) -> None:
        reset_sinks()

    def test_reset_clears_to_stdout(self, tmp_path: Path) -> None:
        sink = add_file_sink(str(tmp_path / "test_log.jsonl"))
        reset_sinks()
        # 重新获取 logger，应该用默认 stdout
        log = get_structured_logger("test_reset")
        # 不抛异常即可
        log.info("test")

    def test_configure_sinks(self) -> None:
        buf = BufferSink()
        configure_sinks(sinks=[buf], level="DEBUG")
        # 新 logger 应该使用新配置
        # （注意：现有 logger 不会自动更新，仅新创建的会用新配置）
        log = StructuredLogger("configured")
        log.info("test")
        # 至少不抛异常

    def test_get_structured_logger_caches(self) -> None:
        l1 = get_structured_logger("cached_logger")
        l2 = get_structured_logger("cached_logger")
        assert l1 is l2


# ──────────────────────────────────────────────────────────────
# 标准 logging 桥接测试
# ──────────────────────────────────────────────────────────────


class TestStandardLoggingBridge:
    """与标准 logging 桥接测试"""

    def test_structured_formatter_outputs_json(self) -> None:
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "hello world"
        assert data["level"] == "info"
        assert data["logger"] == "test.logger"

    def test_structured_formatter_with_exception(self) -> None:
        formatter = StructuredFormatter()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "RuntimeError" in data["exception"]

    def test_install_structured_logging(self) -> None:
        """install 后标准 logging 输出 JSON"""
        import io

        buf = io.StringIO()
        # 临时替换 stderr
        import sys

        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            install_structured_logging("INFO")
            std_log = logging.getLogger("test_install")
            std_log.info("installed_test")
        finally:
            sys.stderr = old_stderr

        output = buf.getvalue()
        # 应该包含 JSON 行
        assert "installed_test" in output
        # 恢复默认 logging 配置
        logging.getLogger().handlers.clear()
        logging.basicConfig()


# ──────────────────────────────────────────────────────────────
# 集成场景
# ──────────────────────────────────────────────────────────────


class TestIntegration:
    """集成场景测试"""

    def test_context_with_logger(self) -> None:
        """LogContext 与 StructuredLogger 配合使用"""
        sink = BufferSink()
        log = StructuredLogger("integration", sinks=[sink], level="DEBUG")

        with LogContext(trace_id="req-123", user_id="user-456"):
            log.info("request_received", path="/api/chat")
            with LogContext(span_id="span-1"):
                log.info("llm_call_started", model="deepseek-chat")
                log.info("llm_call_completed", duration_ms=1234)
            log.info("request_completed", status="ok")

        records = sink.records
        # 所有记录都应有 trace_id 和 user_id
        for r in records:
            assert r["trace_id"] == "req-123"
            assert r["user_id"] == "user-456"
        # 中间两条有 span_id
        assert records[1]["span_id"] == "span-1"
        assert records[2]["span_id"] == "span-1"
        # 第一条和最后一条没有 span_id
        assert "span_id" not in records[0]
        assert "span_id" not in records[3]

    def test_logger_factory_with_context(self) -> None:
        """工厂函数创建的 logger 也能感知上下文"""
        sink = BufferSink()
        configure_sinks(sinks=[sink], level="DEBUG")
        # 创建一个新 logger
        log = StructuredLogger("factory_test", sinks=[sink], level="DEBUG")

        with LogContext(trace_id="factory-1"):
            log.info("op")
        r = sink.records[0]
        assert r["trace_id"] == "factory-1"
        reset_sinks()
