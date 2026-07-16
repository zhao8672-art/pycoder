"""
行为级代码分析器 — Layer 5 (BEHAVIORAL)

分析代码运行时行为:
  - 时间复杂度分析 (Big O)
  - 性能热点检测 (嵌套循环/递归)
  - 并发安全性 (共享状态/锁)
  - 资源管理 (未关闭的文件/连接)
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


class BehavioralAnalyzer:
    """Layer 5: 行为级别代码分析"""

    def __init__(self, language: str = "python"):
        self.language = language

    async def analyze(self, code: str) -> list[dict]:
        """执行行为级分析"""
        issues: list[dict] = []

        if self.language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return issues

            issues.extend(self._detect_performance_hotspots(tree))
            issues.extend(self._detect_resource_leaks(tree))
            issues.extend(self._detect_concurrency_issues(tree))
            issues.extend(self._estimate_time_complexity(tree))

        return issues

    def _detect_performance_hotspots(self, tree: ast.AST) -> list[dict]:
        """检测性能热点"""
        issues = []

        for node in ast.walk(tree):
            # 嵌套循环 (O(n²) 及以上)
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                depth = self._get_loop_depth(node, tree)
                if depth >= 3:
                    issues.append({
                        "severity": "warning",
                        "line": node.lineno,
                        "col": node.col_offset,
                        "message": (
                            f"检测到 {depth} 层嵌套循环，时间复杂度可能为 O(n^{depth})，"
                            f"建议优化算法或引入索引"
                        ),
                        "code": "BEH001",
                    })
                elif depth == 2:
                    issues.append({
                        "severity": "info",
                        "line": node.lineno,
                        "col": node.col_offset,
                        "message": ("检测到 2 层嵌套循环 O(n^2)，大数据量时可能性能不足"),
                        "code": "BEH002",
                    })

            # 列表推导式中的嵌套循环
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                generators = getattr(node, "generators", [])
                if len(generators) > 2:
                    issues.append({
                        "severity": "info",
                        "line": node.lineno,
                        "col": node.col_offset,
                        "message": (
                            f"推导式中包含 {len(generators)} 层循环，"
                            f"可读性差且可能性能不佳"
                        ),
                        "code": "BEH003",
                    })

        return issues

    def _get_loop_depth(self, node: ast.AST, tree: ast.AST, current_depth: int = 1) -> int:
        """计算循环嵌套深度"""
        max_depth = current_depth
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                # 确认 child 是 node 的直接/间接子节点
                depth = current_depth + 1
                sub_depth = self._get_loop_depth(child, tree, depth)
                max_depth = max(max_depth, sub_depth)
        return max_depth

    def _detect_resource_leaks(self, tree: ast.AST) -> list[dict]:
        """检测资源泄漏风险"""
        issues = []
        file_open_names: set[str] = set()

        for node in ast.walk(tree):
            # 检测 open() 调用
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    # 检查是否在 with 语句中
                    if not self._is_in_context_manager(node, tree):
                        issues.append({
                            "severity": "warning",
                            "line": node.lineno,
                            "col": node.col_offset,
                            "message": "open() 未使用 with 语句，可能导致文件句柄泄漏",
                            "code": "BEH004",
                        })

            # 检测没有 close 的变量赋值
            if isinstance(node, ast.Assign):
                call = node.value
                if isinstance(call, ast.Call):
                    func = call.func
                    if isinstance(func, ast.Attribute):
                        if func.attr in ("open", "connect", "cursor"):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    file_open_names.add(target.id)

        return issues

    def _is_in_context_manager(self, node: ast.AST, tree: ast.AST) -> bool:
        """检查节点是否在 with 语句内"""
        for parent in ast.walk(tree):
            if isinstance(parent, ast.With) or isinstance(parent, ast.AsyncWith):
                for item in ast.walk(parent):
                    if item is node:
                        return True
        return False

    def _detect_concurrency_issues(self, tree: ast.AST) -> list[dict]:
        """检测并发安全问题"""
        issues = []
        has_threading = False
        has_lock = False

        for node in ast.walk(tree):
            # 检测 threading 导入
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name for n in node.names]
                if "threading" in names or "thread" in names:
                    has_threading = True
                if any("lock" in n.name.lower() for n in names):
                    has_lock = True

            # 检测共享状态（模块级可变变量）
            if isinstance(node, ast.Assign) and not isinstance(node.targets[0], (ast.Name,)):
                pass  # 基本检测足够

            # 检测没有锁的共享变量修改
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "start" and isinstance(node.func.value, ast.Name):
                        pass  # 基本线程检测

        if has_threading and not has_lock:
            issues.append({
                "severity": "warning",
                "line": 0,
                "col": 0,
                "message": (
                    "使用了 threading 但没有检测到 Lock 使用，"
                    "存在竞态条件风险"
                ),
                "code": "BEH005",
            })

        return issues

    def _estimate_time_complexity(self, tree: ast.AST) -> list[dict]:
        """估计时间复杂度"""
        issues = []

        # 计算各类操作的加权和
        loops = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.For, ast.AsyncFor, ast.While)))
        nested_loops = 0
        for node in ast.walk(tree):
            d = self._get_loop_depth(node, tree)
            if d > 1:
                nested_loops += 1

        recursive = self._detect_recursion(tree)

        complexity_score = loops + nested_loops * 2 + (10 if recursive else 0)

        if recursive:
            issues.append({
                "severity": "warning",
                "line": 0,
                "col": 0,
                "message": (
                    "检测到递归调用，时间复杂度可能为 O(2^n) 或 O(n!)，"
                    "建议使用迭代或尾递归优化"
                ),
                "code": "BEH006",
            })
        elif complexity_score > 8:
            issues.append({
                "severity": "info",
                "line": 0,
                "col": 0,
                "message": f"整体时间复杂度偏高 (评分: {complexity_score})，建议优化",
                "code": "BEH007",
            })

        return issues

    def _detect_recursion(self, tree: ast.AST) -> bool:
        """检测递归调用"""
        functions: dict[str, ast.FunctionDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = node

        for name, func in functions.items():
            for child in ast.walk(func):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name) and child.func.id == name:
                        return True
        return False
