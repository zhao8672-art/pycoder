"""测试运行器 — 自动执行 pytest 并解析结果

提供:
- TestRunner: 异步执行测试，解析输出，返回结构化结果
- TestRunResult: 测试运行结果数据类
- FailureDetail: 失败详情数据类

使用场景:
    runner = TestRunner()
    result = await runner.run("tests/", pattern="test_*.py", timeout=120)
    print(f"通过: {result.passed}, 失败: {result.failed}")
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FailureDetail:
    """测试失败详情"""

    test_name: str = ""
    file_path: str = ""
    line_number: int = 0
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""


@dataclass
class TestRunResult:
    """测试运行结果"""

    success: bool = False
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    warnings: int = 0
    duration: float = 0.0
    failure_details: list[FailureDetail] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "duration": round(self.duration, 2),
            "failure_details": [
                {
                    "test_name": d.test_name,
                    "file_path": d.file_path,
                    "line_number": d.line_number,
                    "error_type": d.error_type,
                    "error_message": d.error_message,
                }
                for d in self.failure_details
            ],
        }


class TestRunner:
    """测试运行器 — 异步执行 pytest 并解析结果"""

    # pytest 摘要行正则: 匹配 "===== N passed, M failed in X.XXs ====="
    # 支持任意顺序的 passed/failed/errors/skipped/warnings
    _SUMMARY_LINE_RE = re.compile(r"=+\s*(.+?)\s+in\s+([\d.]+)s\s*=*", re.IGNORECASE)
    _PASSED_RE = re.compile(r"(\d+)\s+passed", re.IGNORECASE)
    _FAILED_RE = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
    _ERRORS_RE = re.compile(r"(\d+)\s+errors?", re.IGNORECASE)
    _SKIPPED_RE = re.compile(r"(\d+)\s+skipped", re.IGNORECASE)
    _WARNINGS_RE = re.compile(r"(\d+)\s+warnings?", re.IGNORECASE)

    # 失败用例正则: ____ test_name ____ 
    _FAILED_TEST_RE = re.compile(
        r"_+\s*(\w+(?:\.\w+)*)\s*_+",
    )

    # 错误类型正则: E   TypeError: ...
    _ERROR_TYPE_RE = re.compile(
        r"^E\s+(\w+(?:Error|Exception|Warning)):\s*(.*)$",
        re.MULTILINE,
    )

    # 文件位置正则: tests/test_foo.py:42: AssertionError
    _LOCATION_RE = re.compile(
        r"(tests/[^\s:]+):(\d+):",
    )

    async def run(
        self,
        test_path: str = "tests/",
        *,
        pattern: str = "test_*.py",
        verbose: bool = False,
        timeout: int = 120,
        cwd: str = "",
        extra_args: list[str] | None = None,
    ) -> TestRunResult:
        """执行 pytest 测试

        Args:
            test_path: 测试文件或目录路径
            pattern: 测试文件匹配模式 (默认 test_*.py)
            verbose: 是否显示详细输出 (-v)
            timeout: 超时时间 (秒)
            cwd: 工作目录
            extra_args: 额外的 pytest 参数

        Returns:
            TestRunResult: 测试运行结果
        """
        # 构建命令
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            test_path,
            "-p", "no:cacheprovider",  # 禁用缓存避免干扰
            "--tb=long",  # 完整回溯
        ]
        if verbose:
            cmd.append("-v")
        if pattern != "test_*.py":
            cmd.extend(["-k", pattern])
        if extra_args:
            cmd.extend(extra_args)

        # 执行 pytest
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or None,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return TestRunResult(
                success=False,
                stderr=f"测试执行超时 ({timeout}s)",
                duration=float(timeout),
            )
        except FileNotFoundError:
            return TestRunResult(
                success=False,
                stderr="pytest 未安装，请运行: pip install pytest",
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode

        # 解析结果
        result = self._parse_output(stdout, stderr, exit_code)
        result.stdout = stdout[-8000:]  # 保留最后 8000 字符
        result.stderr = stderr[-4000:]
        return result

    def _parse_output(
        self, stdout: str, stderr: str, exit_code: int
    ) -> TestRunResult:
        """解析 pytest 输出"""
        result = TestRunResult()

        # 查找摘要行
        summary_match = self._SUMMARY_LINE_RE.search(stdout)
        if summary_match:
            summary_text = summary_match.group(1)
            result.duration = float(summary_match.group(2) or 0.0)

            # 分别匹配每种类型
            passed_m = self._PASSED_RE.search(summary_text)
            failed_m = self._FAILED_RE.search(summary_text)
            errors_m = self._ERRORS_RE.search(summary_text)
            skipped_m = self._SKIPPED_RE.search(summary_text)
            warnings_m = self._WARNINGS_RE.search(summary_text)

            result.passed = int(passed_m.group(1)) if passed_m else 0
            result.failed = int(failed_m.group(1)) if failed_m else 0
            result.errors = int(errors_m.group(1)) if errors_m else 0
            result.skipped = int(skipped_m.group(1)) if skipped_m else 0
            result.warnings = int(warnings_m.group(1)) if warnings_m else 0
        else:
            # 没有摘要行，尝试从 exit_code 推断
            if exit_code == 0:
                result.passed = 0  # 无法确定数量
            elif exit_code == 5:
                # exit code 5 = 没有收集到测试
                result.skipped = 0
            else:
                result.failed = 1

        result.total = result.passed + result.failed + result.errors + result.skipped
        result.success = result.failed == 0 and result.errors == 0 and exit_code in (0, 5)

        # 解析失败详情
        result.failure_details = self._parse_failures(stdout)

        return result

    def _parse_failures(self, output: str) -> list[FailureDetail]:
        """解析失败测试的详情"""
        details: list[FailureDetail] = []

        # 按失败块分割
        # pytest 失败块格式: ============ FAILURES ============
        failures_section = ""
        fail_marker = "FAILURES"
        if fail_marker in output:
            start = output.find(fail_marker)
            # 找到下一个 summary 行 (===== ... passed/failed ...)
            end_match = re.search(r"={5,}\s*\d+\s+(passed|failed|error)", output[start:])
            end = start + end_match.start() if end_match else len(output)
            failures_section = output[start:end]

        if not failures_section:
            # 没有明确的 FAILURES 段落，尝试从 ERROR 段落解析
            error_marker = "ERRORS"
            if error_marker in output:
                start = output.find(error_marker)
                end_match = re.search(r"={5,}\s*\d+\s+(passed|failed|error)", output[start:])
                end = start + end_match.start() if end_match else len(output)
                failures_section = output[start:end]

        if not failures_section:
            return details

        # 按测试用例分割 (____ test_name ____)
        test_blocks = re.split(r"(_{5,}\s*\w+(?:\.\w+)*\s*_{5,})", failures_section)
        # test_blocks: ['', '____ test_name ____', 'traceback...', '____ test2 ____', 'traceback2...', ...]

        i = 1
        while i < len(test_blocks) - 1:
            test_header = test_blocks[i]
            test_body = test_blocks[i + 1] if i + 1 < len(test_blocks) else ""

            # 提取测试名
            name_match = self._FAILED_TEST_RE.match(test_header)
            test_name = name_match.group(1) if name_match else f"test_{i}"

            # 提取错误类型和消息
            error_match = self._ERROR_TYPE_RE.search(test_body)
            error_type = error_match.group(1) if error_match else "UnknownError"
            error_message = error_match.group(2) if error_match else ""

            # 提取文件位置
            location_match = self._LOCATION_RE.search(test_body)
            file_path = location_match.group(1) if location_match else ""
            line_number = int(location_match.group(2)) if location_match else 0

            # 提取回溯 (截取最后 2000 字符避免过长)
            traceback = test_body.strip()[-2000:] if test_body.strip() else ""

            details.append(
                FailureDetail(
                    test_name=test_name,
                    file_path=file_path,
                    line_number=line_number,
                    error_type=error_type,
                    error_message=error_message,
                    traceback=traceback,
                )
            )
            i += 2

        return details

    async def run_and_fix(
        self,
        test_path: str = "tests/",
        *,
        max_fix_attempts: int = 3,
        timeout: int = 120,
        cwd: str = "",
        fix_callback=None,
    ) -> dict:
        """执行测试并尝试自动修复 (修改→测试→修复 闭环)

        Args:
            test_path: 测试路径
            max_fix_attempts: 最大修复尝试次数
            timeout: 每次测试超时时间
            cwd: 工作目录
            fix_callback: 修复回调函数 (failure_details) -> bool

        Returns:
            dict: 最终结果
        """
        attempts = 0
        last_result = None

        while attempts < max_fix_attempts:
            attempts += 1
            result = await self.run(test_path, verbose=True, timeout=timeout, cwd=cwd)
            last_result = result

            if result.success:
                return {
                    "success": True,
                    "attempts": attempts,
                    "result": result.to_dict(),
                    "message": f"测试在第 {attempts} 次尝试后通过",
                }

            if not fix_callback:
                return {
                    "success": False,
                    "attempts": attempts,
                    "result": result.to_dict(),
                    "message": "未提供修复回调，无法自动修复",
                }

            # 调用修复回调
            try:
                fixed = await fix_callback(result.failure_details) if asyncio.iscoroutinefunction(fix_callback) else fix_callback(result.failure_details)
                if not fixed:
                    return {
                        "success": False,
                        "attempts": attempts,
                        "result": result.to_dict(),
                        "message": f"修复回调在第 {attempts} 次尝试后未能修复",
                    }
            except Exception as e:
                return {
                    "success": False,
                    "attempts": attempts,
                    "result": result.to_dict(),
                    "message": f"修复回调异常: {e}",
                }

        return {
            "success": False,
            "attempts": attempts,
            "result": last_result.to_dict() if last_result else None,
            "message": f"达到最大修复次数 ({max_fix_attempts})",
        }
