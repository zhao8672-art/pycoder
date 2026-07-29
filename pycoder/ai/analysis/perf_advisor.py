"""性能分析器 — AST 级别的性能建议生成

将 _analyze_ast 函数拆分为多个小函数以提高可维护性。
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


def _analyze_ast(tree: ast.AST, source: str) -> list[dict]:
    """分析 AST 树，生成性能建议

    Args:
        tree: AST 树
        source: 源代码字符串

    Returns:
        性能建议列表
    """
    suggestions: list[dict] = []

    # 委托给各个子分析器
    suggestions.extend(_analyze_loops(tree))
    suggestions.extend(_analyze_list_operations(tree))
    suggestions.extend(_analyze_string_operations(tree))
    suggestions.extend(_analyze_function_calls(tree))
    suggestions.extend(_analyze_imports(tree))
    suggestions.extend(_analyze_comprehensions(tree))
    suggestions.extend(_analyze_exceptions(tree))
    suggestions.extend(_analyze_global_variables(tree))
    suggestions.extend(_analyze_recursion(tree))
    suggestions.extend(_analyze_type_conversions(tree))
    suggestions.extend(_analyze_io_patterns(tree))
    suggestions.extend(_analyze_memory_patterns(tree))
    suggestions.extend(_analyze_algorithm_patterns(tree))
    suggestions.extend(_analyze_dict_patterns(tree))
    suggestions.extend(_analyze_loop_invocations(tree))

    return suggestions


def _analyze_loops(tree: ast.AST) -> list[dict]:
    """分析循环性能问题

    Returns:
        循环相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            # 检查嵌套循环
            _check_nested_loops(node, suggestions)
            # 检查 range(len()) 模式
            _check_range_len_pattern(node, suggestions)
            # 检查循环内函数调用
            _check_loop_function_calls(node, suggestions)
    return suggestions


def _check_nested_loops(node: ast.For, suggestions: list[dict]) -> None:
    """检查嵌套循环"""
    for child in ast.walk(node):
        if isinstance(child, ast.For) and child is not node:
            suggestions.append({
                "type": "nested_loop",
                "line": child.lineno,
                "message": "嵌套循环可能导致 O(n²) 复杂度，考虑优化",
                "severity": "warning",
                "suggestion": "考虑使用字典/集合查找替代内层循环",
            })


def _check_range_len_pattern(node: ast.For, suggestions: list[dict]) -> None:
    """检查 range(len()) 模式"""
    if isinstance(node.iter, ast.Call):
        if isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range":
            if node.iter.args and isinstance(node.iter.args[0], ast.Call):
                call = node.iter.args[0]
                if isinstance(call.func, ast.Name) and call.func.id == "len":
                    suggestions.append({
                        "type": "range_len",
                        "line": node.lineno,
                        "message": "使用 range(len()) 模式，建议直接迭代元素",
                        "severity": "info",
                        "suggestion": "使用 for item in iterable: 替代",
                    })


def _check_loop_function_calls(node: ast.For, suggestions: list[dict]) -> None:
    """检查循环内函数调用"""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and child is not node.iter:
            suggestions.append({
                "type": "loop_function_call",
                "line": child.lineno,
                "message": "循环内函数调用可能影响性能",
                "severity": "info",
                "suggestion": "考虑将函数调用移出循环或缓存结果",
            })


