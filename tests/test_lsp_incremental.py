"""LSP 增量诊断测试 — 测试 get_incremental_diagnostics 方法"""
from __future__ import annotations

from unittest.mock import MagicMock

from pycoder.lsp.client import Diagnostic, LSPClient
from pycoder.lsp.context_integration import LSPContextIntegrator


def _make_mock_client_with_diags(
    file_diags: dict[str, list[Diagnostic]],
) -> MagicMock:
    """构造带诊断数据的 mock LSPClient"""
    client = MagicMock(spec=LSPClient)
    client.get_diagnostics = MagicMock(
        side_effect=lambda fp="": file_diags.get(fp, []) if fp else []
    )
    client.get_all_diagnostics = MagicMock(return_value=dict(file_diags))
    return client


class TestIncrementalDiagnostics:
    """LSPContextIntegrator.get_incremental_diagnostics 测试"""

    def test_no_changed_lines_returns_empty(self) -> None:
        """无变化范围返回空列表"""
        client = MagicMock(spec=LSPClient)
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.get_incremental_diagnostics("main.py", [])
        assert result == []

    def test_filters_by_changed_range(self) -> None:
        """仅返回变化范围内的诊断"""
        diags = [
            Diagnostic(file_path="main.py", line=5, severity="error", message="e5"),
            Diagnostic(file_path="main.py", line=10, severity="error", message="e10"),
            Diagnostic(file_path="main.py", line=15, severity="warning", message="w15"),
            Diagnostic(file_path="main.py", line=100, severity="error", message="e100"),
        ]
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics(
            "main.py", [(8, 12)], all_diagnostics=diags
        )
        assert len(result) == 1
        assert result[0].line == 10

    def test_buffer_expands_range(self) -> None:
        """buffer 参数扩大命中范围"""
        diags = [
            Diagnostic(file_path="main.py", line=8, severity="error", message="e8"),
            Diagnostic(file_path="main.py", line=9, severity="error", message="e9"),
            Diagnostic(file_path="main.py", line=12, severity="error", message="e12"),
            Diagnostic(file_path="main.py", line=15, severity="error", message="e15"),
        ]
        integrator = LSPContextIntegrator()
        # changed [10, 10], buffer=2 → 命中 8~12
        result = integrator.get_incremental_diagnostics(
            "main.py", [(10, 10)], all_diagnostics=diags, buffer=2
        )
        lines = {d.line for d in result}
        assert lines == {8, 9, 12}

    def test_buffer_zero_no_expansion(self) -> None:
        """buffer=0 时仅命中完全在范围内的诊断"""
        diags = [
            Diagnostic(file_path="main.py", line=8, severity="error", message="e8"),
            Diagnostic(file_path="main.py", line=10, severity="error", message="e10"),
            Diagnostic(file_path="main.py", line=12, severity="error", message="e12"),
        ]
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics(
            "main.py", [(10, 10)], all_diagnostics=diags, buffer=0
        )
        assert len(result) == 1
        assert result[0].line == 10

    def test_multiple_changed_ranges(self) -> None:
        """支持多个变化范围 (取并集)"""
        diags = [
            Diagnostic(file_path="main.py", line=3, severity="error", message="e3"),
            Diagnostic(file_path="main.py", line=8, severity="error", message="e8"),
            Diagnostic(file_path="main.py", line=20, severity="error", message="e20"),
            Diagnostic(file_path="main.py", line=25, severity="error", message="e25"),
        ]
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics(
            "main.py", [(2, 4), (19, 21)], all_diagnostics=diags
        )
        lines = {d.line for d in result}
        assert lines == {3, 20}

    def test_filter_by_file_path(self) -> None:
        """过滤其他文件的诊断"""
        diags = [
            Diagnostic(file_path="main.py", line=10, severity="error", message="e1"),
            Diagnostic(file_path="other.py", line=10, severity="error", message="e2"),
        ]
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics(
            "main.py", [(0, 100)], all_diagnostics=diags
        )
        assert len(result) == 1
        assert result[0].file_path == "main.py"

    def test_sorted_by_severity_and_line(self) -> None:
        """结果按严重度优先级 + 行号排序"""
        diags = [
            Diagnostic(file_path="main.py", line=10, severity="warning", message="w10"),
            Diagnostic(file_path="main.py", line=5, severity="error", message="e5"),
            Diagnostic(file_path="main.py", line=15, severity="error", message="e15"),
        ]
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics(
            "main.py", [(0, 100)], all_diagnostics=diags
        )
        # 严重度优先 (error < warning), 然后按行号
        assert [(d.severity, d.line) for d in result] == [
            ("error", 5),
            ("error", 15),
            ("warning", 10),
        ]

    def test_no_client_no_diagnostics_returns_empty(self) -> None:
        """无 LSPClient 且无传入诊断时返回空"""
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics("main.py", [(0, 10)])
        assert result == []

    def test_fetches_from_client_when_no_diagnostics(self) -> None:
        """未传 all_diagnostics 时从 LSPClient 拉取"""
        file_path = "main.py"
        diags = [
            Diagnostic(file_path=file_path, line=10, severity="error", message="e"),
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.get_incremental_diagnostics(file_path, [(0, 20)])
        assert len(result) == 1
        assert result[0].line == 10

    def test_client_exception_returns_empty(self) -> None:
        """LSPClient 异常时不抛出, 返回空列表"""
        client = MagicMock(spec=LSPClient)
        client.get_diagnostics = MagicMock(side_effect=RuntimeError("boom"))
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.get_incremental_diagnostics("main.py", [(0, 10)])
        assert result == []

    def test_buffer_clamps_to_zero(self) -> None:
        """变化范围起始 < buffer 时被夹紧到 0"""
        diags = [
            Diagnostic(file_path="main.py", line=0, severity="error", message="e0"),
            Diagnostic(file_path="main.py", line=3, severity="error", message="e3"),
        ]
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics(
            "main.py", [(1, 1)], all_diagnostics=diags, buffer=5
        )
        # [1, 1] - 5 = -4 夹紧到 0, +5 = 6 → 命中 0~6
        lines = {d.line for d in result}
        assert lines == {0, 3}

    def test_empty_diagnostics_returns_empty(self) -> None:
        """传入空诊断列表时返回空"""
        integrator = LSPContextIntegrator()
        result = integrator.get_incremental_diagnostics("main.py", [(0, 10)], [])
        assert result == []
