"""LSP 上下文集成单元测试

测试覆盖:
    - Diagnostic 数据类 (新增)
    - LSPClient 诊断捕获 (publishDiagnostics 处理 + 缓存 + 回调)
    - LSPContextIntegrator (收集/过滤/格式化/锚点片段)
    - DiagnosticsAggregator (LSPClient 模式)
    - ContextOrchestrator 与 LSP 集成 (端到端注入)
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from pycoder.lsp.client import (
    DIAGNOSTIC_SEVERITY,
    Diagnostic,
    LSPClient,
    LSPClientConfig,
)
from pycoder.lsp.context_integration import LSPContextIntegrator
from pycoder.lsp.diagnostics import AggregatedDiagnostic, DiagnosticsAggregator
from pycoder.lsp.protocol import make_notification


# ════════════════════════════════════════════════════════
# Diagnostic 数据类测试
# ════════════════════════════════════════════════════════


class TestDiagnosticDataclass:
    """Diagnostic 数据类测试"""

    def test_default_values(self) -> None:
        d = Diagnostic()
        assert d.file_path == ""
        assert d.line == 0
        assert d.severity == "information"
        assert d.is_error is False
        assert d.is_warning is False

    def test_error_diagnostic(self) -> None:
        d = Diagnostic(severity="error", message="Syntax error", line=10)
        assert d.is_error is True
        assert d.is_warning is False

    def test_warning_diagnostic(self) -> None:
        d = Diagnostic(severity="warning", message="Unused import", line=5)
        assert d.is_warning is True
        assert d.is_error is False

    def test_to_dict_roundtrip(self) -> None:
        d = Diagnostic(
            file_path="main.py",
            line=10,
            character=5,
            end_line=10,
            end_character=15,
            severity="error",
            code="reportMissingImports",
            source="pyright",
            message="Cannot import 'foo'",
        )
        d_dict = d.to_dict()
        assert d_dict["file_path"] == "main.py"
        assert d_dict["severity"] == "error"
        assert d_dict["code"] == "reportMissingImports"
        assert d_dict["source"] == "pyright"

    def test_diagnostic_severity_map(self) -> None:
        """DIAGNOSTIC_SEVERITY 映射完整性"""
        assert DIAGNOSTIC_SEVERITY[1] == "error"
        assert DIAGNOSTIC_SEVERITY[2] == "warning"
        assert DIAGNOSTIC_SEVERITY[3] == "information"
        assert DIAGNOSTIC_SEVERITY[4] == "hint"


# ════════════════════════════════════════════════════════
# LSPClient 诊断捕获测试
# ════════════════════════════════════════════════════════


class TestLSPClientDiagnostics:
    """LSPClient 诊断捕获与查询测试"""

    def test_parse_diagnostic_full(self) -> None:
        """解析完整 LSP 诊断对象"""
        raw = {
            "range": {
                "start": {"line": 10, "character": 5},
                "end": {"line": 10, "character": 15},
            },
            "severity": 1,
            "code": "reportMissingImports",
            "source": "pyright",
            "message": "Cannot import 'foo'",
        }
        d = LSPClient._parse_diagnostic(raw, "/tmp/main.py")
        assert d.file_path == "/tmp/main.py"
        assert d.line == 10
        assert d.character == 5
        assert d.end_line == 10
        assert d.end_character == 15
        assert d.severity == "error"
        assert d.code == "reportMissingImports"
        assert d.source == "pyright"
        assert d.message == "Cannot import 'foo'"

    def test_parse_diagnostic_default_severity(self) -> None:
        """未指定 severity 默认为 information"""
        raw = {
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 0},
            },
            "message": "Some info",
        }
        d = LSPClient._parse_diagnostic(raw, "/tmp/x.py")
        assert d.severity == "information"

    def test_handle_publish_diagnostics(self) -> None:
        """处理 publishDiagnostics 通知应将诊断存入缓存"""
        client = LSPClient()
        params = {
            "uri": "file:///tmp/main.py",
            "diagnostics": [
                {
                    "range": {
                        "start": {"line": 5, "character": 0},
                        "end": {"line": 5, "character": 10},
                    },
                    "severity": 1,
                    "message": "Error 1",
                    "source": "pyright",
                },
                {
                    "range": {
                        "start": {"line": 10, "character": 0},
                        "end": {"line": 10, "character": 5},
                    },
                    "severity": 2,
                    "message": "Warning 1",
                    "source": "pyright",
                },
            ],
        }
        client._handle_publish_diagnostics(params)
        diags = client.get_diagnostics("/tmp/main.py")
        # 应返回 2 个诊断, 按行号排序
        assert len(diags) == 2
        assert diags[0].line == 5
        assert diags[1].line == 10
        assert diags[0].severity == "error"
        assert diags[1].severity == "warning"

    def test_handle_publish_diagnostics_empty(self) -> None:
        """publishDiagnostics 推送空列表表示文件已无错误"""
        client = LSPClient()
        # 先添加一些诊断
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/main.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        assert len(client.get_diagnostics("/tmp/main.py")) == 1
        # 推送空列表
        client._handle_publish_diagnostics(
            {"uri": "file:///tmp/main.py", "diagnostics": []}
        )
        assert len(client.get_diagnostics("/tmp/main.py")) == 0

    def test_handle_publish_diagnostics_no_uri(self) -> None:
        """缺少 URI 的通知应被忽略"""
        client = LSPClient()
        client._handle_publish_diagnostics({"diagnostics": []})
        assert client.get_all_diagnostics() == {}

    def test_get_diagnostics_empty_filepath(self) -> None:
        """空字符串 file_path 返回所有诊断"""
        client = LSPClient()
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/a.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/b.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 2, "character": 0},
                            "end": {"line": 2, "character": 0},
                        },
                        "severity": 2,
                        "message": "warn",
                    }
                ],
            }
        )
        all_diags = client.get_diagnostics("")
        assert len(all_diags) == 2

    def test_get_all_diagnostics(self) -> None:
        """get_all_diagnostics 返回 file_path → diagnostics 映射"""
        client = LSPClient()
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/a.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        mapping = client.get_all_diagnostics()
        assert len(mapping) == 1
        # 键应是 normalize 后的路径
        any_key = next(iter(mapping.keys()))
        assert "a.py" in any_key

    def test_clear_diagnostics_single_file(self) -> None:
        """清除单个文件诊断"""
        client = LSPClient()
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/a.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        client.clear_diagnostics("/tmp/a.py")
        assert client.get_diagnostics("/tmp/a.py") == []

    def test_clear_diagnostics_all(self) -> None:
        """清除所有诊断"""
        client = LSPClient()
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/a.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        client.clear_diagnostics()
        assert client.get_all_diagnostics() == {}

    def test_register_diagnostics_handler(self) -> None:
        """注册的诊断回调应在 publishDiagnostics 时被调用"""
        client = LSPClient()
        captured: list[tuple[str, list[Diagnostic]]] = []

        def handler(file_path: str, diags: list[Diagnostic]) -> None:
            captured.append((file_path, diags))

        client.register_diagnostics_handler(handler)
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/main.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 5, "character": 0},
                            "end": {"line": 5, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        assert len(captured) == 1
        file_path, diags = captured[0]
        assert len(diags) == 1
        assert diags[0].message == "err"

    def test_unregister_diagnostics_handler(self) -> None:
        """注销后回调不再被调用"""
        client = LSPClient()
        captured: list[tuple[str, list[Diagnostic]]] = []

        def handler(file_path: str, diags: list[Diagnostic]) -> None:
            captured.append((file_path, diags))

        client.register_diagnostics_handler(handler)
        client.unregister_diagnostics_handler(handler)
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/main.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        assert len(captured) == 0

    def test_diagnostics_handler_exception_isolated(self) -> None:
        """回调异常不应影响其他回调和诊断存储"""
        client = LSPClient()
        captured: list[Diagnostic] = []

        def bad_handler(file_path: str, diags: list[Diagnostic]) -> None:
            raise ValueError("bad handler")

        def good_handler(file_path: str, diags: list[Diagnostic]) -> None:
            captured.extend(diags)

        client.register_diagnostics_handler(bad_handler)
        client.register_diagnostics_handler(good_handler)
        # 不应抛出异常
        client._handle_publish_diagnostics(
            {
                "uri": "file:///tmp/main.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 1, "character": 0},
                            "end": {"line": 1, "character": 0},
                        },
                        "severity": 1,
                        "message": "err",
                    }
                ],
            }
        )
        # 好回调仍应被调用, 诊断仍应被存储
        assert len(captured) == 1
        assert len(client.get_diagnostics("/tmp/main.py")) == 1

    def test_uri_to_path(self) -> None:
        """file:// URI 转本地路径"""
        # 简单 URI 转换
        path = LSPClient._uri_to_path("file:///tmp/main.py")
        assert "main.py" in path