def _analyze_list_operations(tree: ast.AST) -> list[dict]:
    """分析列表操作性能问题

    Returns:
        列表操作相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "append":
                    _check_append_in_loop(node, suggestions)
                elif node.func.attr == "insert":
                    suggestions.append({
                        "type": "list_insert",
                        "line": node.lineno,
                        "message": "list.insert(0, ...) 是 O(n) 操作",
                        "severity": "warning",
                        "suggestion": "考虑使用 collections.deque 替代",
                    })
                elif node.func.attr == "remove":
                    suggestions.append({
                        "type": "list_remove",
                        "line": node.lineno,
                        "message": "list.remove() 是 O(n) 操作",
                        "severity": "info",
                        "suggestion": "考虑使用集合或字典替代",
                    })
    return suggestions


def _check_append_in_loop(node: ast.Call, suggestions: list[dict]) -> None:
    """检查循环内的 append 操作"""
    for parent in ast.walk(node):
        if isinstance(parent, ast.For):
            suggestions.append({
                "type": "append_in_loop",
                "line": node.lineno,
                "message": "循环内使用 append，建议使用列表推导式",
                "severity": "info",
                "suggestion": "使用 [expr for item in iterable] 替代",
            })
            break


def _analyze_string_operations(tree: ast.AST) -> list[dict]:
    """分析字符串操作性能问题

    Returns:
        字符串操作相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            suggestions.append({
                "type": "string_format",
                "line": node.lineno,
                "message": "使用 % 格式化字符串，建议使用 f-string",
                "severity": "info",
                "suggestion": "使用 f-string: f'{variable}'",
            })
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "join" and isinstance(node.func.value, ast.Str):
                    suggestions.append({
                        "type": "string_join",
                        "line": node.lineno,
                        "message": "字符串连接建议使用 join()",
                        "severity": "info",
                        "suggestion": "使用 ''.join(list) 替代 + 操作",
                    })
    return suggestions


def _analyze_function_calls(tree: ast.AST) -> list[dict]:
    """分析函数调用性能问题

    Returns:
        函数调用相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ("type", "isinstance"):
                    _check_type_check_in_loop(node, suggestions)
    return suggestions


def _check_type_check_in_loop(node: ast.Call, suggestions: list[dict]) -> None:
    """检查循环内的类型检查"""
    for parent in ast.walk(node):
        if isinstance(parent, ast.For):
            suggestions.append({
                "type": "type_check_in_loop",
                "line": node.lineno,
                "message": "循环内类型检查可能影响性能",
                "severity": "info",
                "suggestion": "考虑使用类型注解或鸭子类型",
            })
            break


def _analyze_imports(tree: ast.AST) -> list[dict]:
    """分析导入性能问题

    Returns:
        导入相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("os", "sys", "re"):
                    suggestions.append({
                        "type": "import_inside_function",
                        "line": node.lineno,
                        "message": f"导入 {alias.name} 在函数内部，建议移到文件顶部",
                        "severity": "info",
                        "suggestion": "将 import 语句移到文件顶部",
                    })
    return suggestions


def _analyze_comprehensions(tree: ast.AST) -> list[dict]:
    """分析推导式性能问题

    Returns:
        推导式相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ListComp):
            _check_comprehension_complexity(node, suggestions)
            _check_nested_comprehension(node, suggestions)
        elif isinstance(node, ast.DictComp):
            suggestions.append({
                "type": "dict_comprehension",
                "line": node.lineno,
                "message": "字典推导式可能消耗大量内存",
                "severity": "info",
                "suggestion": "考虑使用生成器表达式或 dict() 构造函数",
            })
            _check_nested_comprehension(node, suggestions)
        elif isinstance(node, (ast.SetComp, ast.GeneratorExp)):
            _check_nested_comprehension(node, suggestions)
    return suggestions


def _check_comprehension_complexity(node: ast.ListComp, suggestions: list[dict]) -> None:
    """检查推导式复杂度"""
    if len(node.generators) > 2:
        suggestions.append({
            "type": "complex_comprehension",
            "line": node.lineno,
            "message": "多层嵌套推导式可读性差",
            "severity": "warning",
            "suggestion": "考虑拆分为多个步骤或使用循环",
        })


def _check_nested_comprehension(
    node: ast.ListComp | ast.DictComp | ast.SetComp | ast.GeneratorExp,
    suggestions: list[dict],
) -> None:
    """检查嵌套推导式（推导式内包含另一个推导式）"""
    comprehension_types = (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)
    for child in ast.walk(node):
        if child is not node and isinstance(child, comprehension_types):
            suggestions.append({
                "type": "nested_comprehension_perf",
                "line": node.lineno,
                "message": "嵌套推导式会为每个外层元素创建新的内层对象，可能影响性能",
                "severity": "warning",
                "suggestion": "将内层推导式提取为变量或使用生成器表达式",
            })
            return


def _analyze_exceptions(tree: ast.AST) -> list[dict]:
    """分析异常处理性能问题

    Returns:
        异常处理相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            _check_bare_except(node, suggestions)
            _check_exception_in_loop(node, suggestions)
    return suggestions


