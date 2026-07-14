"""
进化效果评估器 (EvolutionEvaluator) — Phase 3

职责:
    1. 对每次进化操作进行多维质量评分
    2. 跟踪质量趋势（日/周/月）
    3. 生成可读的评估报告
    4. 自评进化策略是否有效

评分维度:
    - 代码质量 (0-40): 语法/规范/复杂度
    - 性能影响 (0-20): 函数级耗时变化
    - 安全合规 (0-20): 无硬编码/注入风险
    - 测试覆盖 (0-20): 变更行是否有测试

用法:
    from .evo_evaluator import EvoEvaluator
    ev = EvoEvaluator()
    score = ev.evaluate_fix(fix_result, original_code, modified_code)
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass, field


@dataclass
class EvolutionGrade:
    """进化评分"""
    total: float = 0.0           # 总分 0-100
    code_quality: float = 0.0    # 代码质量 0-40
    performance: float = 0.0     # 性能 0-20
    security: float = 0.0        # 安全 0-20
    test_coverage: float = 0.0   # 测试覆盖 0-20
    passed: bool = False         # 是否通过 (≥80分)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    graded_at: float = 0.0


class EvoEvaluator:
    """进化效果自主评估器"""

    def __init__(self, pass_threshold: float = 80.0):
        self._pass_threshold = pass_threshold
        self._history: list[EvolutionGrade] = []

    # ══════════════════════════════════════════════════════
    # 多维评分
    # ══════════════════════════════════════════════════════

    def evaluate_fix(
        self,
        original_code: str,
        modified_code: str,
        test_result: str = "",
        lint_output: str = "",
    ) -> EvolutionGrade:
        """对一次修复进行多维评分"""
        warnings: list[str] = []
        suggestions: list[str] = []

        # 1. 代码质量评分 (0-40)
        code_quality = self._score_code_quality(modified_code, warnings, suggestions)

        # 2. 性能影响评分 (0-20)
        performance = self._score_performance(original_code, modified_code, warnings)

        # 3. 安全合规评分 (0-20)
        security = self._score_security(modified_code, warnings, suggestions)

        # 4. 测试覆盖评分 (0-20)
        test_coverage = self._score_test_coverage(test_result, modified_code, suggestions)

        total = code_quality + performance + security + test_coverage
        grade = EvolutionGrade(
            total=total,
            code_quality=code_quality,
            performance=performance,
            security=security,
            test_coverage=test_coverage,
            passed=total >= self._pass_threshold,
            warnings=warnings,
            suggestions=suggestions,
            graded_at=time.time(),
        )

        self._history.append(grade)
        if len(self._history) > 200:
            self._history = self._history[-200:]

        return grade

    # ── 代码质量评分 ──

    def _score_code_quality(self, code: str, warnings: list, suggestions: list) -> float:
        score = 40.0  # 满分

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            warnings.append(f"语法错误: {e}")
            return 0.0

        # 检测裸 except
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                score -= 8
                warnings.append("存在裸 except")
                suggestions.append("将 'except:' 改为 'except Exception as e:'")

        # 检测过长函数 (>200行)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                if length > 200:
                    score -= 5
                    suggestions.append(f"函数 '{node.name}' 过长({length}行)，建议拆分")

        # 检测缺少类型注解
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name != '__init__']
        if funcs:
            untyped = sum(1 for f in funcs if not f.returns)
            if untyped > len(funcs) * 0.5:
                score -= 5
                suggestions.append(f"大量函数缺少返回类型注解 ({untyped}/{len(funcs)})")

        return max(score, 0)

    # ── 性能影响评分 ──

    def _score_performance(self, old_code: str, new_code: str, warnings: list) -> float:
        score = 20.0

        # 检测是否引入了循环嵌套增加
        old_loops = len(re.findall(r'\b(for|while)\b', old_code))
        new_loops = len(re.findall(r'\b(for|while)\b', new_code))
        if new_loops > old_loops + 3:
            score -= 5
            warnings.append("可能引入了额外循环，请验证性能")

        # 检测是否在循环内使用了 .append() (通常可优化为推导式)
        if re.search(r'for\b.*\n\s+\.append\(', new_code):
            score -= 3
            warnings.append("检测到循环内 .append()，建议使用列表推导式")

        return max(score, 0)

    # ── 安全评分 ──

    _DANGEROUS_CALLS = {"eval", "exec", "__import__", "compile"}
    _SECRET_PATTERNS = {
        r'(api_key|password|secret|token)\s*=\s*["\'][^"\']{8,}["\']': "硬编码密钥",
        r'os\.system\s*\([^)]*input': "用户输入直接传给 os.system",
    }

    def _score_security(self, code: str, warnings: list, suggestions: list) -> float:
        score = 20.0

        # 危险函数
        for call in self._DANGEROUS_CALLS:
            if re.search(rf'\b{call}\s*\(', code):
                score -= 10
                warnings.append(f"使用了危险函数: {call}")
                suggestions.append(f"避免使用 {call}()，寻找安全替代方案")

        # 密钥检测（排除 os.environ/os.getenv）
        for pattern, desc in self._SECRET_PATTERNS.items():
            matches = re.findall(pattern, code, re.IGNORECASE)
            if matches:
                # 排除环境变量引用
                for line in matches:
                    if 'os.environ' not in str(line) and 'os.getenv' not in str(line):
                        score -= 10
                        warnings.append(f"安全风险: {desc}")
                        suggestions.append("使用环境变量存储敏感信息: os.environ.get('KEY')")

        return max(score, 0)

    # ── 测试覆盖评分 ──

    def _score_test_coverage(
        self, test_result: str, code: str, suggestions: list,
    ) -> float:
        score = 20.0

        if "FAILED" in test_result:
            score -= 15
            suggestions.append("测试未通过，请检查并修复后重新提交")
        elif "passed" in test_result.lower() and "error" not in test_result.lower():
            score = 20.0  # 测试通过满分
        else:
            # 无测试结果 — 检测是否有对应的测试函数
            funcs = re.findall(r'def\s+(\w+)\s*\(', code)
            has_test = any(f.startswith('test_') for f in funcs)
            if not has_test and funcs:
                score -= 10
                suggestions.append(f"变更的函数缺少对应的测试: {', '.join(funcs[:3])}")

        return max(score, 0)

    # ══════════════════════════════════════════════════════
    # 趋势分析
    # ══════════════════════════════════════════════════════

    def get_trend(self, window: int = 20) -> dict:
        """获取最近 N 次进化的质量趋势"""
        recent = self._history[-window:]
        if not recent:
            return {"trend": "no_data", "avg_score": 0, "scores": []}

        scores = [g.total for g in recent]
        avg = sum(scores) / len(scores)
        passed = sum(1 for g in recent if g.passed)

        # 趋势: 上升/下降/平稳
        if len(scores) >= 5:
            first_half = sum(scores[:len(scores) // 2]) / max(len(scores) // 2, 1)
            second_half = sum(scores[len(scores) // 2:]) / max(len(scores) - len(scores) // 2, 1)
            if second_half > first_half + 3:
                trend = "improving"
            elif second_half < first_half - 3:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "trend": trend,
            "avg_score": round(avg, 1),
            "pass_rate": round(passed / len(recent), 2) if recent else 0,
            "scores": scores,
            "warnings": [w for g in recent for w in g.warnings],
        }