# ════════════════════════════════════════════════════════
# LSPContextIntegrator 测试
# ════════════════════════════════════════════════════════


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


class TestLSPContextIntegrator:
    """LSP 上下文集成器测试"""

    def test_disabled_by_default_when_no_client(self) -> None:
        """未提供 LSPClient 时集成器应禁用"""
        integrator = LSPContextIntegrator(lsp_client=None)
        assert integrator.enabled is False
        assert integrator.build_diagnostics_context() == ""

    def test_enabled_when_client_provided(self) -> None:
        """提供 LSPClient 时集成器应启用"""
        client = MagicMock(spec=LSPClient)
        integrator = LSPContextIntegrator(lsp_client=client)
        assert integrator.enabled is True

    def test_enable_disable(self) -> None:
        """enable/disable 控制 enabled 状态"""
        integrator = LSPContextIntegrator()
        assert integrator.enabled is False
        client = MagicMock(spec=LSPClient)
        integrator.enable(client)
        assert integrator.enabled is True
        integrator.disable()
        assert integrator.enabled is False

    def test_collect_diagnostics_empty_file_list(self) -> None:
        """空文件列表返回空映射"""
        client = MagicMock(spec=LSPClient)
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.collect_diagnostics([])
        assert result == {}

    def test_collect_diagnostics_filters_by_severity(self) -> None:
        """按严重度过滤诊断"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(file_path=file_path, line=1, severity="error", message="err1"),
            Diagnostic(file_path=file_path, line=2, severity="warning", message="warn1"),
            Diagnostic(file_path=file_path, line=3, severity="information", message="info1"),
            Diagnostic(file_path=file_path, line=4, severity="hint", message="hint1"),
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        # 默认仅包含 error/warning
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.collect_diagnostics([file_path])
        assert file_path in result
        assert len(result[file_path]) == 2
        # 错误优先排序
        assert result[file_path][0].severity == "error"
        assert result[file_path][1].severity == "warning"

    def test_collect_diagnostics_max_per_file(self) -> None:
        """单文件诊断数受 max_diagnostics_per_file 限制"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(file_path=file_path, line=i, severity="error", message=f"err{i}")
            for i in range(10)
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(
            lsp_client=client, max_diagnostics_per_file=3
        )
        result = integrator.collect_diagnostics([file_path])
        assert len(result[file_path]) == 3

    def test_collect_diagnostics_max_total(self) -> None:
        """全局诊断数受 max_total_diagnostics 限制"""
        file_a = "/tmp/a.py"
        file_b = "/tmp/b.py"
        diags_a = [
            Diagnostic(file_path=file_a, line=i, severity="error", message=f"a{i}")
            for i in range(10)
        ]
        diags_b = [
            Diagnostic(file_path=file_b, line=i, severity="error", message=f"b{i}")
            for i in range(10)
        ]
        client = _make_mock_client_with_diags({file_a: diags_a, file_b: diags_b})
        integrator = LSPContextIntegrator(
            lsp_client=client, max_total_diagnostics=5, max_diagnostics_per_file=10
        )
        result = integrator.collect_diagnostics([file_a, file_b])
        total = sum(len(ds) for ds in result.values())
        assert total <= 5

    def test_collect_diagnostics_max_files(self) -> None:
        """文件数受 max_files 限制"""
        client = _make_mock_client_with_diags({})
        integrator = LSPContextIntegrator(lsp_client=client, max_files=2)
        # 提供 5 个文件, 但只应扫描前 2 个
        integrator.collect_diagnostics(["a.py", "b.py", "c.py", "d.py", "e.py"])
        # 验证 get_diagnostics 仅被调用 2 次
        assert client.get_diagnostics.call_count == 2

    def test_format_empty_diagnostics(self) -> None:
        """空诊断映射应返回空字符串"""
        integrator = LSPContextIntegrator()
        result = integrator.format_diagnostics_for_prompt({})
        assert result == ""

    def test_format_diagnostics_with_errors(self) -> None:
        """包含错误的诊断映射应生成有效提示词"""
        integrator = LSPContextIntegrator()
        diagnostics = {
            "/tmp/main.py": [
                Diagnostic(
                    file_path="/tmp/main.py",
                    line=10,
                    character=5,
                    severity="error",
                    code="reportMissingImports",
                    source="pyright",
                    message="Cannot import 'foo'",
                ),
                Diagnostic(
                    file_path="/tmp/main.py",
                    line=20,
                    character=0,
                    severity="warning",
                    message="Unused variable 'x'",
                ),
            ]
        }
        result = integrator.format_diagnostics_for_prompt(diagnostics)
        # 验证关键内容
        assert "## LSP 实时诊断" in result
        assert "1 个错误" in result
        assert "1 个警告" in result
        assert "[ERROR]" in result
        assert "[WARN]" in result
        assert "L11:6" in result  # 0-based 10 → 1-based 11
        assert "Cannot import 'foo'" in result
        assert "[reportMissingImports]" in result
        assert "(pyright)" in result
        # 包含生成建议
        assert "生成建议" in result

    def test_format_diagnostics_no_suggestions(self) -> None:
        """include_suggestions=False 应省略生成建议"""
        integrator = LSPContextIntegrator()
        diagnostics = {
            "/tmp/main.py": [
                Diagnostic(
                    file_path="/tmp/main.py",
                    line=1,
                    severity="error",
                    message="err",
                )
            ]
        }
        result = integrator.format_diagnostics_for_prompt(
            diagnostics, include_suggestions=False
        )
        assert "生成建议" not in result

    def test_build_diagnostics_context_disabled(self) -> None:
        """禁用时 build_diagnostics_context 返回空"""
        integrator = LSPContextIntegrator()  # 未启用
        assert integrator.build_diagnostics_context(["main.py"]) == ""

    def test_build_diagnostics_context_with_files(self) -> None:
        """指定文件列表时构建完整诊断上下文"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(
                file_path=file_path,
                line=5,
                severity="error",
                message="err",
                source="pyright",
            )
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.build_diagnostics_context([file_path])
        assert "## LSP 实时诊断" in result
        assert "err" in result

    def test_build_diagnostics_context_all_files(self) -> None:
        """file_paths=None 扫描所有已缓存文件"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(
                file_path=file_path, line=1, severity="error", message="err"
            )
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.build_diagnostics_context(file_paths=None)
        assert "## LSP 实时诊断" in result

    def test_get_anchor_section_with_diagnostics(self) -> None:
        """get_anchor_section 应包含锚点标记"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(
                file_path=file_path, line=1, severity="error", message="err"
            )
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)
        result = integrator.get_anchor_section([file_path])
        assert "LSP_DIAGNOSTICS_ANCHOR_START" in result
        assert "LSP_DIAGNOSTICS_ANCHOR_END" in result

    def test_get_anchor_section_empty(self) -> None:
        """无诊断时 get_anchor_section 返回空字符串"""
        client = _make_mock_client_with_diags({})
        integrator = LSPContextIntegrator(lsp_client=client)
        assert integrator.get_anchor_section(["/tmp/main.py"]) == ""

    def test_get_stats_no_data(self) -> None:
        """无数据时 stats 全为 0"""
        integrator = LSPContextIntegrator()
        stats = integrator.get_stats()
        assert stats["total_diagnostics"] == 0
        assert stats["errors"] == 0
        assert stats["warnings"] == 0
        assert stats["files_affected"] == 0

    def test_get_stats_after_collect(self) -> None:
        """collect_diagnostics 后 stats 应反映快照"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(file_path=file_path, line=1, severity="error", message="e1"),
            Diagnostic(file_path=file_path, line=2, severity="warning", message="w1"),
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)
        integrator.collect_diagnostics([file_path])
        stats = integrator.get_stats()
        assert stats["total_diagnostics"] == 2
        assert stats["errors"] == 1
        assert stats["warnings"] == 1
        assert stats["files_affected"] == 1

    def test_collect_diagnostics_handles_client_exception(self) -> None:
        """LSPClient 抛异常时 collect_diagnostics 应优雅降级"""
        client = MagicMock(spec=LSPClient)
        client.get_diagnostics = MagicMock(side_effect=RuntimeError("boom"))
        integrator = LSPContextIntegrator(lsp_client=client)
        # 不应抛出异常
        result = integrator.collect_diagnostics(["/tmp/main.py"])
        assert result == {}

    def test_severity_marker(self) -> None:
        """严重度标记映射"""
        assert LSPContextIntegrator._severity_marker("error") == "[ERROR]"
        assert LSPContextIntegrator._severity_marker("warning") == "[WARN]"
        assert LSPContextIntegrator._severity_marker("information") == "[INFO]"
        assert LSPContextIntegrator._severity_marker("hint") == "[HINT]"
        assert LSPContextIntegrator._severity_marker("unknown") == "[?]"

    def test_relative_path_short(self) -> None:
        """短路径应直接返回"""
        assert LSPContextIntegrator._relative_path("/tmp/main.py").endswith("main.py")


