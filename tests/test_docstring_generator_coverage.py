"""
docstring_generator.py 模块单元测试 — 覆盖率目标 >=80%

测试策略:
- 构造各种 Python 代码片段作为 AST 输入
- 覆盖 DocstringGenerator 三种风格 (google/numpy/rest) 的所有分支
- 覆盖 ChineseCommentGenerator 的注释生成逻辑
- 用 tmp_path 隔离文件读写
- 直接调用私有方法以覆盖深层分支
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from pycoder.python.docstring_generator import (
    ChineseCommentGenerator,
    DocstringGenerator,
    DocstringResult,
    FileDocstringResult,
    add_chinese_comments,
    generate_docstring,
)


# ── 数据模型 ──────────────────────────────────────────────


def test_docstring_result_defaults():
    r = DocstringResult(success=True)
    assert r.function_name == ""
    assert r.original_code == ""
    assert r.generated_docstring == ""
    assert r.updated_code == ""
    assert r.style == "google"
    assert r.error == ""


def test_file_docstring_result_defaults():
    r = FileDocstringResult(success=True)
    assert r.file_path == ""
    assert r.functions_processed == 0
    assert r.classes_processed == 0
    assert r.updated_code == ""
    assert r.errors == []


# ── __init__ ──────────────────────────────────────────────


def test_init_lowercases_style():
    g = DocstringGenerator("GOOGLE")
    assert g.style == "google"


def test_init_unknown_style():
    g = DocstringGenerator("unknown")
    assert g.style == "unknown"


# ── _infer_type ───────────────────────────────────────────


def test_infer_type_none():
    assert DocstringGenerator()._infer_type(None) == "None"


def test_infer_type_values():
    g = DocstringGenerator()
    assert g._infer_type(42) == "int"
    assert g._infer_type("hi") == "str"
    assert g._infer_type([1]) == "list"


# ── _annotation_to_str ────────────────────────────────────


def _ann(code: str):
    """从 `x: <ann> = ...` 中提取 annotation 节点"""
    return ast.parse(code).body[0].annotation


def test_annotation_to_str_name():
    assert DocstringGenerator()._annotation_to_str(_ann("x: int = 0")) == "int"


def test_annotation_to_str_attribute():
    assert DocstringGenerator()._annotation_to_str(_ann("x: typing.Any = 0")) == "Any"


def test_annotation_to_str_subscript():
    assert DocstringGenerator()._annotation_to_str(_ann("x: List[int] = []")) == "List[int]"


def test_annotation_to_str_constant():
    assert DocstringGenerator()._annotation_to_str(_ann("x: 42 = 0")) == "42"


def test_annotation_to_str_tuple():
    # Tuple[int, str] 解析为 Subscript(value=Name('Tuple'), slice=Tuple(...))
    # slice 是 Tuple 节点 → _annotation_to_str 走 ast.Tuple 分支
    # 返回 "Tuple[Tuple[int, str]]" (外层 Subscript 包裹内层 Tuple 转换结果)
    result = DocstringGenerator()._annotation_to_str(_ann("x: Tuple[int, str] = 0"))
    assert "Tuple" in result
    assert "int" in result
    assert "str" in result


def test_annotation_to_str_empty_list_ast():
    g = DocstringGenerator()
    list_node = ast.List(elts=[], ctx=ast.Load())
    assert g._annotation_to_str(list_node) == "List"


def test_annotation_to_str_list_with_elts_ast():
    g = DocstringGenerator()
    list_node = ast.List(
        elts=[ast.Name(id="int", ctx=ast.Load()), ast.Name(id="str", ctx=ast.Load())],
        ctx=ast.Load(),
    )
    assert g._annotation_to_str(list_node) == "List[int, str]"


def test_annotation_to_str_call():
    g = DocstringGenerator()
    result = g._annotation_to_str(_ann("x: Annotated[int, 'meta'] = 0"))
    assert "Annotated" in result and "int" in result


def test_annotation_to_str_unknown_returns_any():
    g = DocstringGenerator()
    # Lambda is not handled by any branch → "Any"
    lambda_node = ast.parse("x: (lambda: 0) = 0").body[0].annotation
    assert g._annotation_to_str(lambda_node) == "Any"


# ── _value_to_str ──────────────────────────────────────────


def _val(code: str):
    """从 `x = <val>` 中提取 value 节点"""
    return ast.parse(code).body[0].value


def test_value_to_str_string_constant():
    assert DocstringGenerator()._value_to_str(_val('x = "hello"')) == '"hello"'


def test_value_to_str_int_constant():
    assert DocstringGenerator()._value_to_str(_val("x = 42")) == "42"


def test_value_to_str_name():
    assert DocstringGenerator()._value_to_str(_val("x = y")) == "y"


def test_value_to_str_list():
    assert DocstringGenerator()._value_to_str(_val("x = [1, 2]")) == "[1, 2]"


def test_value_to_str_dict():
    result = DocstringGenerator()._value_to_str(_val('x = {"a": 1}'))
    assert '"a"' in result and "1" in result


def test_value_to_str_unknown():
    g = DocstringGenerator()
    # UnaryOp is not handled → "..."
    op = ast.parse("x = ...").body[0].value
    # ... is Ellipsis (Constant), so actually returns repr(Ellipsis)
    # Use a node that isn't handled
    unhandled = ast.IfExp(test=ast.Constant(value=True), body=ast.Constant(1), orelse=ast.Constant(2))
    assert g._value_to_str(unhandled) == "..."


# ── _infer_function_description ───────────────────────────


def test_infer_function_description_pattern():
    g = DocstringGenerator()
    info = {"is_async": False, "has_loop": False, "has_condition": False, "has_return": False}
    assert g._infer_function_description("add_numbers", info) == "加法运算"
    assert g._infer_function_description("search_items", info) == "搜索操作"


def test_infer_function_description_async():
    g = DocstringGenerator()
    # "zzz" 不匹配任何 pattern → 走 is_async 分支
    info = {"is_async": True, "has_loop": False, "has_condition": False, "has_return": False}
    assert "异步执行" in g._infer_function_description("zzz", info)


def test_infer_function_description_loop_and_condition():
    g = DocstringGenerator()
    info = {"is_async": False, "has_loop": True, "has_condition": True, "has_return": False}
    assert "复杂处理函数" in g._infer_function_description("zzz", info)


def test_infer_function_description_loop_only():
    g = DocstringGenerator()
    info = {"is_async": False, "has_loop": True, "has_condition": False, "has_return": False}
    assert "遍历处理函数" in g._infer_function_description("zzz", info)


def test_infer_function_description_condition_only():
    g = DocstringGenerator()
    info = {"is_async": False, "has_loop": False, "has_condition": True, "has_return": False}
    assert "条件判断函数" in g._infer_function_description("zzz", info)


def test_infer_function_description_return_only():
    g = DocstringGenerator()
    info = {"is_async": False, "has_loop": False, "has_condition": False, "has_return": True}
    assert "返回计算结果" in g._infer_function_description("zzz", info)


def test_infer_function_description_default():
    g = DocstringGenerator()
    info = {"is_async": False, "has_loop": False, "has_condition": False, "has_return": False}
    assert g._infer_function_description("zzz", info) == "zzz 函数"


# ── _infer_arg_description ─────────────────────────────────


@pytest.mark.parametrize(
    "name, arg_type, keyword",
    [
        ("name", "Any", "The name"),
        ("username", "Any", "The name"),
        ("id", "Any", "Unique identifier"),
        ("user_id", "Any", "Unique identifier"),
        ("path", "Any", "Path to"),
        ("file_path", "Any", "Path to"),
        ("data", "Any", "Input data"),
        ("items", "Any", "Input data"),
        ("value", "Any", "The value to process"),
        ("num", "Any", "The value to process"),
        ("callback", "Any", "Callback function"),
        ("func", "Any", "Callback function"),
        ("config", "Any", "Configuration parameters"),
        ("verbose", "Any", "Whether to enable verbose"),
        ("timeout", "Any", "Timeout duration"),
        ("duration", "Any", "Timeout duration"),
        ("x", "str", "String input"),
        ("x", "int", "Integer input"),
        ("x", "float", "Floating-point input"),
        ("x", "bool", "Boolean flag"),
        ("x", "List[int]", "List of items"),
        ("x", "Dict[str, int]", "Dictionary mapping"),
    ],
)
def test_infer_arg_description_branches(name, arg_type, keyword):
    result = DocstringGenerator()._infer_arg_description(name, arg_type)
    assert keyword in result


def test_infer_arg_description_default():
    assert DocstringGenerator()._infer_arg_description("zzz", "Any") == "Description of the parameter."


# ── _infer_return_description ──────────────────────────────


@pytest.mark.parametrize(
    "return_type, keyword",
    [
        ("bool", "True if successful"),
        ("int", "Resulting integer"),
        ("str", "Resulting string"),
        ("float", "Resulting float"),
        ("List[int]", "List of results"),
        ("Dict[str, int]", "Dictionary of results"),
        ("Optional[int]", "Result if available"),
        ("Tuple[int, str]", "Tuple containing"),
    ],
)
def test_infer_return_description_branches(return_type, keyword):
    assert keyword in DocstringGenerator()._infer_return_description(return_type)


def test_infer_return_description_default():
    assert DocstringGenerator()._infer_return_description("CustomType") == "Result of the function."


# ── _generate_example ──────────────────────────────────────


def test_generate_example_all_types():
    g = DocstringGenerator()
    info = {
        "name": "f",
        "args": [
            {"name": "a", "type": "str"},
            {"name": "b", "type": "int"},
            {"name": "c", "type": "float"},
            {"name": "d", "type": "bool"},
            {"name": "e", "type": "List[int]"},
            {"name": "f", "type": "Dict[str, int]"},
            {"name": "g", "type": "CustomType"},
        ],
    }
    example = g._generate_example(info)
    assert '"test"' in example
    assert "10" in example
    assert "10.0" in example
    assert "True" in example
    assert "[1, 2, 3]" in example
    assert '{"key": "value"}' in example
    assert "value" in example


# ── _generate_*_docstring ──────────────────────────────────


@pytest.fixture
def full_info():
    """构造一个触发所有分支的 info dict"""
    return {
        "name": "f",
        "description": "测试函数",
        "args": [
            {"name": "x", "type": "int", "default": None},
            {"name": "y", "type": "str", "default": '"hello"'},
        ],
        "return_type": "bool",
        "has_return": True,
        "has_yield": True,
        "has_raise": True,
    }


@pytest.fixture
def minimal_info():
    """构造一个最小化的 info dict（无参数无返回）"""
    return {
        "name": "f",
        "description": "简单函数",
        "args": [],
        "return_type": None,
        "has_return": False,
        "has_yield": False,
        "has_raise": False,
    }


def test_generate_google_docstring_full(full_info):
    result = DocstringGenerator()._generate_google_docstring(full_info)
    assert '"""' in result
    assert "Args:" in result
    assert "Returns:" in result
    assert "Yields:" in result
    assert "Raises:" in result
    assert "Examples:" in result
    assert "default=" in result


