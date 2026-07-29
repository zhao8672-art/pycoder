"""P2-A: 统一结构化日志聚合 — JSON 输出 + 多 sink + 上下文注入

设计动机:
    现有日志分散在各模块，使用 logging.getLogger(__name__) 各自为政，
    缺乏统一字段（trace_id/span_id/user_id），难以聚合查询。

    本模块提供:
    - StructuredLogger: 统一 JSON 日志格式
    - LogContext: 上下文管理器（自动注入 trace_id/user_id/...）
    - 多 sink: stdout / 文件 / OTLP（可插拔）
    - 与标准 logging 模块兼容（通过 StructuredFormatter）

输出格式（单行 JSON）:
    {"ts":"2026-07-25T10:00:00Z","level":"info","msg":"chat_completed",
     "logger":"pycoder.server.ws_handler_v2","trace_id":"abc123",
     "span_id":"def456","duration_ms":1234,"user_id":"u1",...}

使用方式:
    from pycoder.observability.structured_log import get_structured_logger

    log = get_structured_logger("pycoder.server.ws_handler_v2")

    # 简单日志
    log.info("chat_started", user_id="u1", model="deepseek-chat")

    # 上下文注入
    from pycoder.observability.structured_log import LogContext
    with LogContext(trace_id="abc123", user_id="u1"):
        log.info("processing")  # 自动带 trace_id 和 user_id
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
from datetime import UTC, datetime
from typing import Any

# ── 上下文变量（contextvars 保证 async 安全）──────────────────
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("log_trace_id", default="")
_span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("log_span_id", default="")
_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("log_user_id", default="")
_session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("log_session_id", default="")
_extra_vars: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_extra", default={}
)


# ════════════════════════════════════════════════════════════════════════════
# LogContext — 上下文管理器
# ════════════════════════════════════════════════════════════════════════════


class LogContext:
    """日志上下文管理器 — 自动注入字段到所有日志

    支持 async 上下文（contextvars 自动隔离）。

    用法:
        with LogContext(trace_id="abc", user_id="u1"):
            log.info("processing")  # 自动带 trace_id, user_id

        # 嵌套
        with LogContext(trace_id="outer"):
            log.info("outer")
            with LogContext(span_id="inner"):
                log.info("inner")  # 同时有 trace_id 和 span_id
    """

    def __init__(
        self,
        trace_id: str | None = None,
        span_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        **extra: Any,
    ) -> None:
        self._new_values: dict[str, Any] = {}
        if trace_id is not None:
            self._new_values["trace_id"] = trace_id
        if span_id is not None:
            self._new_values["span_id"] = span_id
        if user_id is not None:
            self._new_values["user_id"] = user_id
        if session_id is not None:
            self._new_values["session_id"] = session_id
        if extra:
            self._new_values["extra"] = extra
        self._tokens: list[Any] = []

    def __enter__(self) -> LogContext:
        for key, value in self._new_values.items():
            if key == "trace_id":
                self._tokens.append(_trace_id_var.set(value))
            elif key == "span_id":
                self._tokens.append(_span_id_var.set(value))
            elif key == "user_id":
                self._tokens.append(_user_id_var.set(value))
            elif key == "session_id":
                self._tokens.append(_session_id_var.set(value))
            elif key == "extra":
                old_extra = _extra_vars.get()
                merged = {**old_extra, **value}
                self._tokens.append(_extra_vars.set(merged))
        return self

    def __exit__(self, *exc: Any) -> None:
        # 反向 reset（栈式恢复）
        for token in reversed(self._tokens):
            try:
                token.var.reset(token)
            except (ValueError, LookupError):
                pass

    async def __aenter__(self) -> LogContext:
        return self.__enter__()

    async def __aexit__(self, *exc: Any) -> None:
        self.__exit__(*exc)


def get_current_trace_id() -> str:
    """获取当前上下文的 trace_id"""
    return _trace_id_var.get()


def get_current_span_id() -> str:
    """获取当前上下文的 span_id"""
    return _span_id_var.get()


def get_current_user_id() -> str:
    """获取当前上下文的 user_id"""
    return _user_id_var.get()


def get_current_session_id() -> str:
    """获取当前上下文的 session_id"""
    return _session_id_var.get()


# ════════════════════════════════════════════════════════════════════════════
# Sink — 日志输出目标
# ════════════════════════════════════════════════════════════════════════════


class LogSink:
    """日志 sink 基类"""

    def emit(self, record: dict[str, Any]) -> None:
        """输出一条日志记录"""
        raise NotImplementedError

    def flush(self) -> None:
        """刷新缓冲区"""


class StdoutSink(LogSink):
    """标准输出 sink（JSON 单行）"""

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()

    def emit(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()

    def flush(self) -> None:
        try:
            self._stream.flush()
        except (AttributeError, OSError):
            pass


class FileSink(LogSink):
    """文件 sink（追加模式，按行 JSON）"""

    def __init__(self, file_path: str) -> None:
        from pathlib import Path

        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self._path, "a", encoding="utf-8")  # noqa: SIM115

    def emit(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            except OSError:
                pass

    def flush(self) -> None:
        try:
            self._fh.flush()
        except (AttributeError, OSError):
            pass

    def close(self) -> None:
        try:
            self._fh.close()
        except (AttributeError, OSError):
            pass


class BufferSink(LogSink):
    """内存缓冲 sink（用于测试）"""

    def __init__(self, max_size: int = 1000) -> None:
        self._records: list[dict[str, Any]] = []
        self._max = max_size
        self._lock = threading.Lock()

    def emit(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max:
                self._records = self._records[-self._max :]

    def flush(self) -> None:
        pass

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


# ════════════════════════════════════════════════════════════════════════════
# StructuredLogger — 主日志器
# ════════════════════════════════════════════════════════════════════════════


_LEVEL_NAMES = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "error",
    "CRITICAL": "critical",
}


class StructuredLogger:
    """结构化日志器 — JSON 输出 + 上下文注入

    线程安全。多 sink 并行输出。

    用法:
        log = StructuredLogger("pycoder.server.app")
        log.info("server_started", port=8423)
        log.error("db_failed", error=str(e), retry_count=3)
    """

    def __init__(
        self,
        name: str,
        sinks: list[LogSink] | None = None,
        level: str = "INFO",
    ) -> None:
        self._name = name
        self._sinks = sinks if sinks is not None else _default_sinks()
        self._level = level.upper()
        self._level_value = _level_to_value(self._level)

    def debug(self, msg: str, **fields: Any) -> None:
        if self._level_value <= 10:
            self._emit("DEBUG", msg, fields)

    def info(self, msg: str, **fields: Any) -> None:
        if self._level_value <= 20:
            self._emit("INFO", msg, fields)

    def warning(self, msg: str, **fields: Any) -> None:
        if self._level_value <= 30:
            self._emit("WARNING", msg, fields)

    def error(self, msg: str, **fields: Any) -> None:
        if self._level_value <= 40:
            self._emit("ERROR", msg, fields)

    def critical(self, msg: str, **fields: Any) -> None:
        if self._level_value <= 50:
            self._emit("CRITICAL", msg, fields)

    def exception(self, msg: str, **fields: Any) -> None:
        """记录异常（自动附带 traceback）"""
        import traceback

        tb = traceback.format_exc()
        fields["traceback"] = tb
        self._emit("ERROR", msg, fields)

    def set_level(self, level: str) -> None:
        """动态调整日志级别"""
        self._level = level.upper()
        self._level_value = _level_to_value(self._level)

    def add_sink(self, sink: LogSink) -> None:
        """添加新的输出 sink"""
        self._sinks.append(sink)

    def _emit(self, level: str, msg: str, fields: dict[str, Any]) -> None:
        """构建并输出日志记录"""
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": _LEVEL_NAMES.get(level, "info"),
            "msg": msg,
            "logger": self._name,
        }

        # 注入上下文变量
        trace_id = _trace_id_var.get()
        if trace_id:
            record["trace_id"] = trace_id
        span_id = _span_id_var.get()
        if span_id:
            record["span_id"] = span_id
        user_id = _user_id_var.get()
        if user_id:
            record["user_id"] = user_id
        session_id = _session_id_var.get()
        if session_id:
            record["session_id"] = session_id

        # 合并额外上下文
        extra = _extra_vars.get()
        if extra:
            for k, v in extra.items():
                if k not in record:
                    record[k] = v

        # 合并调用方字段（覆盖上下文）
        for k, v in fields.items():
            record[k] = v

        # 输出到所有 sink
        for sink in self._sinks:
            try:
                sink.emit(record)
            except Exception as e:
                # sink 失败不能影响主流程
                sys.stderr.write(f"log_sink_failed sink={type(sink).__name__} error={e}\n")


def _level_to_value(level: str) -> int:
    """级别名称转数值"""
    return {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }.get(level.upper(), 20)


# ════════════════════════════════════════════════════════════════════════════
# 全局 sink 配置
# ════════════════════════════════════════════════════════════════════════════


_global_sinks: list[LogSink] = []
_sinks_lock = threading.Lock()
_global_level: str = "INFO"


def _default_sinks() -> list[LogSink]:
    """获取默认 sink 列表（复制全局配置）"""
    with _sinks_lock:
        if not _global_sinks:
            _global_sinks.append(StdoutSink())
        return list(_global_sinks)


def configure_sinks(
    sinks: list[LogSink] | None = None,
    level: str = "INFO",
) -> None:
    """配置全局 sink 和级别

    Args:
        sinks: sink 列表（None 表示保留默认 stdout）
        level: 全局日志级别
    """
    global _global_level
    with _sinks_lock:
        if sinks is not None:
            _global_sinks.clear()
            _global_sinks.extend(sinks)
        _global_level = level.upper()


def add_file_sink(file_path: str) -> FileSink:
    """添加文件 sink（便捷方法）"""
    sink = FileSink(file_path)
    with _sinks_lock:
        _global_sinks.append(sink)
    return sink


def reset_sinks() -> None:
    """重置为默认 stdout sink（用于测试）"""
    with _sinks_lock:
        _global_sinks.clear()
        _global_sinks.append(StdoutSink())


# ── logger 工厂 ─────────────────────────────────────────────


_loggers: dict[str, StructuredLogger] = {}


def get_structured_logger(name: str) -> StructuredLogger:
    """获取或创建一个结构化日志器

    Args:
        name: 日志器名称（通常 __name__）

    Returns:
        StructuredLogger 实例（同名复用）
    """
    if name in _loggers:
        return _loggers[name]
    logger = StructuredLogger(name, level=_global_level)
    _loggers[name] = logger
    return logger


# ════════════════════════════════════════════════════════════════════════════
# 与标准 logging 桥接（可选）
# ════════════════════════════════════════════════════════════════════════════


class StructuredFormatter(logging.Formatter):
    """标准 logging.Formatter 的 JSON 等价物

    将标准 logging.LogRecord 格式化为 JSON 字符串，
    用于桥接第三方库（uvicorn/fastapi）的 logging 输出。

    用法:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        logging.getLogger("uvicorn").addHandler(handler)
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "logger": record.name,
        }

        # 注入上下文
        trace_id = _trace_id_var.get()
        if trace_id:
            log_data["trace_id"] = trace_id
        span_id = _span_id_var.get()
        if span_id:
            log_data["span_id"] = span_id

        # 异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 额外字段
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            }:
                log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False, default=str)


def install_structured_logging(level: str = "INFO") -> None:
    """安装结构化日志到根 logger（影响所有标准 logging 调用）

    Args:
        level: 全局日志级别
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 移除现有 handler，避免重复输出
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # 添加结构化 handler
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)


__all__ = [
    "LogContext",
    "LogSink",
    "StdoutSink",
    "FileSink",
    "BufferSink",
    "StructuredLogger",
    "StructuredFormatter",
    "get_structured_logger",
    "configure_sinks",
    "add_file_sink",
    "reset_sinks",
    "install_structured_logging",
    "get_current_trace_id",
    "get_current_span_id",
    "get_current_user_id",
    "get_current_session_id",
]
