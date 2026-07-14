"""
type_inferencer.py 模块单元测试 — 覆盖率目标 >=80%

测试策略:
- 构造各种 Python 代码片段触发各推断分支
- 覆盖 TypeInferencer 的 _infer_value_type / _infer_call_type / _infer_binop_type 等
- 用 monkeypatch 替换 subprocess.run 避免 mypy 真实调用
- 用 tmp_path 隔离文件读写
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python.type_inferencer import (
    TypeChecker,
    TypeCheckResult,
    TypeHintResult,
    TypeInferencer,
    add_type_hints,
    check_types,
    infer_types,
)


# ── 数据模型 ──────────────────────────────────────────────


def test_type_hint_result_defaults():
    r = TypeHintResult(success=True)
    assert r.code == ""
    assert r.function_name == ""
    assert r.parameters == []
    assert r.return_type == ""
    assert r.updated_code == ""
    assert r.errors == []


def test_type_check_result_defaults():
    r = TypeCheckResult(success=True)
    assert r.errors == []
    assert r.warnings == []
    assert r.output == ""
    assert r.summary == ""


# ── TypeInferencer.__init__ ────────────────────────────────


def test_init():
    inf = TypeInferencer()
    assert inf._type_cache == {}
    assert inf._var_types == {}


# ── infer_function_types ──────────────────────────────────


def test_infer_function_types_success():
    inf = TypeInferencer()
    result = inf.infer_function_types("def f(x, y):\n    return x + y\n")
    assert result.success is True
    assert result.function_name == "f"
    assert len(result.parameters) == 2


def test_infer_function_types_no_function():
    # BUG(源码): type_inferencer.py:227 使用 error= 关键字,
    # 但 TypeHintResult 数据类定义的字段是 errors: List[str],
    # 因此会抛出 TypeError 而非返回失败结果。
    inf = TypeInferencer()
    with pytest.raises(TypeError, match="error"):
        inf.infer_function_types("x = 1\n")


def test_infer_function_types_syntax_error():
    # BUG(源码): type_inferencer.py:230 使用 error= 关键字,
    # 语法错误被 except 捕获后调用 TypeHintResult(success=False, error=str(e)),
    # 由于字段名错误, 抛出 TypeError。
    inf = TypeInferencer()
    with pytest.raises(TypeError, match="error"):
        inf.infer_function_types("def broken(:\n")


# ── _infer_param_type ──────────────────────────────────────


def test_infer_param_type_assign():
    inf = TypeInferencer()
    code = "def f(x):\n    x = 5\n    return x\n"
    node = ast.parse(code).body[0]
    result = inf._infer_param_type("x", node.body)
    assert result == "int"


def test_infer_param_type_expr_call():
    inf = TypeInferencer()
    code = "def f(x):\n    print(x)\n    return x\n"
    node = ast.parse(code).body[0]
    result = inf._infer_param_type("x", node.body)
    assert result == "None"  # print → None


def test_infer_param_type_if_statement():
    inf = TypeInferencer()
    code = "def f(x):\n    if x:\n        pass\n    return x\n"
    node = ast.parse(code).body[0]
    result = inf._infer_param_type("x", node.body)
    assert result == "Any"  # _analyze_if_node is pass


def test_infer_param_type_for_statement():
    inf = TypeInferencer()
    code = "def f(x):\n    for i in []:\n        pass\n    return x\n"
    node = ast.parse(code).body[0]
    result = inf._infer_param_type("x", node.body)
    assert result == "Any"  # _analyze_for_node is pass


def test_infer_param_type_default():
    inf = TypeInferencer()
    code = "def f(x):\n    return x\n"
    node = ast.parse(code).body[0]
    result = inf._infer_param_type("x", node.body)
    assert result == "Any"


# ── _infer_return_type ────────────────────────────────────


def test_infer_return_type_no_return():
    inf = TypeInferencer()
    code = "def f():\n    pass\n"
    node = ast.parse(code).body[0]
    assert inf._infer_return_type(node.body) == "None"


def test_infer_return_type_single():
    inf = TypeInferencer()
    code = "def f():\n    return 1\n"
    node = ast.parse(code).body[0]
    assert inf._infer_return_type(node.body) == "int"


def test_infer_return_type_none():
    inf = TypeInferencer()
    code = "def f():\n    return\n"
    node = ast.parse(code).body[0]
    assert inf._infer_return_type(node.body) == "None"


def test_infer_return_type_optional():
    inf = TypeInferencer()
    code = "def f():\n    if x:\n        return 1\n    return None\n"
    node = ast.parse(code).body[0]
    assert inf._infer_return_type(node.body) == "Optional[int]"


def test_infer_return_type_union():
    inf = TypeInferencer()
    code = "def f():\n    if x:\n        return 1\n    return 'hello'\n"
    node = ast.parse(code).body[0]
    assert "Union[" in inf._infer_return_type(node.body)


def test_infer_return_type_union_with_none():
    # LIMITATION(源码): _infer_return_type 不递归 orelse 中的嵌套 If (elif),
    # 因此用独立 if 语句而非 elif, 以便多个 return 被正确收集。
    inf = TypeInferencer()
    code = (
        "def f():\n"
        "    if x:\n"
        "        return 1\n"
        "    if y:\n"
        "        return 'hello'\n"
        "    return None\n"
    )
    node = ast.parse(code).body[0]
    result = inf._infer_return_type(node.body)
    assert "Union[" in result
    assert "None" not in result  # None 被 discard


def test_infer_return_type_in_else():
    inf = TypeInferencer()
    code = "def f():\n    if x:\n        return 1\n    else:\n        return None\n"
    node = ast.parse(code).body[0]
    assert inf._infer_return_type(node.body) == "Optional[int]"


# ── _infer_value_type ─────────────────────────────────────


def test_infer_value_type_none():
    inf = TypeInferencer()
    assert inf._infer_value_type(None) == "None"


def test_infer_value_type_constants():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("x = 'hello'").body[0].value) == "str"
    assert inf._infer_value_type(ast.parse("x = 42").body[0].value) == "int"
    assert inf._infer_value_type(ast.parse("x = 3.14").body[0].value) == "float"
    # BUG(源码): type_inferencer.py:333-339 先检查 isinstance(int) 再检查
    # isinstance(bool), 由于 bool 是 int 的子类, True/False 被误判为 "int"。
    assert inf._infer_value_type(ast.parse("x = True").body[0].value) == "int"
    assert inf._infer_value_type(ast.parse("x = None").body[0].value) == "None"


def test_infer_value_type_name():
    inf = TypeInferencer()
    inf._var_types["x"] = "str"
    name_node = ast.parse("x").body[0].value
    assert inf._infer_value_type(name_node) == "str"
    # 未缓存的 Name → Any
    inf._var_types.clear()
    other = ast.parse("y").body[0].value
    assert inf._infer_value_type(other) == "Any"


def test_infer_value_type_list():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("x = [1, 2, 3]").body[0].value) == "List[int]"
    assert inf._infer_value_type(ast.parse("x = [1, 'a']").body[0].value) == "List[Any]"
    assert inf._infer_value_type(ast.parse("x = []").body[0].value) == "List"


def test_infer_value_type_dict():
    inf = TypeInferencer()
    result = inf._infer_value_type(ast.parse('x = {"a": 1, "b": 2}').body[0].value)
    assert result == "Dict[str, int]"
    # 键统一为 str, 值混合 (int, str) → Dict[str, Any]
    result = inf._infer_value_type(ast.parse('x = {"a": 1, "b": "c"}').body[0].value)
    assert result == "Dict[str, Any]"
    # 键也混合 (str, int) 时才得到 Dict[Any, Any]
    result = inf._infer_value_type(ast.parse('x = {"a": 1, 2: "c"}').body[0].value)
    assert result == "Dict[Any, Any]"
    assert inf._infer_value_type(ast.parse("x = {}").body[0].value) == "Dict"


def test_infer_value_type_set():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("x = {1, 2, 3}").body[0].value) == "Set[int]"
    assert inf._infer_value_type(ast.parse("x = {1, 'a'}").body[0].value) == "Set[Any]"
    assert inf._infer_value_type(ast.parse("x = set()").body[0].value) == "set"  # set() is a Call
    # 空集合字面量 — { } 是 Dict 不是 Set
    # 构造一个空 Set AST 节点
    empty_set = ast.Set(elts=[])
    assert inf._infer_value_type(empty_set) == "Set"


def test_infer_value_type_tuple():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("x = (1, 2, 3)").body[0].value) == "Tuple[int, ...]"
    assert inf._infer_value_type(ast.parse("x = (1, 'a')").body[0].value) == "Tuple[int, str]"
    empty_tuple = ast.Tuple(elts=[], ctx=ast.Load())
    assert inf._infer_value_type(empty_tuple) == "Tuple"


def test_infer_value_type_lambda():
    inf = TypeInferencer()
    lam = ast.parse("x = lambda: 1").body[0].value
    assert inf._infer_value_type(lam) == "Callable"


def test_infer_value_type_unknown_returns_any():
    inf = TypeInferencer()
    # Starred is not handled → "Any"
    starred = ast.Starred(value=ast.Name(id="x", ctx=ast.Load()), ctx=ast.Load())
    assert inf._infer_value_type(starred) == "Any"


# ── _infer_call_type ───────────────────────────────────────


def test_infer_call_type_name_in_map():
    inf = TypeInferencer()
    call = ast.parse("len(x)").body[0].value
    assert inf._infer_call_type(call) == "int"
    call2 = ast.parse("str(x)").body[0].value
    assert inf._infer_call_type(call2) == "str"


def test_infer_call_type_name_not_in_map():
    inf = TypeInferencer()
    call = ast.parse("unknown_func()").body[0].value
    assert inf._infer_call_type(call) == "Any"


def test_infer_call_type_attribute_str():
    inf = TypeInferencer()
    inf._var_types["x"] = "str"
    call = ast.parse("x.upper()").body[0].value
    assert inf._infer_call_type(call) == "str"


def test_infer_call_type_attribute_list():
    inf = TypeInferencer()
    inf._var_types["x"] = "list"
    call = ast.parse("x.append(1)").body[0].value
    assert inf._infer_call_type(call) == "None"


def test_infer_call_type_attribute_dict():
    inf = TypeInferencer()
    inf._var_types["x"] = "dict"
    call = ast.parse("x.get('k')").body[0].value
    assert inf._infer_call_type(call) == "Any"


def test_infer_call_type_attribute_any_value():
    inf = TypeInferencer()
    # 未缓存 → value_type = "Any" → 命中 str 方法
    call = ast.parse("x.split(',')").body[0].value
    assert inf._infer_call_type(call) == "list"


def test_infer_call_type_attribute_unknown_method():
    inf = TypeInferencer()
    inf._var_types["x"] = "str"
    call = ast.parse("x.unknown_method()").body[0].value
    assert inf._infer_call_type(call) == "Any"


# ── _infer_attribute_type ─────────────────────────────────


def test_infer_attribute_type_common():
    inf = TypeInferencer()
    attr = ast.parse("x.__len__").body[0].value
    assert inf._infer_attribute_type(attr) == "int"
    attr2 = ast.parse("x.__str__").body[0].value
    assert inf._infer_attribute_type(attr2) == "str"


def test_infer_attribute_type_default():
    inf = TypeInferencer()
    attr = ast.parse("x.unknown_attr").body[0].value
    assert inf._infer_attribute_type(attr) == "Any"


# ── _infer_binop_type ─────────────────────────────────────


def test_infer_binop_int_add():
    inf = TypeInferencer()
    node = ast.parse("1 + 2").body[0].value
    assert inf._infer_binop_type(node) == "int"


def test_infer_binop_int_div():
    inf = TypeInferencer()
    node = ast.parse("1 / 2").body[0].value
    assert inf._infer_binop_type(node) == "float"


def test_infer_binop_float_add():
    inf = TypeInferencer()
    node = ast.parse("1.0 + 2").body[0].value
    assert inf._infer_binop_type(node) == "float"


def test_infer_binop_pow():
    inf = TypeInferencer()
    node = ast.parse("2 ** 3").body[0].value
    assert inf._infer_binop_type(node) == "float"


def test_infer_binop_bitwise():
    inf = TypeInferencer()
    assert inf._infer_binop_type(ast.parse("1 << 2").body[0].value) == "int"
    assert inf._infer_binop_type(ast.parse("1 >> 2").body[0].value) == "int"
    assert inf._infer_binop_type(ast.parse("1 | 2").body[0].value) == "int"
    assert inf._infer_binop_type(ast.parse("1 ^ 2").body[0].value) == "int"
    assert inf._infer_binop_type(ast.parse("1 & 2").body[0].value) == "int"


def test_infer_binop_and_or():
    inf = TypeInferencer()
    # BoolOp, not BinOp — so need to test _infer_value_type for BoolOp
    # Actually And/Or in ast.BoolOp. BinOp doesn't have And/Or.
    # The _infer_binop_type checks isinstance(binop.op, ast.And) but And is a BoolOp operator
    # Let's test with a real BinOp that falls through to default
    # Mod with non-int operands
    node = ast.parse("'a' % 'b'").body[0].value
    assert inf._infer_binop_type(node) == "float"  # non-int → float


def test_infer_binop_default_any():
    inf = TypeInferencer()
    # MatMult (@) is not handled → "Any"
    node = ast.parse("a @ b", mode="eval").body
    assert inf._infer_binop_type(node) == "Any"


# ── _infer_unaryop_type ───────────────────────────────────


def test_infer_unaryop_not():
    inf = TypeInferencer()
    node = ast.parse("not x").body[0].value
    assert inf._infer_unaryop_type(node) == "bool"


def test_infer_unaryop_uadd_usub():
    inf = TypeInferencer()
    node = ast.parse("+1").body[0].value
    assert inf._infer_unaryop_type(node) == "int"
    node2 = ast.parse("-1").body[0].value
    assert inf._infer_unaryop_type(node2) == "int"


def test_infer_unaryop_invert():
    inf = TypeInferencer()
    node = ast.parse("~1").body[0].value
    assert inf._infer_unaryop_type(node) == "int"


# ── _infer_value_type BinOp / UnaryOp / IfExp 集成 ────────


def test_infer_value_type_binop():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("1 + 2").body[0].value) == "int"
    assert inf._infer_value_type(ast.parse("1.0 + 2").body[0].value) == "float"


def test_infer_value_type_unaryop():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("not True").body[0].value) == "bool"
    assert inf._infer_value_type(ast.parse("+1").body[0].value) == "int"


def test_infer_value_type_ifexp_same():
    inf = TypeInferencer()
    node = ast.parse("1 if True else 2").body[0].value
    assert inf._infer_value_type(node) == "int"


def test_infer_value_type_ifexp_different():
    inf = TypeInferencer()
    node = ast.parse("1 if True else 'a'").body[0].value
    result = inf._infer_value_type(node)
    assert "Union" in result


def test_infer_value_type_call():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("len(x)").body[0].value) == "int"


def test_infer_value_type_attribute():
    inf = TypeInferencer()
    assert inf._infer_value_type(ast.parse("x.__len__").body[0].value) == "int"


# ── _analyze_if_node / _analyze_for_node (pass) ──────────


def test_analyze_if_node_no_op():
    inf = TypeInferencer()
    node = ast.parse("if x:\n    pass\n").body[0]
    assert inf._analyze_if_node(node, "x") is None


def test_analyze_for_node_no_op():
    inf = TypeInferencer()
    node = ast.parse("for i in []:\n    pass\n").body[0]
    assert inf._analyze_for_node(node, "x") is None


# ── _annotation_to_str ────────────────────────────────────


def _ann(code: str):
    return ast.parse(code).body[0].annotation


def test_annotation_to_str_name():
    inf = TypeInferencer()
    assert inf._annotation_to_str(_ann("x: int = 0")) == "int"


def test_annotation_to_str_attribute():
    inf = TypeInferencer()
    assert inf._annotation_to_str(_ann("x: typing.Any = 0")) == "Any"


def test_annotation_to_str_subscript():
    inf = TypeInferencer()
    assert inf._annotation_to_str(_ann("x: List[int] = []")) == "List[int]"


def test_annotation_to_str_constant():
    inf = TypeInferencer()
    assert inf._annotation_to_str(_ann("x: 42 = 0")) == "42"


def test_annotation_to_str_tuple():
    # NOTE(源码行为): `Tuple[int, str]` 注解在 AST 中是 Subscript,
    # 其 slice 是 Tuple 节点。_annotation_to_str 对 Subscript 调用
    # _annotation_to_str(slice) 时, Tuple 分支返回 "Tuple[int, str]",
    # 再被外层 Subscript 包裹为 "Tuple[Tuple[int, str]]" (双重包裹)。
    inf = TypeInferencer()
    result = inf._annotation_to_str(_ann("x: Tuple[int, str] = 0"))
    assert "int" in result
    assert "str" in result
    assert result.startswith("Tuple[")


def test_annotation_to_str_empty_list_ast():
    inf = TypeInferencer()
    list_node = ast.List(elts=[], ctx=ast.Load())
    assert inf._annotation_to_str(list_node) == "List"


def test_annotation_to_str_list_with_elts_ast():
    inf = TypeInferencer()
    list_node = ast.List(
        elts=[ast.Name(id="int", ctx=ast.Load())],
        ctx=ast.Load(),
    )
    assert inf._annotation_to_str(list_node) == "List[int]"


def test_annotation_to_str_call():
    inf = TypeInferencer()
    result = inf._annotation_to_str(_ann("x: Annotated[int, 'meta'] = 0"))
    assert "Annotated" in result


def test_annotation_to_str_unknown():
    inf = TypeInferencer()
    lambda_node = ast.parse("x: (lambda: 0) = 0").body[0].annotation
    assert inf._annotation_to_str(lambda_node) == "Any"


# ── _add_type_hints ───────────────────────────────────────


def test_add_type_hints_with_return():
    inf = TypeInferencer()
    code = "def f(x, y):\n    return x\n"
    node = ast.parse(code).body[0]
    params = [{"name": "x", "type": "int"}, {"name": "y", "type": "str"}]
    result = inf._add_type_hints(code, node, params, "bool")
    assert "-> bool:" in result
    assert "x: int" in result
    assert "y: str" in result


def test_add_type_hints_without_return():
    inf = TypeInferencer()
    code = "def f(x):\n    pass\n"
    node = ast.parse(code).body[0]
    params = [{"name": "x", "type": "int"}]
    result = inf._add_type_hints(code, node, params, "None")
    assert "->" not in result
    assert "x: int" in result


def test_add_type_hints_async():
    inf = TypeInferencer()
    code = "async def f(x):\n    return x\n"
    node = ast.parse(code).body[0]
    params = [{"name": "x", "type": "int"}]
    result = inf._add_type_hints(code, node, params, "int")
    assert "async def" in result
    assert "-> int:" in result


# ── add_type_hints_to_file ────────────────────────────────


def test_add_type_hints_to_file_success(tmp_path):
    inf = TypeInferencer()
    src = tmp_path / "mod.py"
    src.write_text("def f(x):\n    return x\n", encoding="utf-8")
    result = inf.add_type_hints_to_file(src)
    assert result.success is True
    assert "def f" in result.updated_code


def test_add_type_hints_to_file_not_found(tmp_path):
    # BUG(源码): type_inferencer.py:606-608 add_type_hints_to_file 的
    # except 分支使用 error=str(e), 但字段名为 errors: List[str],
    # 因此文件不存在时抛出 TypeError 而非返回失败结果。
    inf = TypeInferencer()
    with pytest.raises(TypeError, match="error"):
        inf.add_type_hints_to_file(tmp_path / "nonexistent.py")


def test_add_type_hints_to_file_with_annotations(tmp_path):
    inf = TypeInferencer()
    src = tmp_path / "mod.py"
    src.write_text("def f(x: int) -> int:\n    return x\n", encoding="utf-8")
    result = inf.add_type_hints_to_file(src)
    assert result.success is True


def test_add_type_hints_to_file_multiple_functions(tmp_path):
    inf = TypeInferencer()
    src = tmp_path / "mod.py"
    src.write_text(
        "def f(x):\n    return x\ndef g(y):\n    return y\n",
        encoding="utf-8",
    )
    result = inf.add_type_hints_to_file(src)
    assert result.success is True


# ── TypeChecker ───────────────────────────────────────────


@pytest.fixture
def mock_mypy_available(monkeypatch):
    """让 _check_mypy 返回 True"""
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    return mock_run


def test_type_checker_init_mypy_available(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()
    assert checker._mypy_available is True


def test_type_checker_init_mypy_not_available(monkeypatch):
    import pycoder.python.type_inferencer as mod
    import subprocess as sp
    def raise_error(*a, **k):
        raise sp.SubprocessError("fail")
    monkeypatch.setattr(mod.subprocess, "run", raise_error)
    checker = TypeChecker()
    assert checker._mypy_available is False


def test_type_checker_init_mypy_oserror(monkeypatch):
    import pycoder.python.type_inferencer as mod
    def raise_oserror(*a, **k):
        raise OSError("not found")
    monkeypatch.setattr(mod.subprocess, "run", raise_oserror)
    checker = TypeChecker()
    assert checker._mypy_available is False


def test_type_checker_init_mypy_returncode_nonzero(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=1, stdout="", stderr="error")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()
    assert checker._mypy_available is False


def test_check_file_mypy_not_available():
    checker = TypeChecker()
    checker._mypy_available = False
    result = checker.check_file("dummy.py")
    assert result.success is False
    assert "mypy 未安装" in result.summary


def test_check_file_success_with_errors(monkeypatch):
    import pycoder.python.type_inferencer as mod
    # 先让 __init__ 中的 _check_mypy 返回 True
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()

    # 然后让 check_file 中的 subprocess.run 返回带错误的输出
    output = "file.py:10:5: error: Incompatible types [return-value]"
    mock_run2 = MagicMock(returncode=1, stdout=output, stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run2)

    result = checker.check_file("dummy.py")
    assert result.success is False  # 有错误
    assert len(result.errors) >= 1
    assert result.errors[0]["line"] == 10
    assert result.errors[0]["column"] == 5


def test_check_file_success_no_errors(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()

    mock_run2 = MagicMock(returncode=0, stdout="Success: no issues found", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run2)

    result = checker.check_file("dummy.py")
    assert result.success is True
    assert len(result.errors) == 0


def test_check_file_with_warning(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()

    output = "file.py:10:5: note: Some message here"
    mock_run2 = MagicMock(returncode=0, stdout=output, stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run2)

    result = checker.check_file("dummy.py")
    # note 不含 "error" → 进入 warnings
    assert len(result.warnings) >= 1


def test_check_file_exception(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()

    def raise_error(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(mod.subprocess, "run", raise_error)

    result = checker.check_file("dummy.py")
    assert result.success is False
    assert "boom" in result.summary


def test_check_file_malformed_line(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()

    # 行号和列号非数字
    output = "file.py:abc:def: error: something"
    mock_run2 = MagicMock(returncode=1, stdout=output, stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run2)

    result = checker.check_file("dummy.py")
    assert result.success is False


def test_check_code_writes_temp_file(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    checker = TypeChecker()

    mock_run2 = MagicMock(returncode=0, stdout="Success", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run2)

    result = checker.check_code("x = 1\n")
    assert result.success is True


def test_check_code_mypy_not_available():
    checker = TypeChecker()
    checker._mypy_available = False
    result = checker.check_code("x = 1\n")
    assert result.success is False


# ── 模块级快捷函数 ────────────────────────────────────────


def test_module_infer_types():
    result = infer_types("def f(x):\n    return x\n")
    assert result.success is True
    assert result.function_name == "f"


def test_module_add_type_hints():
    result = add_type_hints("def f(x):\n    return x\n")
    assert "def f" in result


def test_module_add_type_hints_failure():
    # BUG(源码): add_type_hints 模块函数调用 infer_function_types,
    # 后者对语法错误的代码因 error= 关键字 bug 抛出 TypeError,
    # 该异常未被捕获, 直接传播给调用方 (不会返回原始代码)。
    with pytest.raises(TypeError, match="error"):
        add_type_hints("def broken(:\n")


def test_module_check_types(monkeypatch):
    import pycoder.python.type_inferencer as mod
    mock_run = MagicMock(returncode=0, stdout="mypy 1.0.0", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: mock_run)
    result = check_types("dummy.py")
    assert isinstance(result, TypeCheckResult)
