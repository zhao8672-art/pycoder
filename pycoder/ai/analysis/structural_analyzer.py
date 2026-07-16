"""
结构级代码分析器 — Layer 3 (STRUCTURAL)

分析代码结构关系:
  - 调用图构建
  - 模块间耦合度
  - 循环依赖检测
  - 扇入/扇出分析
  - 依赖关系矩阵
"""

from __future__ import annotations

import ast
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class StructuralAnalyzer:
    """Layer 3: 结构级别代码分析"""

    def __init__(self, language: str = "python"):
        self.language = language

    async def analyze(self, code: str) -> list[dict]:
        """执行结构级分析"""
        issues: list[dict] = []

        if self.language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return issues

            call_graph = self._build_call_graph(tree)
            coupling = self._analyze_coupling(tree)
            circular = self._detect_circular_dependencies(call_graph)

            issues.extend(coupling)
            issues.extend(circular)

            # 附件: 元数据
            self._last_analysis = {
                "call_graph": call_graph,
                "fan_in": coupling.get("_fan_in", {}),
                "fan_out": coupling.get("_fan_out", {}),
            }

        return issues

    async def build_call_graph(self, code: str) -> dict[str, list[str]]:
        """构建调用图 (外部 API)"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {}
        return dict(self._build_call_graph(tree))

    async def calculate_coupling(self, code: str) -> dict:
        """计算耦合度 (外部 API)"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {"cohesion": 0, "coupling": 0}
        return self._analyze_coupling(tree)

    def _build_call_graph(self, tree: ast.AST) -> dict[str, set[str]]:
        """构建函数/方法调用图"""
        graph: dict[str, set[str]] = {}
        current_func: str = ""

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                current_func = node.name
                if current_func not in graph:
                    graph[current_func] = set()

                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            graph[current_func].add(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            graph[current_func].add(child.func.attr)

        return graph

    def _analyze_coupling(self, tree: ast.AST) -> list[dict]:
        """分析模块耦合度"""
        issues: list[dict] = []

        # 函数定义及外部引用
        defined: set[str] = set()
        references: dict[str, set[str]] = defaultdict(set)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)

            elif isinstance(node, ast.Call):
                caller = "global"
                # 尝试找最近的外层函数
                for parent in ast.walk(tree):
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for child in ast.walk(parent):
                            if child is node:
                                caller = parent.name

                callee = ""
                if isinstance(node.func, ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    callee = node.func.attr

                if callee:
                    references[caller].add(callee)

        # 扇入/扇出分析
        fan_in: dict[str, int] = defaultdict(int)
        fan_out: dict[str, int] = defaultdict(int)

        for caller, callees in references.items():
            fan_out[caller] = len(callees)
            for callee in callees:
                fan_in[callee] += 1

        self._last_coupling = {
            "fan_in": dict(fan_in),
            "fan_out": dict(fan_out),
        }

        # 高扇出警告 (单函数调用过多)
        for func, count in fan_out.items():
            if count > 8:
                issues.append({
                    "severity": "warning",
                    "line": 0,
                    "col": 0,
                    "message": f"函数 '{func}' 扇出过高 ({count})，直接依赖过多模块/函数",
                    "code": "STR001",
                })

        # 高扇入警告 (过于中心化)
        for func, count in fan_in.items():
            if count > 10 and func != "global":
                issues.append({
                    "severity": "info",
                    "line": 0,
                    "col": 0,
                    "message": f"函数 '{func}' 扇入过高 ({count})，作为中心节点",
                    "code": "STR002",
                })

        return issues

    def _detect_circular_dependencies(self, graph: dict[str, set[str]]) -> list[dict]:
        """检测循环依赖"""
        issues = []

        def dfs(
            node: str,
            visited: set[str],
            path: list[str],
        ) -> list[list[str]]:
            cycles = []
            if node in path:
                cycle_start = path.index(node)
                cycles.append(path[cycle_start:] + [node])
                return cycles

            if node in visited:
                return cycles

            visited.add(node)
            path.append(node)

            for neighbor in graph.get(node, set()):
                if neighbor in graph:  # 只关注图中已有的节点
                    cycles.extend(dfs(neighbor, visited, path[:]))

            return cycles

        all_nodes = list(graph.keys())
        checked: set[str] = set()
        seen_cycles: set[str] = set()

        for node in all_nodes:
            if node not in checked:
                cycles = dfs(node, set(), [])
                checked.add(node)

                for cycle in cycles:
                    # 规范化签名去重
                    sig = "->".join(sorted(set(cycle)))
                    if sig not in seen_cycles:
                        seen_cycles.add(sig)
                        cycle_nodes = [n for n in cycle if n != cycle[-1] or n != cycle[0]]
                        if len(cycle_nodes) >= 2:
                            issues.append({
                                "severity": "warning",
                                "line": 0,
                                "col": 0,
                                "message": f"检测到循环依赖: {' → '.join(cycle_nodes)} → {cycle_nodes[0]}",
                                "code": "STR003",
                            })

        return issues

    def get_last_analysis(self) -> dict:
        """获取最近的分析结果 (包含元数据)"""
        return getattr(self, "_last_analysis", {})

    def get_coupling(self) -> dict:
        """获取耦合度数据"""
        return getattr(self, "_last_coupling", {})
