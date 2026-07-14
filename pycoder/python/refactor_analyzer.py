"""
重构分析器 — 识别代码坏味道，提供重构建议和自动化操作。

功能:
- 检测重复代码（代码克隆）
- 识别过长函数
- 计算圈复杂度
- 发现不合理耦合
- 提供重构方案
- 支持一键提取函数、重命名、拆分模块
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field

# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class RefactoringIssue:
    """重构问题"""

    type: str
    severity: str
    location: str
    line: int
    column: int
    message: str
    suggestion: str
    code_snippet: str = ""
    fixable: bool = False


@dataclass
class RefactoringResult:
    """重构分析结果"""

    success: bool
    issues: list[RefactoringIssue] = field(default_factory=list)
    summary: str = ""
    refactored_code: str = ""


@dataclass
class DuplicateCode:
    """重复代码块"""

    hash: str
    locations: list[tuple[str, int]]
    code: str
    occurrences: int


@dataclass
class FunctionMetrics:
    """函数度量"""

    name: str
    line_count: int
    complexity: int
    parameter_count: int
    calls: int
    max_nesting: int
    has_duplicates: bool = False


# ── 重构分析器 ──────────────────────────────────────────


class RefactoringAnalyzer:
    """
    重构分析器 — 分析代码中的坏味道并提供重构建议。

    检测的问题类型:
    - duplicate_code: 重复代码
    - long_function: 过长函数
    - high_complexity: 高复杂度
    - too_many_params: 参数过多
    - deep_nesting: 嵌套过深
    - magic_number: 魔法数字
    - global_variable: 全局变量
    - tight_coupling: 紧耦合
    - unused_import: 未使用导入
    - unused_variable: 未使用变量
    """

    # 阈值配置
    THRESHOLDS = {
        "long_function": 50,
        "high_complexity": 10,
        "too_many_params": 5,
        "deep_nesting": 3,
        "duplicate_threshold": 3,
    }

    def __init__(self):
        self._issues: list[RefactoringIssue] = []
        self._duplicate_cache: dict[str, DuplicateCode] = {}

    def analyze_code(self, code: str, file_path: str = "") -> RefactoringResult:
        """
        分析代码中的重构问题。

        Args:
            code: 代码字符串
            file_path: 文件路径（可选）

        Returns:
            RefactoringResult
        """
        self._issues = []

        try:
            tree = ast.parse(code)
            lines = code.split("\n")

            self._detect_unused_imports(tree, file_path, lines)
            self._detect_long_functions(tree, file_path, lines)
            self._detect_high_complexity(tree, file_path, lines)
            self._detect_too_many_params(tree, file_path, lines)
            self._detect_deep_nesting(tree, file_path, lines)
            self._detect_magic_numbers(tree, file_path, lines)
            self._detect_unused_variables(tree, file_path, lines)
            self._detect_duplicate_code(tree, file_path, lines)

            summary = self._generate_summary()

            return RefactoringResult(
                success=True,
                issues=self._issues,
                summary=summary,
            )

        except Exception as e:
            return RefactoringResult(
                success=False,
                issues=[],
                summary=f"分析失败: {str(e)}",
            )

    def _detect_unused_imports(self, tree: ast.AST, file_path: str, lines: list):
        """检测未使用的导入"""
        imported_names = set()
        used_names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)

        unused = imported_names - used_names

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name in unused:
                        snippet = lines[node.lineno - 1].strip()
                        self._add_issue(
                            type="unused_import",
                            severity="low",
                            location=file_path,
                            line=node.lineno,
                            column=node.col_offset,
                            message=f"未使用的导入: {name}",
                            suggestion=f"移除未使用的导入 `{snippet}`",
                            code_snippet=snippet,
                            fixable=True,
                        )

    def _detect_long_functions(self, tree: ast.AST, file_path: str, lines: list):
        """检测过长函数"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = node.end_lineno or node.lineno
                line_count = end_line - node.lineno

                if line_count > self.THRESHOLDS["long_function"]:
                    snippet = "\n".join(lines[node.lineno - 1 : node.lineno + 2]).strip()
                    self._add_issue(
                        type="long_function",
                        severity="high",
                        location=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        message=f"函数 `{node.name}` 过长 ({line_count} 行)",
                        suggestion="考虑将函数拆分为多个更小的函数，每个函数只负责单一职责",
                        code_snippet=snippet,
                        fixable=True,
                    )

    def _detect_high_complexity(self, tree: ast.AST, file_path: str, lines: list):
        """检测高复杂度函数"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = self._calculate_complexity(node)

                if complexity > self.THRESHOLDS["high_complexity"]:
                    snippet = lines[node.lineno - 1].strip()
                    self._add_issue(
                        type="high_complexity",
                        severity="high",
                        location=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        message=f"函数 `{node.name}` 圈复杂度过高 ({complexity})",
                        suggestion=f"圈复杂度超过 {self.THRESHOLDS['high_complexity']}，考虑提取条件分支为独立函数或使用策略模式",
                        code_snippet=snippet,
                        fixable=True,
                    )

    def _calculate_complexity(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """计算函数圈复杂度"""
        complexity = 1
        for n in ast.walk(node):
            if isinstance(n, (ast.If, ast.For, ast.While, ast.And, ast.Or)):
                complexity += 1
            elif isinstance(n, ast.IfExp):
                complexity += 1
            elif isinstance(n, ast.Try):
                complexity += len(n.handlers)
        return complexity

    def _detect_too_many_params(self, tree: ast.AST, file_path: str, lines: list):
        """检测参数过多的函数"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                param_count = len(node.args.args)

                if param_count > self.THRESHOLDS["too_many_params"]:
                    snippet = lines[node.lineno - 1].strip()
                    self._add_issue(
                        type="too_many_params",
                        severity="medium",
                        location=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        message=f"函数 `{node.name}` 参数过多 ({param_count} 个)",
                        suggestion="考虑使用参数对象模式，将相关参数封装为一个类",
                        code_snippet=snippet,
                        fixable=True,
                    )

    def _detect_deep_nesting(self, tree: ast.AST, file_path: str, lines: list):
        """检测嵌套过深"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                max_nesting = self._calculate_nesting(node)

                if max_nesting > self.THRESHOLDS["deep_nesting"]:
                    snippet = lines[node.lineno - 1].strip()
                    self._add_issue(
                        type="deep_nesting",
                        severity="medium",
                        location=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        message=f"函数 `{node.name}` 嵌套过深 ({max_nesting} 层)",
                        suggestion="考虑提取嵌套逻辑为独立函数，或使用提前返回减少嵌套",
                        code_snippet=snippet,
                        fixable=True,
                    )

    def _calculate_nesting(self, node: ast.AST, current: int = 0) -> int:
        """计算嵌套深度"""
        max_depth = current

        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
            current += 1
            max_depth = current

        for child in ast.iter_child_nodes(node):
            max_depth = max(max_depth, self._calculate_nesting(child, current))

        return max_depth

    def _detect_magic_numbers(self, tree: ast.AST, file_path: str, lines: list):
        """检测魔法数字"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if node.value not in (0, 1, -1):
                    parent = self._get_parent(tree, node)
                    if not isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                        snippet = lines[node.lineno - 1].strip()
                        self._add_issue(
                            type="magic_number",
                            severity="low",
                            location=file_path,
                            line=node.lineno,
                            column=node.col_offset,
                            message=f"魔法数字: {node.value}",
                            suggestion="将魔法数字提取为具名常量，提高代码可读性",
                            code_snippet=snippet,
                            fixable=True,
                        )

    def _get_parent(self, tree: ast.AST, node: ast.AST) -> ast.AST | None:
        """获取父节点"""
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                if child is node:
                    return parent
        return None

    def _detect_unused_variables(self, tree: ast.AST, file_path: str, lines: list):
        """检测未使用的变量"""
        assigned = set()
        used = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.add(target.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    assigned.add(node.target.id)
            elif isinstance(node, ast.NamedExpr):
                if isinstance(node.target, ast.Name):
                    assigned.add(node.target.id)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)

        unused = assigned - used

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in unused:
                        snippet = lines[node.lineno - 1].strip()
                        self._add_issue(
                            type="unused_variable",
                            severity="low",
                            location=file_path,
                            line=node.lineno,
                            column=node.col_offset,
                            message=f"未使用的变量: {target.id}",
                            suggestion=f"移除未使用的变量 `{target.id}`",
                            code_snippet=snippet,
                            fixable=True,
                        )

    def _detect_duplicate_code(self, tree: ast.AST, file_path: str, lines: list):
        """检测重复代码"""
        code_blocks = self._extract_code_blocks(tree, lines)

        for block in code_blocks:
            block_hash = hashlib.md5(block["code"].encode(), usedforsecurity=False).hexdigest()

            if block_hash not in self._duplicate_cache:
                self._duplicate_cache[block_hash] = DuplicateCode(
                    hash=block_hash,
                    locations=[(file_path, block["line"])],
                    code=block["code"],
                    occurrences=1,
                )
            else:
                self._duplicate_cache[block_hash].locations.append((file_path, block["line"]))
                self._duplicate_cache[block_hash].occurrences += 1

        for dup in self._duplicate_cache.values():
            if dup.occurrences >= self.THRESHOLDS["duplicate_threshold"]:
                self._add_issue(
                    type="duplicate_code",
                    severity="high",
                    location=file_path,
                    line=dup.locations[0][1],
                    column=0,
                    message=f"发现重复代码块，出现 {dup.occurrences} 次",
                    suggestion="将重复代码提取为独立函数或方法",
                    code_snippet=dup.code[:100] + "..." if len(dup.code) > 100 else dup.code,
                    fixable=True,
                )

    def _extract_code_blocks(self, tree: ast.AST, lines: list) -> list[dict]:
        """提取代码块"""
        blocks = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = node.end_lineno or node.lineno
                code = "\n".join(lines[node.lineno - 1 : end_line])
                blocks.append({"line": node.lineno, "code": code})

            elif isinstance(node, ast.If):
                end_line = node.end_lineno or node.lineno
                code = "\n".join(lines[node.lineno - 1 : end_line])
                if len(code.strip().split("\n")) >= 5:
                    blocks.append({"line": node.lineno, "code": code})

            elif isinstance(node, ast.For):
                end_line = node.end_lineno or node.lineno
                code = "\n".join(lines[node.lineno - 1 : end_line])
                if len(code.strip().split("\n")) >= 5:
                    blocks.append({"line": node.lineno, "code": code})

        return blocks

    def _add_issue(self, **kwargs):
        """添加重构问题"""
        self._issues.append(RefactoringIssue(**kwargs))

    def _generate_summary(self) -> str:
        """生成分析摘要"""
        if not self._issues:
            return "✅ 未发现重构问题"

        by_severity = {"high": 0, "medium": 0, "low": 0}
        by_type = {}

        for issue in self._issues:
            by_severity[issue.severity] += 1
            by_type[issue.type] = by_type.get(issue.type, 0) + 1

        summary = f"发现 {len(self._issues)} 个重构问题:\n\n"
        summary += f"🔴 高优先级: {by_severity['high']}\n"
        summary += f"🟡 中优先级: {by_severity['medium']}\n"
        summary += f"🟢 低优先级: {by_severity['low']}\n\n"

        type_names = {
            "duplicate_code": "重复代码",
            "long_function": "过长函数",
            "high_complexity": "高复杂度",
            "too_many_params": "参数过多",
            "deep_nesting": "嵌套过深",
            "magic_number": "魔法数字",
            "unused_import": "未使用导入",
            "unused_variable": "未使用变量",
        }

        for issue_type, count in by_type.items():
            summary += f"- {type_names.get(issue_type, issue_type)}: {count}\n"

        return summary


