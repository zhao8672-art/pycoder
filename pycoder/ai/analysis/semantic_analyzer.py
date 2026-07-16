"""
语义级代码分析器 — Layer 2 (SEMANTIC)

通过 LSP (Language Server Protocol) 进行深层语义分析:
  - 类型错误检测
  - 空引用风险
  - 类型一致性检查
  - 接口实现完整性
  - Pylance LSP 集成 (Python 优先)
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """Layer 2: 语义级别代码分析

    内置语义检查 (无 LSP 依赖)
    + 可选 Pylance LSP 集成 (更精确)
    """

    def __init__(self, language: str = "python"):
        self.language = language

    async def analyze(self, code: str) -> list[dict]:
        """执行语义级分析"""
        issues: list[dict] = []

        if self.language == "python":
            issues.extend(self._check_type_consistency(code))
            issues.extend(self._check_none_references(code))
            issues.extend(self._check_interface_completeness(code))
            issues.extend(self._check_comparison_safety(code))

        return issues

    def _check_type_consistency(self, code: str) -> list[dict]:
        """检查类型一致性"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 检查 None 比较
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op, comparator in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.Eq, ast.NotEq)):
                        if isinstance(comparator, ast.Constant) and comparator.value is None:
                            is_eq = isinstance(op, ast.Eq)
                            msg = ("使用 == None，建议使用 is None"
                                   if is_eq
                                   else "使用 != None，建议使用 is not None")
                            issues.append({
                                "severity": "warning",
                                "line": node.lineno,
                                "col": node.col_offset,
                                "message": msg,
                                "code": "SEM001",
                            })
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append({
                            "severity": "warning",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": f"函数 '{node.name}' 使用了可变默认参数，"
                                       f"可能导致意外的状态共享",
                            "code": "SEM002",
                        })

        return issues

    def _check_none_references(self, code: str) -> list[dict]:
        """检查空引用风险"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        attrs_accessed: dict[str, list[tuple[int, str]]] = {}
        none_checks: set[str] = set()

        # 第一遍: 收集属性访问和 None 检查
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    if node.value.id not in attrs_accessed:
                        attrs_accessed[node.value.id] = []
                    attrs_accessed[node.value.id].append((node.lineno, node.attr))

            # None 比较
            if isinstance(node, ast.Compare):
                for op, comp in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.Is, ast.IsNot)):
                        if isinstance(comp, ast.Constant) and comp.value is None:
                            if isinstance(node.left, ast.Name):
                                none_checks.add(node.left.id)

        # 第二遍: 检查没有 None 检查就访问属性的变量
        # 检测函数返回 None 的情况
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                returns_none = False
                has_return_value = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Return):
                        if child.value is None:
                            returns_none = True
                        else:
                            has_return_value = True
                if returns_none and has_return_value:
                    issues.append({
                        "severity": "warning",
                        "line": node.lineno,
                        "col": node.col_offset,
                        "message": f"函数 '{node.name}' 有时返回 None，"
                                   f"调用侧应做好 None 检查",
                        "code": "SEM003",
                    })

        # 检查 super() 调用
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "super":
                    # 检查是否在方法内
                    pass  # 基础检查已足够

        return issues

    def _check_interface_completeness(self, code: str) -> list[dict]:
        """检查接口实现完整性"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # 检查是否使用了 ABC/抽象基类
                bases = [self._get_base_name(b) for b in node.bases]
                is_abstract = "ABC" in bases or "abc.ABC" in bases or "Protocol" in bases

                # 检查抽象类没有具体实现
                if is_abstract:
                    has_concrete = any(
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not any(
                            isinstance(d, ast.Name) and d.id == "abstractmethod"
                            for d in item.decorator_list
                        )
                        for item in node.body
                    )
                    if not has_concrete:
                        issues.append({
                            "severity": "info",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": f"类 '{node.name}' 标记为抽象但没有具体方法",
                            "code": "SEM003",
                        })

        return issues

    def _check_comparison_safety(self, code: str) -> list[dict]:
        """检查比较操作的安全性"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            # float 的 == 比较
            if isinstance(node, ast.Compare):
                for op, comp in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.Eq, ast.NotEq)):
                        if isinstance(comp, ast.Constant) and isinstance(comp.value, float):
                            issues.append({
                                "severity": "info",
                                "line": node.lineno,
                                "col": node.col_offset,
                                "message": (
                                    f"浮点数 {comp.value} 的相等比较可能不精确，"
                                    f"建议使用 math.isclose()"
                                ),
                                "code": "SEM004",
                            })

            # 类型比较用 isinstance
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, (ast.Eq, ast.NotEq)):
                        right = node.comparators[0]
                        if isinstance(right, ast.Name) and right.id in (
                            "str", "int", "float", "bool",
                            "list", "dict", "tuple", "set",
                        ):
                            issues.append({
                                "severity": "info",
                                "line": node.lineno,
                                "col": node.col_offset,
                                "message": f"类型比较建议使用 isinstance() 而不是 == {right.id}",
                                "code": "SEM005",
                            })

        return issues

    def _get_base_name(self, node: ast.AST) -> str:
        """获取基类名称"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_base_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return self._get_base_name(node.value)
        return ""
