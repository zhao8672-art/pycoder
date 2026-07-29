"""LSP 反馈采集器单元测试

测试覆盖:
    - FeedbackSignal LSP 字段扩展
    - FeedbackLoop.collect_from_lsp_diagnostics
    - FeedbackLoop.get_lsp_feedback_stats
    - LSPFeedbackCollector 生命周期 (start/stop/flush)
    - LSPFeedbackCollector 自动 flush
    - LSPFeedbackCollector 错误模式学习报告
    - LSPFeedbackCollector 优雅降级
    - 与 LSPClient 集成 (诊断回调)
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from pycoder.capabilities.self_evo.learning.feedback_loop import (
    FeedbackLoop,
    FeedbackSignal,
)
from pycoder.lsp.client import Diagnostic, LSPClient
from pycoder.lsp.feedback_collector import (
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_FLUSH_THRESHOLD,
    LSPFeedbackCollector,
)


# ════════════════════════════════════════════════════════
# FeedbackSignal LSP 字段测试
# ════════════════════════════════════════════════════════


class TestFeedbackSignalLSPFields:
    """FeedbackSignal LSP 字段扩展测试"""

    def test_default_lsp_fields_empty(self) -> None:
        """默认 LSP 字段应为空值"""
        s = FeedbackSignal()
        assert s.lsp_error_codes == []
        assert s.lsp_source == ""
        assert s.lsp_error_count == 0
        assert s.lsp_warning_count == 0
        assert s.lsp_files_affected == 0

    def test_lsp_signal_type(self) -> None:
        """signal_type 支持 'lsp' 值"""
        s = FeedbackSignal(signal_type="lsp", lsp_source="pyright")
        assert s.signal_type == "lsp"
        assert s.lsp_source == "pyright"

    def test_lsp_signal_with_codes(self) -> None:
        """带错误码的 LSP 信号"""
        s = FeedbackSignal(
            signal_type="lsp",
            lsp_error_codes=["reportMissingImports", "reportUndefinedVariable"],
            lsp_error_count=2,
            lsp_source="pyright",
        )
        assert len(s.lsp_error_codes) == 2
        assert s.lsp_error_count == 2


# ════════════════════════════════════════════════════════
# FeedbackLoop LSP 集成测试
# ════════════════════════════════════════════════════════


def _make_diagnostic(
    file_path: str = "/tmp/main.py",
    line: int = 1,
    severity: str = "error",
    code: str = "",
    source: str = "pyright",
    message: str = "err",
) -> Diagnostic:
    """构造测试用 Diagnostic"""
    return Diagnostic(
        file_path=file_path,
        line=line,
        character=0,
        end_line=line,
        end_character=5,
        severity=severity,
        code=code,
        source=source,
        message=message,
    )


@pytest.fixture
def isolated_feedback_loop(tmp_path, monkeypatch) -> FeedbackLoop:
    """隔离的 FeedbackLoop (避免全局信号文件污染测试)

    将 FEEDBACK_DIR 重定向到临时目录, 确保每次测试从空状态开始。
    """
    from pycoder.capabilities.self_evo.learning import feedback_loop as fl_module

    monkeypatch.setattr(fl_module, "FEEDBACK_DIR", tmp_path)
    loop = FeedbackLoop()
    return loop


class TestFeedbackLoopLSPIntegration:
    """FeedbackLoop LSP 集成测试"""

    def test_collect_from_lsp_diagnostics_empty(self) -> None:
        """空诊断列表不应产生信号"""
        loop = FeedbackLoop()
        initial_count = len(loop._signals)
        loop.collect_from_lsp_diagnostics("T-001", [])
        assert len(loop._signals) == initial_count

    def test_collect_from_lsp_diagnostics_errors(self) -> None:
        """错误诊断应产生 failure 信号"""
        loop = FeedbackLoop()
        diags = [
            _make_diagnostic(
                code="reportMissingImports", severity="error", message="Missing import"
            ),
            _make_diagnostic(
                line=2,
                code="reportUndefinedVariable",
                severity="error",
                message="Undefined var",
            ),
        ]
        loop.collect_from_lsp_diagnostics("T-001", diags, lsp_source="pyright")
        assert len(loop._signals) >= 1
        signal = loop._signals[-1]
        assert signal.signal_type == "lsp"
        assert signal.outcome == "failure"
        assert signal.lsp_error_count == 2
        assert signal.lsp_warning_count == 0
        assert signal.lsp_source == "pyright"
        assert signal.test_passed is False
        # 错误码应被收集
        assert "reportMissingImports" in signal.lsp_error_codes
        assert "reportUndefinedVariable" in signal.lsp_error_codes
        # 主错误类型应取出现次数最多的 code (此处平局, 取任一)
        assert signal.error_type in (
            "reportMissingImports",
            "reportUndefinedVariable",
        )
        # 质量评分: 100 - 2*5 = 90
        assert signal.quality_score == 90.0

    def test_collect_from_lsp_diagnostics_warnings_only(self) -> None:
        """仅警告应产生 partial 信号"""
        loop = FeedbackLoop()
        diags = [
            _make_diagnostic(severity="warning", code="reportUnusedImport"),
            _make_diagnostic(line=2, severity="warning", code="reportUnusedVariable"),
        ]
        loop.collect_from_lsp_diagnostics("T-001", diags)
        signal = loop._signals[-1]
        assert signal.outcome == "partial"
        assert signal.lsp_error_count == 0
        assert signal.lsp_warning_count == 2
        assert signal.test_passed is True  # 无错误即视为通过
        # 质量评分: 100 - 2*2 = 96
        assert signal.quality_score == 96.0

    def test_collect_from_lsp_diagnostics_files_affected(self) -> None:
        """受影响文件数统计"""
        loop = FeedbackLoop()
        diags = [
            _make_diagnostic(file_path="/tmp/a.py", severity="error"),
            _make_diagnostic(file_path="/tmp/b.py", severity="error"),
            _make_diagnostic(file_path="/tmp/a.py", line=2, severity="error"),
        ]
        loop.collect_from_lsp_diagnostics("T-001", diags)
        signal = loop._signals[-1]
        # 3 个诊断但只影响 2 个文件
        assert signal.lsp_files_affected == 2

    def test_collect_from_lsp_diagnostics_quality_floor(self) -> None:
        """质量评分不应低于 0"""
        loop = FeedbackLoop()
        # 30 个错误: 100 - 30*5 = -50 → 应为 0
        diags = [
            _make_diagnostic(line=i, severity="error") for i in range(30)
        ]
        loop.collect_from_lsp_diagnostics("T-001", diags)
        signal = loop._signals[-1]
        assert signal.quality_score == 0.0

    def test_get_lsp_feedback_stats_empty(self, isolated_feedback_loop) -> None:
        """无 LSP 信号时统计应为零值"""
        loop = isolated_feedback_loop
        stats = loop.get_lsp_feedback_stats()
        assert stats["total_lsp_signals"] == 0
        assert stats["recent_lsp_signals"] == 0
        assert stats["top_error_codes"] == []
        assert stats["avg_error_count"] == 0.0
        assert stats["lsp_sources"] == {}

    def test_get_lsp_feedback_stats_with_signals(self, isolated_feedback_loop) -> None:
        """有 LSP 信号时统计应正确聚合"""
        loop = isolated_feedback_loop
        # 推送 3 次 LSP 诊断
        for i in range(3):
            diags = [
                _make_diagnostic(code="reportMissingImports", severity="error"),
                _make_diagnostic(line=2, code="reportUnusedImport", severity="warning"),
            ]
            loop.collect_from_lsp_diagnostics(f"T-{i:03d}", diags, lsp_source="pyright")

        stats = loop.get_lsp_feedback_stats()
        assert stats["total_lsp_signals"] == 3
        assert stats["recent_lsp_signals"] == 3
        # reportMissingImports 出现 3 次, reportUnusedImport 出现 3 次
        code_dict = dict(stats["top_error_codes"])
        assert code_dict.get("reportMissingImports") == 3
        assert code_dict.get("reportUnusedImport") == 3
        assert stats["avg_error_count"] == 1.0
        assert stats["avg_warning_count"] == 1.0
        assert stats["lsp_sources"] == {"pyright": 3}

    def test_signal_to_dict_includes_lsp_fields(self) -> None:
        """_signal_to_dict 应包含 LSP 字段"""
        loop = FeedbackLoop()
        diags = [_make_diagnostic(code="E1", severity="error")]
        loop.collect_from_lsp_diagnostics("T-001", diags, lsp_source="pyright")
        signal = loop._signals[-1]
        d = loop._signal_to_dict(signal)
        assert "lsp_error_codes" in d
        assert "lsp_source" in d
        assert "lsp_error_count" in d
        assert "lsp_warning_count" in d
        assert "lsp_files_affected" in d
        assert d["lsp_source"] == "pyright"
        assert d["lsp_error_count"] == 1


# ════════════════════════════════════════════════════════
# LSPFeedbackCollector 测试
# ════════════════════════════════════════════════════════


class TestLSPFeedbackCollectorInit:
    """采集器初始化测试"""

    def test_default_values(self) -> None:
        """默认配置"""
        collector = LSPFeedbackCollector()
        assert collector.enabled is False  # 无 client + loop
        assert collector._lsp_source == "pyright"
        assert collector._flush_interval == DEFAULT_FLUSH_INTERVAL
        assert collector._flush_threshold == DEFAULT_FLUSH_THRESHOLD

    def test_enabled_when_client_and_loop_provided(self) -> None:
        """提供 client + loop 时启用"""
        client = MagicMock(spec=LSPClient)
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(lsp_client=client, feedback_loop=loop)
        assert collector.enabled is True
        # 应注册到 client
        client.register_diagnostics_handler.assert_called_once()

    def test_register_handler_exception_isolated(self) -> None:
        """注册回调异常不应影响初始化"""
        client = MagicMock(spec=LSPClient)
        client.register_diagnostics_handler = MagicMock(
            side_effect=RuntimeError("boom")
        )
        loop = MagicMock(spec=FeedbackLoop)
        # 不应抛出异常
        collector = LSPFeedbackCollector(lsp_client=client, feedback_loop=loop)
        assert collector is not None


class TestLSPFeedbackCollectorLifecycle:
    """采集器生命周期测试"""

    def test_start_sets_task_id(self) -> None:
        """start 设置当前任务 ID"""
        collector = LSPFeedbackCollector()
        collector.start("T-001")
        assert collector._current_task_id == "T-001"
        assert collector._task_started_at > 0

    def test_start_flushes_existing_buffer(self) -> None:
        """start 时若有未 flush 的诊断应先 flush"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        # 添加一些诊断到缓冲
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        assert len(collector._buffer) == 1
        collector.start("T-002")
        # 缓冲应被清空
        assert len(collector._buffer) == 0
        # loop.collect_from_lsp_diagnostics 应被调用
        loop.collect_from_lsp_diagnostics.assert_called_once()

    def test_stop_flushes_buffer(self) -> None:
        """stop 时 flush 剩余诊断"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.start("T-001")
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        collector.stop()
        assert len(collector._buffer) == 0
        assert collector._current_task_id == ""
        loop.collect_from_lsp_diagnostics.assert_called_once()


class TestLSPFeedbackCollectorBuffering:
    """采集器诊断缓冲测试"""

    def test_add_diagnostics(self) -> None:
        """手动添加诊断"""
        collector = LSPFeedbackCollector()
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        assert "/tmp/main.py" in collector._buffer
        assert len(collector._buffer["/tmp/main.py"]) == 1

    def test_add_empty_diagnostics_clears_file(self) -> None:
        """添加空诊断列表应清除该文件 (LSP 语义)"""
        collector = LSPFeedbackCollector()
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        assert "/tmp/main.py" in collector._buffer
        collector.add_diagnostics("/tmp/main.py", [])
        assert "/tmp/main.py" not in collector._buffer

    def test_get_stats(self) -> None:
        """get_stats 返回采集器状态"""
        collector = LSPFeedbackCollector()
        collector.start("T-001")
        collector.add_diagnostics(
            "/tmp/a.py", [_make_diagnostic(severity="error")]
        )
        collector.add_diagnostics(
            "/tmp/b.py",
            [_make_diagnostic(severity="error"), _make_diagnostic(line=2, severity="warning")],
        )
        stats = collector.get_stats()
        assert stats["current_task_id"] == "T-001"
        assert stats["buffered_files"] == 2
        assert stats["buffered_diagnostics"] == 3
        assert stats["history_count"] == 0

    def test_reset(self) -> None:
        """reset 清空缓冲与历史"""
        collector = LSPFeedbackCollector()
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        collector._history.append({"test": True})
        collector.reset()
        assert len(collector._buffer) == 0
        assert len(collector._history) == 0


class TestLSPFeedbackCollectorFlush:
    """采集器 flush 测试"""

    def test_flush_empty_buffer_returns_none(self) -> None:
        """空缓冲 flush 返回 None"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        assert collector.flush() is None
        loop.collect_from_lsp_diagnostics.assert_not_called()

    def test_flush_pushes_to_feedback_loop(self) -> None:
        """flush 应将聚合诊断推送到 FeedbackLoop"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop, lsp_source="pyright")
        collector.start("T-001")
        collector.add_diagnostics(
            "/tmp/main.py",
            [
                _make_diagnostic(code="E1", severity="error"),
                _make_diagnostic(line=2, code="W1", severity="warning"),
            ],
        )
        result = collector.flush()
        assert result is not None
        assert result["error_count"] == 1
        assert result["warning_count"] == 1
        assert result["files_affected"] == 1
        # FeedbackLoop 应被调用
        loop.collect_from_lsp_diagnostics.assert_called_once()
        call_args = loop.collect_from_lsp_diagnostics.call_args
        assert call_args.kwargs["task_id"] == "T-001"
        assert call_args.kwargs["lsp_source"] == "pyright"
        assert len(call_args.kwargs["diagnostics"]) == 2

    def test_flush_clears_buffer(self) -> None:
        """flush 后缓冲应清空"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        collector.flush()
        assert len(collector._buffer) == 0

    def test_flush_records_history(self) -> None:
        """flush 应记录历史"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        collector.flush()
        assert len(collector._history) == 1
        assert collector._history[0]["error_count"] == 1

    def test_flush_feedback_loop_exception_isolated(self) -> None:
        """FeedbackLoop 异常不应影响 flush 流程"""
        loop = MagicMock(spec=FeedbackLoop)
        loop.collect_from_lsp_diagnostics = MagicMock(side_effect=RuntimeError("boom"))
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.add_diagnostics(
            "/tmp/main.py", [_make_diagnostic(severity="error")]
        )
        # 不应抛出异常
        result = collector.flush()
        # 仍应返回统计 (即使推送失败)
        assert result is not None
        assert result["error_count"] == 1
        # 缓冲仍应清空, 历史仍应记录
        assert len(collector._buffer) == 0
        assert len(collector._history) == 1

    def test_flush_stats_correctness(self) -> None:
        """flush 统计正确性"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.add_diagnostics(
            "/tmp/a.py",
            [
                _make_diagnostic(file_path="/tmp/a.py", code="E1", severity="error"),
                _make_diagnostic(file_path="/tmp/a.py", line=2, code="E1", severity="error"),
                _make_diagnostic(file_path="/tmp/a.py", line=3, code="W1", severity="warning"),
            ],
        )
        collector.add_diagnostics(
            "/tmp/b.py",
            [_make_diagnostic(file_path="/tmp/b.py", code="E2", severity="error")],
        )
        result = collector.flush()
        assert result is not None
        assert result["total"] == 4
        assert result["error_count"] == 3
        assert result["warning_count"] == 1
        assert result["files_affected"] == 2
        # error_codes 应为 top N 列表
        code_dict = dict(result["error_codes"])
        assert code_dict.get("E1") == 2
        assert code_dict.get("E2") == 1


