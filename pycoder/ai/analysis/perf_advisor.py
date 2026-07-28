"""性能顾问 — 代码生成后自动检测性能问题

功能:
  1. AST 模式匹配检测常见性能反模式
  2. 生成性能告警 (含优化建议)
  3. 按严重级别分类

使用场景:
    advisor = PerformanceAdvisor()
    warnings = advisor.analyze_code(code)
    for w in warnings:
        print(f"行 {w.line}: {w.suggestion}")
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass
class PerfWarning:
    """性能告警"""

    line: int = 0
    pattern: str = ""  # 检测到的模式名
    severity: str = "medium"  # high / medium / low
    suggestion: str = ""
    code_snippet: str = ""


@dataclass
class PerfRule:
    """性能规则"""

    name: str
    description: str
    severity: str  # high / medium / low
    suggestion: str
    example_fix: str = ""


# ══════════════════════════════════════════════════════════
# 性能规则库
# ══════════════════════════════════════════════════════════

PERF_RULES: list[PerfRule] = [
    PerfRule(
        name="loop_io",
        description="循环内重复 I/O 操作 (文件读取/网络请求)",
        severity="high",
        suggestion="将文件读取/网络请求移到循环外，缓存结果后在循环内使用",
        example_fix="data = load_file()  # 循环外\nfor item in items:\n    process(item, data)",
    ),
    PerfRule(
        name="loop_object_creation",
        description="循环内重复创建重对象 (如 pygame.mixer.Sound)",
        severity="high",
        suggestion="在循环外创建对象，在循环内重用",
        example_fix="sound = pygame.mixer.Sound('x.wav')  # 循环外\nfor _ in range(n):\n    sound.play()",
    ),
    PerfRule(
        name="time_delay_in_loop",
        description="主循环中使用 time.delay()/time.sleep() 会导致卡顿",
        severity="high",
        suggestion="使用事件驱动或非阻塞等待 (如 pygame.time.Clock.tick)",
        example_fix="clock = pygame.time.Clock()\nclock.tick(60)  # 替代 time.sleep(0.016)",
    ),
    PerfRule(
        name="string_concat_in_loop",
        description="循环内使用 += 拼接字符串 (O(n²) 复杂度)",
        severity="medium",
        suggestion="使用列表 + join 替代字符串拼接",
        example_fix="parts = []\nfor x in items:\n    parts.append(str(x))\nresult = ''.join(parts)",
    ),
    PerfRule(
        name="recompile_regex",
        description="循环内重复编译正则表达式",
        severity="medium",
        suggestion="在循环外预编译正则表达式",
        example_fix="pattern = re.compile(r'\\d+')  # 循环外\nfor s in strings:\n    pattern.match(s)",
    ),
    PerfRule(
        name="global_var_access",
        description="频繁访问全局变量 (比局部变量慢)",
        severity="low",
        suggestion="将全局变量赋值给局部变量",
        example_fix="local_var = global_var  # 函数内\nfor _ in range(n):\n    use(local_var)",
    ),
    PerfRule(
        name="list_append_in_loop",
        description="循环内使用 append (可优化为列表推导式)",
        severity="low",
        suggestion="使用列表推导式替代 for 循环 + append",
        example_fix="result = [transform(x) for x in items]  # 替代 for+append",
    ),
    PerfRule(
        name="repeated_function_call",
        description="循环条件中重复调用函数 (如 len())",
        severity="medium",
        suggestion="将函数调用结果缓存到变量中",
        example_fix="n = len(items)  # 缓存\nfor i in range(n):\n    ...",
    ),
    PerfRule(
        name="inefficient_membership_test",
        description="在列表上使用 'in' 操作 (O(n) 复杂度)",
        severity="medium",
        suggestion="使用集合 (set) 进行成员测试 (O(1) 复杂度)",
        example_fix="valid = set(valid_list)  # 转 set\nif x in valid:  # O(1)\n    ...",
    ),
    PerfRule(
        name="nested_loop",
        description="嵌套循环 (O(n²) 或更高复杂度)",
        severity="medium",
        suggestion="考虑使用字典/集合优化查找，或使用 itertools",
        example_fix="lookup = {item.key: item for item in items}\nfor x in xs:\n    if x.key in lookup:  # O(1)\n        ...",
    ),
]


class PerformanceAdvisor:
    """性能顾问 — AST 分析 + 模式匹配"""

    def __init__(self) -> None:
        self._rules = {rule.name: rule for rule in PERF_RULES}

    def analyze_code(self, code: str, language: str = "python") -> list[PerfWarning]:
        """分析代码性能问题

        Args:
            code: 源代码字符串
            language: 语言 (目前仅支持 python)

        Returns:
            性能告警列表
        """
        if language != "python" or not code.strip():
            return []

        warnings: list[PerfWarning] = []

        # AST 分析
        try:
            tree = ast.parse(code)
            warnings.extend(self._analyze_ast(tree, code))
        except SyntaxError:
            # 语法错误时使用正则分析
            warnings.extend(self._analyze_regex(code))

        # 正则补充分析 (AST 无法检测的模式)
        warnings.extend(self._analyze_regex(code))

        # 去重 (按 line + pattern)
        seen: set[str] = set()
        unique: list[PerfWarning] = []
        for w in warnings:
            key = f"{w.line}:{w.pattern}"
            if key not in seen:
                seen.add(key)
                unique.append(w)

        return sorted(unique, key=lambda w: w.line)

    def _analyze_ast(self, tree: ast.AST, source: str) -> list[PerfWarning]:
        """AST 分析"""
        warnings: list[PerfWarning] = []
        lines = source.splitlines()

        for node in ast.walk(tree):
            # 检测循环内 I/O
            if isinstance(node, (ast.For, ast.While)):
                warnings.extend(self._check_loop_body(node, lines))

            # 检测循环条件中重复调用函数
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
                if isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range":
                    if isinstance(node.iter.args[0] if node.iter.args else None, ast.Call):
                        func = node.iter.args[0].func
                        if isinstance(func, ast.Name) and func.id == "len":
                            warnings.append(PerfWarning(
                                line=node.lineno,
                                pattern="repeated_function_call",
                                severity="medium",
                                suggestion="range(len(x)) 中 len() 每次迭代都会调用，建议缓存: n = len(x); for i in range(n)",
                                code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                            ))

            # 检测列表上使用 'in'
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if isinstance(comparator, (ast.List, ast.Tuple)):
                        warnings.append(PerfWarning(
                            line=node.lineno,
                            pattern="inefficient_membership_test",
                            severity="medium",
                            suggestion="在列表/元组上使用 'in' 是 O(n)，建议转为集合: if x in set(lst)",
                            code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                        ))

        return warnings

    def _check_loop_body(self, loop_node: ast.AST, lines: list[str]) -> list[PerfWarning]:
        """检查循环体内的性能问题"""
        warnings: list[PerfWarning] = []

        if not hasattr(loop_node, "body"):
            return warnings

        for child in ast.walk(ast.Module(body=loop_node.body, type_ignores=[])):
            # 检测循环内的 time.sleep / time.delay
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                func_name = child.func.attr
                if func_name in ("sleep", "delay") and isinstance(child.func.value, ast.Name):
                    if child.func.value.id in ("time", "pygame", "pygame.time"):
                        warnings.append(PerfWarning(
                            line=child.lineno,
                            pattern="time_delay_in_loop",
                            severity="high",
                            suggestion="循环内使用 sleep/delay 会导致卡顿，建议使用事件驱动或 Clock.tick",
                            code_snippet=lines[child.lineno - 1].strip() if child.lineno <= len(lines) else "",
                        ))

                # 检测循环内正则编译
                if func_name == "compile" and isinstance(child.func.value, ast.Name) and child.func.value.id == "re":
                    warnings.append(PerfWarning(
                        line=child.lineno,
                        pattern="recompile_regex",
                        severity="medium",
                        suggestion="循环内重复编译正则表达式，建议在循环外预编译",
                        code_snippet=lines[child.lineno - 1].strip() if child.lineno <= len(lines) else "",
                    ))

            # 检测循环内字符串拼接 (AugAssign with +)
            if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                warnings.append(PerfWarning(
                    line=child.lineno,
                    pattern="string_concat_in_loop",
                    severity="medium",
                    suggestion="循环内 += 拼接字符串是 O(n²)，建议使用列表 + join",
                    code_snippet=lines[child.lineno - 1].strip() if child.lineno <= len(lines) else "",
                ))

        return warnings

    def _analyze_regex(self, code: str) -> list[PerfWarning]:
        """正则补充分析"""
        warnings: list[PerfWarning] = []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 检测 pygame.mixer.Sound 在循环中 (简化检测)
            if "pygame.mixer.Sound" in stripped and any(
                kw in stripped for kw in ["for ", "while "]
            ):
                warnings.append(PerfWarning(
                    line=i,
                    pattern="loop_object_creation",
                    severity="high",
                    suggestion="循环内创建 pygame.mixer.Sound 对象，建议在循环外预加载",
                    code_snippet=stripped,
                ))

            # 检测 print 在循环中
            if "print(" in stripped and any(
                kw in lines[max(0, i-3):i] for kw in ["for ", "while "]
            ):
                if not stripped.startswith("#"):
                    warnings.append(PerfWarning(
                        line=i,
                        pattern="loop_io",
                        severity="low",
                        suggestion="循环内使用 print 会影响性能，生产环境建议使用 logging",
                        code_snippet=stripped,
                    ))

        return warnings

    def format_warnings(self, warnings: list[PerfWarning]) -> str:
        """格式化告警为文本"""
        if not warnings:
            return ""

        lines = ["⚠️ **性能注意**:", ""]
        for w in warnings:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(w.severity, "⚪")
            lines.append(f"{severity_icon} 行 {w.line} [{w.pattern}]: {w.suggestion}")
            if w.code_snippet:
                lines.append(f"   `{w.code_snippet}`")
        return "\n".join(lines)
