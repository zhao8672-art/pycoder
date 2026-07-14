"""
类型推断器 — 根据函数体推断参数/返回值类型，自动补全 Type Hints。

功能:
- 基于 AST 分析函数体，推断参数和返回值类型
- 支持常见类型模式识别（列表推导、字典操作、字符串处理等）
- 生成符合 PEP 484 标准的 Type Hints
- 支持 mypy 静默检查并返回类型错误
- 批量为文件添加类型注解
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class TypeHintResult:
    """类型注解结果"""

    success: bool
    code: str = ""
    original_code: str = ""
    function_name: str = ""
    parameters: list[dict[str, str]] = field(default_factory=list)
    return_type: str = ""
    updated_code: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class TypeCheckResult:
    """类型检查结果"""

    success: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    output: str = ""
    summary: str = ""


# ── 类型推断器 ──────────────────────────────────────────


class TypeInferencer:
    """
    类型推断器 — 基于 AST 分析推断函数参数和返回值类型。

    支持的推断模式:
    - 变量赋值类型推断
    - 返回语句类型推断
    - 条件分支类型推断
    - 容器类型推断（列表、字典、集合）
    - 常见函数调用返回类型推断
    """

    # 常见函数/方法返回类型映射
    RETURN_TYPE_MAP = {
        "len": "int",
        "str": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
        "list": "list",
        "dict": "dict",
        "set": "set",
        "tuple": "tuple",
        "range": "range",
        "type": "type",
        "isinstance": "bool",
        "issubclass": "bool",
        "callable": "bool",
        "hasattr": "bool",
        "getattr": "Any",
        "setattr": "None",
        "delattr": "None",
        "enumerate": "enumerate",
        "zip": "zip",
        "map": "map",
        "filter": "filter",
        "sorted": "list",
        "reversed": "reversed",
        "sum": "int",
        "min": "Any",
        "max": "Any",
        "abs": "float",
        "round": "int",
        "divmod": "tuple",
        "pow": "float",
        "open": "IO",
        "print": "None",
        "input": "str",
        "repr": "str",
        "ascii": "str",
        "chr": "str",
        "ord": "int",
        "hex": "str",
        "oct": "str",
        "bin": "str",
        "complex": "complex",
        "bytes": "bytes",
        "bytearray": "bytearray",
        "memoryview": "memoryview",
        "frozenset": "frozenset",
        "slice": "slice",
        "iter": "iterator",
        "next": "Any",
        "id": "int",
        "hash": "int",
        "help": "None",
        "dir": "list",
        "vars": "dict",
        "locals": "dict",
        "globals": "dict",
        "__import__": "module",
    }

    # 字符串方法返回类型
    STRING_METHODS = {
        "capitalize": "str",
        "casefold": "str",
        "center": "str",
        "count": "int",
        "encode": "bytes",
        "endswith": "bool",
        "expandtabs": "str",
        "find": "int",
        "format": "str",
        "format_map": "str",
        "index": "int",
        "isalnum": "bool",
        "isalpha": "bool",
        "isascii": "bool",
        "isdecimal": "bool",
        "isdigit": "bool",
        "isidentifier": "bool",
        "islower": "bool",
        "isnumeric": "bool",
        "isprintable": "bool",
        "isspace": "bool",
        "istitle": "bool",
        "isupper": "bool",
        "join": "str",
        "ljust": "str",
        "lower": "str",
        "lstrip": "str",
        "maketrans": "dict",
        "partition": "tuple",
        "removeprefix": "str",
        "removesuffix": "str",
        "replace": "str",
        "rfind": "int",
        "rindex": "int",
        "rjust": "str",
        "rpartition": "tuple",
        "rsplit": "list",
        "rstrip": "str",
        "split": "list",
        "splitlines": "list",
        "startswith": "bool",
        "strip": "str",
        "swapcase": "str",
        "title": "str",
        "translate": "str",
        "upper": "str",
        "zfill": "str",
    }

    # 列表方法返回类型
    LIST_METHODS = {
        "append": "None",
        "clear": "None",
        "copy": "list",
        "count": "int",
        "extend": "None",
        "index": "int",
        "insert": "None",
        "pop": "Any",
        "remove": "None",
        "reverse": "None",
        "sort": "None",
    }

    # 字典方法返回类型
    DICT_METHODS = {
        "clear": "None",
        "copy": "dict",
        "fromkeys": "dict",
        "get": "Any",
        "items": "dict_items",
        "keys": "dict_keys",
        "pop": "Any",
        "popitem": "tuple",
        "setdefault": "Any",
        "update": "None",
        "values": "dict_values",
    }

    def __init__(self):
        self._type_cache: dict[str, str] = {}
        self._var_types: dict[str, str] = {}

    def infer_function_types(self, code: str) -> TypeHintResult:
        """
        推断函数的参数和返回值类型。

        Args:
            code: 函数代码

        Returns:
            TypeHintResult
        """
        try:
            tree = ast.parse(code)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return self._analyze_function(node, code)

            return TypeHintResult(success=False, error="未找到函数定义")

        except Exception as e:
            return TypeHintResult(success=False, error=str(e))

    def _analyze_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, code: str
    ) -> TypeHintResult:
        """分析函数"""
        self._var_types.clear()

        parameters = []

        for arg in node.args.args:
            param_info = {"name": arg.arg}

            if arg.annotation:
                param_info["type"] = self._annotation_to_str(arg.annotation)
            else:
                param_info["type"] = self._infer_param_type(arg.arg, node.body)

            parameters.append(param_info)

        return_type = ""
        if node.returns:
            return_type = self._annotation_to_str(node.returns)
        else:
            return_type = self._infer_return_type(node.body)

        updated_code = self._add_type_hints(code, node, parameters, return_type)

        return TypeHintResult(
            success=True,
            code=code,
            function_name=node.name,
            parameters=parameters,
            return_type=return_type,
            updated_code=updated_code,
        )

    def _infer_param_type(self, param_name: str, body: list) -> str:
        """推断参数类型"""
        for stmt in body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == param_name:
                        return self._infer_value_type(stmt.value)

            elif isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Call):
                    func = stmt.value.func
                    args = stmt.value.args
                    for _i, arg in enumerate(args):
                        if isinstance(arg, ast.Name) and arg.id == param_name:
                            if isinstance(func, ast.Name) and func.id in self.RETURN_TYPE_MAP:
                                return self.RETURN_TYPE_MAP[func.id]

            elif isinstance(stmt, ast.If):
                self._analyze_if_node(stmt, param_name)

            elif isinstance(stmt, ast.For):
                self._analyze_for_node(stmt, param_name)

        return "Any"

    def _infer_return_type(self, body: list) -> str:
        """推断返回类型"""
        return_types = set()

        for stmt in body:
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    return_types.add("None")
                else:
                    return_types.add(self._infer_value_type(stmt.value))

            elif isinstance(stmt, ast.If):
                for sub_stmt in stmt.body:
                    if isinstance(sub_stmt, ast.Return):
                        if sub_stmt.value is None:
                            return_types.add("None")
                        else:
                            return_types.add(self._infer_value_type(sub_stmt.value))
                if stmt.orelse:
                    for sub_stmt in stmt.orelse:
                        if isinstance(sub_stmt, ast.Return):
                            if sub_stmt.value is None:
                                return_types.add("None")
                            else:
                                return_types.add(self._infer_value_type(sub_stmt.value))

        if len(return_types) == 0:
            return "None"
        elif len(return_types) == 1:
            return return_types.pop()
        else:
            return_types.discard("None")
            if len(return_types) == 1:
                return f"Optional[{return_types.pop()}]"
            return "Union[" + ", ".join(sorted(return_types)) + "]"

    def _infer_value_type(self, value) -> str:
        """推断值的类型"""
        if value is None:
            return "None"

        if isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                return "str"
            elif isinstance(value.value, int):
                return "int"
            elif isinstance(value.value, float):
                return "float"
            elif isinstance(value.value, bool):
                return "bool"
            elif value.value is None:
                return "None"
            return "Any"

        elif isinstance(value, ast.Name):
            return self._var_types.get(value.id, "Any")

        elif isinstance(value, ast.List):
            if value.elts:
                element_types = {self._infer_value_type(e) for e in value.elts}
                if len(element_types) == 1:
                    return f"List[{element_types.pop()}]"
                return "List[Any]"
            return "List"

        elif isinstance(value, ast.Dict):
            if value.keys and value.values:
                key_types = {self._infer_value_type(k) for k in value.keys}
                val_types = {self._infer_value_type(v) for v in value.values}
                key_type = key_types.pop() if len(key_types) == 1 else "Any"
                val_type = val_types.pop() if len(val_types) == 1 else "Any"
                return f"Dict[{key_type}, {val_type}]"
            return "Dict"

        elif isinstance(value, ast.Set):
            if value.elts:
                element_types = {self._infer_value_type(e) for e in value.elts}
                if len(element_types) == 1:
                    return f"Set[{element_types.pop()}]"
                return "Set[Any]"
            return "Set"

        elif isinstance(value, ast.Tuple):
            if value.elts:
                element_types = [self._infer_value_type(e) for e in value.elts]
                if len(set(element_types)) == 1:
                    return f"Tuple[{element_types[0]}, ...]"
                return "Tuple[" + ", ".join(element_types) + "]"
            return "Tuple"

        elif isinstance(value, ast.Call):
            return self._infer_call_type(value)

        elif isinstance(value, ast.Attribute):
            return self._infer_attribute_type(value)

        elif isinstance(value, ast.BinOp):
            return self._infer_binop_type(value)

        elif isinstance(value, ast.UnaryOp):
            return self._infer_unaryop_type(value)

        elif isinstance(value, ast.IfExp):
            true_type = self._infer_value_type(value.body)
            false_type = self._infer_value_type(value.orelse)
            if true_type == false_type:
                return true_type
            return f"Union[{true_type}, {false_type}]"

        elif isinstance(value, ast.Lambda):
            return "Callable"

        return "Any"

    def _infer_call_type(self, call: ast.Call) -> str:
        """推断函数调用的返回类型"""
        func = call.func

        if isinstance(func, ast.Name):
            func_name = func.id
            if func_name in self.RETURN_TYPE_MAP:
                return self.RETURN_TYPE_MAP[func_name]

        elif isinstance(func, ast.Attribute):
            attr_name = func.attr
            value_type = self._infer_value_type(func.value)

            if value_type.startswith("str") or value_type == "Any":
                if attr_name in self.STRING_METHODS:
                    return self.STRING_METHODS[attr_name]

            if value_type.startswith("list") or value_type == "Any":
                if attr_name in self.LIST_METHODS:
                    return self.LIST_METHODS[attr_name]

            if value_type.startswith("dict") or value_type == "Any":
                if attr_name in self.DICT_METHODS:
                    return self.DICT_METHODS[attr_name]

        return "Any"

    def _infer_attribute_type(self, attr: ast.Attribute) -> str:
        """推断属性访问的类型"""
        self._infer_value_type(attr.value)

        common_attrs = {
            "__len__": "int",
            "__str__": "str",
            "__repr__": "str",
            "__iter__": "Iterator",
            "__next__": "Any",
            "__getitem__": "Any",
            "__setitem__": "None",
            "__delitem__": "None",
            "__contains__": "bool",
        }

        if attr.attr in common_attrs:
            return common_attrs[attr.attr]

        return "Any"

    def _infer_binop_type(self, binop: ast.BinOp) -> str:
        """推断二元运算的类型"""
        left_type = self._infer_value_type(binop.left)
        right_type = self._infer_value_type(binop.right)

        if isinstance(binop.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            if left_type == "int" and right_type == "int":
                if isinstance(binop.op, ast.Div):
                    return "float"
                return "int"
            return "float"

        elif isinstance(binop.op, ast.Pow):
            return "float"

        elif isinstance(binop.op, (ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd)):
            return "int"

        elif isinstance(binop.op, ast.And):
            return "bool"

        elif isinstance(binop.op, ast.Or):
            return "bool"

        return "Any"

    def _infer_unaryop_type(self, unaryop: ast.UnaryOp) -> str:
        """推断一元运算的类型"""
        operand_type = self._infer_value_type(unaryop.operand)

        if isinstance(unaryop.op, ast.Not):
            return "bool"

        if isinstance(unaryop.op, (ast.UAdd, ast.USub)):
            return operand_type

        if isinstance(unaryop.op, ast.Invert):
            return "int"

        return operand_type

    def _analyze_if_node(self, node: ast.If, param_name: str):
        """分析 if 语句，推断 isinstance 类型守卫"""
        # 检查 isinstance(x, SomeType) 模式
        if isinstance(node.test, ast.Call):
            if isinstance(node.test.func, ast.Name) and node.test.func.id == "isinstance":
                if len(node.test.args) == 2:
                    arg = node.test.args[0]
                    type_arg = node.test.args[1]
                    # 如果 isinstance 的第一个参数是目标参数
                    if isinstance(arg, ast.Name) and arg.id == param_name:
                        # 推断类型
                        if isinstance(type_arg, ast.Name):
                            self._var_types[param_name] = type_arg.id
                        elif isinstance(type_arg, ast.Tuple):
                            # isinstance(x, (int, str)) -> Union[int, str]
                            types = []
                            for elt in type_arg.elts:
                                if isinstance(elt, ast.Name):
                                    types.append(elt.id)
                            if types:
                                self._var_types[param_name] = f"Union[{', '.join(types)}]"

    def _analyze_for_node(self, node: ast.For, param_name: str):
        """分析 for 语句，从迭代器推断元素类型"""
        # 检查 for target in iter: 模式
        target = node.target
        iter_node = node.iter

        # 如果目标变量是参数
        if isinstance(target, ast.Name) and target.id == param_name:
            # 从迭代器推断元素类型
            iter_type = self._infer_value_type(iter_node)

            # 解析容器类型
            if iter_type.startswith("List["):
                # List[T] -> T
                element_type = iter_type[5:-1]
                self._var_types[param_name] = element_type
            elif iter_type.startswith("Dict["):
                # Dict[K, V] -> K (for key in dict)
                parts = iter_type[5:-1].split(", ", 1)
                if parts:
                    self._var_types[param_name] = parts[0]
            elif iter_type == "str":
                # for char in string -> str
                self._var_types[param_name] = "str"
            elif iter_type in ("range", "list", "tuple", "set"):
                # 通用容器 -> Any
                self._var_types[param_name] = "Any"

    def _annotation_to_str(self, annotation) -> str:
        """将类型注解转换为字符串"""
        if isinstance(annotation, ast.Name):
            return annotation.id
        elif isinstance(annotation, ast.Attribute):
            return annotation.attr
        elif isinstance(annotation, ast.Subscript):
            value_str = self._annotation_to_str(annotation.value)
            slice_str = self._annotation_to_str(annotation.slice)
            return f"{value_str}[{slice_str}]"
        elif isinstance(annotation, ast.Constant):
            return repr(annotation.value)
        elif isinstance(annotation, ast.Tuple):
            return "Tuple[" + ", ".join(self._annotation_to_str(e) for e in annotation.elts) + "]"
        elif isinstance(annotation, ast.List):
            if annotation.elts:
                return (
                    "List[" + ", ".join(self._annotation_to_str(e) for e in annotation.elts) + "]"
                )
            return "List"
        elif isinstance(annotation, ast.Call):
            func_str = self._annotation_to_str(annotation.func)
            args_str = ", ".join(self._annotation_to_str(arg) for arg in annotation.args)
            return f"{func_str}({args_str})"
        return "Any"

    def _add_type_hints(
        self,
        code: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parameters: list,
        return_type: str,
    ) -> str:
        """为代码添加类型注解"""
        lines = code.split("\n")

        lines[node.lineno - 1]

        indent = " " * node.col_offset
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        params_str = ", ".join(f"{p['name']}: {p['type']}" for p in parameters)

        if return_type and return_type != "None":
            new_func_line = f"{indent}{prefix}def {node.name}({params_str}) -> {return_type}:"
        else:
            new_func_line = f"{indent}{prefix}def {node.name}({params_str}):"

        lines[node.lineno - 1] = new_func_line

        return "\n".join(lines)

    def add_type_hints_to_file(self, file_path: str | Path) -> TypeHintResult:
        """
        为文件中的所有函数添加类型注解。

        Args:
            file_path: 文件路径

        Returns:
            TypeHintResult
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            lines = content.split("\n")

            functions = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node)

            functions.sort(key=lambda x: x.lineno, reverse=True)

            for node in functions:
                self._var_types.clear()

                parameters = []
                for arg in node.args.args:
                    param_info = {"name": arg.arg}
                    if arg.annotation:
                        param_info["type"] = self._annotation_to_str(arg.annotation)
                    else:
                        param_info["type"] = self._infer_param_type(arg.arg, node.body)
                    parameters.append(param_info)

                return_type = ""
                if node.returns:
                    return_type = self._annotation_to_str(node.returns)
                else:
                    return_type = self._infer_return_type(node.body)

                params_str = ", ".join(f"{p['name']}: {p['type']}" for p in parameters)

                indent = " " * (node.col_offset)
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""

                if return_type and return_type != "None":
                    new_line = f"{indent}{prefix}def {node.name}({params_str}) -> {return_type}:"
                else:
                    new_line = f"{indent}{prefix}def {node.name}({params_str}):"

                lines[node.lineno - 1] = new_line

            return TypeHintResult(
                success=True,
                code=content,
                updated_code="\n".join(lines),
                errors=[],
            )

        except Exception as e:
            return TypeHintResult(
                success=False,
                error=str(e),
            )