class TestLSPFeedbackCollectorAutoFlush:
    """采集器自动 flush 测试"""

    def test_auto_flush_by_threshold(self) -> None:
        """诊断数达阈值时自动 flush"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(
            feedback_loop=loop,
            flush_threshold=3,
            flush_interval=3600,  # 避免时间触发
        )
        collector.start("T-001")
        # 添加 2 个诊断 (未达阈值)
        collector.add_diagnostics(
            "/tmp/a.py", [_make_diagnostic(severity="error")]
        )
        collector.add_diagnostics(
            "/tmp/b.py", [_make_diagnostic(severity="error")]
        )
        loop.collect_from_lsp_diagnostics.assert_not_called()
        # 添加第 3 个 (达阈值, 触发自动 flush)
        collector.add_diagnostics(
            "/tmp/c.py", [_make_diagnostic(severity="error")]
        )
        loop.collect_from_lsp_diagnostics.assert_called_once()

    def test_auto_flush_by_interval(self) -> None:
        """超过时间间隔时自动 flush"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(
            feedback_loop=loop,
            flush_threshold=100,  # 避免数量触发
            flush_interval=0.05,  # 50ms
        )
        collector.start("T-001")
        collector.add_diagnostics(
            "/tmp/a.py", [_make_diagnostic(severity="error")]
        )
        # 立即检查: 不应触发 (时间未到)
        loop.collect_from_lsp_diagnostics.assert_not_called()
        # 等待超过间隔
        time.sleep(0.1)
        # 添加新诊断应触发时间检查并 flush
        collector.add_diagnostics(
            "/tmp/b.py", [_make_diagnostic(severity="error")]
        )
        loop.collect_from_lsp_diagnostics.assert_called_once()

    def test_auto_flush_disabled(self) -> None:
        """auto_flush=False 时不自动 flush"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(
            feedback_loop=loop,
            flush_threshold=1,
            flush_interval=0,
            auto_flush=False,
        )
        collector.start("T-001")
        collector.add_diagnostics(
            "/tmp/a.py", [_make_diagnostic(severity="error")]
        )
        loop.collect_from_lsp_diagnostics.assert_not_called()


class TestLSPFeedbackCollectorLearningReport:
    """采集器错误模式学习报告测试"""

    def test_learning_report_empty_history(self) -> None:
        """无历史时报告为空"""
        collector = LSPFeedbackCollector()
        assert collector.get_learning_report() == ""

    def test_learning_report_with_errors(self) -> None:
        """有错误历史的报告应包含高频错误码"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        # 模拟多次 flush
        for _ in range(3):
            collector.add_diagnostics(
                "/tmp/main.py",
                [
                    _make_diagnostic(code="reportMissingImports", severity="error"),
                    _make_diagnostic(line=2, code="reportUnusedImport", severity="warning"),
                ],
            )
            collector.flush()

        report = collector.get_learning_report()
        assert "## LSP 错误模式学习报告" in report
        assert "reportMissingImports" in report
        assert "reportUnusedImport" in report
        assert "自进化建议" in report

    def test_learning_report_includes_fix_suggestions(self) -> None:
        """报告应包含错误码对应的修复建议"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.add_diagnostics(
            "/tmp/main.py",
            [_make_diagnostic(code="reportMissingImports", severity="error")],
        )
        collector.flush()
        report = collector.get_learning_report()
        # reportMissingImports 有内置建议
        assert "缺少导入" in report

    def test_learning_report_top_code_suggestion(self) -> None:
        """报告应针对最高频错误码给出建议"""
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(feedback_loop=loop)
        # 推送大量 reportUndefinedVariable 错误
        for _ in range(5):
            collector.add_diagnostics(
                "/tmp/main.py",
                [
                    _make_diagnostic(code="reportUndefinedVariable", severity="error"),
                ],
            )
            collector.flush()
        report = collector.get_learning_report()
        assert "reportUndefinedVariable" in report
        assert "自进化建议" in report

    def test_lookup_fix_suggestion_known_code(self) -> None:
        """已知错误码应返回修复建议"""
        suggestion = LSPFeedbackCollector._lookup_fix_suggestion(
            "reportMissingImports"
        )
        assert "缺少导入" in suggestion

    def test_lookup_fix_suggestion_unknown_code(self) -> None:
        """未知错误码应返回空字符串"""
        suggestion = LSPFeedbackCollector._lookup_fix_suggestion("unknownCode123")
        assert suggestion == ""

    def test_lookup_fix_suggestion_empty_code(self) -> None:
        """空错误码应返回空字符串"""
        assert LSPFeedbackCollector._lookup_fix_suggestion("") == ""


class TestLSPFeedbackCollectorClientIntegration:
    """采集器与 LSPClient 集成测试"""

    def test_registered_handler_receives_diagnostics(self) -> None:
        """注册的回调应接收 LSPClient 推送的诊断"""
        client = MagicMock(spec=LSPClient)
        loop = MagicMock(spec=FeedbackLoop)
        collector = LSPFeedbackCollector(lsp_client=client, feedback_loop=loop)

        # 模拟 LSPClient 注册的 handler
        handler = client.register_diagnostics_handler.call_args[0][0]
        # 推送诊断
        handler(
            "/tmp/main.py",
            [_make_diagnostic(code="E1", severity="error")],
        )
        # 缓冲应有诊断
        assert collector._buffer.get("/tmp/main.py")
        assert len(collector._buffer["/tmp/main.py"]) == 1

    def test_client_diagnostics_clear_propagates(self) -> None:
        """LSPClient 推送空诊断 (文件已无错误) 应清除缓冲"""
        client = MagicMock(spec=LSPClient)
        collector = LSPFeedbackCollector(lsp_client=client)
        handler = client.register_diagnostics_handler.call_args[0][0]

        # 先推送诊断
        handler("/tmp/main.py", [_make_diagnostic(severity="error")])
        assert "/tmp/main.py" in collector._buffer
        # 推送空列表
        handler("/tmp/main.py", [])
        assert "/tmp/main.py" not in collector._buffer


# ════════════════════════════════════════════════════════
# 端到端集成测试
# ════════════════════════════════════════════════════════


class TestLSPFeedbackEndToEnd:
    """LSP 诊断 → FeedbackLoop 端到端测试"""

    def test_full_pipeline_collect_and_stats(self, isolated_feedback_loop) -> None:
        """完整管道: 诊断 → 采集 → flush → FeedbackLoop → 统计"""
        # 使用隔离的 FeedbackLoop (而非 mock)
        loop = isolated_feedback_loop
        collector = LSPFeedbackCollector(feedback_loop=loop, lsp_source="pyright")
        collector.start("T-001")

        # 模拟 LSP 推送多次诊断
        for i in range(3):
            collector.add_diagnostics(
                f"/tmp/file{i}.py",
                [
                    _make_diagnostic(
                        file_path=f"/tmp/file{i}.py",
                        code="reportMissingImports",
                        severity="error",
                    ),
                    _make_diagnostic(
                        file_path=f"/tmp/file{i}.py",
                        line=2,
                        code="reportUnusedImport",
                        severity="warning",
                    ),
                ],
            )
        # flush 到 FeedbackLoop
        collector.flush()

        # 验证 FeedbackLoop 收到信号
        stats = loop.get_lsp_feedback_stats()
        assert stats["total_lsp_signals"] == 1
        assert stats["recent_lsp_signals"] == 1
        assert stats["avg_error_count"] == 3.0
        assert stats["avg_warning_count"] == 3.0
        code_dict = dict(stats["top_error_codes"])
        assert code_dict.get("reportMissingImports") == 3
        assert code_dict.get("reportUnusedImport") == 3
        assert stats["lsp_sources"] == {"pyright": 1}

    def test_full_pipeline_learning_report(self) -> None:
        """完整管道: 多次 flush → 学习报告"""
        loop = FeedbackLoop()
        collector = LSPFeedbackCollector(feedback_loop=loop)
        collector.start("T-001")

        # 模拟多次诊断 + flush
        for _ in range(5):
            collector.add_diagnostics(
                "/tmp/main.py",
                [
                    _make_diagnostic(code="reportMissingImports", severity="error"),
                    _make_diagnostic(line=2, code="reportUndefinedVariable", severity="error"),
                ],
            )
            collector.flush()

        report = collector.get_learning_report()
        assert "## LSP 错误模式学习报告" in report
        assert "reportMissingImports" in report
        assert "reportUndefinedVariable" in report
        # 累计 5 次 flush
        assert "5 次诊断聚合" in report
