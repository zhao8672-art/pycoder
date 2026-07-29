"""P1-A: 懒加载工具单元测试

验证:
- LazyModule 首次访问触发 import
- 线程安全
- 启动性能埋点准确
"""

from __future__ import annotations

import threading
import time

import pytest

from pycoder.core.lazy_import import (
    LazyModule,
    StartupProfiler,
    get_startup_profiler,
    lazy_callable,
    lazy_module,
)

# ──────────────────────────────────────────────────────────────
# LazyModule 测试
# ──────────────────────────────────────────────────────────────


class TestLazyModule:
    """LazyModule 行为测试"""

    def test_not_loaded_on_creation(self) -> None:
        """创建 LazyModule 时不应触发 import"""
        proxy = LazyModule("os")  # os 是轻量模块，但同样验证
        assert proxy.is_loaded() is False

    def test_loaded_on_attribute_access(self) -> None:
        """首次访问属性时触发 import"""
        proxy = LazyModule("os.path")
        _ = proxy.join  # 触发 import
        assert proxy.is_loaded() is True

    def test_returns_correct_attribute(self) -> None:
        """返回的属性应与直接 import 一致"""
        import os.path as osp

        proxy = LazyModule("os.path")
        assert proxy.join is osp.join
        assert proxy.dirname is osp.dirname

    def test_load_ms_recorded(self) -> None:
        """加载耗时被记录"""
        proxy = LazyModule("json")
        _ = proxy.loads
        assert proxy.load_ms >= 0.0  # 至少为 0
        assert proxy.is_loaded() is True

    def test_raises_on_underscore_attribute(self) -> None:
        """下划线属性不应触发加载（防止内部属性污染）"""
        proxy = LazyModule("os")
        with pytest.raises(AttributeError):
            _ = proxy._internal_attr

    def test_failed_import_raises(self) -> None:
        """不存在的模块应抛出 ImportError"""
        proxy = LazyModule("pycoder.nonexistent.module.xyz")
        with pytest.raises(ImportError):
            _ = proxy.some_attr

    def test_thread_safety(self) -> None:
        """多线程并发访问只加载一次"""
        proxy = LazyModule("calendar")
        results: list[object] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                results.append(proxy.month_name)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20
        assert proxy.is_loaded() is True

    def test_reuses_existing_module(self) -> None:
        """已加载的模块应直接从 sys.modules 复用"""
        import sys

        # json 已经被前面的测试加载
        assert "json" in sys.modules
        proxy = LazyModule("json")
        result = proxy.dumps
        assert result is sys.modules["json"].dumps


# ──────────────────────────────────────────────────────────────
# lazy_module 工厂函数测试
# ──────────────────────────────────────────────────────────────


class TestLazyModuleFactory:
    """lazy_module 工厂函数测试"""

    def test_factory_returns_lazy_module(self) -> None:
        proxy = lazy_module("os")
        assert isinstance(proxy, LazyModule)

    def test_factory_lazy_until_access(self) -> None:
        proxy = lazy_module("os.path")
        assert proxy.is_loaded() is False
        _ = proxy.exists
        assert proxy.is_loaded() is True


# ──────────────────────────────────────────────────────────────
# lazy_callable 装饰器测试
# ──────────────────────────────────────────────────────────────