def test_generate_google_docstring_minimal(minimal_info):
    result = DocstringGenerator()._generate_google_docstring(minimal_info)
    assert '"""' in result
    assert "Args:" not in result
    assert "Returns:" not in result


def test_generate_numpy_docstring_full(full_info):
    result = DocstringGenerator()._generate_numpy_docstring(full_info)
    assert "Parameters" in result
    assert "----------" in result
    assert "Returns" in result
    assert "-------" in result
    assert "Yields" in result
    assert "Raises" in result
    assert "Examples" in result
    assert "optional" in result
    assert "Default is" in result


def test_generate_numpy_docstring_minimal(minimal_info):
    result = DocstringGenerator()._generate_numpy_docstring(minimal_info)
    assert "Parameters" not in result
    assert "Returns" not in result


def test_generate_rest_docstring_full(full_info):
    result = DocstringGenerator()._generate_rest_docstring(full_info)
    assert ":param" in result
    assert ":type" in result
    assert ":return:" in result
    assert ":rtype:" in result
    assert ".. code-block:: python" in result


def test_generate_rest_docstring_minimal(minimal_info):
    result = DocstringGenerator()._generate_rest_docstring(minimal_info)
    assert ":param" not in result
    assert ":return:" not in result


def test_generate_rest_docstring_single_arg():
    """ReST 风格只有一个参数时的分支"""
    info = {
        "name": "f",
        "description": "单参数",
        "args": [{"name": "x", "type": "int", "default": None}],
        "return_type": None,
        "has_return": False,
        "has_yield": False,
        "has_raise": False,
    }
    result = DocstringGenerator()._generate_rest_docstring(info)
    assert ":param x:" in result