# ════════════════════════════════════════════════════════
# DiagnosticsAggregator (LSPClient 模式) 测试
# ════════════════════════════════════════════════════════


class TestDiagnosticsAggregatorClientMode:
    """DiagnosticsAggregator LSPClient 模式测试"""

    def test_scan_file_from_client_no_client(self) -> None:
        """未提供 lsp_client 时返回空列表"""
        agg = DiagnosticsAggregator()
        assert agg.scan_file_from_client("/tmp/main.py") == []

    def test_scan_file_from_client_with_diags(self) -> None:
        """通过 LSPClient 扫描文件诊断"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(
                file_path=file_path,
                line=10,
                character=5,
                severity="error",
                message="err",
                source="pyright",
                code="E1",
            )
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        agg = DiagnosticsAggregator(lsp_client=client)
        result = agg.scan_file_from_client(file_path)
        assert len(result) == 1
        agg_d = result[0]
        assert isinstance(agg_d, AggregatedDiagnostic)
        assert agg_d.file_path == file_path
        assert agg_d.severity == "error"
        assert agg_d.message == "err"
        assert agg_d.language == "python"  # 由扩展名推断
        assert agg_d.source == "pyright"
        assert agg_d.code == "E1"

    def test_scan_file_from_client_handles_exception(self) -> None:
        """LSPClient 异常应被捕获"""
        client = MagicMock(spec=LSPClient)
        client.get_diagnostics = MagicMock(side_effect=RuntimeError("boom"))
        agg = DiagnosticsAggregator(lsp_client=client)
        assert agg.scan_file_from_client("/tmp/main.py") == []

    def test_scan_all_from_client(self) -> None:
        """扫描所有已缓存文件"""
        file_a = "/tmp/a.py"
        file_b = "/tmp/b.ts"
        client = _make_mock_client_with_diags(
            {
                file_a: [
                    Diagnostic(file_path=file_a, line=1, severity="error", message="a")
                ],
                file_b: [
                    Diagnostic(file_path=file_b, line=2, severity="warning", message="b")
                ],
            }
        )
        agg = DiagnosticsAggregator(lsp_client=client)
        result = agg.scan_all_from_client()
        assert len(result) == 2
        languages = {d.language for d in result}
        assert "python" in languages
        assert "typescript" in languages

    def test_infer_language(self) -> None:
        """语言推断"""
        assert DiagnosticsAggregator._infer_language("/tmp/main.py") == "python"
        assert DiagnosticsAggregator._infer_language("/tmp/app.ts") == "typescript"
        assert DiagnosticsAggregator._infer_language("/tmp/App.java") == "java"
        assert DiagnosticsAggregator._infer_language("/tmp/main.cpp") == "cpp"
        assert DiagnosticsAggregator._infer_language("/tmp/main.go") == "go"
        assert DiagnosticsAggregator._infer_language("/tmp/noext") == "unknown"

    def test_aggregated_diagnostic_to_dict(self) -> None:
        """AggregatedDiagnostic.to_dict 完整性"""
        d = AggregatedDiagnostic(
            file_path="/tmp/main.py",
            language="python",
            severity="error",
            message="err",
            line=10,
            column=5,
            source="pyright",
            code="E1",
            end_line=10,
            end_column=10,
        )
        d_dict = d.to_dict()
        assert d_dict["file_path"] == "/tmp/main.py"
        assert d_dict["language"] == "python"
        assert d_dict["severity"] == "error"
        assert d_dict["end_line"] == 10


# ════════════════════════════════════════════════════════
# ContextOrchestrator LSP 集成测试
# ════════════════════════════════════════════════════════


class TestContextOrchestratorLSPIntegration:
    """ContextOrchestrator 与 LSP 集成器端到端测试"""

    def _make_orchestrator(self) -> Any:
        """构造 ContextOrchestrator (避免依赖全局单例)"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        return ContextOrchestrator(project="test_project")

    def test_set_lsp_integrator(self) -> None:
        """set_lsp_integrator 注册集成器"""
        orch = self._make_orchestrator()
        assert orch._lsp_integrator is None

        client = MagicMock(spec=LSPClient)
        integrator = LSPContextIntegrator(lsp_client=client)
        orch.set_lsp_integrator(integrator)
        assert orch._lsp_integrator is integrator

        # 移除
        orch.set_lsp_integrator(None)
        assert orch._lsp_integrator is None

    def test_set_context_files(self) -> None:
        """set_context_files 设置文件列表"""
        orch = self._make_orchestrator()
        orch.set_context_files(["a.py", "b.py"])
        assert orch._context_files == ["a.py", "b.py"]

    def test_add_context_file_dedup(self) -> None:
        """add_context_file 去重"""
        orch = self._make_orchestrator()
        orch.add_context_file("a.py")
        orch.add_context_file("a.py")  # 重复
        orch.add_context_file("b.py")
        assert orch._context_files == ["a.py", "b.py"]

    def test_get_lsp_diagnostics_snippet_no_integrator(self) -> None:
        """未注册集成器时 get_lsp_diagnostics_snippet 返回空"""
        orch = self._make_orchestrator()
        assert orch.get_lsp_diagnostics_snippet() == ""

    def test_get_lsp_diagnostics_snippet_disabled_integrator(self) -> None:
        """集成器禁用时 get_lsp_diagnostics_snippet 返回空"""
        orch = self._make_orchestrator()
        integrator = LSPContextIntegrator()  # 未启用
        orch.set_lsp_integrator(integrator)
        assert orch.get_lsp_diagnostics_snippet() == ""

    def test_get_lsp_diagnostics_snippet_with_diagnostics(self) -> None:
        """有诊断时 get_lsp_diagnostics_snippet 返回格式化片段"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(
                file_path=file_path, line=5, severity="error", message="err"
            )
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)
        orch = self._make_orchestrator()
        orch.set_lsp_integrator(integrator)
        orch.set_context_files([file_path])

        snippet = orch.get_lsp_diagnostics_snippet()
        assert "## LSP 实时诊断" in snippet
        assert "err" in snippet

    def test_process_user_message_injects_lsp_diagnostics(self) -> None:
        """process_user_message 应将 LSP 诊断注入到 anchor 中"""
        file_path = "/tmp/main.py"
        diags = [
            Diagnostic(
                file_path=file_path,
                line=10,
                severity="error",
                message="Cannot import 'foo'",
                source="pyright",
            )
        ]
        client = _make_mock_client_with_diags({file_path: diags})
        integrator = LSPContextIntegrator(lsp_client=client)

        orch = self._make_orchestrator()
        orch.set_lsp_integrator(integrator)
        orch.set_context_files([file_path])

        result = asyncio.run(orch.process_user_message("请帮我修复代码"))
        # anchor 中应包含 LSP 诊断片段
        assert "## LSP 实时诊断" in result["anchor"]
        assert "Cannot import 'foo'" in result["anchor"]
        # 返回结果中应包含独立的 lsp_diagnostics 字段
        assert "## LSP 实时诊断" in result["lsp_diagnostics"]
        # 统计信息应非空
        assert result["lsp_stats"]["errors"] == 1
        # 应推送 lsp_diagnostics 事件
        lsp_events = [ev for ev in result["events"] if ev["type"] == "lsp_diagnostics"]
        assert len(lsp_events) == 1
        assert lsp_events[0]["stats"]["errors"] == 1

    def test_process_user_message_no_lsp_when_disabled(self) -> None:
        """未注册集成器时 process_user_message 不应注入 LSP"""
        orch = self._make_orchestrator()
        result = asyncio.run(orch.process_user_message("请帮我修复代码"))
        # lsp_diagnostics 应为空字符串
        assert result["lsp_diagnostics"] == ""
        # 无 lsp_diagnostics 事件
        lsp_events = [ev for ev in result["events"] if ev["type"] == "lsp_diagnostics"]
        assert len(lsp_events) == 0

    def test_process_user_message_lsp_exception_isolated(self) -> None:
        """LSP 集成器异常不应影响主流程"""
        client = MagicMock(spec=LSPClient)
        client.get_diagnostics = MagicMock(side_effect=RuntimeError("boom"))
        integrator = LSPContextIntegrator(lsp_client=client)

        orch = self._make_orchestrator()
        orch.set_lsp_integrator(integrator)
        orch.set_context_files(["/tmp/main.py"])

        # 不应抛出异常
        result = asyncio.run(orch.process_user_message("请帮我修复代码"))
        # 主流程仍应正常返回
        assert "anchor" in result
        assert result["lsp_diagnostics"] == ""
