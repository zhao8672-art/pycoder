"""
进化编排器 (EvoOrchestrator) — 自我进化总调度中心

集成四大优化模块为统一进化流程:
    EvoCache      → 高效缓存 + 增量扫描
    FeedbackLoop  → 多维学习 (已有)
    EvoEvaluator  → 进化效果评估
    ErrorClassifier → 错误分类闭环

与现有 SelfEvolutionEngine 的关系:
    不替换 engine.py，而是作为升级层包裹在它外面。
    engine.py 保持向后兼容，EvoOrchestrator 提供新的高性能入口。

进化流程:
    触发(定时/事件) → EvoCache.get_changed_files() → 增量扫描
        → AST/LLM 分析 → ErrorClassifier.classify() → 分类
        → EvoCache.find_rule() → 热规则优先修复
        → engine.generate_fix() → LLM 深度修复 (仅复杂问题)
        → engine.apply_fix() → 安全应用
        → EvoEvaluator.evaluate_fix() → 质量评分
        → ErrorClassifier.verify_fix() → 二次验证
        → EvoCache.register_hot_rule() → 规则固化

用法:
    from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator
    orch = EvoOrchestrator()
    report = await orch.run_evolution_cycle("pycoder/server")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier
from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache
from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

try:
    from pycoder.capabilities.self_evo.learning.feedback_loop import FeedbackLoop
except ImportError:
    FeedbackLoop = None  # type: ignore[assignment]

try:
    from pycoder.capabilities.self_evo.learning.pattern_extractor import PatternExtractor
except ImportError:
    PatternExtractor = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class EvolutionCycleReport:
    """一次进化周期的完整报告"""
    cycle_id: str = ""
    files_scanned: int = 0
    files_cached: int = 0
    issues_found: int = 0
    hot_rule_fixes: int = 0        # 热规则命中
    llm_fixes: int = 0              # LLM 深度修复
    fixes_applied: int = 0
    fixes_verified: int = 0
    quality_scores: list[float] = field(default_factory=list)
    grade_trend: str = "stable"     # improving / stable / declining
    duration_ms: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    tickets_created: int = 0
    tickets_closed: int = 0


class EvoOrchestrator:
    """进化编排器 — 自我进化总调度中心"""

    def __init__(self, engine: Any = None):
        self.engine = engine  # 可选注入现有 SelfEvolutionEngine
        self.cache = EvoCache()
        self.evaluator = EvoEvaluator()
        self.classifier = ErrorClassifier()
        self.feedback = FeedbackLoop() if FeedbackLoop else None
        self.patterns = PatternExtractor() if PatternExtractor else None
        self._cycle_count: int = 0
        self._total_fixes: int = 0
        self._total_latency_ms: int = 0

    # ══════════════════════════════════════════════════════
    # 主进化周期
    # ══════════════════════════════════════════════════════

    async def run_evolution_cycle(
        self,
        target_dir: str = "pycoder",
        max_fixes: int = 5,
        use_llm: bool = True,
    ) -> EvolutionCycleReport:
        """运行一次完整的进化周期

        Returns:
            包含所有统计数据的报告
        """
        t0 = time.perf_counter()
        cycle_id = f"EVO-{int(time.time())}-{self._cycle_count + 1:03d}"
        report = EvolutionCycleReport(cycle_id=cycle_id)

        try:
            # ── 阶段 1: 增量扫描（缓存命中则跳过）──
            changed_files = self.cache.get_changed_files(target_dir)
            cached_count = 0
            all_files = len(list(__import__('pathlib').Path(target_dir).rglob("*.py")))

            if hasattr(self.cache, '_scans'):
                cached_count = len(self.cache._scans)

            if not changed_files:
                report.files_scanned = all_files
                report.files_cached = all_files
                report.duration_ms = (time.perf_counter() - t0) * 1000
                report.warnings.append("无文件变更，跳过扫描")
                return report

            report.files_scanned = len(changed_files)
            report.files_cached = cached_count - len(changed_files)

            # ── 阶段 2: AST 分析（复用 engine 或内建）──
            issues = await self._scan_batch(changed_files, use_llm)
            report.issues_found = len(issues)

            if not issues:
                report.duration_ms = (time.perf_counter() - t0) * 1000
                return report

            # ── 阶段 3: 错误分类 + 热规则优先修复 ──
            for issue in issues[:max_fixes * 2]:
                ticket = self.classifier.open_ticket(
                    error_signature=issue.get("title", "")[:200],
                    error_message=issue.get("description", ""),
                    file_path=issue.get("file", ""),
                    line=issue.get("line", 0),
                )
                report.tickets_created += 1

                # 热规则优先
                hot_rule = self.cache.find_rule(ticket.error_signature)
                if hot_rule and hot_rule.success_rate >= 0.8:
                    report.hot_rule_fixes += 1
                    self.cache.register_hot_rule(
                        ticket.error_signature, hot_rule.fix_template, hot_rule.success_rate,
                    )
                    self.classifier.mark_fixed(ticket.error_signature, "hot_rule")

            # ── 阶段 4: LLM 深度修复（仅复杂问题）──
            complex_issues = [
                i for i in issues
                if i.get("severity") in ("critical", "high")
                and not self.cache.find_rule(i.get("title", ""))
            ][:max_fixes]

            if complex_issues and use_llm and self.engine:
                for issue in complex_issues:
                    try:
                        original = self._read_file(issue["file"])
                        fix_proposal = await self.engine.generate_fix(
                            self._to_code_issue(issue)
                        )
                        result = await self.engine.apply_fix(fix_proposal)
                        if result and result.success:
                            report.llm_fixes += 1
                            report.fixes_applied += 1

                            # 修复质量评估
                            modified = self._read_file(issue["file"])
                            grade = self.evaluator.evaluate_fix(
                                original, modified or "",
                                result.test_result or "",
                            )
                            report.quality_scores.append(grade.total)

                            # 二次验证
                            if grade.passed and result.test_passed:
                                self.classifier.verify_fix(
                                    issue.get("title", ""), "test",
                                )
                                report.fixes_verified += 1
                                report.tickets_closed += 1

                            # 规则固化
                            self.cache.register_hot_rule(
                                issue.get("title", ""),
                                fix_proposal.new_code[:500],
                                success_rate=1.0 if grade.passed else 0.5,
                            )
                    except Exception as e:
                        logger.warning("llm_fix_failed: %s", e)
                        report.warnings.append(f"修复失败: {str(e)[:100]}")

            # ── 阶段 5: 趋势分析 ──
            trend_data = self.evaluator.get_trend()
            report.grade_trend = str(trend_data.get("trend", "stable"))

            # ── 持久化 ──
            self.cache.save()

        except Exception as e:
            report.error = str(e)[:500]
            logger.error("evolution_cycle_failed: %s", e)

        report.duration_ms = (time.perf_counter() - t0) * 1000
        self._cycle_count += 1
        self._total_fixes += report.fixes_applied
        self._total_latency_ms += int(report.duration_ms)

        return report

    # ══════════════════════════════════════════════════════
    # 扫描辅助
    # ══════════════════════════════════════════════════════

    async def _scan_batch(self, files: list[str], use_llm: bool) -> list[dict]:
        """批量扫描文件，优先使用缓存"""
        issues: list[dict] = []
        for fpath in files:
            fhash = self.cache.compute_hash(fpath)
            if not fhash:
                continue
            if self.cache.is_cached(fpath, fhash):
                cached = self.cache.get_cached_issues(fpath)
                issues.extend(cached)
                continue
            # 实际扫描（通过 engine 或 AST）
            try:
                from pathlib import Path
                source = Path(fpath).read_text(encoding="utf-8", errors="replace")
                import ast
                tree = ast.parse(source)
                file_issues = self._scan_ast(tree, fpath, source)
                issues.extend(file_issues)
                self.cache.mark_scanned(fpath, fhash, file_issues)
            except SyntaxError as e:
                issues.append({
                    "file": fpath, "line": 1, "severity": "critical",
                    "issue_type": "bug", "title": f"语法错误: {e}",
                })
            except (OSError, ValueError, AttributeError):
                pass
        return issues

    @staticmethod
    def _scan_ast(tree, fpath: str, source: str) -> list[dict]:
        """AST 静态扫描"""
        import ast
        issues: list[dict] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append({
                    "file": fpath, "line": node.lineno, "severity": "high",
                    "issue_type": "bug", "title": "裸 except 吞掉所有异常",
                })
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec"):
                    issues.append({
                        "file": fpath, "line": node.lineno, "severity": "critical",
                        "issue_type": "security",
                        "title": f"使用了危险函数 '{node.func.id}'",
                    })
        return issues

    @staticmethod
    def _read_file(file_path: str) -> str:
        try:
            from pathlib import Path
            return Path(file_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return ""

    @staticmethod
    def _to_code_issue(issue: dict) -> Any:
        """将 dict 转换为 CodeIssue"""
        try:
            from pycoder.capabilities.self_evo.engine import CodeIssue
            return CodeIssue(
                file=issue.get("file", ""),
                line=issue.get("line", 0),
                severity=issue.get("severity", "medium"),
                issue_type=issue.get("issue_type", "bug"),
                title=issue.get("title", ""),
                description=issue.get("description", ""),
            )
        except ImportError:
            return None

    # ══════════════════════════════════════════════════════
    # 状态查询
    # ══════════════════════════════════════════════════════

    def get_status(self) -> dict:
        """获取进化编排器的完整状态"""
        return {
            "cycle_count": self._cycle_count,
            "total_fixes": self._total_fixes,
            "avg_latency_ms": (
                self._total_latency_ms // max(self._cycle_count, 1)
            ),
            "cache": self.cache.get_stats(),
            "evaluator_trend": self.evaluator.get_trend(),
            "classifier": self.classifier.get_stats(),
            "recurrence": self.classifier.get_recurrence_report()[:5],
        }