# ── 类型检查器 ──────────────────────────────────────────


class TypeChecker:
    """
    类型检查器 — 使用 mypy/pyright 进行类型检查。
    """

    def __init__(self):
        self._mypy_available = self._check_mypy()

    def _check_mypy(self) -> bool:
        """检查 mypy 是否可用"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "mypy", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("check_mypy_failed error=%s", e)
            return False

    def check_file(self, file_path: str | Path) -> TypeCheckResult:
        """
        检查文件的类型错误。

        Args:
            file_path: 文件路径

        Returns:
            TypeCheckResult
        """
        if not self._mypy_available:
            return TypeCheckResult(
                success=False,
                errors=[],
                warnings=[],
                output="",
                summary="mypy 未安装，请运行: pip install mypy",
            )

        try:
            result = subprocess.run(
                [sys.executable, "-m", "mypy", str(file_path), "--no-error-summary"],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            errors = []
            warnings = []

            output_lines = result.stdout.split("\n") + result.stderr.split("\n")

            for line in output_lines:
                if not line.strip():
                    continue

                parts = line.split(":")
                if len(parts) >= 4:
                    file_name = parts[0]
                    line_num = parts[1]
                    col_num = parts[2]
                    message = ":".join(parts[3:]).strip()

                    if "error" in message.lower():
                        errors.append(
                            {
                                "file": file_name,
                                "line": int(line_num) if line_num.isdigit() else 0,
                                "column": int(col_num) if col_num.isdigit() else 0,
                                "message": message,
                            }
                        )
                    else:
                        warnings.append(
                            {
                                "file": file_name,
                                "line": int(line_num) if line_num.isdigit() else 0,
                                "column": int(col_num) if col_num.isdigit() else 0,
                                "message": message,
                            }
                        )

            summary = f"发现 {len(errors)} 个类型错误，{len(warnings)} 个警告"

            return TypeCheckResult(
                success=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                output=result.stdout + result.stderr,
                summary=summary,
            )

        except Exception as e:
            return TypeCheckResult(
                success=False,
                errors=[],
                warnings=[],
                output="",
                summary=str(e),
            )

    def check_code(self, code: str) -> TypeCheckResult:
        """
        检查代码片段的类型错误。

        Args:
            code: 代码字符串

        Returns:
            TypeCheckResult
        """
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            return self.check_file(temp_path)
        finally:
            import os

            os.unlink(temp_path)


# ── 快捷函数 ─────────────────────────────────────────────


def infer_types(code: str) -> TypeHintResult:
    """推断函数类型注解"""
    inferencer = TypeInferencer()
    return inferencer.infer_function_types(code)


def add_type_hints(code: str) -> str:
    """为代码添加类型注解"""
    inferencer = TypeInferencer()
    result = inferencer.infer_function_types(code)
    return result.updated_code if result.success else code


def check_types(file_path: str | Path) -> TypeCheckResult:
    """检查文件类型错误"""
    checker = TypeChecker()
    return checker.check_file(file_path)