class TestLazyCallable:
    """lazy_callable 装饰器测试"""

    def test_loader_called_once(self) -> None:
        """loader 函数应只调用一次"""
        call_count = [0]

        @lazy_callable
        def get_thing():
            call_count[0] += 1
            return {"value": 42}

        r1 = get_thing()
        r2 = get_thing()
        r3 = get_thing()

        assert call_count[0] == 1
        assert r1 is r2 is r3
        assert r1["value"] == 42

    def test_lazy_until_first_call(self) -> None:
        """装饰后 loader 不会被立即执行"""
        executed = [False]

        @lazy_callable
        def get_thing():
            executed[0] = True
            return "ready"

        assert executed[0] is False
        result = get_thing()
        assert executed[0] is True
        assert result == "ready"

    def test_thread_safety(self) -> None:
        """多线程并发调用 loader 只执行一次"""
        call_count = [0]
        lock = threading.Lock()

        @lazy_callable
        def get_thing():
            with lock:
                call_count[0] += 1
            time.sleep(0.01)  # 模拟耗时初始化
            return object()

        results: list[object] = []
        threads = [threading.Thread(target=lambda: results.append(get_thing())) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count[0] == 1
        assert all(r is results[0] for r in results)

    def test_lazy_loaded_flag(self) -> None:
        """_lazy_loaded 标记应正确反映加载状态"""

        @lazy_callable
        def get_thing():
            return "ok"

        assert get_thing._lazy_loaded() is False
        get_thing()
        assert get_thing._lazy_loaded() is True


# ──────────────────────────────────────────────────────────────
# StartupProfiler 测试
# ──────────────────────────────────────────────────────────────


class TestStartupProfiler:
    """StartupProfiler 启动性能记录器测试"""

    def test_empty_report(self) -> None:
        profiler = StartupProfiler()
        assert profiler.report() == {}
        assert "no stages" in profiler.format_report()

    def test_record_stage(self) -> None:
        profiler = StartupProfiler()
        profiler.record("test_stage", 123.4)
        report = profiler.report()
        assert report["test_stage"] == 123.4

    def test_measure_context(self) -> None:
        profiler = StartupProfiler()
        with profiler.measure("sleep_stage"):
            time.sleep(0.05)
        report = profiler.report()
        assert "sleep_stage" in report
        assert report["sleep_stage"] >= 40.0  # 至少 40ms（容忍误差）

    def test_multiple_stages(self) -> None:
        profiler = StartupProfiler()
        with profiler.measure("a"):
            pass
        with profiler.measure("b"):
            pass
        report = profiler.report()
        assert len(report) == 2
        assert "a" in report
        assert "b" in report

    def test_format_report_contains_total(self) -> None:
        profiler = StartupProfiler()
        profiler.record("x", 100.0)
        profiler.record("y", 200.0)
        text = profiler.format_report()
        assert "total=300.0" in text
        assert "x: 100.0" in text
        assert "y: 200.0" in text

    def test_thread_safety(self) -> None:
        """多线程并发 record 不丢数据"""
        profiler = StartupProfiler()

        def worker() -> None:
            for i in range(50):
                profiler.record(f"stage_{threading.get_ident()}_{i}", float(i))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 8 threads × 50 records = 400
        assert len(profiler.report()) == 400


# ──────────────────────────────────────────────────────────────
# 全局 profiler 测试
# ──────────────────────────────────────────────────────────────


class TestGlobalProfiler:
    """全局启动记录器测试"""

    def test_singleton(self) -> None:
        p1 = get_startup_profiler()
        p2 = get_startup_profiler()
        assert p1 is p2

    def test_can_record(self) -> None:
        profiler = get_startup_profiler()
        before = len(profiler.report())
        profiler.record("test_global_stage", 1.0)
        after = len(profiler.report())
        assert after == before + 1


# ──────────────────────────────────────────────────────────────
# 集成场景: 懒加载真实模块
# ──────────────────────────────────────────────────────────────


class TestLazyModuleIntegration:
    """懒加载真实 pycoder 模块"""

    def test_lazy_load_pycoder_module(self) -> None:
        """懒加载 pycoder 内部模块"""
        proxy = lazy_module("pycoder.core.lazy_import")
        assert proxy.is_loaded() is False
        # 访问 LazyModule 类
        cls = proxy.LazyModule
        assert cls is LazyModule
        assert proxy.is_loaded() is True

    def test_repeated_access_does_not_reload(self) -> None:
        proxy = lazy_module("json")
        v1 = proxy.dumps
        v2 = proxy.dumps
        assert v1 is v2
