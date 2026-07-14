"""lsp 模块测试"""
from __future__ import annotations

import pytest
from pycoder.lsp.lsp_manager import LSPManager, LSPStatus


class TestLSPManager:
    @pytest.fixture
    def manager(self, tmp_path):
        return LSPManager(workspace=tmp_path)

    def test_get_language_for_file_python(self, manager):
        assert manager.get_language_for_file("src/main.py") == "python"

    def test_get_language_for_file_typescript(self, manager):
        assert manager.get_language_for_file("src/app.ts") == "typescript"

    def test_get_language_for_file_javascript(self, manager):
        assert manager.get_language_for_file("src/utils.js") == "typescript"

    def test_get_language_for_file_java(self, manager):
        assert manager.get_language_for_file("src/Main.java") == "java"

    def test_get_language_for_file_cpp(self, manager):
        assert manager.get_language_for_file("src/main.cpp") == "cpp"

    def test_get_language_for_file_header(self, manager):
        assert manager.get_language_for_file("include/header.h") == "cpp"

    def test_get_language_for_file_go(self, manager):
        assert manager.get_language_for_file("src/main.go") == "go"

    def test_get_language_for_file_unknown(self, manager):
        assert manager.get_language_for_file("README.md") is None

    def test_get_language_for_file_unknown_ext(self, manager):
        assert manager.get_language_for_file("config.yaml") is None

    def test_get_status_default(self, manager):
        assert manager.get_status("python") == LSPStatus.STOPPED

    def test_list_languages(self, manager):
        langs = manager.list_languages()
        assert "python" in langs
        assert "typescript" in langs
        assert "java" in langs
        assert "cpp" in langs
        assert "go" in langs
        assert len(langs) == 5

    def test_get_supported_extensions(self, manager):
        exts = manager.get_supported_extensions()
        assert ".py" in exts["python"]
        assert ".ts" in exts["typescript"]
        assert ".js" in exts["typescript"]
        assert ".java" in exts["java"]
        assert ".cpp" in exts["cpp"]
        assert ".go" in exts["go"]


class TestLSPDiagnostics:
    @pytest.mark.asyncio
    async def test_scan_file_unknown_language(self, tmp_path):
        from pycoder.lsp.diagnostics import DiagnosticsAggregator
        manager = LSPManager(workspace=tmp_path)
        agg = DiagnosticsAggregator(manager)
        diags = await agg.scan_file("README.md")
        assert diags == []

    @pytest.mark.asyncio
    async def test_scan_workspace(self, tmp_path):
        from pycoder.lsp.diagnostics import DiagnosticsAggregator
        manager = LSPManager(workspace=tmp_path)
        agg = DiagnosticsAggregator(manager)
        diags = await agg.scan_workspace()
        assert diags == []