def _check_bare_except(node: ast.Try, suggestions: list[dict]) -> None:
    """检查裸 except"""
    for handler in node.handlers:
        if handler.type is None:
            suggestions.append({
                "type": "bare_except",
                "line": handler.lineno,
                "message": "裸 except 会捕获所有异常，包括 SystemExit",
                "severity": "warning",
                "suggestion": "指定具体的异常类型: except Exception:",
            })


def _check_exception_in_loop(node: ast.Try, suggestions: list[dict]) -> None:
    """检查循环内的异常处理"""
    for parent in ast.walk(node):
        if isinstance(parent, ast.For):
            suggestions.append({
                "type": "exception_in_loop",
                "line": node.lineno,
                "message": "循环内异常处理可能影响性能",
                "severity": "info",
                "suggestion": "考虑将异常处理移出循环",
            })
            break


def _analyze_global_variables(tree: ast.AST) -> list[dict]:
    """分析全局变量性能问题

    Returns:
        全局变量相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            suggestions.append({
                "type": "global_variable",
                "line": node.lineno,
                "message": "使用全局变量可能影响性能",
                "severity": "info",
                "suggestion": "考虑使用函数参数或类属性替代",
            })
    return suggestions


def _analyze_recursion(tree: ast.AST) -> list[dict]:
    """分析递归性能问题

    Returns:
        递归相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            _check_recursive_function(node, suggestions)
    return suggestions


def _check_recursive_function(node: ast.FunctionDef, suggestions: list[dict]) -> None:
    """检查递归函数"""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name) and child.func.id == node.name:
                suggestions.append({
                    "type": "recursion",
                    "line": child.lineno,
                    "message": f"函数 {node.name} 是递归的，可能栈溢出",
                    "severity": "warning",
                    "suggestion": "考虑使用迭代或尾递归优化",
                })
                break


def _analyze_type_conversions(tree: ast.AST) -> list[dict]:
    """分析类型转换性能问题

    Returns:
        类型转换相关的性能建议
    """
    suggestions: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("int", "float", "str"):
                _check_conversion_in_loop(node, suggestions)
    return suggestions


def _check_conversion_in_loop(node: ast.Call, suggestions: list[dict]) -> None:
    """检查循环内的类型转换"""
    for parent in ast.walk(node):
        if isinstance(parent, ast.For):
            suggestions.append({
                "type": "conversion_in_loop",
                "line": node.lineno,
                "message": "循环内类型转换可能影响性能",
                "severity": "info",
                "suggestion": "考虑在循环外预处理数据",
            })
            break


# ── I/O 模式分析 ────────────────────────────────────────


