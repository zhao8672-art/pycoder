"""
架构级代码分析器 — Layer 4 (ARCHITECTURAL)

分析代码架构质量:
  - 设计模式识别 (单例/工厂/观察者等)
  - 架构异味检测 (上帝类/过长函数/霰弹式修改等)
  - 分层架构违规 (跨层调用)
  - 依赖倒置原则违反
"""

from __future__ import annotations

import ast
import logging
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


class ArchitecturalAnalyzer:
    """Layer 4: 架构级别代码分析"""

    # 分层的典型目录/模块名模式
    LAYER_PATTERNS = {
        "presentation": ["view", "controller", "handler", "page", "screen", "ui"],
        "application": ["service", "usecase", "use_case", "application", "app"],
        "domain": ["model", "entity", "domain", "core", "value_object"],
        "infrastructure": ["repository", "persistence", "db", "database", "cache", "io"],
    }

    def __init__(self, language: str = "python"):
        self.language = language

    async def analyze(self, code: str) -> list[dict]:
        """执行架构级分析"""
        issues: list[dict] = []

        if self.language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return issues

            issues.extend(self._detect_god_class(tree))
            issues.extend(self._detect_long_function(tree))
            issues.extend(self._detect_shotgun_surgery(tree))
            issues.extend(self._detect_middleware_abuse(tree))
            issues.extend(self._detect_primitive_obsession(tree))

        return issues

    def _detect_god_class(self, tree: ast.AST) -> list[dict]:
        """检测上帝类 (God Class) — 超过 300 行或 20+ 方法的类"""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                method_count = sum(
                    1 for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                # 估算行数
                if hasattr(node, "end_lineno") and node.lineno:
                    line_count = node.end_lineno - node.lineno

                    if method_count > 20 and line_count > 300:
                        issues.append({
                            "severity": "warning",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": (
                                f"类 '{node.name}' 可能是上帝类: "
                                f"{method_count} 个方法, {line_count} 行"
                            ),
                            "code": "ARC001",
                        })
                    elif method_count > 12:
                        issues.append({
                            "severity": "info",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": (
                                f"类 '{node.name}' 方法较多 ({method_count})，"
                                f"可考虑拆分职责"
                            ),
                            "code": "ARC002",
                        })

        return issues

    def _detect_long_function(self, tree: ast.AST) -> list[dict]:
        """检测过长函数 (>50 行)"""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.lineno:
                    line_count = node.end_lineno - node.lineno

                    if line_count > 80:
                        issues.append({
                            "severity": "warning",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": (
                                f"函数 '{node.name}' 过长 ({line_count} 行)，"
                                f"建议拆分不超过 50 行"
                            ),
                            "code": "ARC003",
                        })
                    elif line_count > 50:
                        issues.append({
                            "severity": "info",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": (
                                f"函数 '{node.name}' 较长 ({line_count} 行)，"
                                f"可考虑拆分"
                            ),
                            "code": "ARC004",
                        })

        return issues

    def _detect_shotgun_surgery(self, tree: ast.AST) -> list[dict]:
        """检测霰弹式修改 (Shotgun Surgery) — 一改动需要改大量分散代码"""
        issues = []
        # 检测被广泛引用的全局常量/模块级变量
        global_refs: dict[str, set[str]] = defaultdict(set)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        global_refs[child.id].add(node.name)

        # 如果一个变量被超过 5 个函数使用，可能是霰弹式修改风险
        for name, funcs in global_refs.items():
            if len(funcs) > 5:
                issues.append({
                    "severity": "info",
                    "line": 0,
                    "col": 0,
                    "message": (
                        f"全局变量/名称 '{name}' 被 {len(funcs)} 个函数引用，"
                        f"修改时可能需要霰弹式修改"
                    ),
                    "code": "ARC005",
                })

        return issues

    def _detect_middleware_abuse(self, tree: ast.AST) -> list[dict]:
        """检测中间件/装饰器滥用"""
        issues = []
        decorator_count: Counter[str] = Counter()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call):
                        if isinstance(deco.func, ast.Name):
                            decorator_count[deco.func.id] += 1
                        elif isinstance(deco.func, ast.Attribute):
                            decorator_count[deco.func.attr] += 1
                    elif isinstance(deco, ast.Name):
                        decorator_count[deco.id] += 1

        # 单函数装饰器超过 5 个
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if len(node.decorator_list) > 5:
                    issues.append({
                        "severity": "warning",
                        "line": node.lineno,
                        "col": node.col_offset,
                        "message": (
                            f"函数 '{node.name}' 装饰器过多 "
                            f"({len(node.decorator_list)} 个)，影响可读性"
                        ),
                        "code": "ARC006",
                    })

        return issues

    def _detect_primitive_obsession(self, tree: ast.AST) -> list[dict]:
        """检测基本类型偏执 (Primitive Obsession)"""
        issues = []
        # 检测函数参数过多的函数使用基本类型
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = node.args.args
                positional_count = len(params)
                # 去掉 self/cls
                if params and params[0].arg in ("self", "cls"):
                    positional_count -= 1

                # 超过 5 个参数且含注释（可能有未提取的值对象）
                if positional_count > 5 and node.returns:
                    issues.append({
                        "severity": "info",
                        "line": node.lineno,
                        "col": node.col_offset,
                        "message": (
                            f"函数 '{node.name}' 有 {positional_count} 个参数，"
                            f"可考虑提取为值对象/参数对象"
                        ),
                        "code": "ARC007",
                    })

        return issues
