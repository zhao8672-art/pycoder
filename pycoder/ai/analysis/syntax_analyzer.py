"""
语法级代码分析器 — Layer 1 (SYNTAX)

使用 Python 内置 ast 模块进行静态语法分析:
  - 语法错误检测
  - 代码风格问题 (PEP 8)
  - 死代码检测 (未使用变量/导入)
  - 命名规范检查
  - 代码复杂度评估
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


class SyntaxIssue:
    """语法问题"""

    def __init__(self, severity: str, line: int, col: int, message: str, code: str):
        self.severity = severity  # error / warning / info
        self.line = line
        self.col = col
        self.message = message
        self.code = code

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "line": self.line,
            "col": self.col,
            "message": self.message,
            "code": self.code,
        }


class SyntaxAnalyzer:
    """Layer 1: 语法级别代码分析"""

    # PEP 8 命名正则模式
    _PATTERNS = {
        "module": r"^[a-z][a-z0-9_]*$",
        "class": r"^[A-Z][a-zA-Z0-9]*$",
        "function": r"^[a-z][a-z0-9_]*$",
        "variable": r"^[a-z][a-z0-9_]*$",
        "constant": r"^[A-Z][A-Z0-9_]*$",
    }

    def __init__(self, language: str = "python"):
        self.language = language

    async def analyze(self, code: str) -> list[dict]:
        """执行语法级分析"""
        issues: list[SyntaxIssue] = []

        if self.language == "python":
            issues.extend(self._check_syntax(code))
            issues.extend(self._check_dead_code(code))
            issues.extend(self._check_naming(code))
            issues.extend(self._check_complexity(code))

        # 额外风格检查
        issues.extend(self._check_style(code))

        return [i.to_dict() for i in issues]

    async def calculate_metrics(self, code: str) -> dict:
        """计算代码基础度量"""
        lines = code.splitlines()
        total_lines = len(lines)
        code_lines = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        comment_lines = sum(1 for ln in lines if ln.strip().startswith("#"))
        blank_lines = total_lines - code_lines - comment_lines

        try:
            tree = ast.parse(code)
            classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
            functions = sum(
                1 for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            imports = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        except SyntaxError:
            classes = functions = imports = 0

        return {
            "total_lines": total_lines,
            "code_lines": code_lines,
            "comment_lines": comment_lines,
            "blank_lines": blank_lines,
            "comment_density": round(comment_lines / max(code_lines, 1), 3),
            "class_count": classes,
            "function_count": functions,
            "import_count": imports,
        }

    def _check_syntax(self, code: str) -> list[SyntaxIssue]:
        """检查语法错误"""
        issues = []
        try:
            ast.parse(code)
        except SyntaxError as e:
            issues.append(SyntaxIssue(
                severity="error",
                line=e.lineno or 1,
                col=e.offset or 0,
                message=f"语法错误: {e.msg}",
                code="SYN001",
            ))
        return issues

    def _check_dead_code(self, code: str) -> list[SyntaxIssue]:
        """检测死代码"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 检测未使用的导入
        imported_names = set()
        used_names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Name):
                used_names.add(node.id)

        unused_imports = imported_names - used_names
        for name in unused_imports:
            issues.append(SyntaxIssue(
                severity="warning",
                line=0,
                col=0,
                message=f"未使用的导入: '{name}'",
                code="SYN002",
            ))

        # 检测未使用的变量
        assigned_vars: set[str] = set()
        used_vars: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned_vars.add(target.id)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    used_vars.add(node.id)

        unused_vars = assigned_vars - used_vars - {"__all__"}
        # 过滤掉明显的魔术变量
        unused_vars = {v for v in unused_vars if not v.startswith("_")}
        for name in unused_vars:
            issues.append(SyntaxIssue(
                severity="info",
                line=0,
                col=0,
                message=f"可能未使用的变量: '{name}'",
                code="SYN003",
            ))

        return issues

    def _check_naming(self, code: str) -> list[SyntaxIssue]:
        """检查命名规范"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if not node.name[0].isupper():
                    issues.append(SyntaxIssue(
                        severity="warning",
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"类名 '{node.name}' 应使用 CapWords 约定",
                        code="SYN004",
                    ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue  # 私有方法跳过
                if not node.name[0].islower():
                    issues.append(SyntaxIssue(
                        severity="warning",
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"函数名 '{node.name}' 应使用 snake_case",
                        code="SYN005",
                    ))

        return issues

    def _check_complexity(self, code: str) -> list[SyntaxIssue]:
        """检查代码复杂度"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # McCabe 复杂度近似: 决策点数量
                decisions = self._count_decisions(node)
                if decisions > 10:
                    issues.append(SyntaxIssue(
                        severity="warning",
                        line=node.lineno,
                        col=node.col_offset,
                        message=(
                            f"函数 '{node.name}' 的循环复杂度为 {decisions}，"
                            f"超过 10 的阈值，建议拆分"
                        ),
                        code="SYN006",
                    ))
                elif decisions > 5:
                    issues.append(SyntaxIssue(
                        severity="info",
                        line=node.lineno,
                        col=node.col_offset,
                        message=(
                            f"函数 '{node.name}' 的循环复杂度为 {decisions}，"
                            f"可考虑简化"
                        ),
                        code="SYN007",
                    ))

        return issues

    def _count_decisions(self, node: ast.AST) -> int:
        """统计函数中的决策点数量 (McCabe 近似)"""
        count = 1  # 基础路径
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1  # and/or 增加分支
            elif isinstance(child, ast.ExceptHandler):
                count += 1  # 每个 except 算一个分支
        return count

    def _check_style(self, code: str) -> list[SyntaxIssue]:
        """检查代码风格"""
        issues = []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            # 行太长 (>79 for PEP 8, >100 宽松)
            if len(line) > 120:
                issues.append(SyntaxIssue(
                    severity="info",
                    line=i,
                    col=0,
                    message=f"行过长 ({len(line)} > 120 字符)",
                    code="SYN008",
                ))
            # 尾部空白
            if line != line.rstrip():
                issues.append(SyntaxIssue(
                    severity="info",
                    line=i,
                    col=0,
                    message="行尾存在多余空白字符",
                    code="SYN009",
                ))
            # Tab 缩进
            if "\t" in line:
                issues.append(SyntaxIssue(
                    severity="warning",
                    line=i,
                    col=0,
                    message="使用了 Tab 缩进，建议使用空格",
                    code="SYN010",
                ))
            # 连续空行过多
            if i > 1 and line == "" and lines[i - 2] == "" and lines[i - 3] == "":
                issues.append(SyntaxIssue(
                    severity="info",
                    line=i,
                    col=0,
                    message="连续空行过多 (建议最多2行)",
                    code="SYN011",
                ))

        return issues