def _analyze_io_patterns(tree: ast.AST) -> list[dict]:
    """分析 I/O 模式性能问题

    Returns:
        I/O 模式相关的性能建议
    """
    suggestions: list[dict] = []

    # 收集所有 async 函数内的节点
    async_descendants: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for child in ast.walk(node):
                async_descendants.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # sync_io_in_async: 检测 async 函数中的同步 I/O
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                if id(node) in async_descendants:
                    suggestions.append({
                        "type": "sync_io_in_async",
                        "line": node.lineno,
                        "message": "async 函数中使用了同步 open()，可能阻塞事件循环",
                        "severity": "warning",
                        "suggestion": "使用 aiofiles.open() 或 run_in_executor()",
                    })
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in ("read", "write", "readline", "readlines", "writelines"):
                    if id(node) in async_descendants:
                        suggestions.append({
                            "type": "sync_io_in_async",
                            "line": node.lineno,
                            "message": f"async 函数中使用了同步 {node.func.attr}()，可能阻塞事件循环",
                            "severity": "warning",
                            "suggestion": "使用异步 I/O 或 run_in_executor()",
                        })

            # unbuffered_io: 检测无缓冲的文件操作
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                has_buffering = False
                for kw in node.keywords:
                    if kw.arg == "buffering":
                        has_buffering = True
                        if isinstance(kw.value, ast.Constant) and kw.value.value == 0:
                            suggestions.append({
                                "type": "unbuffered_io",
                                "line": node.lineno,
                                "message": "使用无缓冲 I/O (buffering=0) 可能影响性能",
                                "severity": "info",
                                "suggestion": "考虑使用默认缓冲或显式设置 buffering=-1",
                            })
                        break
                if not has_buffering:
                    suggestions.append({
                        "type": "unbuffered_io",
                        "line": node.lineno,
                        "message": "open() 未指定缓冲策略，建议显式设置 buffering 参数",
                        "severity": "info",
                        "suggestion": "显式设置 buffering 参数以优化 I/O 性能",
                    })

    return suggestions


# ── 内存管理分析 ─────────────────────────────────────────


def _analyze_memory_patterns(tree: ast.AST) -> list[dict]:
    """分析内存管理性能问题

    Returns:
        内存管理相关的性能建议
    """
    suggestions: list[dict] = []

    # 收集 with 语句内的所有节点
    with_children: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for child in ast.walk(node):
                with_children.add(id(child))

    # 收集每个函数内的 global 声明
    func_globals: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_globals[id(node)] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Global):
                    func_globals[id(node)].update(child.names)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # unclosed_resource: 检测未使用 with 语句的 open()
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                if id(node) not in with_children:
                    suggestions.append({
                        "type": "unclosed_resource",
                        "line": node.lineno,
                        "message": "open() 未使用 with 语句，可能导致资源泄漏",
                        "severity": "warning",
                        "suggestion": "使用 with open(...) as f: 确保文件正确关闭",
                    })

            # growing_collection: 检测全局缓存的无限增长
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ("append", "extend", "add", "update"):
                    if isinstance(node.func.value, ast.Name):
                        var_name = node.func.value.id
                        # 检查该变量是否在某个函数内被声明为 global
                        for _func_id, globals_set in func_globals.items():
                            if var_name in globals_set:
                                suggestions.append({
                                    "type": "growing_collection",
                                    "line": node.lineno,
                                    "message": f"全局集合 '{var_name}' 持续增长，可能导致内存泄漏",
                                    "severity": "warning",
                                    "suggestion": "考虑添加大小限制或使用 LRU 缓存",
                                })
                                break

    return suggestions


# ── 算法复杂度分析 ────────────────────────────────────────


def _analyze_algorithm_patterns(tree: ast.AST) -> list[dict]:
    """分析算法复杂度性能问题

    Returns:
        算法复杂度相关的性能建议
    """
    suggestions: list[dict] = []

    # repeated_sort: 检测同一变量多次排序
    sort_vars: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "sort":
                if isinstance(node.func.value, ast.Name):
                    name = node.func.value.id
                    if name not in sort_vars:
                        sort_vars[name] = []
                    sort_vars[name].append(node.lineno)

    for name, lines in sort_vars.items():
        if len(lines) > 1:
            suggestions.append({
                "type": "repeated_sort",
                "line": lines[0],
                "message": f"对 '{name}' 重复排序 ({len(lines)} 次)，可能影响性能",
                "severity": "warning",
                "suggestion": "考虑将排序结果缓存或使用 sorted() 一次性排序",
            })

    # missing_bisect: 检测已排序列表的线性搜索
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            _check_linear_search_in_loop(node, suggestions)

    return suggestions


