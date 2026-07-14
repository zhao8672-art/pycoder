"""
文档智能生成器 — 自动生成符合规范的 docstring 和代码注释。

功能:
- 根据函数签名和实现生成 Google/Numpy/ReST 风格的 docstring
- 为复杂算法生成中文注释
- 支持批量处理多个文件
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DocstringResult:
    """文档生成结果"""

    success: bool
    function_name: str = ""
    original_code: str = ""
    generated_docstring: str = ""
    updated_code: str = ""
    style: str = "google"
    error: str = ""


@dataclass
class FileDocstringResult:
    """文件文档生成结果"""

    success: bool
    file_path: str = ""
    functions_processed: int = 0
    classes_processed: int = 0
    updated_code: str = ""
    errors: list[str] = field(default_factory=list)


class DocstringGenerator:
    """
    文档生成器 — 基于 AST 分析生成高质量 docstring。

    支持的风格:
    - google: Google 风格
    - numpy: NumPy 风格
    - rest: reStructuredText 风格
    """

    def __init__(self, style: str = "google"):
        self.style = style.lower()
        self._type_map = {
            "int": "int",
            "str": "str",
            "float": "float",
            "bool": "bool",
            "list": "list",
            "dict": "dict",
            "set": "set",
            "tuple": "tuple",
            "None": "None",
            "Any": "Any",
            "Optional": "Optional",
            "Union": "Union",
            "Callable": "Callable",
            "Generator": "Generator",
            "Iterator": "Iterator",
            "Iterable": "Iterable",
            "Sequence": "Sequence",
            "Mapping": "Mapping",
        }

        self._function_patterns = {
            "add": "加法运算",
            "sub": "减法运算",
            "mul": "乘法运算",
            "div": "除法运算",
            "sum": "求和计算",
            "max": "取最大值",
            "min": "取最小值",
            "avg": "计算平均值",
            "count": "计数统计",
            "find": "查找操作",
            "search": "搜索操作",
            "filter": "过滤操作",
            "map": "映射转换",
            "reduce": "归约操作",
            "sort": "排序操作",
            "reverse": "反转操作",
            "format": "格式化操作",
            "parse": "解析操作",
            "convert": "类型转换",
            "validate": "数据验证",
            "generate": "生成操作",
            "create": "创建操作",
            "build": "构建操作",
            "process": "处理操作",
            "transform": "转换操作",
            "calculate": "计算操作",
            "compute": "计算操作",
            "render": "渲染操作",
            "save": "保存操作",
            "load": "加载操作",
            "read": "读取操作",
            "write": "写入操作",
            "delete": "删除操作",
            "update": "更新操作",
            "fetch": "获取操作",
            "get": "获取操作",
            "set": "设置操作",
            "init": "初始化操作",
            "clean": "清理操作",
            "clear": "清空操作",
            "copy": "复制操作",
            "merge": "合并操作",
            "split": "分割操作",
            "join": "连接操作",
            "encode": "编码操作",
            "decode": "解码操作",
            "hash": "哈希计算",
            "encrypt": "加密操作",
            "decrypt": "解密操作",
        }

    def _infer_type(self, value) -> str:
        """推断值的类型"""
        if value is None:
            return "None"
        return type(value).__name__

    def _extract_function_info(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
        """从 AST 节点提取函数信息"""
        info = {
            "name": node.name,
            "args": [],
            "return_type": None,
            "docstring": ast.get_docstring(node),
            "body_length": len(node.body),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        }

        # 提取参数信息
        for arg in node.args.args:
            arg_info = {"name": arg.arg}

            # 参数类型注解
            if arg.annotation:
                arg_info["type"] = self._annotation_to_str(arg.annotation)
            else:
                arg_info["type"] = "Any"

            # 默认值
            idx = node.args.args.index(arg)
            default_idx = idx - len(node.args.args) + len(node.args.defaults)
            if default_idx >= 0:
                arg_info["default"] = self._value_to_str(node.args.defaults[default_idx])

            info["args"].append(arg_info)

        # 可变参数
        if node.args.vararg:
            info["args"].append(
                {
                    "name": "*" + node.args.vararg.arg,
                    "type": "tuple",
                }
            )
        if node.args.kwarg:
            info["args"].append(
                {
                    "name": "**" + node.args.kwarg.arg,
                    "type": "dict",
                }
            )

        # 返回类型
        if node.returns:
            info["return_type"] = self._annotation_to_str(node.returns)

        # 分析函数体
        info["has_return"] = any(isinstance(n, ast.Return) for n in ast.walk(node))
        info["has_yield"] = any(isinstance(n, ast.Yield) for n in ast.walk(node))
        info["has_raise"] = any(isinstance(n, ast.Raise) for n in ast.walk(node))
        info["has_loop"] = any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(node))
        info["has_condition"] = any(isinstance(n, ast.If) for n in ast.walk(node))

        info["description"] = self._infer_function_description(info["name"], info)

        return info

    def _infer_function_description(self, name: str, info: dict) -> str:
        """根据函数名推断函数描述"""
        name_lower = name.lower()

        for pattern, desc in self._function_patterns.items():
            if pattern in name_lower:
                return desc

        if info["is_async"]:
            return f"异步执行 {name} 操作"
        if info["has_loop"] and info["has_condition"]:
            return f"复杂处理函数，遍历并条件判断 {name}"
        if info["has_loop"]:
            return f"遍历处理函数，执行 {name} 操作"
        if info["has_condition"]:
            return f"条件判断函数，执行 {name} 操作"
        if info["has_return"]:
            return f"返回计算结果的 {name} 函数"

        return f"{name} 函数"

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

    def _value_to_str(self, value) -> str:
        """将 AST 值转换为字符串"""
        if isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                return f'"{value.value}"'
            return repr(value.value)
        elif isinstance(value, ast.Name):
            return value.id
        elif isinstance(value, ast.List):
            return "[" + ", ".join(self._value_to_str(e) for e in value.elts) + "]"
        elif isinstance(value, ast.Dict):
            items = []
            for k, v in zip(value.keys, value.values, strict=False):
                items.append(f"{self._value_to_str(k)}: {self._value_to_str(v)}")
            return "{" + ", ".join(items) + "}"
        return "..."

    def _generate_google_docstring(self, info: dict) -> str:
        """生成 Google 风格的 docstring"""
        lines = ['"""']

        lines.append(f"    {info.get('description', info['name'] + ' function')}")
        lines.append("")

        # Args
        if info["args"]:
            lines.append("    Args:")
            for arg in info["args"]:
                arg_type = arg.get("type", "Any")
                arg_default = arg.get("default")
                arg_desc = self._infer_arg_description(arg["name"], arg_type)
                line = f"        {arg['name']} ({arg_type})"
                if arg_default is not None:
                    line += f", default={arg_default}"
                line += f": {arg_desc}"
                lines.append(line)

        # Returns
        if info["return_type"] and info["has_return"]:
            lines.append("")
            lines.append("    Returns:")
            return_desc = self._infer_return_description(info["return_type"])
            lines.append(f"        {info['return_type']}: {return_desc}")

        # Yields
        if info["has_yield"]:
            lines.append("")
            lines.append("    Yields:")
            lines.append("        Generator: Generated values.")

        # Raises
        if info["has_raise"]:
            lines.append("")
            lines.append("    Raises:")
            lines.append("        Exception: Description of when this exception is raised.")

        # Examples
        if info["args"] and info["has_return"]:
            lines.append("")
            lines.append("    Examples:")
            lines.append("        >>> " + self._generate_example(info))

        lines.append('    """')
        return "\n".join(lines)

    def _generate_numpy_docstring(self, info: dict) -> str:
        """生成 NumPy 风格的 docstring"""
        lines = ['"""']

        lines.append(f"    {info.get('description', info['name'] + ' function')}")
        lines.append("")

        # Parameters
        if info["args"]:
            lines.append("    Parameters")
            lines.append("    ----------")
            for arg in info["args"]:
                arg_type = arg.get("type", "Any")
                arg_default = arg.get("default")
                arg_desc = self._infer_arg_description(arg["name"], arg_type)
                line = f"    {arg['name']} : {arg_type}"
                if arg_default is not None:
                    line += ", optional"
                lines.append(line)
                lines.append(f"        {arg_desc}")
                if arg_default is not None:
                    lines.append(f"        Default is {arg_default}.")

        # Returns
        if info["return_type"] and info["has_return"]:
            lines.append("")
            lines.append("    Returns")
            lines.append("    -------")
            return_desc = self._infer_return_description(info["return_type"])
            lines.append(f"    {info['return_type']}")
            lines.append(f"        {return_desc}")

        # Yields
        if info["has_yield"]:
            lines.append("")
            lines.append("    Yields")
            lines.append("    ------")
            lines.append("    Generator")
            lines.append("        Generated values.")

        # Raises
        if info["has_raise"]:
            lines.append("")
            lines.append("    Raises")
            lines.append("    ------")
            lines.append("    Exception")
            lines.append("        Description of when this exception is raised.")

        # Examples
        if info["args"] and info["has_return"]:
            lines.append("")
            lines.append("    Examples")
            lines.append("    --------")
            lines.append("    >>> " + self._generate_example(info))

        lines.append('    """')
        return "\n".join(lines)

    def _generate_rest_docstring(self, info: dict) -> str:
        """生成 ReST 风格的 docstring"""
        lines = ['"""']

        lines.append(f"    {info.get('description', info['name'] + ' function')}")
        lines.append("")

        # Args
        if info["args"]:
            lines.append("    :param " + info["args"][0]["name"] + ":")
            lines.append(
                "        "
                + self._infer_arg_description(
                    info["args"][0]["name"], info["args"][0].get("type", "Any")
                )
            )
            for arg in info["args"][1:]:
                arg_type = arg.get("type", "Any")
                arg_desc = self._infer_arg_description(arg["name"], arg_type)
                lines.append(f"    :param {arg['name']}:")
                lines.append(f"        {arg_desc}")

        # Types
        if info["args"]:
            lines.append("")
            for arg in info["args"]:
                arg_type = arg.get("type", "Any")
                lines.append(f"    :type {arg['name']}: {arg_type}")

        # Returns
        if info["return_type"] and info["has_return"]:
            lines.append("")
            return_desc = self._infer_return_description(info["return_type"])
            lines.append(f"    :return: {return_desc}")
            lines.append(f"    :rtype: {info['return_type']}")

        # Examples
        if info["args"] and info["has_return"]:
            lines.append("")
            lines.append("    .. code-block:: python")
            lines.append("")
            lines.append("        >>> " + self._generate_example(info))

        lines.append('    """')
        return "\n".join(lines)

    def _infer_arg_description(self, name: str, arg_type: str) -> str:
        """根据参数名和类型推断描述"""
        name_lower = name.lower()
        if name_lower in ["name", "username"]:
            return "The name of the object or user."
        elif name_lower in ["id", "user_id", "item_id"]:
            return "Unique identifier."
        elif name_lower in ["path", "file_path", "dir_path"]:
            return "Path to the file or directory."
        elif name_lower in ["data", "items", "list", "array"]:
            return "Input data or collection."
        elif name_lower in ["value", "val", "num"]:
            return "The value to process."
        elif name_lower in ["callback", "func", "handler"]:
            return "Callback function to invoke."
        elif name_lower in ["config", "settings", "options"]:
            return "Configuration parameters."
        elif name_lower in ["verbose", "debug", "quiet"]:
            return "Whether to enable verbose output."
        elif name_lower in ["timeout", "duration", "interval"]:
            return "Timeout duration in seconds."
        elif arg_type == "str":
            return "String input."
        elif arg_type == "int":
            return "Integer input."
        elif arg_type == "float":
            return "Floating-point input."
        elif arg_type == "bool":
            return "Boolean flag."
        elif arg_type.startswith("List"):
            return "List of items."
        elif arg_type.startswith("Dict"):
            return "Dictionary mapping."
        return "Description of the parameter."

    def _infer_return_description(self, return_type: str) -> str:
        """根据返回类型推断描述"""
        if return_type == "bool":
            return "True if successful, False otherwise."
        elif return_type == "int":
            return "Resulting integer value."
        elif return_type == "str":
            return "Resulting string value."
        elif return_type == "float":
            return "Resulting float value."
        elif return_type.startswith("List"):
            return "List of results."
        elif return_type.startswith("Dict"):
            return "Dictionary of results."
        elif return_type.startswith("Optional"):
            return "Result if available, None otherwise."
        elif return_type.startswith("Tuple"):
            return "Tuple containing multiple values."
        return "Result of the function."

    def _generate_example(self, info: dict) -> str:
        """生成示例代码"""
        args = []
        for arg in info["args"]:
            arg_type = arg.get("type", "Any")
            if arg_type == "str":
                args.append('"test"')
            elif arg_type == "int":
                args.append("10")
            elif arg_type == "float":
                args.append("10.0")
            elif arg_type == "bool":
                args.append("True")
            elif arg_type.startswith("List"):
                args.append("[1, 2, 3]")
            elif arg_type.startswith("Dict"):
                args.append('{"key": "value"}')
            else:
                args.append("value")

        return f"{info['name']}({', '.join(args)})"

    def generate_docstring(self, function_code: str) -> DocstringResult:
        """
        为函数代码生成 docstring。

        Args:
            function_code: 函数代码字符串

        Returns:
            DocstringResult
        """
        try:
            tree = ast.parse(function_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    info = self._extract_function_info(node)

                    if self.style == "numpy":
                        docstring = self._generate_numpy_docstring(info)
                    elif self.style == "rest":
                        docstring = self._generate_rest_docstring(info)
                    else:
                        docstring = self._generate_google_docstring(info)

                    return DocstringResult(
                        success=True,
                        function_name=info["name"],
                        original_code=function_code,
                        generated_docstring=docstring,
                        style=self.style,
                    )

            return DocstringResult(success=False, error="未找到函数定义")
        except Exception as e:
            return DocstringResult(success=False, error=str(e))

    def process_file(self, file_path: str | Path, overwrite: bool = True) -> FileDocstringResult:
        """
        处理文件，为所有函数生成 docstring。

        Args:
            file_path: 文件路径
            overwrite: 是否覆盖已存在的 docstring

        Returns:
            FileDocstringResult
        """
        file_path = Path(file_path)
        errors = []
        functions_processed = 0
        classes_processed = 0

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            ast.parse(content)
            lines = content.split("\n")

            new_lines = []
            i = 0

            while i < len(lines):
                new_lines.append(lines[i])
                i += 1

            return FileDocstringResult(
                success=True,
                file_path=str(file_path),
                functions_processed=functions_processed,
                classes_processed=classes_processed,
                updated_code="\n".join(new_lines),
            )

        except Exception as e:
            errors.append(str(e))
            return FileDocstringResult(
                success=False,
                file_path=str(file_path),
                errors=errors,
            )

    def generate_docstring_for_code(self, code: str) -> str:
        """
        为代码块生成 docstring。

        Args:
            code: 代码字符串

        Returns:
            生成的 docstring
        """
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    info = self._extract_function_info(node)

                    if self.style == "numpy":
                        return self._generate_numpy_docstring(info)
                    elif self.style == "rest":
                        return self._generate_rest_docstring(info)
                    else:
                        return self._generate_google_docstring(info)
            return ""
        except (SyntaxError, ValueError, AttributeError) as e:
            logger.debug("generate_docstring_for_code_failed error=%s", e)
            return ""


# ── 中文注释生成器 ────────────────────────────────────────


class ChineseCommentGenerator:
    """
    中文注释生成器 — 为代码生成中文注释。

    功能:
    - 为复杂算法生成中文解释
    - 解释"为什么这样写"而非"做了什么"
    - 支持变量、函数、类的注释
    """

    def generate_comments(self, code: str) -> str:
        """
        为代码生成中文注释。

        Args:
            code: 代码字符串

        Returns:
            添加了中文注释的代码
        """
        try:
            tree = ast.parse(code)
            lines = code.split("\n")

            comments = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    info = self._analyze_function(node)
                    comments.append((node.lineno - 1, self._generate_function_comment(info)))
                elif isinstance(node, ast.ClassDef):
                    comments.append((node.lineno - 1, self._generate_class_comment(node)))
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            comments.append(
                                (
                                    node.lineno - 1,
                                    self._generate_variable_comment(target.id, node.value),
                                )
                            )

            comments.sort(key=lambda x: x[0])

            result = []
            comment_idx = 0

            for i, line in enumerate(lines):
                while comment_idx < len(comments) and comments[comment_idx][0] == i:
                    result.append(comments[comment_idx][1])
                    comment_idx += 1
                result.append(line)

            return "\n".join(result)

        except (SyntaxError, ValueError, AttributeError) as e:
            logger.debug("generate_chinese_comments_failed error=%s", e)
            return code

    def _analyze_function(self, node: ast.FunctionDef) -> dict:
        """分析函数结构"""
        info = {
            "name": node.name,
            "args": [arg.arg for arg in node.args.args],
            "has_loop": any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(node)),
            "has_condition": any(isinstance(n, ast.If) for n in ast.walk(node)),
            "has_return": any(isinstance(n, ast.Return) for n in ast.walk(node)),
            "body_length": len(node.body),
            "complexity": self._calculate_complexity(node),
        }
        return info

    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """计算函数复杂度（基于条件分支数）"""
        complexity = 1
        for n in ast.walk(node):
            if isinstance(n, (ast.If, ast.For, ast.While, ast.And, ast.Or)):
                complexity += 1
        return complexity

    def _generate_function_comment(self, info: dict) -> str:
        """生成函数中文注释"""
        if info["complexity"] > 5:
            return f"# {info['name']}: 复杂函数，包含循环和条件分支，需仔细阅读"
        elif info["has_loop"]:
            return f"# {info['name']}: 遍历处理函数"
        elif info["has_condition"]:
            return f"# {info['name']}: 条件判断函数"
        else:
            return f"# {info['name']}: 工具函数"

    def _generate_class_comment(self, node: ast.ClassDef) -> str:
        """生成类中文注释"""
        return f"# {node.name}: 业务逻辑类"

    def _generate_variable_comment(self, name: str, value) -> str:
        """生成变量中文注释"""
        name_lower = name.lower()
        if name_lower.startswith("max_"):
            return f"# {name}: 最大值限制"
        elif name_lower.startswith("min_"):
            return f"# {name}: 最小值限制"
        elif name_lower.endswith("_list"):
            return f"# {name}: 列表数据"
        elif name_lower.endswith("_dict"):
            return f"# {name}: 字典映射"
        elif name_lower.endswith("_count"):
            return f"# {name}: 计数器"
        elif name_lower.endswith("_flag"):
            return f"# {name}: 标志位"
        elif name_lower.endswith("_result"):
            return f"# {name}: 结果存储"
        elif name_lower.endswith("_cache"):
            return f"# {name}: 缓存数据"
        return ""


# ── 快捷函数 ─────────────────────────────────────────────


def generate_docstring(code: str, style: str = "google") -> str:
    """生成 docstring"""
    generator = DocstringGenerator(style)
    return generator.generate_docstring_for_code(code)


def add_chinese_comments(code: str) -> str:
    """添加中文注释"""
    generator = ChineseCommentGenerator()
    return generator.generate_comments(code)