# ── _extract_function_info ─────────────────────────────────


def test_extract_function_info_basic():
    g = DocstringGenerator()
    code = textwrap.dedent('''
        def add(x: int, y: int = 10) -> int:
            """Add two numbers."""
            return x + y
    ''')
    node = ast.parse(code).body[0]
    info = g._extract_function_info(node)
    assert info["name"] == "add"
    assert info["args"][0]["name"] == "x"
    assert info["args"][0]["type"] == "int"
    assert info["args"][1]["name"] == "y"
    assert info["args"][1]["default"] == "10"
    assert info["return_type"] == "int"
    assert info["has_return"] is True
    assert info["is_async"] is False
    assert info["docstring"] == "Add two numbers."


def test_extract_function_info_async():
    g = DocstringGenerator()
    code = "async def f():\n    yield 1\n"
    node = ast.parse(code).body[0]
    info = g._extract_function_info(node)
    assert info["is_async"] is True
    assert info["has_yield"] is True


def test_extract_function_info_vararg_kwarg():
    g = DocstringGenerator()
    code = "def f(a, *args, **kwargs):\n    raise ValueError()\n    for i in []:\n        pass\n    if True:\n        pass\n"
    node = ast.parse(code).body[0]
    info = g._extract_function_info(node)
    names = [a["name"] for a in info["args"]]
    assert "*args" in names
    assert "**kwargs" in names
    assert info["has_raise"] is True
    assert info["has_loop"] is True
    assert info["has_condition"] is True