def _check_linear_search_in_loop(loop_node: ast.For, suggestions: list[dict]) -> None:
    """检查循环内是否在做线性搜索（相等比较 + break）"""
    for child in ast.walk(loop_node):
        if isinstance(child, ast.If) and child is not loop_node:
            if isinstance(child.test, ast.Compare):
                for op in child.test.ops:
                    if isinstance(op, ast.Eq):
                        for sub in ast.walk(child):
                            if isinstance(sub, ast.Break):
                                suggestions.append({
                                    "type": "missing_bisect",
                                    "line": loop_node.lineno,
                                    "message": "在循环中进行线性搜索（== 比较 + break），建议使用 bisect 模块",
                                    "severity": "info",
                                    "suggestion": "使用 bisect 模块进行二分查找",
                                })
                                return


# ── 字典操作分析 ─────────────────────────────────────────


def _analyze_dict_patterns(tree: ast.AST) -> list[dict]:
    """分析字典操作性能问题

    Returns:
        字典操作相关的性能建议
    """
    suggestions: list[dict] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                # defaultdict_missing: 检测 dict.get() 模式
                if node.func.attr == "get":
                    suggestions.append({
                        "type": "defaultdict_missing",
                        "line": node.lineno,
                        "message": "使用 dict.get() 模式，建议使用 collections.defaultdict",
                        "severity": "info",
                        "suggestion": "使用 collections.defaultdict 替代 dict.get() 模式",
                    })

                # setdefault_misuse: 检测 dict.setdefault 总是创建默认值
                if node.func.attr == "setdefault":
                    suggestions.append({
                        "type": "setdefault_misuse",
                        "line": node.lineno,
                        "message": "dict.setdefault() 总是创建默认值，可能浪费资源",
                        "severity": "info",
                        "suggestion": "使用 collections.defaultdict 替代 setdefault()",
                    })

    return suggestions


# ── 循环内特定调用分析 ─────────────────────────────────────


def _analyze_loop_invocations(tree: ast.AST) -> list[dict]:
    """分析循环内特定函数调用性能问题

    Returns:
        循环内函数调用相关的性能建议
    """
    suggestions: list[dict] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    # datetime_strptime_in_loop
                    if isinstance(child.func, ast.Attribute):
                        if child.func.attr == "strptime":
                            # 匹配 datetime.strptime 或 datetime.datetime.strptime
                            is_datetime = False
                            if (isinstance(child.func.value, ast.Attribute)
                                    and child.func.value.attr == "datetime"):
                                is_datetime = True
                            elif (isinstance(child.func.value, ast.Name)
                                    and child.func.value.id == "datetime"):
                                is_datetime = True
                            if is_datetime:
                                suggestions.append({
                                    "type": "datetime_strptime_in_loop",
                                    "line": child.lineno,
                                    "message": "循环内重复调用 datetime.strptime，建议预编译格式",
                                    "severity": "warning",
                                    "suggestion": "将日期格式预编译或在循环外解析",
                                })

                        # re_compile_in_loop
                        if child.func.attr == "compile":
                            if (isinstance(child.func.value, ast.Name)
                                    and child.func.value.id == "re"):
                                suggestions.append({
                                    "type": "re_compile_in_loop",
                                    "line": child.lineno,
                                    "message": "循环内重复调用 re.compile，建议移到循环外",
                                    "severity": "warning",
                                    "suggestion": "将 re.compile() 移到循环外",
                                })

    return suggestions


# ── 性能分析面向对象 API ────────────────────────────────

from dataclasses import dataclass  # noqa: E402


@dataclass
class PerfWarning:
    """性能警告"""

    pattern: str = ""
    message: str = ""
    line: int = 0
    severity: str = "warning"
    suggestion: str = ""


