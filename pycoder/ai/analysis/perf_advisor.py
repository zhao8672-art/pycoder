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
    # ── P1 扩展规则 (2026-07-29) ──
    PerfRule(
        name="n_plus_1_query",
        description="循环内执行数据库查询 (N+1 查询问题)",
        severity="high",
        suggestion="使用批量查询 (selectinload / prefetch_related) 一次性加载关联数据",
        example_fix="# 一次查询\nitems = session.query(Item).all()\nids = [i.user_id for i in items]\nusers = session.query(User).filter(User.id.in_(ids)).all()",
    ),
    PerfRule(
        name="sync_io_in_async",
        description="async 函数中使用同步 I/O (阻塞事件循环)",
        severity="high",
        suggestion="使用 aiofiles / httpx.AsyncClient / asyncio.to_thread 替代同步调用",
        example_fix="async with aiofiles.open(path) as f:\n    data = await f.read()  # 非阻塞",
    ),
    PerfRule(
        name="import_in_loop",
        description="循环内 import (每次迭代都会触发模块查找)",
        severity="medium",
        suggestion="将 import 移到模块顶部或函数开头",
        example_fix="import json  # 顶部\nfor s in strings:\n    json.loads(s)  # 直接使用",
    ),
    PerfRule(
        name="deep_copy_large",
        description="对大对象使用 deepcopy (O(n) 内存 + CPU 开销)",
        severity="medium",
        suggestion="使用浅拷贝或显式构造新对象，避免 deepcopy 整树",
        example_fix="new_list = list(old_list)  # 浅拷贝\n# 或 new_dict = {**old_dict}",
    ),
    PerfRule(
        name="sort_then_reverse",
        description="先 sort() 再 reverse() (双次遍历)",
        severity="low",
        suggestion="使用 sort(reverse=True) 一次到位",
        example_fix="items.sort(reverse=True)  # 替代 items.sort(); items.reverse()",
    ),
    PerfRule(
        name="bare_except_perf",
        description="裸 except 会捕获 BaseException (包括 KeyboardInterrupt/GC)",
        severity="medium",
        suggestion="使用具体异常类型 (except ValueError: ...) 提升性能和正确性",
        example_fix="try:\n    ...\nexcept ValueError as e:\n    handle(e)  # 只捕获需要的异常",
    ),
    PerfRule(
        name="dict_keys_to_list",
        description="将 dict.keys() 转为 list 后遍历 (多余内存)",
        severity="low",
        suggestion="直接遍历 dict.keys() (Python 3 返回 view, O(1) 内存)",
        example_fix="for k in d.keys():  # view, 无内存分配\n    ...",
    ),
    PerfRule(
        name="manual_loop_search",
        description="循环查找第一个匹配元素 (O(n))",
        severity="low",
        suggestion="使用 next() + 生成器表达式, 找到即停止",
        example_fix="item = next((x for x in items if x.ok), None)  # 找到即停",
    ),
    PerfRule(
        name="repeated_dict_lookup",
        description="同一字典多次查询同一 key",
        severity="low",
        suggestion="使用 dict.get() 一次取值或 try/except KeyError",
        example_fix="val = d.get(key)\nif val is not None:\n    process(val)  # 只查一次",
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

        # 检测 async 函数中的同步 I/O
        async_func_lines = self._find_async_functions(tree)

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

            # 检测 async 函数内的同步 I/O (open/requests.get)
            if isinstance(node, ast.Call) and hasattr(node, "lineno"):
                if node.lineno in async_func_lines and self._is_sync_io_call(node):
                    warnings.append(PerfWarning(
                        line=node.lineno,
                        pattern="sync_io_in_async",
                        severity="high",
                        suggestion="async 函数中调用同步 I/O 会阻塞事件循环，使用 aiofiles / httpx.AsyncClient",
                        code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                    ))

            # 检测循环内的 import
            if isinstance(node, (ast.For, ast.While)) and hasattr(node, "body"):
                for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(child, ast.Import) or isinstance(child, ast.ImportFrom):
                        warnings.append(PerfWarning(
                            line=child.lineno,
                            pattern="import_in_loop",
                            severity="medium",
                            suggestion="循环内 import 会增加查找开销，建议移到模块顶部",
                            code_snippet=lines[child.lineno - 1].strip() if child.lineno <= len(lines) else "",
                        ))

            # 检测 deepcopy 调用
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "deepcopy":
                    warnings.append(PerfWarning(
                        line=node.lineno,
                        pattern="deep_copy_large",
                        severity="medium",
                        suggestion="deepcopy 对大对象开销大，考虑浅拷贝或显式构造",
                        code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                    ))

            # 检测 sort() 后 reverse() 调用
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == "reverse":
                    warnings.append(PerfWarning(
                        line=node.lineno,
                        pattern="sort_then_reverse",
                        severity="low",
                        suggestion="使用 sort(reverse=True) 一次到位，避免双次遍历",
                        code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                    ))

            # 检测裸 except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                warnings.append(PerfWarning(
                    line=node.lineno,
                    pattern="bare_except_perf",
                    severity="medium",
                    suggestion="裸 except 会捕获 BaseException，使用具体异常类型",
                    code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                ))

            # 检测 list(d.keys()) 调用
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "list" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                        if arg.func.attr == "keys":
                            warnings.append(PerfWarning(
                                line=node.lineno,
                                pattern="dict_keys_to_list",
                                severity="low",
                                suggestion="直接遍历 d.keys() 即可 (Python 3 返回 view)，无需 list()",
                                code_snippet=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
                            ))

        return warnings

    def _find_async_functions(self, tree: ast.AST) -> set[int]:
        """收集 async 函数所在的所有行号区间"""
        lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef,)):
                # 标记函数体内所有行
                start = node.lineno
                end = node.end_lineno or node.lineno
                for ln in range(start, end + 1):
                    lines.add(ln)
        return lines

    @staticmethod
    def _is_sync_io_call(node: ast.Call) -> bool:
        """判断是否为同步 I/O 调用 (在 async 上下文中应避免)"""
        # open(...)
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            return True
        # xxx.open / requests.get / requests.post / urllib.request.urlopen
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr == "open":
                return True
            if attr in ("get", "post", "put", "delete", "request"):
                if isinstance(node.func.value, ast.Name) and node.func.value.id in (
                    "requests", "urllib", "httpx", "socket", "subprocess"
                ):
                    return True
        return False

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

        # 跟踪最近一个 for/while 行号
        last_loop_line = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 记录循环行
            if re.match(r"\s*(for|while)\s", line):
                last_loop_line = i

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

            # 检测循环内数据库查询 (N+1 查询模式)
            if last_loop_line and i > last_loop_line and i - last_loop_line < 20:
                db_patterns = [
                    r"\.query\s*\(",
                    r"\.execute\s*\(",
                    r"\.filter\s*\(",
                    r"\.all\s*\(\s*\)",
                    r"\.first\s*\(\s*\)",
                    r"session\.",
                    r"\.objects\.",
                ]
                if any(re.search(p, stripped) for p in db_patterns) and not stripped.startswith("#"):
                    warnings.append(PerfWarning(
                        line=i,
                        pattern="n_plus_1_query",
                        severity="high",
                        suggestion="循环内执行数据库查询 (N+1)，建议使用批量查询或预加载关联数据",
                        code_snippet=stripped,
                    ))

            # 检测 for-break 查找模式 (manual_loop_search)
            if re.match(r"\s*for\s+\w+\s+in\s+.+:", line):
                # 检查后续 5 行内是否有 break (range 上界需 +1 以包含最后一行)
                for j in range(i, min(i + 5, len(lines)) + 1):
                    if j <= len(lines) and "break" in lines[j - 1]:
                        warnings.append(PerfWarning(
                            line=i,
                            pattern="manual_loop_search",
                            severity="low",
                            suggestion="for+break 查找模式可用 next() + 生成器表达式替代",
                            code_snippet=stripped,
                        ))
                        break

            # 检测重复字典查询 (简化版: 同行多次出现 d["key"])
            dict_lookups = re.findall(r'(\w+)\[["\']([^"\']+)["\']\]', stripped)
            if dict_lookups:
                counts: dict[str, int] = {}
                for var, key in dict_lookups:
                    name = f"{var}['{key}']"
                    counts[name] = counts.get(name, 0) + 1
                for name, cnt in counts.items():
                    if cnt >= 2:
                        warnings.append(PerfWarning(
                            line=i,
                            pattern="repeated_dict_lookup",
                            severity="low",
                            suggestion=f"行内多次查询 {name}，建议缓存到局部变量",
                            code_snippet=stripped,
                        ))
                        break

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