def test_extract_function_info_no_annotation():
    g = DocstringGenerator()
    code = "def f(x):\n    pass\n"
    node = ast.parse(code).body[0]
    info = g._extract_function_info(node)
    assert info["args"][0]["type"] == "Any"
    assert info["return_type"] is None


# ── generate_docstring ─────────────────────────────────────


def test_generate_docstring_success_google():
    g = DocstringGenerator("google")
    result = g.generate_docstring("def add(a: int, b: int) -> int:\n    return a + b\n")
    assert result.success is True
    assert result.function_name == "add"
    assert "Args:" in result.generated_docstring
    assert result.style == "google"


def test_generate_docstring_success_numpy():
    g = DocstringGenerator("numpy")
    result = g.generate_docstring("def f(x: int) -> int:\n    return x\n")
    assert result.success is True
    assert "Parameters" in result.generated_docstring


def test_generate_docstring_success_rest():
    g = DocstringGenerator("rest")
    result = g.generate_docstring("def f(x: int) -> int:\n    return x\n")
    assert result.success is True
    assert ":param" in result.generated_docstring


def test_generate_docstring_unknown_style_falls_back_to_google():
    g = DocstringGenerator("unknown")
    result = g.generate_docstring("def f(x: int) -> int:\n    return x\n")
    assert result.success is True
    assert "Args:" in result.generated_docstring


def test_generate_docstring_no_function():
    result = DocstringGenerator().generate_docstring("x = 1\n")
    assert result.success is False
    assert "未找到函数定义" in result.error


def test_generate_docstring_syntax_error():
    result = DocstringGenerator().generate_docstring("def broken(:\n")
    assert result.success is False
    assert result.error != ""


# ── generate_docstring_for_code ───────────────────────────


def test_generate_docstring_for_code_success():
    result = DocstringGenerator().generate_docstring_for_code("def f(x: int) -> int:\n    return x\n")
    assert '"""' in result
    assert "Args:" in result


def test_generate_docstring_for_code_no_function():
    assert DocstringGenerator().generate_docstring_for_code("x = 1\n") == ""


def test_generate_docstring_for_code_syntax_error():
    assert DocstringGenerator().generate_docstring_for_code("def broken(:\n") == ""


# ── process_file ───────────────────────────────────────────


