"""P1-2: ImpactAnalyzer 单元测试

测试覆盖:
1. 符号提取（def/class/method）
2. 引用关系提取
3. find_callers / find_callees / find_impact
4. DOT/JSON 导出
5. 异常文件处理（语法错误、不可读）
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sample_workspace():
    """创建临时工作区，含 3 个相互调用的 Python 文件"""
    tmp = Path(tempfile.mkdtemp(prefix="impact_test_"))

    # 文件 a.py: 定义 foo 和 bar
    (tmp / "a.py").write_text(
        '''"""Module A"""
def foo(x):
    """foo function"""
    return x + 1

def bar(x):
    """bar function"""
    return foo(x) * 2
''',
        encoding="utf-8",
    )

    # 文件 b.py: 从 a 导入并调用
    (tmp / "b.py").write_text(
        '''"""Module B - depends on A"""
from a import foo, bar

def caller_a():
    return foo(1)

def caller_b():
    return bar(2)

class MyClass:
    def method(self):
        return foo(3)
''',
        encoding="utf-8",
    )

    # 文件 c.py: 定义一个独立类
    (tmp / "c.py").write_text(
        '''"""Module C - independent"""
class Helper:
    def compute(self, x):
        return x * 3
''',
        encoding="utf-8",
    )

    # 一个语法错误文件（应被跳过，不影响其他）
    (tmp / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_symbol_extraction(sample_workspace):
    """应能正确提取所有 def/class/method 符号"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    syms = analyzer.list_symbols()
    names = {(s.file, s.qualname) for s in syms}
    # a.py 中应有 foo/bar
    assert ("a.py", "foo") in names
    assert ("a.py", "bar") in names
    # b.py 中应有 caller_a/caller_b/MyClass/MyClass.method
    assert ("b.py", "caller_a") in names
    assert ("b.py", "caller_b") in names
    assert ("b.py", "MyClass") in names
    assert ("b.py", "MyClass.method") in names
    # c.py 中应有 Helper/Helper.compute
    assert ("c.py", "Helper") in names
    assert ("c.py", "Helper.compute") in names


def test_function_args_and_docstring(sample_workspace):
    """函数符号应正确记录参数和文档"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    foo = analyzer.get_symbol("a.py", "foo")
    assert foo is not None
    assert foo.kind == "function"
    assert foo.args == ["x"]
    assert "foo function" in foo.docstring


def test_find_callers(sample_workspace):
    """find_callers 应正确返回调用点"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    # foo 被 caller_a 和 caller_b 内部调用
    callers = analyzer.find_callers("foo", file="a.py")
    assert len(callers) >= 1
    # bar 也调用了 foo（在 a.py 内）
    caller_names = {ref.caller_symbol for ref in callers}
    assert "bar" in caller_names

    # 跨文件：b.py 中的 caller_a/caller_b/MyClass.method 都调用了 foo
    callers_b = analyzer.find_callers("foo", file="b.py")
    # 注：b.py 是 import from，ast 解析后 callee_name 仍为 'foo'
    assert len(callers_b) >= 1


def test_find_callees(sample_workspace):
    """find_callees 应返回函数内部调用的下游符号"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    # bar 调用了 foo
    callees = analyzer.find_callees("bar", file="a.py")
    callee_names = {ref.callee_name for ref in callees}
    assert "foo" in callee_names

    # caller_a 调用了 foo
    callees_a = analyzer.find_callees("caller_a", file="b.py")
    assert any(ref.callee_name == "foo" for ref in callees_a)


def test_find_impact(sample_workspace):
    """find_impact 应反向递归查找所有调用方"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    # 修改 foo 应至少影响 bar（同一文件）
    impact = analyzer.find_impact("foo", file="a.py", max_depth=3)
    assert impact.total_count >= 1
    affected_symbols = {a["symbol"] for a in impact.affected}
    assert "bar" in affected_symbols