class PerformanceAdvisor:
    """性能顾问 — 分析代码并给出性能建议"""

    def __init__(self):
        self._rules = PERF_RULES

    def analyze_code(self, source: str) -> list[PerfWarning]:
        """分析源代码，返回性能警告列表"""
        warnings: list[PerfWarning] = []
        try:
            tree = ast.parse(source)
            suggestions = _analyze_ast(tree, source)
            for s in suggestions:
                warnings.append(PerfWarning(
                    pattern=s.get("type", "unknown"),
                    message=s.get("message", ""),
                    line=s.get("line", 0),
                    severity=s.get("severity", "warning"),
                    suggestion=s.get("suggestion", ""),
                ))
        except SyntaxError:
            pass
        return warnings

    @staticmethod
    def format_warnings(warnings: list[PerfWarning]) -> str:
        """格式化警告列表为可读的字符串"""
        if not warnings:
            return ""
        lines = []
        for w in warnings:
            lines.append(f"[{w.severity.upper()}] L{w.line}: {w.message}")
            if w.suggestion:
                lines.append(f"    → {w.suggestion}")
        return "\n".join(lines)


# ── 性能规则注册表 ──────────────────────────────────────

PERF_RULES: list[dict] = [
    # 字符串操作
    {"id": "string_concat_in_loop", "category": "string", "severity": "warning",
     "message": "循环内字符串拼接应使用 join() 或列表推导式"},
    {"id": "repeated_string_format", "category": "string", "severity": "info",
     "message": "重复字符串格式化可预计算模板"},
    # 列表操作
    {"id": "append_in_loop", "category": "list", "severity": "warning",
     "message": "循环内逐元素 append 应使用列表推导式"},
    {"id": "list_copy_in_loop", "category": "list", "severity": "info",
     "message": "循环内复制大列表可能影响性能"},
    {"id": "range_len_pattern", "category": "list", "severity": "warning",
     "message": "for i in range(len(x)) 应改为 for i, v in enumerate(x)"},
    # 循环优化
    {"id": "nested_loops", "category": "loop", "severity": "warning",
     "message": "嵌套循环可能导致 O(n²) 复杂度"},
    {"id": "loop_invariant", "category": "loop", "severity": "info",
     "message": "循环不变量应提到循环外"},
    {"id": "loop_function_calls", "category": "loop", "severity": "info",
     "message": "循环内重复调用函数可缓存结果"},
    # 函数调用
    {"id": "type_check_in_loop", "category": "function", "severity": "info",
     "message": "循环内 isinstance 检查可提到循环外"},
    {"id": "repeated_computation", "category": "function", "severity": "info",
     "message": "重复计算应缓存结果"},
    # 导入优化
    {"id": "import_in_loop", "category": "import", "severity": "warning",
     "message": "循环内导入模块应移到顶部"},
    {"id": "star_import", "category": "import", "severity": "info",
     "message": "通配符导入可能导入不需要的模块"},
    # 推导式
    {"id": "comprehension_complexity", "category": "comprehension", "severity": "info",
     "message": "复杂推导式应拆分为多行或使用生成器"},
    {"id": "nested_comprehension", "category": "comprehension", "severity": "warning",
     "message": "嵌套推导式可读性差且可能影响性能"},
    # 异常处理
    {"id": "bare_except", "category": "exception", "severity": "warning",
     "message": "裸 except 会捕获所有异常，应指定具体异常类型"},
    {"id": "exception_in_loop", "category": "exception", "severity": "info",
     "message": "循环内异常处理开销较大"},
    # 全局变量
    {"id": "global_variable", "category": "global", "severity": "info",
     "message": "过度使用全局变量影响可维护性"},
    {"id": "global_in_loop", "category": "global", "severity": "warning",
     "message": "循环内修改全局变量有性能开销"},
    # 递归
    {"id": "deep_recursion", "category": "recursion", "severity": "warning",
     "message": "深度递归可能导致栈溢出，考虑迭代实现"},
    {"id": "non_tail_recursion", "category": "recursion", "severity": "info",
     "message": "非尾递归可能消耗更多内存"},
    # 类型转换
    {"id": "conversion_in_loop", "category": "conversion", "severity": "info",
     "message": "循环内类型转换可预处理"},
    {"id": "redundant_conversion", "category": "conversion", "severity": "info",
     "message": "冗余类型转换可省略"},
    # 并发（P2 扩展）
    {"id": "blocking_io", "category": "concurrency", "severity": "warning",
     "message": "同步 I/O 可能阻塞事件循环"},
    {"id": "unbounded_thread_pool", "category": "concurrency", "severity": "warning",
     "message": "无界线程池可能导致资源耗尽"},
    # 内存（P2 扩展）
    {"id": "large_list_in_memory", "category": "memory", "severity": "warning",
     "message": "大列表全部加载到内存，考虑使用生成器"},
    {"id": "circular_reference", "category": "memory", "severity": "info",
     "message": "循环引用可能导致内存泄漏"},
    # 序列化（P2 扩展）
    {"id": "json_loads_in_loop", "category": "serialization", "severity": "warning",
     "message": "循环内重复解析 JSON 可缓存结果"},
    {"id": "pickle_security", "category": "serialization", "severity": "warning",
     "message": "pickle 反序列化不可信数据有安全风险"},
    # 数据结构（P2 扩展）
    {"id": "list_as_queue", "category": "data_structure", "severity": "warning",
     "message": "list 作为队列 pop(0) 是 O(n)，应使用 collections.deque"},
    {"id": "linear_search", "category": "data_structure", "severity": "info",
     "message": "线性搜索 O(n)，考虑使用 set/dict 或排序后二分查找"},
    # 缓存（P2 扩展）
    {"id": "repeated_db_query", "category": "cache", "severity": "warning",
     "message": "重复数据库查询应使用缓存"},
    {"id": "missing_lru_cache", "category": "cache", "severity": "info",
     "message": "纯函数可添加 @lru_cache 装饰器"},
    # I/O 模式（P3 扩展）
    {"id": "sync_io_in_async", "category": "io", "severity": "warning",
     "message": "async 函数中使用了同步 I/O 操作，可能阻塞事件循环"},
    {"id": "unbuffered_io", "category": "io", "severity": "info",
     "message": "未指定缓冲策略或使用了无缓冲 I/O，可能影响 I/O 性能"},
    # 算法复杂度（P3 扩展）
    {"id": "repeated_sort", "category": "algorithm", "severity": "warning",
     "message": "对同一列表重复排序，应缓存排序结果"},
    {"id": "missing_bisect", "category": "algorithm", "severity": "info",
     "message": "已排序列表的线性搜索，建议使用 bisect 模块"},
    {"id": "nested_comprehension_perf", "category": "algorithm", "severity": "warning",
     "message": "嵌套推导式会为每个外层元素创建新的内层对象"},
    # 内存管理（P3 扩展）
    {"id": "growing_collection", "category": "memory", "severity": "warning",
     "message": "全局集合无限增长，可能导致内存泄漏"},
    {"id": "unclosed_resource", "category": "memory", "severity": "warning",
     "message": "文件/连接未使用 with 语句，可能导致资源泄漏"},
    # 字典操作（P3 扩展）
    {"id": "defaultdict_missing", "category": "data_structure", "severity": "info",
     "message": "使用 dict.get() 模式，建议使用 collections.defaultdict"},
    {"id": "setdefault_misuse", "category": "data_structure", "severity": "info",
     "message": "dict.setdefault() 总是创建默认值，建议使用 defaultdict"},
    # 循环内调用（P3 扩展）
    {"id": "datetime_strptime_in_loop", "category": "loop", "severity": "warning",
     "message": "循环内重复调用 datetime.strptime，应预编译格式"},
    {"id": "re_compile_in_loop", "category": "loop", "severity": "warning",
     "message": "循环内重复调用 re.compile，应移到循环外"},
]
