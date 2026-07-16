"""
代码度量分析器 — McCabe 复杂度 / 可维护性指数 / 耦合度

纯本地计算，零 Token 成本。
"""

from __future__ import annotations

import ast
import logging
import math

logger = logging.getLogger(__name__)


class MetricsAnalyzer:
    """代码度量分析器 — 纯本地计算"""

    async def analyze(self, code: str, language: str = "python") -> dict:
        """执行完整代码度量"""
        if language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return self._empty_metrics()
            return await self._analyze_python(tree, code)
        return self._empty_metrics()

    async def _analyze_python(self, tree: ast.AST, code: str) -> dict:
        lines = code.splitlines()
        total = len(lines)
        code_lines = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        comment_lines = sum(1 for ln in lines if ln.strip().startswith("#"))
        blank_lines = total - code_lines - comment_lines

        # 函数级度量
        func_metrics = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mc = self._mccabe(node)
                sloc = 0
                if hasattr(node, "end_lineno"):
                    sloc = node.end_lineno - node.lineno + 1
                func_metrics.append({
                    "name": node.name,
                    "type": "async" if isinstance(node, ast.AsyncFunctionDef) else "sync",
                    "line": node.lineno,
                    "mccabe": mc,
                    "sloc": sloc,
                    "mi": self._maintainability_index(mc, sloc, 0),
                })

        # 类级度量
        class_metrics = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = sum(
                    1 for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                class_metrics.append({
                    "name": node.name,
                    "line": node.lineno,
                    "method_count": methods,
                })

        # 模块级聚合
        total_mccabe = sum(f["mccabe"] for f in func_metrics)
        avg_mccabe = round(total_mccabe / max(len(func_metrics), 1), 1)
        max_mccabe = max((f["mccabe"] for f in func_metrics), default=0)

        # 模块级可维护性指数
        module_mi = self._maintainability_index(avg_mccabe, code_lines, comment_lines)

        # 耦合度估算 (外部引用 / 总模块)
        imports = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        defined = len(func_metrics) + len(class_metrics)
        coupling = round(imports / max(defined + imports, 1), 3)

        # 深度嵌套检测
        deep_nesting = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While, ast.If)):
                depth = self._nesting_depth(node)
                if depth >= 4:
                    deep_nesting += 1

        return {
            "summary": {
                "total_lines": total,
                "code_lines": code_lines,
                "comment_lines": comment_lines,
                "blank_lines": blank_lines,
                "comment_density": round(comment_lines / max(code_lines, 1), 3),
            },
            "complexity": {
                "total_mccabe": total_mccabe,
                "avg_mccabe": avg_mccabe,
                "max_mccabe": max_mccabe,
                "high_complexity_count": sum(1 for f in func_metrics if f["mccabe"] > 10),
            },
            "maintainability": {
                "module_mi": round(module_mi, 1),
                "mi_rating": (
                    "good" if module_mi >= 80
                    else "moderate" if module_mi >= 60
                    else "poor"
                ),
            },
            "coupling": {
                "import_count": imports,
                "defined_count": defined,
                "coupling_ratio": coupling,
            },
            "structure": {
                "function_count": len(func_metrics),
                "class_count": len(class_metrics),
                "deep_nesting_count": deep_nesting,
            },
            "functions": sorted(func_metrics, key=lambda f: f["mccabe"], reverse=True)[:20],
            "classes": class_metrics,
        }

    def _mccabe(self, node: ast.AST) -> int:
        """计算 McCabe 循环复杂度"""
        count = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
            elif isinstance(child, ast.ExceptHandler):
                count += 1
            elif isinstance(child, ast.Assert):
                count += 1
        return count

    def _nesting_depth(self, node: ast.AST, depth: int = 0) -> int:
        """计算嵌套深度"""
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try)):
                nd = self._nesting_depth(child, depth + 1)
                max_depth = max(max_depth, nd)
        return max_depth

    def _maintainability_index(self, mccabe: float, sloc: int, comments: int) -> float:
        """计算可维护性指数 (MI)"""
        if sloc == 0:
            return 100.0
        # MI = 171 - 5.2*ln(HV) - 0.23*CC - 16.2*ln(LOC)
        # 简化版: 使用 McCabe + SLOC + 注释折算
        loc_term = math.log(max(sloc, 1)) * 16.2
        cc_term = mccabe * 0.23
        comment_term = (comments / max(sloc, 1)) * 16.2
        mi = 171.0 - loc_term - cc_term + comment_term
        return max(0, min(100, mi))

    def _empty_metrics(self) -> dict:
        return {
            "summary": {
                "total_lines": 0, "code_lines": 0, "comment_lines": 0,
                "blank_lines": 0, "comment_density": 0,
            },
            "complexity": {
                "total_mccabe": 0, "avg_mccabe": 0, "max_mccabe": 0,
                "high_complexity_count": 0,
            },
            "maintainability": {"module_mi": 100, "mi_rating": "good"},
            "coupling": {"import_count": 0, "defined_count": 0, "coupling_ratio": 0},
            "structure": {"function_count": 0, "class_count": 0, "deep_nesting_count": 0},
            "functions": [], "classes": [],
        }
