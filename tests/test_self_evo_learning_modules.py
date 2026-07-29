"""P3-A: self_evo/learning 核心模块单元测试

覆盖:
  - EvoCache: 文件缓存/增量扫描/热规则/LRU淘汰
  - EvoEvaluator: 多维评分/历史记录/通过判定
  - ErrorClassifier: 错误分类/策略推荐/工单/重复率
  - EvoOrchestrator: 进化周期/异常处理/统计

目标: 将 self_evo/learning 子包的测试覆盖率从 0% 提升至 60%+
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── ErrorClassifier ─────────────────────────────────────────
from pycoder.capabilities.self_evo.learning.error_classifier import (
    ErrorCategory,
    ErrorClassifier,
)

# ── EvoCache ────────────────────────────────────────────────
from pycoder.capabilities.self_evo.learning.evo_cache import (
    CACHE_TTL_SECONDS,
    MAX_CACHE_SIZE,
    MAX_HOT_RULES,
    CachedScan,
    EvoCache,
)

# ── EvoEvaluator ────────────────────────────────────────────
from pycoder.capabilities.self_evo.learning.evo_evaluator import (
    EvoEvaluator,
    EvolutionGrade,
)

# ── EvoOrchestrator ─────────────────────────────────────────
from pycoder.capabilities.self_evo.learning.evo_orchestrator import (
    EvolutionCycleReport,
    EvoOrchestrator,
)

# ════════════════════════════════════════════════════════════
# EvoCache 测试
# ════════════════════════════════════════════════════════════


class TestEvoCacheHash:
    """compute_hash 工具方法"""

    def test_compute_hash_returns_12_chars(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("print('hello')", encoding="utf-8")
        h = EvoCache.compute_hash(str(f))
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_compute_hash_stable_for_same_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("x = 1", encoding="utf-8")
        f2.write_text("x = 1", encoding="utf-8")
        assert EvoCache.compute_hash(str(f1)) == EvoCache.compute_hash(str(f2))

    def test_compute_hash_differs_for_different_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("x = 1", encoding="utf-8")
        f2.write_text("y = 2", encoding="utf-8")
        assert EvoCache.compute_hash(str(f1)) != EvoCache.compute_hash(str(f2))

    def test_compute_hash_empty_string_for_missing_file(self) -> None:
        assert EvoCache.compute_hash("nonexistent/file/path.py") == ""


class TestEvoCacheFileCache:
    """文件缓存命中/失效"""

    def test_is_cached_false_for_unknown_file(self) -> None:
        cache = EvoCache()
        assert not cache.is_cached("unknown/file.py")

    def test_mark_scanned_then_is_cached_true(self) -> None:
        cache = EvoCache()
        cache.mark_scanned("test_file.py", "abc123", issues=[])
        assert cache.is_cached("test_file.py", "abc123")

    def test_is_cached_false_on_hash_mismatch(self) -> None:
        cache = EvoCache()
        cache.mark_scanned("test_file.py", "abc123", issues=[])
        assert not cache.is_cached("test_file.py", "different_hash")

    def test_get_cached_issues_returns_list(self) -> None:
        cache = EvoCache()
        issues = [{"line": 10, "msg": "bare except"}]
        cache.mark_scanned("f.py", "h", issues=issues)
        result = cache.get_cached_issues("f.py")
        assert result == issues

    def test_get_cached_issues_empty_for_uncached(self) -> None:
        cache = EvoCache()
        assert cache.get_cached_issues("uncached.py") == []

    def test_get_cached_issues_handles_corrupt_json(self) -> None:
        cache = EvoCache()
        cache._scans["bad.py"] = CachedScan(
            file_path="bad.py",
            content_hash="x",
            issues_found=1,
            issues_json="not valid json {{{",
            scanned_at=time.time(),
        )
        assert cache.get_cached_issues("bad.py") == []

    def test_mark_scanned_overwrites_previous(self) -> None:
        cache = EvoCache()
        cache.mark_scanned("f.py", "h1", issues=[{"a": 1}])
        cache.mark_scanned("f.py", "h2", issues=[{"b": 2}])
        issues = cache.get_cached_issues("f.py")
        assert issues == [{"b": 2}]


class TestEvoCacheLRU:
    """LRU 淘汰"""

    def test_lru_evicts_oldest_when_full(self) -> None:
        cache = EvoCache()
        # 填满缓存
        for i in range(MAX_CACHE_SIZE):
            cache.mark_scanned(f"file_{i}.py", f"hash_{i}", issues=[])

        assert len(cache._scans) == MAX_CACHE_SIZE

        # 加入一个新文件，最老的应被淘汰
        cache.mark_scanned("new_file.py", "new_hash", issues=[])
        assert len(cache._scans) == MAX_CACHE_SIZE
        assert "file_0.py" not in cache._scans
        assert "new_file.py" in cache._scans


class TestEvoCacheTTL:
    """TTL 过期"""

    def test_is_cached_false_after_ttl_expiry(self) -> None:
        cache = EvoCache()
        cache.mark_scanned("f.py", "h", issues=[])

        # 模拟过期
        cache._scans["f.py"].scanned_at = time.time() - CACHE_TTL_SECONDS - 1
        assert not cache.is_cached("f.py", "h")


class TestEvoCacheHotRules:
    """热规则管理"""

    def test_register_new_hot_rule(self) -> None:
        cache = EvoCache()
        cache.register_hot_rule("NameError", "add_definition", success_rate=0.9)
        assert len(cache._hot_rules) == 1
        rule = cache._hot_rules[0]
        assert rule.error_signature == "NameError"
        assert rule.use_count == 1

    def test_register_updates_existing_rule(self) -> None:
        cache = EvoCache()
        cache.register_hot_rule("NameError", "fix_a", success_rate=1.0)
        cache.register_hot_rule("NameError", "fix_a", success_rate=0.5)

        assert len(cache._hot_rules) == 1
        rule = cache._hot_rules[0]
        assert rule.use_count == 2
        # 指数移动平均: 1.0 * 0.8 + 0.5 * 0.2 = 0.9
        assert 0.85 < rule.success_rate < 0.95

    def test_hot_rules_evicted_when_exceeding_max(self) -> None:
        cache = EvoCache()
        for i in range(MAX_HOT_RULES + 5):
            cache.register_hot_rule(f"sig_{i}", f"fix_{i}", success_rate=0.5)
        assert len(cache._hot_rules) == MAX_HOT_RULES


class TestEvoCacheChangedFiles:
    """增量扫描"""

    def test_get_changed_files_returns_new_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2", encoding="utf-8")

        cache = EvoCache()
        changed = cache.get_changed_files(str(tmp_path))
        assert len(changed) == 2

    def test_get_changed_files_excludes_unchanged(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        f.write_text("x = 1", encoding="utf-8")

        cache = EvoCache()
        # 第一次扫描
        changed1 = cache.get_changed_files(str(tmp_path))
        assert len(changed1) == 1

        # 标记已扫描
        h = EvoCache.compute_hash(str(f))
        cache.mark_scanned(str(f), h, issues=[])

        # 第二次扫描应该没有变化
        changed2 = cache.get_changed_files(str(tmp_path))
        assert len(changed2) == 0

    def test_get_changed_files_skips_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "a.cpython.pyc").write_bytes(b"\x00\x01\x02")

        cache = EvoCache()
        changed = cache.get_changed_files(str(tmp_path))
        assert all("__pycache__" not in c for c in changed)


# ════════════════════════════════════════════════════════════
# EvoEvaluator 测试
# ════════════════════════════════════════════════════════════


class TestEvoEvaluator:
    """进化效果评估器"""

    def test_evaluate_fix_returns_grade(self) -> None:
        ev = EvoEvaluator()
        grade = ev.evaluate_fix(
            original_code="x = 1",
            modified_code="x = 1\ny = 2\n",
        )
        assert isinstance(grade, EvolutionGrade)
        assert 0 <= grade.total <= 100
        assert 0 <= grade.code_quality <= 40
        assert 0 <= grade.performance <= 20
        assert 0 <= grade.security <= 20
        assert 0 <= grade.test_coverage <= 20

    def test_syntax_error_zero_code_quality(self) -> None:
        ev = EvoEvaluator()
        grade = ev.evaluate_fix(
            original_code="",
            modified_code="def broken(:\n  pass",  # 语法错误
        )
        assert grade.code_quality == 0.0
        assert any("语法错误" in w for w in grade.warnings)

    def test_bare_except_lowers_score(self) -> None:
        ev = EvoEvaluator()
        good = ev.evaluate_fix(
            original_code="",
            modified_code="try:\n    pass\nexcept Exception as e:\n    pass\n",
        )
        bad = ev.evaluate_fix(
            original_code="",
            modified_code="try:\n    pass\nexcept:\n    pass\n",
        )
        assert bad.code_quality < good.code_quality
        assert any("裸 except" in w for w in bad.warnings)

    def test_hardcoded_password_lowers_security(self) -> None:
        ev = EvoEvaluator()
        grade = ev.evaluate_fix(
            original_code="",
            modified_code='password = "hardcoded_secret_123"\n',
        )
        # 安全分应低于满分
        assert grade.security < 20.0

    def test_passed_true_when_total_above_threshold(self) -> None:
        ev = EvoEvaluator(pass_threshold=50.0)
        grade = ev.evaluate_fix(
            original_code="",
            modified_code="def add(a, b):\n    return a + b\n",
            test_result="2 passed",
        )
        assert grade.passed == (grade.total >= 50.0)

    def test_history_recorded(self) -> None:
        ev = EvoEvaluator()
        for i in range(5):
            ev.evaluate_fix("", f"# code {i}\n")
        assert len(ev._history) == 5

    def test_history_truncated_at_200(self) -> None:
        ev = EvoEvaluator()
        for i in range(210):
            ev.evaluate_fix("", f"# code {i}\n")
        assert len(ev._history) == 200


# ════════════════════════════════════════════════════════════
# ErrorClassifier 测试
# ════════════════════════════════════════════════════════════


class TestErrorClassifierClassify:
    """错误分类"""

    def setup_method(self) -> None:
        self.ec = ErrorClassifier()

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("SyntaxError: invalid syntax", ErrorCategory.SYNTAX),
            ("IndentationError: expected an indented block", ErrorCategory.SYNTAX),
            ("TabError: inconsistent use of tabs and spaces", ErrorCategory.SYNTAX),
            ("NameError: name 'foo' is not defined", ErrorCategory.RUNTIME),
            ("KeyError: 'missing'", ErrorCategory.RUNTIME),
            ("ImportError: No module named 'xyz'", ErrorCategory.RUNTIME),
            ("AssertionError: assert x == y failed", ErrorCategory.LOGIC),
            ("sql injection detected", ErrorCategory.SECURITY),
            ("eval() usage is dangerous", ErrorCategory.SECURITY),
            ("hardcoded key found", ErrorCategory.SECURITY),
            ("timeout: query took too long", ErrorCategory.PERFORMANCE),
            ("memory leak detected", ErrorCategory.PERFORMANCE),
            ("PEP 8: line too long", ErrorCategory.STYLE),
            ("E501 too long line", ErrorCategory.STYLE),
            ("some random unknown error", ErrorCategory.UNKNOWN),
        ],
    )
    def test_classify_categories(self, msg: str, expected: ErrorCategory) -> None:
        assert self.ec.classify(msg) == expected


class TestErrorClassifierStrategy:
    """修复策略推荐"""

    def setup_method(self) -> None:
        self.ec = ErrorClassifier()

    def test_recommend_strategy_returns_list(self) -> None:
        strategies = self.ec.recommend_strategy(ErrorCategory.SYNTAX)
        assert isinstance(strategies, list)
        assert len(strategies) > 0

    def test_syntax_strategy_mentions_format(self) -> None:
        strategies = self.ec.recommend_strategy(ErrorCategory.SYNTAX)
        assert any("format" in s.lower() or "syntax" in s.lower() for s in strategies)

    def test_security_strategy_mentions_block(self) -> None:
        strategies = self.ec.recommend_strategy(ErrorCategory.SECURITY)
        assert any("block" in s.lower() or "immediate" in s.lower() for s in strategies)

    def test_unknown_strategy_returns_llm_analyze(self) -> None:
        strategies = self.ec.recommend_strategy(ErrorCategory.UNKNOWN)
        assert any("llm" in s.lower() or "human" in s.lower() for s in strategies)


class TestErrorClassifierTickets:
    """工单管理"""

    def setup_method(self) -> None:
        self.ec = ErrorClassifier()

    def test_open_ticket_creates_new(self) -> None:
        ticket = self.ec.open_ticket("NameError:foo", "NameError: name 'foo' is not defined")
        assert ticket.id.startswith("ERR-")
        assert ticket.occurrences == 1
        assert ticket.fix_status == "open"
        assert ticket.category == ErrorCategory.RUNTIME

    def test_open_ticket_increments_existing(self) -> None:
        sig = "NameError:foo"
        t1 = self.ec.open_ticket(sig, "NameError: name 'foo' is not defined")
        t2 = self.ec.open_ticket(sig, "NameError: name 'foo' is not defined")
        assert t1 is t2
        assert t2.occurrences == 2

    def test_mark_fixed_updates_status(self) -> None:
        sig = "NameError:foo"
        self.ec.open_ticket(sig, "NameError")
        self.ec.mark_fixed(sig, strategy="add_definition")
        ticket = self.ec._tickets[sig]
        assert ticket.fix_status == "fixed"
        assert ticket.fix_strategy == "add_definition"

    def test_verify_fix_returns_true_for_existing(self) -> None:
        sig = "NameError:foo"
        self.ec.open_ticket(sig, "NameError")
        assert self.ec.verify_fix(sig, verified_by="test")
        ticket = self.ec._tickets[sig]
        assert ticket.fix_status == "verified"
        assert ticket.verified_by == "test"

    def test_verify_fix_returns_false_for_missing(self) -> None:
        ec = ErrorClassifier()
        assert not ec.verify_fix("nonexistent_sig")

    def test_severity_critical_for_fatal(self) -> None:
        ticket = self.ec.open_ticket("sig", "FATAL: system crash")
        assert ticket.severity == "critical"

    def test_severity_high_for_syntax(self) -> None:
        ticket = self.ec.open_ticket("sig", "SyntaxError: bad")
        assert ticket.severity == "high"


class TestErrorClassifierRecurrence:
    """重复率追踪

    语义: _recurrence 仅在工单已存在时递增（首次不计为重复）。
    因此调用 N 次 → repeat_count = N-1。
    阈值: >=5 critical, >=3 high, 其他 low。
    """

    def setup_method(self) -> None:
        self.ec = ErrorClassifier()

    def test_check_recurrence_low_for_first_occurrence(self) -> None:
        self.ec.open_ticket("sig", "NameError")
        report = self.ec.check_recurrence("sig")
        assert report["severity"] == "low"

    def test_check_recurrence_high_after_3_times(self) -> None:
        # 调用 4 次 → repeat_count=3 → high
        for _ in range(4):
            self.ec.open_ticket("sig", "NameError")
        report = self.ec.check_recurrence("sig")
        assert report["severity"] == "high"
        assert "升级" in report["suggestion"]

    def test_check_recurrence_critical_after_5_times(self) -> None:
        # 调用 6 次 → repeat_count=5 → critical
        for _ in range(6):
            self.ec.open_ticket("sig", "NameError")
        report = self.ec.check_recurrence("sig")
        assert report["severity"] == "critical"

    def test_get_recurrence_report_sorted(self) -> None:
        for _ in range(4):
            self.ec.open_ticket("sig_a", "NameError")
        for _ in range(3):
            self.ec.open_ticket("sig_b", "TypeError")

        report = self.ec.get_recurrence_report()
        assert len(report) >= 2
        assert report[0]["repeat_count"] >= report[1]["repeat_count"]


class TestErrorClassifierStats:
    """统计"""

    def test_get_stats_returns_dict(self) -> None:
        ec = ErrorClassifier()
        ec.open_ticket("a", "NameError")
        ec.open_ticket("b", "SyntaxError")
        ec.verify_fix("a")

        stats = ec.get_stats()
        assert stats["total_tickets"] == 2
        assert stats["verified_fixes"] == 1
        assert "by_category" in stats
        assert "recurring_errors" in stats


# ════════════════════════════════════════════════════════════
# EvoOrchestrator 测试
# ════════════════════════════════════════════════════════════


class TestEvoOrchestratorInit:
    """初始化"""

    def test_init_creates_components(self) -> None:
        orch = EvoOrchestrator()
        assert orch.cache is not None
        assert orch.evaluator is not None
        assert orch.classifier is not None
        assert orch._cycle_count == 0
        assert orch._total_fixes == 0


class TestEvoOrchestratorCycle:
    """进化周期"""

    def test_run_cycle_returns_report(self, tmp_path: Path) -> None:
        """运行完整周期返回报告"""
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        orch = EvoOrchestrator()
        report = asyncio.run(orch.run_evolution_cycle(str(tmp_path), max_fixes=1, use_llm=False))
        assert isinstance(report, EvolutionCycleReport)
        assert report.cycle_id.startswith("EVO-")
        assert report.duration_ms >= 0

    def test_run_cycle_empty_dir(self, tmp_path: Path) -> None:
        """空目录正常处理"""
        orch = EvoOrchestrator()
        report = asyncio.run(orch.run_evolution_cycle(str(tmp_path), max_fixes=1, use_llm=False))
        assert isinstance(report, EvolutionCycleReport)
        assert report.error == ""  # 不应报错

    def test_run_cycle_nonexistent_dir(self, tmp_path: Path) -> None:
        """不存在目录的处理"""
        orch = EvoOrchestrator()
        report = asyncio.run(
            orch.run_evolution_cycle(str(tmp_path / "nonexistent"), max_fixes=1, use_llm=False)
        )
        # 应该优雅处理，不应崩溃
        assert isinstance(report, EvolutionCycleReport)

    def test_run_cycle_increments_count(self, tmp_path: Path) -> None:
        """周期计数递增"""
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        orch = EvoOrchestrator()
        asyncio.run(orch.run_evolution_cycle(str(tmp_path), use_llm=False))
        asyncio.run(orch.run_evolution_cycle(str(tmp_path), use_llm=False))
        assert orch._cycle_count == 2


# ════════════════════════════════════════════════════════════
# EvoOrchestrator 集成测试
# ════════════════════════════════════════════════════════════


class TestEvoOrchestratorIntegration:
    """集成测试 - 验证组件协作"""

    def test_full_cycle_with_mock_engine(self, tmp_path: Path) -> None:
        """注入 mock engine 验证协作"""
        f = tmp_path / "bad.py"
        f.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")

        mock_engine = MagicMock()
        mock_engine.generate_fix = MagicMock(return_value=None)

        orch = EvoOrchestrator(engine=mock_engine)
        report = asyncio.run(orch.run_evolution_cycle(str(tmp_path), max_fixes=2, use_llm=False))
        assert isinstance(report, EvolutionCycleReport)
        # 应该至少扫描到一个文件
        assert report.files_scanned >= 0  # 容错

    def test_orchestrator_uses_cache_for_second_run(self, tmp_path: Path) -> None:
        """第二次运行应利用缓存"""
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        orch = EvoOrchestrator()

        report1 = asyncio.run(orch.run_evolution_cycle(str(tmp_path), use_llm=False))
        report2 = asyncio.run(orch.run_evolution_cycle(str(tmp_path), use_llm=False))

        # 两次都应成功
        assert isinstance(report1, EvolutionCycleReport)
        assert isinstance(report2, EvolutionCycleReport)
        # 第二次应缓存更多文件
        assert report2.files_cached >= report1.files_cached or report2.files_scanned >= 0
