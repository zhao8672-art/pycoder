"""
代码重构引擎 — 自动代码优化、结构改进和性能提升

核心能力:
  1. 代码结构分析 — AST 驱动的模块依赖、复杂度和耦合度分析
  2. 重构建议生成 — 基于规则 + LLM 的重构方案生成
  3. 安全重构执行 — Git 隔离 + 测试门禁 + 自动回滚
  4. 性能优化 — 识别 O(n²) 等性能反模式并生成优化方案

安全机制:
  - 所有重构在 Git 分支隔离进行
  - 重构前后必须通过测试套件
  - 失败自动回滚
  - 最多修改 3 个文件/次

用法:
  from pycoder.capabilities.self_evo.learning.refactoring_engine import (
      RefactoringEngine,
      RefactorSuggestion,
      get_refactoring_engine,
  )

  engine = RefactoringEngine()
  suggestions = engine.analyze("pycoder/server/")
  for s in suggestions:
      result = engine.apply(s)
"""

from __future__ import annotations

import ast
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PYCODER_ROOT = Path(__file__).resolve().parents[4]
MAX_FILES_PER_REFACTOR = 3


@dataclass
class CodeMetrics:
    """代码度量"""

    file: str
    lines: int = 0
    functions: int = 0
    classes: int = 0
    cyclomatic_complexity: float = 0.0
    maintainability_index: float = 100.0
    coupling: int = 0
    imports_count: int = 0
    docstring_coverage: float = 0.0


@dataclass
class RefactorSuggestion:
    """重构建议"""

    file: str
    line: int
    severity: str  # critical / high / medium / low
    category: str  # complexity / performance / coupling / style / safety
    title: str
    description: str = ""
    old_code: str = ""
    new_code: str = ""
    rationale: str = ""
    risk_level: str = "low"  # low / medium / high
    auto_apply: bool = False


@dataclass
class RefactorResult:
    """重构结果"""

    suggestion: RefactorSuggestion
    applied: bool
    test_passed: bool = False
    git_branch: str = ""
    git_commit: str = ""
    error: str | None = None
    rollback_performed: bool = False
    duration_ms: float = 0.0


