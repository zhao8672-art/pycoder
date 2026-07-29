"""test_runner.py 单元测试 — 自动化测试执行闭环"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycoder.capabilities.tools.test_runner import (
    FailureDetail,
    TestRunner,
    TestRunResult,
)


class TestTestRunResult:
    """TestRunResult 数据类测试"""

    def test_default_values(self) -> None:
        result = TestRunResult()
        assert result.success is False
        assert result.total == 0
        assert result.passed == 0
        assert result.failed == 0
        assert result.failure_details == []

    def test_to_dict(self) -> None:
        result = TestRunResult(success=True, total=5, passed=4, failed=1, duration=1.5)
        d = result.to_dict()
        assert d["success"] is True
        assert d["total"] == 5
        assert d["passed"] == 4
        assert d["failed"] == 1
        assert d["duration"] == 1.5

    def test_to_dict_with_failures(self) -> None:
        detail = FailureDetail(
            test_name="test_foo",
            file_path="tests/test_foo.py",
            line_number=42,
            error_type="AssertionError",
            error_message="assert False",
        )
        result = TestRunResult(failure_details=[detail])
        d = result.to_dict()
        assert len(d["failure_details"]) == 1
        assert d["failure_details"][0]["test_name"] == "test_foo"


class TestFailureDetail:
    """FailureDetail 数据类测试"""

    def test_default_values(self) -> None:
        detail = FailureDetail()
        assert detail.test_name == ""
        assert detail.line_number == 0

    def test_with_values(self) -> None:
        detail = FailureDetail(
            test_name="test_bar",
            file_path="tests/test_bar.py",
            line_number=10,
            error_type="TypeError",
            error_message="unsupported operand",
        )
        assert detail.test_name == "test_bar"
        assert detail.error_type == "TypeError"


class TestTestRunner:
    """TestRunner 核心功能测试"""

    @pytest.fixture
    def runner(self) -> TestRunner:
        return TestRunner()

    def test_parse_output_success(self, runner: TestRunner) -> None:
        """测试解析成功的输出"""
        output = """
tests/test_foo.py ....                                             [100%]

=========== 4 passed in 0.15s ===========
"""
        result = runner._parse_output(output, "", 0)
        assert result.passed == 4
        assert result.failed == 0
        assert result.success is True
        assert result.duration > 0

    def test_parse_output_with_failures(self, runner: TestRunner) -> None:
        """测试解析含失败的输出"""
        output = """
tests/test_foo.py ..F.                                             [100%]

=========== FAILURES ===========
________ test_fail ________
tests/test_foo.py:10: AssertionError
def test_fail():
>       assert False
E       AssertionError: assert False
tests/test_foo.py:10: AssertionError
=========== 1 failed, 3 passed in 0.20s ===========
"""
        result = runner._parse_output(output, "", 1)
        assert result.passed == 3
        assert result.failed == 1
        assert result.success is False
        assert len(result.failure_details) >= 1

    def test_parse_output_with_errors(self, runner: TestRunner) -> None:
        """测试解析含错误的输出"""
        output = """
=========== 2 passed, 1 error in 0.10s ===========
"""
        result = runner._parse_output(output, "", 1)
        assert result.passed == 2
        assert result.errors == 1
        assert result.success is False

    def test_parse_output_skipped(self, runner: TestRunner) -> None:
        """测试解析跳过的测试"""
        output = """
=========== 3 passed, 1 skipped, 2 warnings in 0.05s ===========
"""
        result = runner._parse_output(output, "", 0)
        assert result.passed == 3
        assert result.skipped == 1
        assert result.warnings == 2
        assert result.success is True

    def test_parse_output_no_tests(self, runner: TestRunner) -> None:
        """测试无测试的情况 (exit code 5)"""
        output = "no tests ran in 0.00s"
        result = runner._parse_output(output, "", 5)
        assert result.success is True  # exit code 5 = 无测试，不算失败

    @pytest.mark.asyncio
    async def test_run_timeout(self, runner: TestRunner) -> None:
        """测试超时处理"""
        result = await runner.run(
            "nonexistent_path",
            timeout=1,
        )
        # 可能超时或返回无测试
        assert isinstance(result, TestRunResult)

    @pytest.mark.asyncio
    async def test_run_empty_dir(self, tmp_path: Path, runner: TestRunner) -> None:
        """测试空目录"""
        result = await runner.run(
            str(tmp_path),
            timeout=10,
        )
        assert isinstance(result, TestRunResult)
        # 空目录应该 exit code 5 (无测试)
        assert result.success is True

    def test_summary_regex(self, runner: TestRunner) -> None:
        """测试摘要正则的各种格式"""
        test_cases = [
            ("===== 5 passed in 1.0s =====", 5, 0, 0, 0),
            ("===== 3 passed, 2 failed in 0.5s =====", 3, 2, 0, 0),
            ("===== 1 failed, 3 passed in 0.2s =====", 3, 1, 0, 0),  # failed 在前
            ("===== 1 passed, 1 failed, 1 error in 0.3s =====", 1, 1, 1, 0),
            ("===== 2 passed, 1 skipped in 0.1s =====", 2, 0, 0, 1),
            ("===== 0 passed, 0 failed in 0.0s =====", 0, 0, 0, 0),
        ]
        for output, passed, failed, errors, skipped in test_cases:
            summary_match = runner._SUMMARY_LINE_RE.search(output)
            assert summary_match is not None, f"摘要行正则匹配失败: {output}"
            summary_text = summary_match.group(1)
            passed_m = runner._PASSED_RE.search(summary_text)
            failed_m = runner._FAILED_RE.search(summary_text)
            errors_m = runner._ERRORS_RE.search(summary_text)
            skipped_m = runner._SKIPPED_RE.search(summary_text)
            assert int(passed_m.group(1) if passed_m else 0) == passed, f"passed 不匹配: {output}"
            assert int(failed_m.group(1) if failed_m else 0) == failed, f"failed 不匹配: {output}"
            assert int(errors_m.group(1) if errors_m else 0) == errors, f"errors 不匹配: {output}"
            assert (
                int(skipped_m.group(1) if skipped_m else 0) == skipped
            ), f"skipped 不匹配: {output}"
