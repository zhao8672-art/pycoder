"""意识引擎测试 — ConsciousnessEngine 与 SystemEvent"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.brain.consciousness import (
    ConsciousnessEngine,
    OperatingMode,
    SystemEvent,
)


# ══════════════════════════════════════════════════════════
# SystemEvent 数据类测试
# ══════════════════════════════════════════════════════════


class TestSystemEvent:
    """SystemEvent 数据类"""

    def test_create_event_defaults(self):
        """默认值创建事件"""
        event = SystemEvent(event_type="file_changed")
        assert event.event_type == "file_changed"
        assert event.source == ""
        assert event.summary == ""
        assert event.severity == "info"
        assert event.data == {}
        assert event.auto_fixable is False
        assert isinstance(event.timestamp, float)

    def test_create_event_full(self):
        """完整参数创建事件"""
        event = SystemEvent(
            event_type="error",
            source="lsp",
            summary="类型错误: str 无法赋值给 int",
            severity="error",
            data={"line": 42, "file": "main.py"},
            auto_fixable=True,
        )
        assert event.event_type == "error"
        assert event.source == "lsp"
        assert event.summary == "类型错误: str 无法赋值给 int"
        assert event.severity == "error"
        assert event.data["line"] == 42
        assert event.auto_fixable is True

    def test_event_timestamp_custom(self):
        """自定义时间戳"""
        ts = 1234567890.0
        event = SystemEvent(event_type="test", timestamp=ts)
        assert event.timestamp == ts


# ══════════════════════════════════════════════════════════
# OperatingMode 枚举测试
# ══════════════════════════════════════════════════════════


class TestOperatingMode:
    """OperatingMode 枚举"""

    def test_all_modes_exist(self):
        """验证所有运行模式存在"""
        assert OperatingMode.IDLE.value == "idle"
        assert OperatingMode.AWARE.value == "aware"
        assert OperatingMode.FOCUSED.value == "focused"
        assert OperatingMode.REFLECT.value == "reflect"

    def test_enum_is_string(self):
        """验证枚举是字符串类型"""
        mode = OperatingMode.IDLE
        assert isinstance(mode, str)
        assert mode == "idle"


# ══════════════════════════════════════════════════════════
# ConsciousnessEngine 核心测试
# ══════════════════════════════════════════════════════════


class TestConsciousnessEngine:
    """意识引擎核心功能"""

    @pytest.fixture
    def engine(self):
        """创建意识引擎实例"""
        return ConsciousnessEngine()

    def test_initial_mode_is_idle(self, engine):
        """初始模式应为 IDLE"""
        assert engine.mode == OperatingMode.IDLE

    def test_set_mode(self, engine):
        """切换运行模式"""
        engine.set_mode(OperatingMode.AWARE)
        assert engine.mode == OperatingMode.AWARE

        engine.set_mode(OperatingMode.FOCUSED)
        assert engine.mode == OperatingMode.FOCUSED

        engine.set_mode(OperatingMode.REFLECT)
        assert engine.mode == OperatingMode.REFLECT

        engine.set_mode(OperatingMode.IDLE)
        assert engine.mode == OperatingMode.IDLE

    def test_set_mode_all_transitions(self, engine):
        """验证所有模式切换"""
        modes = list(OperatingMode)
        for mode in modes:
            engine.set_mode(mode)
            assert engine.mode == mode

    @pytest.mark.asyncio
    async def test_perceive_critical_in_idle(self, engine):
        """IDLE 模式下仅处理 critical 级别事件"""
        # 注册一个 mock handler
        handler = AsyncMock()
        engine.on("test_event", handler)

        # 普通事件在 IDLE 模式下应被忽略
        event = SystemEvent(event_type="test_event", severity="info")
        await engine.perceive(event)
        # handler 不会被调用，因为事件未达到阈值（buffer 为 1 条，但 IDLE 模式下只允许 critical）
        # 但 perceive 会直接 return in IDLE mode for non-critical
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_perceive_critical_in_idle_processed(self, engine):
        """IDLE 模式下 critical 事件应被处理"""
        handler = AsyncMock()
        engine.on("critical_event", handler)

        event = SystemEvent(
            event_type="critical_event",
            severity="critical",
            summary="系统故障",
        )
        await engine.perceive(event)

        # 给异步任务一点时间
        await asyncio.sleep(0.01)
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_perceive_in_aware_mode(self, engine):
        """AWARE 模式下处理所有事件"""
        engine.set_mode(OperatingMode.AWARE)
        handler = AsyncMock()
        engine.on("test_event", handler)

        event = SystemEvent(event_type="test_event", severity="info")
        await engine.perceive(event)

        await asyncio.sleep(0.01)
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_perceive_in_focused_mode(self, engine):
        """FOCUSED 模式下处理所有事件"""
        engine.set_mode(OperatingMode.FOCUSED)
        handler = AsyncMock()
        engine.on("test_event", handler)

        event = SystemEvent(event_type="test_event", severity="warning")
        await engine.perceive(event)

        await asyncio.sleep(0.01)
        handler.assert_called_once()

    def test_register_handler(self, engine):
        """注册事件处理器"""
        handler = MagicMock()
        engine.on("custom_event", handler)
        assert len(engine._handlers["custom_event"]) == 1
        assert engine._handlers["custom_event"][0] is handler

    def test_register_multiple_handlers(self, engine):
        """同一事件类型注册多个处理器"""
        h1 = MagicMock()
        h2 = MagicMock()
        engine.on("multi_event", h1)
        engine.on("multi_event", h2)
        assert len(engine._handlers["multi_event"]) == 2

    @pytest.mark.asyncio
    async def test_event_buffering_and_merge(self, engine):
        """事件缓冲与合并"""
        engine.set_mode(OperatingMode.AWARE)
        handler = AsyncMock()
        engine.on("file_save", handler)

        # 发送 5 个 file_save 事件以达到阈值
        for i in range(5):
            event = SystemEvent(
                event_type="file_save",
                source="vscode",
                summary=f"文件保存 {i}",
            )
            await engine.perceive(event)

        await asyncio.sleep(0.01)
        # 阈值 5 到达后触发合并处理
        handler.assert_called_once()
        # 合并后的事件应包含合并信息
        called_event = handler.call_args[0][0]
        assert "合并" in called_event.summary

    @pytest.mark.asyncio
    async def test_sync_handler(self, engine):
        """同步处理器也能被调用"""
        engine.set_mode(OperatingMode.AWARE)
        sync_handler = MagicMock()
        engine.on("sync_event", sync_handler)

        event = SystemEvent(event_type="sync_event", severity="info")
        await engine.perceive(event)

        await asyncio.sleep(0.01)
        sync_handler.assert_called_once()

    def test_generate_awareness_report(self, engine):
        """生成感知报告"""
        report = engine.generate_awareness_report()
        assert "mode" in report
        assert report["mode"] == "idle"
        assert "queue_size" in report
        assert isinstance(report["queue_size"], int)
        assert "buffered_events" in report
        assert "last_action_seconds_ago" in report

    @pytest.mark.asyncio
    async def test_generate_awareness_report_after_events(self, engine):
        """处理事件后生成感知报告"""
        engine.set_mode(OperatingMode.AWARE)

        event = SystemEvent(event_type="file_save", severity="info")
        await engine.perceive(event)

        report = engine.generate_awareness_report()
        assert report["mode"] == "aware"
        # 缓冲区可能有未达阈值的事件
        assert "buffered_events" in report

    @pytest.mark.asyncio
    async def test_on_file_changed_in_focused_mode(self, engine):
        """FOCUSED 模式下文件变化处理被跳过"""
        engine.set_mode(OperatingMode.FOCUSED)
        event = SystemEvent(
            event_type="file_changed",
            source="vscode",
            summary="main.py 已修改",
        )
        await engine._on_file_changed(event)
        # 不应抛出异常，静默跳过

    @pytest.mark.asyncio
    async def test_on_git_change(self, engine):
        """Git 变化处理"""
        event = SystemEvent(
            event_type="git_change",
            summary="新提交: feat: 添加新功能",
        )
        await engine._on_git_change(event)
        # 不应抛出异常

    @pytest.mark.asyncio
    async def test_on_test_failure_auto_fixable(self, engine):
        """测试失败且可自动修复"""
        engine.set_mode(OperatingMode.AWARE)
        event = SystemEvent(
            event_type="test_failure",
            summary="test_add 失败",
            auto_fixable=True,
        )
        await engine._on_test_failure(event)
        # 不应抛出异常，应尝试自动修复

    @pytest.mark.asyncio
    async def test_on_test_failure_not_auto_fixable(self, engine):
        """测试失败但不可自动修复"""
        engine.set_mode(OperatingMode.AWARE)
        event = SystemEvent(
            event_type="test_failure",
            summary="test_add 失败",
            auto_fixable=False,
        )
        await engine._on_test_failure(event)
        # 不应抛出异常

    @pytest.mark.asyncio
    async def test_on_security_issue(self, engine):
        """安全问题处理"""
        event = SystemEvent(
            event_type="security_issue",
            summary="检测到硬编码密钥",
            severity="critical",
        )
        await engine._on_security_issue(event)
        # 不应抛出异常

    @pytest.mark.asyncio
    async def test_on_perf_regression(self, engine):
        """性能回归处理"""
        event = SystemEvent(
            event_type="performance_regression",
            summary="API 响应时间增加 200%",
        )
        await engine._on_perf_regression(event)
        # 不应抛出异常

    @pytest.mark.asyncio
    async def test_handler_exception_isolation(self, engine):
        """单个处理器异常不影响其他处理器"""
        engine.set_mode(OperatingMode.AWARE)

        failing_handler = AsyncMock(side_effect=RuntimeError("处理失败"))
        good_handler = AsyncMock()

        engine.on("isolated_event", failing_handler)
        engine.on("isolated_event", good_handler)

        event = SystemEvent(event_type="isolated_event", severity="info")
        await engine.perceive(event)

        await asyncio.sleep(0.01)
        # 失败的处理器被调用
        failing_handler.assert_called_once()
        # 好的处理器也应被调用（异常隔离）
        good_handler.assert_called_once()

    def test_merge_events_single(self, engine):
        """单事件合并返回自身"""
        event = SystemEvent(
            event_type="test",
            source="src",
            summary="单个事件",
            severity="error",
        )
        merged = ConsciousnessEngine._merge_events([event])
        assert merged.event_type == "test"
        assert merged.summary == "单个事件"

    def test_merge_events_multiple(self, engine):
        """多事件合并"""
        events = [
            SystemEvent(
                event_type="file_save",
                source="vscode",
                summary="保存 main.py",
                severity="info",
            )
            for _ in range(3)
        ]
        merged = ConsciousnessEngine._merge_events(events)
        assert merged.event_type == "file_save"
        assert "合并了 3 个事件" in merged.summary

    @pytest.mark.asyncio
    async def test_perceive_empty_event_dataset(self, engine):
        """空 data 事件正常处理"""
        engine.set_mode(OperatingMode.AWARE)
        handler = AsyncMock()
        engine.on("empty_data", handler)

        event = SystemEvent(event_type="empty_data", severity="info")
        await engine.perceive(event)

        await asyncio.sleep(0.01)
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_handlers_registered(self, engine):
        """默认处理器已注册"""
        assert "file_changed" in engine._handlers
        assert "git_change" in engine._handlers
        assert "test_failure" in engine._handlers
        assert "security_issue" in engine._handlers
        assert "performance_regression" in engine._handlers