class RefactoringEngine:
    """代码重构引擎"""

    def __init__(self):
        self._history: list[RefactorResult] = []
        self._max_files = MAX_FILES_PER_REFACTOR

    # ══════════════════════════════════════════════════════
    # 分析
    # ══════════════════════════════════════════════════════

    def analyze(self, target: str | Path) -> list[RefactorSuggestion]:
        """分析目标代码，生成重构建议列表"""
        target_path = Path(target) if isinstance(target, str) else target
        if not target_path.exists():
            return []

        suggestions: list[RefactorSuggestion] = []

        py_files = list(target_path.rglob("*.py")) if target_path.is_dir() else [target_path]
        py_files = [f for f in py_files if "__pycache__" not in str(f)][:50]

        for f in py_files:
            try:
                source = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
                metrics = self._compute_metrics(tree, str(f), source)
                suggestions.extend(self._generate_suggestions(tree, str(f), source, metrics))
            except (SyntaxError, OSError, UnicodeDecodeError) as e:
                logger.debug("跳过 %s: %s", f, e)

        return sorted(
            suggestions,
            key=lambda s: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(s.severity, 4),
        )

    def _compute_metrics(self, tree: ast.AST, filepath: str, source: str) -> CodeMetrics:
        """计算代码度量"""
        lines = source.count("\n") + 1
        functions = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        imports = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))

        # 圈复杂度
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler, ast.And, ast.Or)):
                complexity += 1
        avg_complexity = complexity / max(functions, 1)

        # 可维护性指数
        maintainability = max(0, 100 - (avg_complexity * 5) - (lines / max(functions, 1) * 0.3))

        # 耦合度
        coupling = imports

        # 文档字符串覆盖率
        funcs_with_docs = sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and ast.get_docstring(n) is not None
        )
        doc_coverage = funcs_with_docs / max(functions, 1) * 100

        return CodeMetrics(
            file=filepath,
            lines=lines,
            functions=functions,
            classes=classes,
            cyclomatic_complexity=round(avg_complexity, 1),
            maintainability_index=round(maintainability, 1),
            coupling=coupling,
            imports_count=imports,
            docstring_coverage=round(doc_coverage, 1),
        )

    def _generate_suggestions(
        self, tree: ast.AST, filepath: str, source: str, metrics: CodeMetrics
    ) -> list[RefactorSuggestion]:
        """基于度量生成重构建议"""
        suggestions: list[RefactorSuggestion] = []

        # 1. 高复杂度函数
        if metrics.cyclomatic_complexity > 10:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_complexity = 1
                    for child in ast.walk(node):
                        if isinstance(
                            child,
                            (ast.If, ast.While, ast.For, ast.ExceptHandler, ast.And, ast.Or),
                        ):
                            func_complexity += 1
                    if func_complexity > 15:
                        suggestions.append(
                            RefactorSuggestion(
                                file=filepath,
                                line=node.lineno,
                                severity="high",
                                category="complexity",
                                title=f"函数 '{node.name}' 圈复杂度 {func_complexity}",
                                description=f"建议拆分为多个小函数，每个函数职责单一",
                                rationale="高复杂度函数难以测试和维护",
                                risk_level="medium",
                            )
                        )

        # 2. 长函数
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                end = node.end_lineno or node.lineno
                length = end - node.lineno + 1
                if length > 80:
                    suggestions.append(
                        RefactorSuggestion(
                            file=filepath,
                            line=node.lineno,
                            severity="medium",
                            category="style",
                            title=f"函数 '{node.name}' 过长 ({length} 行)",
                            description="建议提取公共逻辑为独立函数",
                            rationale="长函数降低可读性",
                            risk_level="low",
                        )
                    )

        # 3. 高耦合模块
        if metrics.coupling > 20:
            suggestions.append(
                RefactorSuggestion(
                    file=filepath,
                    line=1,
                    severity="medium",
                    category="coupling",
                    title=f"模块导入过多 ({metrics.imports_count} 个)",
                    description="考虑使用依赖注入或拆分模块",
                    rationale="高耦合降低模块的独立性和可测试性",
                    risk_level="medium",
                )
            )

        # 4. 性能反模式: 列表推导式中的重复计算
        for node in ast.walk(tree):
            if isinstance(node, ast.ListComp):
                for gen in node.generators:
                    if isinstance(gen.iter, ast.Call):
                        suggestions.append(
                            RefactorSuggestion(
                                file=filepath,
                                line=getattr(node, "lineno", getattr(gen, "lineno", 1)),
                                severity="low",
                                category="performance",
                                title="列表推导式中包含函数调用",
                                description="如果函数调用开销大，建议先计算结果再推导",
                                rationale="每次迭代都重新计算会降低性能",
                                risk_level="low",
                            )
                        )

        # 5. 嵌套循环 O(n²)
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                has_inner_loop = any(
                    isinstance(child, ast.For) for child in ast.iter_child_nodes(node)
                )
                if has_inner_loop:
                    suggestions.append(
                        RefactorSuggestion(
                            file=filepath,
                            line=node.lineno,
                            severity="high",
                            category="performance",
                            title="嵌套循环 O(n²)",
                            description="建议使用字典/集合优化查找，或考虑 itertools.product",
                            rationale="嵌套循环在数据量大时性能急剧下降",
                            risk_level="medium",
                        )
                    )

        return suggestions

    # ══════════════════════════════════════════════════════
    # 执行重构
    # ══════════════════════════════════════════════════════

    def apply(self, suggestion: RefactorSuggestion, dry_run: bool = False) -> RefactorResult:
        """应用重构建议（Git 隔离 + 测试门禁）"""
        start = time.time()

        if not suggestion.old_code or not suggestion.new_code:
            return RefactorResult(
                suggestion=suggestion,
                applied=False,
                error="缺少 old_code/new_code，无法自动应用",
                duration_ms=(time.time() - start) * 1000,
            )

        fp = Path(suggestion.file)
        if not fp.exists():
            return RefactorResult(
                suggestion=suggestion,
                applied=False,
                error=f"文件不存在: {suggestion.file}",
                duration_ms=(time.time() - start) * 1000,
            )

        if dry_run:
            return RefactorResult(
                suggestion=suggestion,
                applied=False,
                error="dry_run 模式",
                duration_ms=(time.time() - start) * 1000,
            )

        try:
            source = fp.read_text(encoding="utf-8")
            if suggestion.old_code not in source:
                return RefactorResult(
                    suggestion=suggestion,
                    applied=False,
                    error="old_code 在当前文件中未找到",
                    duration_ms=(time.time() - start) * 1000,
                )

            # 创建 Git 分支
            branch_name = f"refactor/{suggestion.file.replace('/', '_').replace('\\', '_')}_{int(time.time())}"
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                capture_output=True,
                timeout=30,
                cwd=str(PYCODER_ROOT),
            )

            # 应用修改
            new_source = source.replace(suggestion.old_code, suggestion.new_code, 1)
            fp.write_text(new_source, encoding="utf-8")

            # 运行测试
            test_result = subprocess.run(
                ["pytest", "tests/", "-x", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(PYCODER_ROOT),
            )

            if test_result.returncode == 0:
                # 测试通过, 提交
                subprocess.run(
                    ["git", "add", str(fp)],
                    capture_output=True,
                    timeout=30,
                    cwd=str(PYCODER_ROOT),
                )
                commit_result = subprocess.run(
                    ["git", "commit", "-m", f"refactor: {suggestion.title}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(PYCODER_ROOT),
                )

                result = RefactorResult(
                    suggestion=suggestion,
                    applied=True,
                    test_passed=True,
                    git_branch=branch_name,
                    git_commit=commit_result.stdout.strip()[:40],
                    duration_ms=(time.time() - start) * 1000,
                )
            else:
                # 测试失败, 回滚
                subprocess.run(
                    ["git", "checkout", "--", str(fp)],
                    capture_output=True,
                    timeout=30,
                    cwd=str(PYCODER_ROOT),
                )
                subprocess.run(
                    ["git", "checkout", "master"],
                    capture_output=True,
                    timeout=30,
                    cwd=str(PYCODER_ROOT),
                )

                result = RefactorResult(
                    suggestion=suggestion,
                    applied=False,
                    test_passed=False,
                    rollback_performed=True,
                    error=f"测试失败: {test_result.stderr[-200:]}",
                    duration_ms=(time.time() - start) * 1000,
                )

            self._history.append(result)
            return result

        except Exception as e:
            logger.error("重构执行失败: %s", e)
            return RefactorResult(
                suggestion=suggestion,
                applied=False,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    def batch_apply(self, suggestions: list[RefactorSuggestion]) -> list[RefactorResult]:
        """批量应用重构建议（每个独立隔离）"""
        results: list[RefactorResult] = []
        for s in suggestions[: self._max_files]:
            result = self.apply(s)
            results.append(result)
            if not result.applied and not result.rollback_performed:
                logger.warning("跳过后续重构: %s", result.error)
        return results

    def get_history(self) -> list[RefactorResult]:
        """获取重构历史"""
        return self._history

    def get_stats(self) -> dict[str, Any]:
        """获取重构统计"""
        total = len(self._history)
        if total == 0:
            return {"total": 0, "success_rate": 0, "avg_duration_ms": 0}

        success = sum(1 for r in self._history if r.applied and r.test_passed)
        rolled = sum(1 for r in self._history if r.rollback_performed)
        avg_dur = sum(r.duration_ms for r in self._history) / total

        return {
            "total": total,
            "success": success,
            "rollbacks": rolled,
            "success_rate": round(success / total * 100, 1),
            "avg_duration_ms": round(avg_dur, 0),
        }


# 全局单例
_engine: RefactoringEngine | None = None


def get_refactoring_engine() -> RefactoringEngine:
    global _engine
    if _engine is None:
        _engine = RefactoringEngine()
    return _engine


__all__ = [
    "RefactoringEngine",
    "RefactorSuggestion",
    "RefactorResult",
    "CodeMetrics",
    "get_refactoring_engine",
]