def test_stats(sample_workspace):
    """stats 应返回合理统计"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    stats = analyzer.stats()
    assert stats["total_symbols"] >= 7  # foo, bar, caller_a, caller_b, MyClass, MyClass.method, Helper, Helper.compute
    assert stats["total_references"] >= 3  # bar→foo, caller_a→foo, caller_b→bar, etc
    assert stats["files"] == 3  # a.py, b.py, c.py (bad.py 解析失败不计入符号)


def test_export_json(sample_workspace):
    """JSON 导出应可序列化"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    json_str = analyzer.export_json()
    data = json.loads(json_str)
    assert "stats" in data
    assert "symbols" in data
    assert "references" in data
    assert len(data["symbols"]) >= 7


def test_export_dot(sample_workspace):
    """DOT 导出应包含合法的 Graphviz 语法"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    dot = analyzer.export_dot()
    assert dot.startswith("digraph impact {")
    assert "rankdir=LR" in dot
    assert "->" in dot
    assert dot.endswith("}")


def test_syntax_error_file_handled(sample_workspace):
    """语法错误的文件应被跳过，不影响其他文件解析"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()  # 不应抛异常

    # a/b/c 文件应正常被解析
    syms = analyzer.list_symbols()
    files = {s.file for s in syms}
    assert "a.py" in files
    assert "b.py" in files
    assert "c.py" in files


def test_exclude_patterns():
    """应正确排除 venv/__pycache__ 等目录"""
    import tempfile

    from pycoder.python.impact_analyzer import ImpactAnalyzer

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # 主代码
        (tmp / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
        # venv 中的代码（应被排除）
        (tmp / ".venv").mkdir()
        (tmp / ".venv" / "lib.py").write_text("def venv_func():\n    pass\n", encoding="utf-8")
        # __pycache__（应被排除）
        (tmp / "__pycache__").mkdir()
        (tmp / "__pycache__" / "cached.py").write_text("def cached_func():\n    pass\n", encoding="utf-8")

        analyzer = ImpactAnalyzer(workspace=tmp)
        analyzer.build()

        files = {s.file for s in analyzer.list_symbols()}
        assert "main.py" in files
        # 排除规则应避免 venv 和 __pycache__
        assert not any(".venv" in f for f in files)
        assert not any("__pycache__" in f for f in files)


def test_class_method_extraction(sample_workspace):
    """类方法应被正确识别为 'ClassName.method' 全限定名"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    method = analyzer.get_symbol("b.py", "MyClass.method")
    assert method is not None
    assert method.kind == "method"
    assert "self" in method.args


def test_generate_prompt_context(sample_workspace):
    """应能生成可用的 Prompt 上下文"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    ctx = analyzer.generate_prompt_context()
    assert "## 项目引用图概览" in ctx
    assert "符号总数" in ctx
    assert "foo" in ctx or "bar" in ctx  # 高频被引用符号


def test_find_callers_no_match(sample_workspace):
    """不存在的符号应返回空列表而非抛异常"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    callers = analyzer.find_callers("nonexistent_func_xyz")
    assert callers == []


def test_attribute_call_detection(sample_workspace):
    """属性调用 (obj.method()) 应被正确识别"""
    from pycoder.python.impact_analyzer import ImpactAnalyzer

    analyzer = ImpactAnalyzer(workspace=sample_workspace)
    analyzer.build()

    # 添加一个测试文件含属性调用
    test_file = sample_workspace / "attr_test.py"
    test_file.write_text(
        '''"""Test attribute calls"""
class MyClass:
    def method(self):
        return 1

def use_obj():
    obj = MyClass()
    return obj.method()
''',
        encoding="utf-8",
    )

    analyzer.build()
    callees = analyzer.find_callees("use_obj", file="attr_test.py")
    assert any(ref.is_attribute for ref in callees)
    attr_ref = next(ref for ref in callees if ref.is_attribute)
    assert attr_ref.callee_name == "method"
    assert attr_ref.attribute_target == "obj"
