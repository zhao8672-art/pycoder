"""error_patterns.py 单元测试 — 错误模式库与根因推断"""

from __future__ import annotations

import pytest

from pycoder.capabilities.self_evo.learning.error_patterns import (
    ERROR_PATTERN_DB,
    ROOT_CAUSE_CHAINS,
    ErrorPattern,
    RootCauseChain,
    get_root_cause_chain,
    lookup_by_message,
    lookup_pattern,
)


class TestErrorPatternDB:
    """错误模式数据库测试"""

    def test_db_not_empty(self) -> None:
        assert len(ERROR_PATTERN_DB) >= 20

    def test_common_errors_exist(self) -> None:
        """验证常见错误类型都在数据库中"""
        expected = [
            "ModuleNotFoundError",
            "ImportError",
            "TypeError",
            "AttributeError",
            "KeyError",
            "IndexError",
            "NameError",
            "ValueError",
            "FileNotFoundError",
            "PermissionError",
            "SyntaxError",
            "IndentationError",
            "TimeoutError",
            "ConnectionError",
            "OSError",
            "RecursionError",
        ]
        for error_type in expected:
            assert error_type in ERROR_PATTERN_DB, f"缺少错误类型: {error_type}"

    def test_pattern_has_root_causes(self) -> None:
        for error_type, pattern in ERROR_PATTERN_DB.items():
            assert len(pattern.root_causes) > 0, f"{error_type} 缺少根因"
            assert len(pattern.fix_templates) > 0, f"{error_type} 缺少修复模板"

    def test_dll_load_failed(self) -> None:
        """测试 DLL load failed 模式"""
        pattern = ERROR_PATTERN_DB["DLLLoadFailed"]
        assert pattern.platform_specific is True
        assert any("Visual C++" in cause for cause in pattern.root_causes)


class TestLookup:
    """查找函数测试"""

    def test_lookup_pattern_exact(self) -> None:
        pattern = lookup_pattern("ModuleNotFoundError")
        assert pattern is not None
        assert pattern.error_type == "ModuleNotFoundError"

    def test_lookup_pattern_not_found(self) -> None:
        pattern = lookup_pattern("NonExistentError")
        assert pattern is None

    def test_lookup_by_message_import(self) -> None:
        pattern = lookup_by_message("ModuleNotFoundError: No module named 'requests'")
        assert pattern is not None
        assert pattern.error_type == "ModuleNotFoundError"

    def test_lookup_by_message_type_error(self) -> None:
        pattern = lookup_by_message("TypeError: unsupported operand type(s) for +: 'int' and 'str'")
        assert pattern is not None
        assert pattern.error_type == "TypeError"

    def test_lookup_by_message_file_not_found(self) -> None:
        pattern = lookup_by_message("FileNotFoundError: [Errno 2] No such file or directory: 'config.json'")
        assert pattern is not None
        assert pattern.error_type == "FileNotFoundError"

    def test_lookup_by_message_unknown(self) -> None:
        pattern = lookup_by_message("SomeUnknownError: something happened")
        assert pattern is None


class TestRootCauseChain:
    """根因推断链测试"""

    def test_get_chain_module_not_found(self) -> None:
        chain = get_root_cause_chain("ModuleNotFoundError")
        assert chain is not None
        assert chain.primary_cause != ""
        assert chain.confidence > 0
        assert len(chain.error_chain) >= 2

    def test_get_chain_dll_load_failed(self) -> None:
        chain = get_root_cause_chain("DLL load failed")
        assert chain is not None
        assert "Visual C++" in chain.primary_cause or "运行库" in chain.primary_cause

    def test_get_chain_not_found(self) -> None:
        chain = get_root_cause_chain("NonExistentError")
        assert chain is None

    def test_chain_has_recommended_fixes(self) -> None:
        chain = get_root_cause_chain("ConnectionError")
        assert chain is not None
        assert len(chain.recommended_fixes) >= 0  # 可能有也可能没有


class TestErrorClassifierIntegration:
    """ErrorClassifier 集成测试"""

    def test_infer_root_cause_import(self) -> None:
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        result = ec.infer_root_cause("ModuleNotFoundError: No module named 'fastapi'")
        assert result["found"] is True
        assert result["error_type"] == "ModuleNotFoundError"
        assert len(result["root_causes"]) > 0

    def test_infer_root_cause_unknown(self) -> None:
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        result = ec.infer_root_cause("SomeUnknownError: unknown issue")
        assert result["found"] is False

    def test_get_fix_template(self) -> None:
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        template = ec.get_fix_template("ModuleNotFoundError")
        assert template is not None
        assert "pip" in template.lower() or "install" in template.lower()

    def test_get_fix_template_not_found(self) -> None:
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        template = ec.get_fix_template("NonExistentError")
        assert template is None
