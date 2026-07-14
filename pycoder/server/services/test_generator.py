"""
智能测试生成器 — 分析源码 → 生成 pytest 测试 → 运行 → 覆盖率报告

流程:
  1. AST 解析源文件, 提取所有函数/方法/参数/返回类型
  2. 为每个函数生成测试用例（正常路径 + 边界 + 异常）
  3. 生成完整 pytest 文件
  4. 运行 pytest --cov 获取覆盖率
  5. 返回测试结果和覆盖率报告
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pycoder.server.log import log


@dataclass
class TestCase:
    """单个测试用例"""

    name: str
    source: str
    category: str = "normal"  # normal | edge | error


@dataclass
class TestGenerationResult:
    """测试生成结果"""

    success: bool
    test_file: str = ""
    test_count: int = 0
    passed: int = 0
    failed: int = 0
    coverage_percent: float = 0.0
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


class TestGenerator:
    """
    智能测试生成器 — 单例模式
    """

    def __init__(self, workspace_root: str | Path | None = None):
        self._workspace = Path(workspace_root or os.getcwd()).resolve()
        self._test_dir = self._workspace / ".pycoder_tests"
        self._test_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, source_path: str | Path) -> TestGenerationResult:
        """
        分析源文件并生成 pytest 测试文件。

        Args:
            source_path: 源文件路径（绝对或相对项目根）

        Returns:
            TestGenerationResult
        """
        target = Path(source_path)
        if not target.is_absolute():
            target = self._workspace / target
        if not target.exists():
            return TestGenerationResult(success=False, error=f"文件不存在: {source_path}")

        code = target.read_text(encoding="utf-8")
        start_time = time.time()

        # 1. AST 解析
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return TestGenerationResult(success=False, error=f"语法错误: {e}")

        # 2. 提取函数/类信息
        functions = []
        classes = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(self._analyze_function(node, None))
            elif isinstance(node, ast.ClassDef):
                cls_info = {"name": node.name, "methods": []}
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        cls_info["methods"].append(self._analyze_function(item, node.name))
                classes.append(cls_info)

        if not functions and not classes:
            # 回退: 没有可测试函数, 生成最小占位测试
            return self._generate_placeholder(source_path)

        # 3. 为每个函数生成测试用例
        test_cases: list[TestCase] = []
        for func in functions:
            test_cases.extend(self._generate_tests_for_function(func))

        # 4. 为每个类方法生成测试用例
        for cls_info in classes:
            for method in cls_info["methods"]:
                test_cases.extend(self._generate_tests_for_function(method))

        if not test_cases:
            return self._generate_placeholder(source_path)

        # 5. 生成 pytest 文件
        module_name = target.stem
        test_filename = f"test_{module_name}.py"
        test_file = self._test_dir / test_filename

        test_content = self._build_test_file(code, module_name, test_cases)
        test_file.write_text(test_content, encoding="utf-8")

        # 6. 运行测试
        run_result = self._run_tests(test_file)

        duration = (time.time() - start_time) * 1000

        return TestGenerationResult(
            success=run_result["success"],
            test_file=str(test_file),
            test_count=len(test_cases),
            passed=run_result["passed"],
            failed=run_result["failed"],
            coverage_percent=run_result["coverage"],
            output=run_result["output"],
            duration_ms=duration,
        )

    def _analyze_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None
    ) -> dict:
        """分析函数的参数/返回类型/文档"""
        info = {
            "name": node.name,
            "class_name": class_name,
            "args": [],
            "return_type": None,
            "docstring": ast.get_docstring(node) or "",
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "has_return": False,
            "raises": [],
        }

        # 参数分析
        for arg in node.args.args:
            arg_info = {"name": arg.arg, "type": None}
            if arg.annotation:
                arg_info["type"] = self._extract_type_name(arg.annotation)
            info["args"].append(arg_info)

        # 返回类型
        if node.returns:
            info["return_type"] = self._extract_type_name(node.returns)

        # 分析函数体
        for body_node in ast.walk(node):
            if isinstance(body_node, ast.Return) and body_node.value is not None:
                info["has_return"] = True
            if isinstance(body_node, ast.Raise):
                if hasattr(body_node, "exc") and body_node.exc:
                    if hasattr(body_node.exc, "func") and hasattr(body_node.exc.func, "id"):
                        info["raises"].append(body_node.exc.func.id)

        return info

    def _extract_type_name(self, node: ast.AST) -> str:
        """从 AST 节点提取类型名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                return f"{node.value.id}[...]"
            return "..."
        elif isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.BinOp):
            return "Union"
        return "Any"

    def _generate_tests_for_function(self, func: dict) -> list[TestCase]:
        """为单个函数生成测试用例"""
        cases = []
        full_name = f"{func['class_name']}_{func['name']}" if func["class_name"] else func["name"]

        # 判断参数类型以生成合适的测试数据
        has_str_arg = any(a["type"] in ("str", "string", "Any") for a in func["args"])
        has_int_arg = any(a["type"] in ("int", "float", "number") for a in func["args"])

        # 正常路径测试
        normal_args = []
        for arg in func["args"]:
            if arg["type"] in ("str", "string", "Any"):
                normal_args.append('"test_input"')
            elif arg["type"] in ("int", "float", "number"):
                normal_args.append("42")
            elif arg["type"] in ("bool",):
                normal_args.append("True")
            elif arg["type"] in ("list", "List"):
                normal_args.append("[1, 2, 3]")
            elif arg["type"] in ("dict", "Dict", "Mapping"):
                normal_args.append('{"key": "value"}')
            elif arg["type"] in ("Optional", "NoneType"):
                normal_args.append("None")
            else:
                normal_args.append('"test"')

        if func["args"]:
            call_args = ", ".join(normal_args)
            # 普通测试
            normal_test = (
                f"def test_{full_name}_normal():\n" f'    """测试 {func["name"]} 基本功能"""\n'
            )
            if func["class_name"]:
                normal_test += (
                    f"    instance = {func['class_name']}()\n"
                    f"    result = instance.{func['name']}({call_args})\n"
                )
            else:
                normal_test += f"    result = {func['name']}({call_args})\n"
            if func["has_return"]:
                normal_test += "    assert result is not None\n"

            cases.append(
                TestCase(
                    name=f"test_{full_name}_normal",
                    source=normal_test,
                    category="normal",
                )
            )

        # 边界测试 (字符串参数)
        if has_str_arg:
            edge_test = (
                f"def test_{full_name}_empty_string():\n"
                f'    """测试 {func["name"]} 空字符串输入"""\n'
            )
            edge_args = []
            for arg in func["args"]:
                if arg["type"] in ("str", "string", "Any"):
                    edge_args.append('""')
                else:
                    edge_args.append(normal_args[len(edge_args)])
            call_args = ", ".join(edge_args)
            if func["class_name"]:
                edge_test += (
                    f"    instance = {func['class_name']}()\n"
                    f"    result = instance.{func['name']}({call_args})\n"
                )
            else:
                edge_test += f"    result = {func['name']}({call_args})\n"
            cases.append(
                TestCase(
                    name=f"test_{full_name}_empty_string",
                    source=edge_test,
                    category="edge",
                )
            )

        # 边界测试 (整数参数)
        if has_int_arg:
            edge_test = (
                f"def test_{full_name}_zero():\n" f'    """测试 {func["name"]} 零值输入"""\n'
            )
            edge_args = []
            for arg in func["args"]:
                if arg["type"] in ("int", "float", "number"):
                    edge_args.append("0")
                else:
                    edge_args.append(normal_args[len(edge_args)])
            call_args = ", ".join(edge_args)
            if func["class_name"]:
                edge_test += (
                    f"    instance = {func['class_name']}()\n"
                    f"    result = instance.{func['name']}({call_args})\n"
                )
            else:
                edge_test += f"    result = {func['name']}({call_args})\n"
            cases.append(
                TestCase(
                    name=f"test_{full_name}_zero",
                    source=edge_test,
                    category="edge",
                )
            )

        # 无参数函数
        if not func["args"]:
            noarg_test = (
                f"def test_{full_name}_basic():\n" f'    """测试 {func["name"]} 无参数调用"""\n'
            )
            if func["class_name"]:
                noarg_test += (
                    f"    instance = {func['class_name']}()\n"
                    f"    result = instance.{func['name']}()\n"
                )
            else:
                noarg_test += f"    result = {func['name']}()\n"
            cases.append(
                TestCase(
                    name=f"test_{full_name}_basic",
                    source=noarg_test,
                    category="normal",
                )
            )

        return cases

    def _build_test_file(
        self, source_code: str, module_name: str, test_cases: list[TestCase]
    ) -> str:
        """构建完整的 pytest 文件"""
        lines = [
            '"""',
            f"自动生成的测试文件 — {module_name}",
            "由 PyCoder 智能测试生成器生成",
            '"""',
            "",
            "import pytest",
            "import sys",
            "from pathlib import Path",
            "",
            "# 将项目根目录加入 sys.path",
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))",
            "",
            f"from {module_name} import *",
            "",
        ]

        for tc in test_cases:
            lines.append("")
            lines.append(tc.source)

        return "\n".join(lines)

    def _run_tests(self, test_file: Path) -> dict:
        """运行 pytest 并返回结果"""
        try:
            # 先用子进程运行 pytest
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(test_file),
                    "-v",
                    "--tb=short",
                    "--no-header",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self._workspace),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            output = proc.stdout + "\n" + proc.stderr
            passed = output.count("PASSED")
            failed = output.count("FAILED")
            success = proc.returncode == 0

            # 尝试获取覆盖率
            coverage = self._get_coverage(test_file)

            return {
                "success": success,
                "passed": passed or (1 if success else 0),
                "failed": failed or (0 if success else 1),
                "coverage": coverage,
                "output": output[:2000],  # 截断避免过大
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "passed": 0,
                "failed": 1,
                "coverage": 0.0,
                "output": "测试执行超时 (60s)",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "passed": 0,
                "failed": 1,
                "coverage": 0.0,
                "output": "pytest 未安装 (pip install pytest)",
            }
        except Exception as e:
            return {
                "success": False,
                "passed": 0,
                "failed": 1,
                "coverage": 0.0,
                "output": f"运行错误: {e}",
            }

    def _get_coverage(self, test_file: Path) -> float:
        """使用 coverage 模块获取覆盖率"""
        try:
            import coverage  # type: ignore

            cov = coverage.Coverage(source=[str(self._workspace)])
            cov.start()
            subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"],
                capture_output=True,
                timeout=60,
                cwd=str(self._workspace),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            cov.stop()
            cov.save()
            data = cov.get_data()
            # 简单计算行覆盖率
            total = 0
            covered = 0
            for filename in data.measured_files():
                if "site-packages" not in filename and ".pycoder_tests" not in filename:
                    analysis = cov.analysis(filename)
                    total += len(analysis[1])
                    covered += len([x for x in analysis[1] if x > 0])  # noqa
            if total > 0:
                return round(covered / total * 100, 1)
            return 0.0
        except ImportError:
            # 无 coverage 模块, 尝试通过 pytest-cov
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        str(test_file),
                        "-q",
                        "--tb=short",
                        "--cov=" + str(self._workspace),
                        "--cov-report=term-missing",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=str(self._workspace),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                # 从输出中提取覆盖率
                import re

                m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", proc.stdout)
                if m:
                    return float(m.group(1))
                return 0.0
            except (subprocess.SubprocessError, OSError, ValueError) as e:
                log.debug("coverage_via_pytest_cov_failed", test_file=str(test_file), error=str(e))
                return 0.0
        except Exception as e:
            # coverage 模块整体失败（导入/启动/数据收集），降级返回 0
            log.debug("coverage_measurement_failed", test_file=str(test_file), error=str(e))
            return 0.0

    def _generate_placeholder(self, source_path: Path) -> TestGenerationResult:
        """当没有可测试函数时生成占位测试"""
        module_name = source_path.stem
        test_file = self._test_dir / f"test_{module_name}.py"
        content = (
            f'"""\n'
            f"占位测试 — {module_name}\n"
            f'"""\n\n'
            f"import pytest\n\n\n"
            f"def test_placeholder():\n"
            f'    """基础占位测试"""\n'
            f"    assert True\n"
        )
        test_file.write_text(content, encoding="utf-8")
        return TestGenerationResult(
            success=True,
            test_file=str(test_file),
            test_count=0,
            output="源文件中未发现可测试的函数或方法, 已生成占位测试",
        )


# 全局快捷函数
_generator: TestGenerator | None = None


def get_test_generator(workspace: str | Path | None = None) -> TestGenerator:
    global _generator
    if _generator is None:
        _generator = TestGenerator(workspace)
    return _generator