def test_process_file_success(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("def f():\n    return 1\n", encoding="utf-8")
    result = DocstringGenerator().process_file(src)
    assert result.success is True
    assert result.file_path == str(src)


def test_process_file_not_found(tmp_path):
    result = DocstringGenerator().process_file(tmp_path / "nope.py")
    assert result.success is False
    assert len(result.errors) > 0


# ── ChineseCommentGenerator ────────────────────────────────


def test_chinese_comments_generate_success():
    g = ChineseCommentGenerator()
    code = textwrap.dedent('''
        max_value = 100
        items_list = [1, 2, 3]
        result_cache = {}
        normal_var = 42

        class MyClass:
            pass

        def simple_func():
            return 1

        def loop_func():
            for i in range(10):
                pass
            return i

        def cond_func():
            if True:
                return 1
            return 0

        def complex_func():
            if a:
                if b:
                    if c:
                        if d:
                            if e:
                                if f:
                                    pass
    ''')
    result = g.generate_comments(code)
    assert "最大值限制" in result
    assert "列表数据" in result
    assert "缓存数据" in result
    assert "业务逻辑类" in result
    assert "工具函数" in result
    assert "遍历处理函数" in result
    assert "条件判断函数" in result
    assert "复杂函数" in result


def test_chinese_comments_syntax_error_returns_original():
    g = ChineseCommentGenerator()
    code = "def broken(:\n"
    assert g.generate_comments(code) == code


def test_analyze_function_basic():
    g = ChineseCommentGenerator()
    node = ast.parse("def f(a, b):\n    if a:\n        for i in []:\n            pass\n    return b\n").body[0]
    info = g._analyze_function(node)
    assert info["name"] == "f"
    assert info["args"] == ["a", "b"]
    assert info["has_loop"] is True
    assert info["has_condition"] is True
    assert info["has_return"] is True
    assert info["complexity"] >= 3


def test_calculate_complexity_simple():
    g = ChineseCommentGenerator()
    node = ast.parse("def f():\n    return 1\n").body[0]
    assert g._calculate_complexity(node) == 1


def test_generate_function_comment_complex():
    g = ChineseCommentGenerator()
    info = {"name": "f", "complexity": 10, "has_loop": True, "has_condition": True}
    assert "复杂函数" in g._generate_function_comment(info)


def test_generate_function_comment_loop():
    g = ChineseCommentGenerator()
    info = {"name": "f", "complexity": 2, "has_loop": True, "has_condition": False}
    assert "遍历处理函数" in g._generate_function_comment(info)


def test_generate_function_comment_condition():
    g = ChineseCommentGenerator()
    info = {"name": "f", "complexity": 2, "has_loop": False, "has_condition": True}
    assert "条件判断函数" in g._generate_function_comment(info)


def test_generate_function_comment_tool():
    g = ChineseCommentGenerator()
    info = {"name": "f", "complexity": 1, "has_loop": False, "has_condition": False}
    assert "工具函数" in g._generate_function_comment(info)


def test_generate_class_comment():
    g = ChineseCommentGenerator()
    node = ast.parse("class Foo:\n    pass\n").body[0]
    assert "业务逻辑类" in g._generate_class_comment(node)


@pytest.mark.parametrize(
    "name, keyword",
    [
        ("max_value", "最大值限制"),
        ("min_value", "最小值限制"),
        ("items_list", "列表数据"),
        ("config_dict", "字典映射"),
        ("retry_count", "计数器"),
        ("done_flag", "标志位"),
        ("final_result", "结果存储"),
        ("data_cache", "缓存数据"),
    ],
)
def test_generate_variable_comment_prefixes(name, keyword):
    g = ChineseCommentGenerator()
    assert keyword in g._generate_variable_comment(name, None)


def test_generate_variable_comment_default():
    g = ChineseCommentGenerator()
    assert g._generate_variable_comment("normal_var", None) == ""


# ── 模块级快捷函数 ────────────────────────────────────────


def test_module_generate_docstring():
    result = generate_docstring("def f(x: int) -> int:\n    return x\n", style="numpy")
    assert "Parameters" in result


def test_module_add_chinese_comments():
    code = "max_val = 100\ndef f():\n    return 1\n"
    result = add_chinese_comments(code)
    assert "最大值限制" in result
