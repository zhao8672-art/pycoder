"""
refactor_analyzer.py 模块单元测试 — 覆盖率目标 >=80%

测试策略:
- 构造各种 Python 代码片段触发各检测器分支
- 覆盖 RefactoringAnalyzer 的所有 _detect_* 方法
- 覆盖 RefactoringExecutor 的 extract/rename/inline 操作
- 直接调用私有方法以覆盖深层分支
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from pycoder.python.refactor_analyzer import (
    DuplicateCode,
    FunctionMetrics,
    RefactoringExecutor,
    RefactoringIssue,
    RefactoringResult,
    RefactoringAnalyzer,
    analyze_refactoring,
    extract_function,
    rename_variable,
)


# ── 数据模型 ──────────────────────────────────────────────


def test_refactoring_issue_defaults():
    issue = RefactoringIssue(
        type="unused_import", severity="low", location="", line=1, column=0,
        message="msg", suggestion="sug",
    )
    assert issue.code_snippet == ""
    assert issue.fixable is False


def test_refactoring_result_defaults():
    r = RefactoringResult(success=True)
    assert r.issues == []
    assert r.summary == ""
    assert r.refactored_code == ""


def test_duplicate_code_defaults():
    d = DuplicateCode(hash="abc", locations=[], code="x", occurrences=1)
    assert d.hash == "abc"


def test_function_metrics_defaults():
    m = FunctionMetrics(name="f", line_count=1, complexity=1, parameter_count=0, calls=0, max_nesting=0)
    assert m.has_duplicates is False


# ── RefactoringAnalyzer.analyze_code ──────────────────────


def test_analyze_code_success_clean():
    """无问题的代码"""
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code("x = 1\nprint(x)\n")
    assert result.success is True
    assert result.issues == []


def test_analyze_code_syntax_error():
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code("def broken(:\n")
    assert result.success is False
    assert "分析失败" in result.summary


def test_analyze_code_with_file_path():
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code("x = 1\nprint(x)\n", file_path="test.py")
    assert result.success is True


# ── _detect_unused_imports ────────────────────────────────


def test_detect_unused_imports():
    analyzer = RefactoringAnalyzer()
    code = textwrap.dedent('''
        import os
        import unused_mod
        from sys import path
        from json import loads as l

        print(os.getcwd())
    ''')
    tree = ast.parse(code)
    lines = code.split("\n")
    analyzer._detect_unused_imports(tree, "test.py", lines)
    types = [i.type for i in analyzer._issues]
    assert "unused_import" in types
    unused_names = [i.message for i in analyzer._issues if i.type == "unused_import"]
    assert any("unused_mod" in m for m in unused_names)
    assert any("path" in m for m in unused_names)
    assert any("l" in m for m in unused_names)


def test_detect_unused_imports_all_used():
    analyzer = RefactoringAnalyzer()
    code = "import os\nprint(os.getcwd())\n"
    tree = ast.parse(code)
    analyzer._detect_unused_imports(tree, "", code.split("\n"))
    assert analyzer._issues == []


# ── _detect_long_functions ────────────────────────────────


def test_detect_long_functions():
    analyzer = RefactoringAnalyzer()
    # 构造一个超过 50 行的函数
    body = "\n".join(f"    x{i} = {i}" for i in range(55))
    code = f"def long_func():\n{body}\n"
    tree = ast.parse(code)
    analyzer._detect_long_functions(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "long_function" in types


def test_detect_long_functions_short():
    analyzer = RefactoringAnalyzer()
    code = "def short():\n    return 1\n"
    tree = ast.parse(code)
    analyzer._detect_long_functions(tree, "", code.split("\n"))
    assert analyzer._issues == []


# ── _detect_high_complexity / _calculate_complexity ───────


def test_calculate_complexity_simple():
    analyzer = RefactoringAnalyzer()
    node = ast.parse("def f():\n    return 1\n").body[0]
    assert analyzer._calculate_complexity(node) == 1


def test_calculate_complexity_branches():
    analyzer = RefactoringAnalyzer()
    code = textwrap.dedent('''
        def f(a, b):
            if a and b:
                for i in []:
                    while False:
                        pass
            return 1 if a else 0
    ''')
    node = ast.parse(code).body[0]
    # if(1) + and(1) + for(1) + while(1) + IfExp(1) = base 1 + 5 = 6
    assert analyzer._calculate_complexity(node) >= 6


def test_calculate_complexity_try():
    analyzer = RefactoringAnalyzer()
    code = textwrap.dedent('''
        def f():
            try:
                pass
            except ValueError:
                pass
            except TypeError:
                pass
    ''')
    node = ast.parse(code).body[0]
    # base 1 + 2 handlers = 3
    assert analyzer._calculate_complexity(node) == 3


def test_detect_high_complexity():
    analyzer = RefactoringAnalyzer()
    branches = "\n".join(f"    if x{i}: pass" for i in range(15))
    code = f"def f():\n{branches}\n"
    tree = ast.parse(code)
    analyzer._detect_high_complexity(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "high_complexity" in types


def test_detect_high_complexity_low():
    analyzer = RefactoringAnalyzer()
    code = "def f():\n    if x: pass\n"
    tree = ast.parse(code)
    analyzer._detect_high_complexity(tree, "", code.split("\n"))
    assert analyzer._issues == []


# ── _detect_too_many_params ───────────────────────────────


def test_detect_too_many_params():
    analyzer = RefactoringAnalyzer()
    params = ", ".join(f"a{i}" for i in range(8))
    code = f"def f({params}):\n    pass\n"
    tree = ast.parse(code)
    analyzer._detect_too_many_params(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "too_many_params" in types


def test_detect_too_many_params_few():
    analyzer = RefactoringAnalyzer()
    code = "def f(a, b):\n    pass\n"
    tree = ast.parse(code)
    analyzer._detect_too_many_params(tree, "", code.split("\n"))
    assert analyzer._issues == []


# ── _detect_deep_nesting / _calculate_nesting ─────────────


def test_calculate_nesting_flat():
    analyzer = RefactoringAnalyzer()
    node = ast.parse("x = 1\n")
    assert analyzer._calculate_nesting(node) == 0


def test_calculate_nesting_deep():
    analyzer = RefactoringAnalyzer()
    code = textwrap.dedent('''
        def f():
            if a:
                if b:
                    if c:
                        if d:
                            pass
    ''')
    node = ast.parse(code).body[0]
    # def > if > if > if > if = 4 层 (if 计数)
    assert analyzer._calculate_nesting(node) >= 4


def test_detect_deep_nesting():
    analyzer = RefactoringAnalyzer()
    code = textwrap.dedent('''
        def f():
            if a:
                if b:
                    if c:
                        if d:
                            pass
    ''')
    tree = ast.parse(code)
    analyzer._detect_deep_nesting(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "deep_nesting" in types


def test_detect_deep_nesting_shallow():
    analyzer = RefactoringAnalyzer()
    code = "def f():\n    if a: pass\n"
    tree = ast.parse(code)
    analyzer._detect_deep_nesting(tree, "", code.split("\n"))
    assert analyzer._issues == []


# ── _detect_magic_numbers / _get_parent ───────────────────


def test_detect_magic_numbers_in_call():
    analyzer = RefactoringAnalyzer()
    code = "print(42)\n"
    tree = ast.parse(code)
    analyzer._detect_magic_numbers(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "magic_number" in types


def test_detect_magic_numbers_in_assignment_skipped():
    analyzer = RefactoringAnalyzer()
    code = "x = 42\n"
    tree = ast.parse(code)
    analyzer._detect_magic_numbers(tree, "", code.split("\n"))
    assert analyzer._issues == []


def test_detect_magic_numbers_zero_one_skipped():
    analyzer = RefactoringAnalyzer()
    code = "print(0)\nprint(1)\nprint(-1)\n"
    tree = ast.parse(code)
    analyzer._detect_magic_numbers(tree, "", code.split("\n"))
    assert analyzer._issues == []


def test_get_parent_returns_none_for_root():
    analyzer = RefactoringAnalyzer()
    tree = ast.parse("x = 1\n")
    root = tree
    # root has no parent
    assert analyzer._get_parent(tree, root) is None


def test_get_parent_finds_parent():
    analyzer = RefactoringAnalyzer()
    tree = ast.parse("x = 1\n")
    assign = tree.body[0]
    value = assign.value
    parent = analyzer._get_parent(tree, value)
    assert parent is assign


# ── _detect_unused_variables ──────────────────────────────


def test_detect_unused_variables():
    analyzer = RefactoringAnalyzer()
    code = "unused = 1\nused = 2\nprint(used)\n"
    tree = ast.parse(code)
    analyzer._detect_unused_variables(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "unused_variable" in types
    msgs = [i.message for i in analyzer._issues if i.type == "unused_variable"]
    assert any("unused" in m for m in msgs)


def test_detect_unused_variables_all_used():
    analyzer = RefactoringAnalyzer()
    code = "x = 1\nprint(x)\n"
    tree = ast.parse(code)
    analyzer._detect_unused_variables(tree, "", code.split("\n"))
    assert analyzer._issues == []


def test_detect_unused_variables_annassign():
    """AnnAssign 分支被第一个循环执行（加入 assigned 集合），
    但第二个循环只检查 ast.Assign，因此 AnnAssign 的未使用变量不会生成 issue。
    这里验证 AnnAssign 与 Assign 混合时，Assign 的未使用变量仍被检测到。"""
    analyzer = RefactoringAnalyzer()
    code = "y: int = 5\nz = 10\n"
    tree = ast.parse(code)
    analyzer._detect_unused_variables(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    # z (Assign) 被检测为未使用变量
    assert "unused_variable" in types
    msgs = [i.message for i in analyzer._issues if i.type == "unused_variable"]
    assert any("z" in m for m in msgs)


# ── _detect_duplicate_code / _extract_code_blocks ─────────


def test_extract_code_blocks_function():
    analyzer = RefactoringAnalyzer()
    code = "def f():\n    return 1\n"
    tree = ast.parse(code)
    blocks = analyzer._extract_code_blocks(tree, code.split("\n"))
    assert len(blocks) == 1
    assert "def f" in blocks[0]["code"]


def test_extract_code_blocks_if_for():
    analyzer = RefactoringAnalyzer()
    code = textwrap.dedent('''
        if x:
            a = 1
            b = 2
            c = 3
            d = 4
            e = 5
        for i in []:
            a = 1
            b = 2
            c = 3
            d = 4
            e = 5
    ''')
    tree = ast.parse(code)
    blocks = analyzer._extract_code_blocks(tree, code.split("\n"))
    assert len(blocks) >= 2


def test_detect_duplicate_code_three_identical_functions():
    analyzer = RefactoringAnalyzer()
    func_def = textwrap.dedent('''
        def f():
            x = 1
            y = 2
            z = 3
            return x + y + z
    ''').strip()
    code = func_def + "\n\n" + func_def + "\n\n" + func_def + "\n"
    tree = ast.parse(code)
    analyzer._detect_duplicate_code(tree, "test.py", code.split("\n"))
    types = [i.type for i in analyzer._issues]
    assert "duplicate_code" in types


def test_detect_duplicate_code_below_threshold():
    analyzer = RefactoringAnalyzer()
    func_def = "def f():\n    return 1\n"
    code = func_def + "\n" + func_def  # 仅 2 次，阈值 3
    tree = ast.parse(code)
    analyzer._detect_duplicate_code(tree, "", code.split("\n"))
    assert analyzer._issues == []


# ── _generate_summary ─────────────────────────────────────


def test_generate_summary_no_issues():
    analyzer = RefactoringAnalyzer()
    assert "未发现重构问题" in analyzer._generate_summary()


def test_generate_summary_with_issues():
    analyzer = RefactoringAnalyzer()
    analyzer._add_issue(
        type="unused_import", severity="low", location="", line=1, column=0,
        message="msg", suggestion="sug",
    )
    analyzer._add_issue(
        type="long_function", severity="high", location="", line=1, column=0,
        message="msg", suggestion="sug",
    )
    analyzer._add_issue(
        type="magic_number", severity="medium", location="", line=1, column=0,
        message="msg", suggestion="sug",
    )
    summary = analyzer._generate_summary()
    assert "3 个重构问题" in summary
    assert "高优先级: 1" in summary
    assert "中优先级: 1" in summary
    assert "低优先级: 1" in summary
    assert "重复代码" not in summary  # 没有 duplicate_code 类型


def test_generate_summary_unknown_type():
    analyzer = RefactoringAnalyzer()
    analyzer._add_issue(
        type="custom_type", severity="low", location="", line=1, column=0,
        message="msg", suggestion="sug",
    )
    summary = analyzer._generate_summary()
    assert "custom_type" in summary  # 未知类型直接显示类型名


# ── _add_issue ─────────────────────────────────────────────


def test_add_issue_appends():
    analyzer = RefactoringAnalyzer()
    analyzer._add_issue(
        type="test", severity="low", location="", line=1, column=0,
        message="m", suggestion="s",
    )
    assert len(analyzer._issues) == 1
    assert analyzer._issues[0].type == "test"


# ── analyze_code 综合测试 ─────────────────────────────────


def test_analyze_code_comprehensive():
    analyzer = RefactoringAnalyzer()
    # 构造一个超过 50 行的函数以触发 long_function
    code = "import unused_import_xyz\n\n"
    code += "def long_function(a, b, c, d, e, f):\n"
    for i in range(55):
        code += f"    v{i} = {i}\n"
    code += "    if a:\n"
    code += "        if b:\n"
    code += "            if c:\n"
    code += "                if d:\n"
    code += "                    pass\n"
    code += "    return v0\n"
    code += "print(99)\n"
    result = analyzer.analyze_code(code, "test.py")
    assert result.success is True
    types = [i.type for i in result.issues]
    assert "unused_import" in types
    assert "long_function" in types
    assert "too_many_params" in types
    assert "deep_nesting" in types
    assert "magic_number" in types


# ── RefactoringExecutor.extract_function ──────────────────


def test_extract_function_out_of_range():
    executor = RefactoringExecutor()
    result = executor.extract_function("line1\nline2\n", 0, 5, "new_func")
    assert result.success is False
    assert "行号超出范围" in result.summary


def test_extract_function_success():
    executor = RefactoringExecutor()
    code = "    x = 1\n    y = 2\n    return x + y\n"
    result = executor.extract_function(code, 1, 3, "extracted")
    assert result.success is True
    assert "def extracted():" in result.refactored_code
    assert "return ..." in result.refactored_code
    assert "extracted()" in result.refactored_code
    assert "成功提取函数" in result.summary


def test_extract_function_exception():
    executor = RefactoringExecutor()
    # 传入非字符串以触发异常 — 但 split 是 str 方法，所以用特殊方式
    # 直接测试正常的边界情况
    result = executor.extract_function("x\n", 1, 1, "f")
    assert result.success is True


# ── RefactoringExecutor.rename_variable ───────────────────


def test_rename_variable_success():
    executor = RefactoringExecutor()
    code = "x = 1\nprint(x)\ny = x + 1\n"
    result = executor.rename_variable(code, "x", "renamed")
    assert result.success is True
    assert "renamed" in result.refactored_code
    assert "成功" in result.summary


def test_rename_variable_not_found():
    executor = RefactoringExecutor()
    code = "x = 1\n"
    result = executor.rename_variable(code, "nonexistent", "renamed")
    assert result.success is True  # 没找到也返回 success
    assert result.refactored_code == code


def test_rename_variable_syntax_error():
    executor = RefactoringExecutor()
    result = executor.rename_variable("def broken(:\n", "x", "y")
    assert result.success is False
    assert "重命名变量失败" in result.summary


# ── RefactoringExecutor.inline_function ───────────────────


def test_inline_function_not_found():
    executor = RefactoringExecutor()
    result = executor.inline_function("def f():\n    return 1\n", "nonexistent")
    assert result.success is False
    assert "未找到函数" in result.summary


def test_inline_function_success():
    executor = RefactoringExecutor()
    code = textwrap.dedent('''
        def helper():
            return 42
        result = helper()
    ''').strip()
    result = executor.inline_function(code, "helper")
    assert result.success is True
    assert "成功内联函数" in result.summary


def test_inline_function_syntax_error():
    executor = RefactoringExecutor()
    result = executor.inline_function("def broken(:\n", "f")
    assert result.success is False
    assert "内联函数失败" in result.summary


# ── 模块级快捷函数 ────────────────────────────────────────


def test_module_analyze_refactoring():
    result = analyze_refactoring("x = 1\nprint(x)\n", "test.py")
    assert result.success is True


def test_module_extract_function():
    result = extract_function("x = 1\n", 1, 1, "f")
    assert result.success is True


def test_module_rename_variable():
    result = rename_variable("x = 1\nprint(x)\n", "x", "y")
    assert result.success is True
    assert "y" in result.refactored_code