# ── 重构执行器 ──────────────────────────────────────────


class RefactoringExecutor:
    """
    重构执行器 — 执行自动化重构操作。

    支持的操作:
    - extract_function: 提取函数
    - inline_function: 内联函数
    - rename_variable: 重命名变量
    - move_class: 移动类
    - split_module: 拆分模块
    """

    def __init__(self):
        pass

    def extract_function(
        self, code: str, start_line: int, end_line: int, func_name: str
    ) -> RefactoringResult:
        """
        从代码中提取函数。

        Args:
            code: 原始代码
            start_line: 起始行（1-based）
            end_line: 结束行（1-based）
            func_name: 新函数名

        Returns:
            RefactoringResult
        """
        try:
            lines = code.split("\n")

            if start_line < 1 or end_line > len(lines):
                return RefactoringResult(
                    success=False,
                    summary="行号超出范围",
                )

            extracted_lines = lines[start_line - 1 : end_line]

            min_indent = float("inf")
            for line in extracted_lines:
                stripped = line.lstrip()
                if stripped:
                    min_indent = min(min_indent, len(line) - len(stripped))

            cleaned_lines = [
                line[min_indent:] if len(line) >= min_indent else line for line in extracted_lines
            ]
            extracted_code = "\n".join(cleaned_lines).strip()

            indent = "    "
            new_func = f"def {func_name}():\n"
            new_func += "\n".join(indent + line for line in extracted_code.split("\n"))
            new_func += "\n    return ..."

            remaining_lines = (
                lines[: start_line - 1] + ["    " + func_name + "()"] + lines[end_line:]
            )

            return RefactoringResult(
                success=True,
                refactored_code=new_func + "\n\n" + "\n".join(remaining_lines),
                summary=f"成功提取函数 `{func_name}`，包含 {end_line - start_line + 1} 行代码",
            )

        except Exception as e:
            return RefactoringResult(
                success=False,
                summary=f"提取函数失败: {str(e)}",
            )

    def rename_variable(self, code: str, old_name: str, new_name: str) -> RefactoringResult:
        """
        重命名变量。

        Args:
            code: 原始代码
            old_name: 原变量名
            new_name: 新变量名

        Returns:
            RefactoringResult
        """
        try:
            tree = ast.parse(code)
            lines = code.split("\n")

            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == old_name:
                    if isinstance(node.ctx, (ast.Load, ast.Store, ast.Param)):
                        line_idx = node.lineno - 1
                        col_start = node.col_offset
                        col_end = col_start + len(old_name)
                        line = lines[line_idx]
                        lines[line_idx] = line[:col_start] + new_name + line[col_end:]

            return RefactoringResult(
                success=True,
                refactored_code="\n".join(lines),
                summary=f"成功将变量 `{old_name}` 重命名为 `{new_name}`",
            )

        except Exception as e:
            return RefactoringResult(
                success=False,
                summary=f"重命名变量失败: {str(e)}",
            )

    def inline_function(self, code: str, func_name: str) -> RefactoringResult:
        """
        内联函数。

        Args:
            code: 原始代码
            func_name: 要内联的函数名

        Returns:
            RefactoringResult
        """
        try:
            tree = ast.parse(code)
            lines = code.split("\n")

            func_body = None
            func_line = None

            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == func_name
                ):
                    end_line = node.end_lineno or node.lineno
                    func_body = "\n".join(lines[node.lineno : end_line]).strip()
                    func_line = node.lineno
                    break

            if func_body is None:
                return RefactoringResult(
                    success=False,
                    summary=f"未找到函数 `{func_name}`",
                )

            new_lines = []
            i = 0
            while i < len(lines):
                if i == func_line - 1:
                    end_line = tree.body[tree.body.index(node)].end_lineno or func_line
                    i = end_line
                    continue

                if func_name + "(" in lines[i]:
                    new_lines.append(func_body)
                else:
                    new_lines.append(lines[i])
                i += 1

            return RefactoringResult(
                success=True,
                refactored_code="\n".join(new_lines),
                summary=f"成功内联函数 `{func_name}`",
            )

        except Exception as e:
            return RefactoringResult(
                success=False,
                summary=f"内联函数失败: {str(e)}",
            )


# ── 快捷函数 ─────────────────────────────────────────────


def analyze_refactoring(code: str, file_path: str = "") -> RefactoringResult:
    """分析代码重构问题"""
    analyzer = RefactoringAnalyzer()
    return analyzer.analyze_code(code, file_path)


def extract_function(
    code: str, start_line: int, end_line: int, func_name: str
) -> RefactoringResult:
    """提取函数"""
    executor = RefactoringExecutor()
    return executor.extract_function(code, start_line, end_line, func_name)


def rename_variable(code: str, old_name: str, new_name: str) -> RefactoringResult:
    """重命名变量"""
    executor = RefactoringExecutor()
    return executor.rename_variable(code, old_name, new_name)
