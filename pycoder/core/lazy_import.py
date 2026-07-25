"""P1-A: 模块级懒加载工具 — 减少启动时间

核心思想:
    将重型模块的 import 推迟到首次属性访问时执行，
    避免启动时一次性加载所有依赖。

用法 1: LazyModule 包装
    >>> from pycoder.core.lazy_import import lazy_module
    >>> chat_bridge = lazy_module("pycoder.server.chat_bridge", attr="ChatBridge")
    >>> # ChatBridge 模块此时未加载
    >>> bridge = chat_bridge()  # 首次访问触发 import

用法 2: lazy_callable 装饰器
    >>> @lazy_callable
    ... def get_bridge():
    ...     from pycoder.server.chat_bridge import ChatBridge
    ...     return ChatBridge()
"""
from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class LazyModule:
    """模块懒加载代理 — 首次访问任意属性时才执行 import

    设计要点:
        - 线程安全（双重检查锁定）
        - 记录加载耗时（用于启动性能分析）
        - 支持访问模块顶层属性 / 函数 / 类
        - 不支持 `from lazy_module import xxx` 语法（必须通过属性访问）

    示例:
        >>> deep_memory = LazyModule("pycoder.memory.deep_memory")
        >>> # 此时 pycoder.memory.deep_memory 尚未 import
        >>> memory = deep_memory.DeepMemory()  # 触发 import
    """

    __slots__ = ("_module_name", "_module", "_lock", "_loaded", "_load_ms")

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module: Any = None
        self._lock = threading.Lock()
        self._loaded = False
        self._load_ms: float = 0.0

    def _ensure_loaded(self) -> Any:
        """双重检查锁定加载模块"""
        if self._loaded:
            return self._module
        with self._lock:
            if self._loaded:
                return self._module
            t0 = time.perf_counter()
            try:
                # 如果模块已加载（被其他路径 import），直接复用
                if self._module_name in sys.modules:
                    self._module = sys.modules[self._module_name]
                else:
                    self._module = importlib.import_module(self._module_name)
                self._load_ms = (time.perf_counter() - t0) * 1000
                self._loaded = True
                logger.info(
                    "lazy_module_loaded name=%s ms=%.1f",
                    self._module_name,
                    self._load_ms,
                )
            except ImportError as e:
                logger.error(
                    "lazy_module_load_failed name=%s error=%s",
                    self._module_name,
                    e,
                )
                raise
            return self._module

    def __getattr__(self, item: str) -> Any:
        """首次访问属性时触发模块加载"""
        if item.startswith("_"):
            raise AttributeError(item)
        module = self._ensure_loaded()
        return getattr(module, item)

    def is_loaded(self) -> bool:
        """模块是否已加载"""
        return self._loaded

    @property
    def load_ms(self) -> float:
        """加载耗时（毫秒），未加载则返回 0"""
        return self._load_ms


def lazy_module(module_name: str) -> LazyModule:
    """工厂函数 — 创建 LazyModule 代理"""
    return LazyModule(module_name)


def lazy_callable(loader: Callable[[], Any]) -> Callable[..., Any]:
    """装饰器 — 将函数变为懒加载调用

    首次调用时执行 loader() 获取真实对象，后续调用直接复用。
    线程安全。

    示例:
        >>> @lazy_callable
        ... def get_chat_bridge():
        ...     from pycoder.server.chat_bridge import ChatBridge
        ...     return ChatBridge()
        >>> bridge = get_chat_bridge()  # 首次调用触发 import + 实例化
    """
    lock = threading.Lock()
    instance: list[Any] = []  # 使用 list 作为可变容器，避免 nonlocal
    loaded = [False]

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if loaded[0]:
            return instance[0]
        with lock:
            if loaded[0]:
                return instance[0]
            instance.append(loader())
            loaded[0] = True
            return instance[0]

    wrapper._lazy_loaded = lambda: loaded[0]  # type: ignore[attr-defined]
    return wrapper


class StartupProfiler:
    """启动性能埋点 — 记录关键阶段耗时

    用法:
        >>> profiler = StartupProfiler()
        >>> with profiler.measure("v2_engine_init"):
        ...     init_v2_engine()
        >>> profiler.report()
        v2_engine_init: 1234.5ms
    """

    def __init__(self) -> None:
        self._stages: list[tuple[str, float]] = []
        self._lock = threading.Lock()

    def measure(self, name: str):
        """上下文管理器 — 测量某个阶段耗时"""
        return _StageContext(self, name)

    def record(self, name: str, duration_ms: float) -> None:
        """记录一个阶段耗时"""
        with self._lock:
            self._stages.append((name, duration_ms))

    def report(self) -> dict[str, float]:
        """输出耗时报告（毫秒）"""
        with self._lock:
            return {name: ms for name, ms in self._stages}

    def format_report(self) -> str:
        """格式化耗时报告为字符串"""
        with self._lock:
            if not self._stages:
                return "StartupProfiler: no stages recorded"
            total = sum(ms for _, ms in self._stages)
            lines = [f"StartupProfiler (total={total:.1f}ms):"]
            for name, ms in self._stages:
                lines.append(f"  {name}: {ms:.1f}ms")
            return "\n".join(lines)


class _StageContext:
    """阶段计时上下文"""

    def __init__(self, profiler: StartupProfiler, name: str) -> None:
        self._profiler = profiler
        self._name = name
        self._t0: float = 0.0

    def __enter__(self) -> "_StageContext":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        duration_ms = (time.perf_counter() - self._t0) * 1000
        self._profiler.record(self._name, duration_ms)


# ── 全局启动性能记录器 ──────────────────────────────────────────
_global_profiler = StartupProfiler()


def get_startup_profiler() -> StartupProfiler:
    """获取全局启动性能记录器"""
    return _global_profiler


__all__ = [
    "LazyModule",
    "lazy_module",
    "lazy_callable",
    "StartupProfiler",
    "get_startup_profiler",
]
