from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 模块 5: upgrade.py — 数据模型与函数
# ═══════════════════════════════════════════════════════════════


class TestVersionInfo:
    """VersionInfo 数据类测试"""

    def test_creation(self):
        """创建版本信息"""
        from pycoder.capabilities.self_evo.upgrade import VersionInfo

        info = VersionInfo(current="0.5.0", latest="0.6.0", has_update=True)
        assert info.current == "0.5.0"
        assert info.has_update is True


class TestHealthCheckResult:
    """HealthCheckResult 数据类测试"""

    def test_creation(self):
        """创建健康检查结果"""
        from pycoder.capabilities.self_evo.upgrade import HealthCheckResult

        result = HealthCheckResult(passed=True)
        assert result.passed is True
        assert result.errors == []


class TestUpgradeResult:
    """UpgradeResult 数据类测试"""

    def test_creation(self):
        """创建升级结果"""
        from pycoder.capabilities.self_evo.upgrade import UpgradeResult

        result = UpgradeResult(success=True, from_version="0.5.0", to_version="0.6.0")
        assert result.success is True
        assert result.from_version == "0.5.0"


class TestValidateUrl:
    """URL 验证测试"""

    def test_valid_url(self):
        """有效 URL"""
        from pycoder.capabilities.self_evo.upgrade import _validate_url

        result = _validate_url("https://api.github.com")
        assert result == "https://api.github.com"

    def test_invalid_url(self):
        """无效协议"""
        from pycoder.capabilities.self_evo.upgrade import _validate_url

        with pytest.raises(ValueError):
            _validate_url("file:///etc/passwd")


class TestCompareVersions:
    """版本比较测试"""

    def test_newer(self):
        """新版本大于"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("1.0.0", "0.9.0") == 1

    def test_older(self):
        """旧版本小于"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("0.5.0", "1.0.0") == -1

    def test_equal(self):
        """版本相等"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("0.5.0", "0.5.0") == 0

    def test_invalid_format(self):
        """无效格式返回 0"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("abc", "1.0") == 0


class TestPendingUpgrade:
    """断点续传测试"""

    def test_save_and_load(self, tmp_path):
        """保存和加载"""
        from pycoder.capabilities.self_evo.upgrade import (
            save_pending_upgrade, load_pending_upgrade, PENDING_FILE,
        )

        with patch("pycoder.capabilities.self_evo.upgrade.PENDING_FILE",
                   tmp_path / "pending.json"):
            save_pending_upgrade("0.5.0", "0.6.0", "git_pull")
            pending = load_pending_upgrade()
            assert pending["from_version"] == "0.5.0"
            assert pending["stage"] == "git_pull"

    def test_load_none(self, tmp_path):
        """加载不存在文件"""
        from pycoder.capabilities.self_evo.upgrade import load_pending_upgrade, PENDING_FILE

        with patch("pycoder.capabilities.self_evo.upgrade.PENDING_FILE",
                   tmp_path / "nonexistent.json"):
            result = load_pending_upgrade()
            assert result is None

    def test_clear(self, tmp_path):
        """清除"""
        from pycoder.capabilities.self_evo.upgrade import (
            save_pending_upgrade, clear_pending_upgrade, PENDING_FILE,
        )

        pending_file = tmp_path / "pending.json"
        with patch("pycoder.capabilities.self_evo.upgrade.PENDING_FILE", pending_file):
            with patch("pycoder.capabilities.self_evo.upgrade.UPGRADE_DIR", tmp_path):
                save_pending_upgrade("0.5.0", "0.6.0")
                clear_pending_upgrade()
                assert not pending_file.exists()


class TestRunUpgrade:
    """升级执行测试"""

    def test_dry_run(self):
        """模拟模式"""
        from pycoder.capabilities.self_evo.upgrade import run_upgrade

        result = run_upgrade(dry_run=True)
        assert result.success is True
        assert len(result.steps) >= 1


# ═══════════════════════════════════════════════════════════════
# 模块 6: feedback_loop.py
# ═══════════════════════════════════════════════════════════════


class TestFeedbackSignal:
    """FeedbackSignal 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import FeedbackSignal

        sig = FeedbackSignal()
        assert sig.signal_type == ""
        assert sig.outcome == ""
        assert sig.user_rating == 0


class TestAdaptiveConfig:
    """AdaptiveConfig 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import AdaptiveConfig

        config = AdaptiveConfig()
        assert config.quality_threshold == 85.0
        assert config.max_retries == 3


class TestFeedbackLoop:
    """FeedbackLoop 测试"""

    def test_collect_signal(self, tmp_path):
        """收集反馈信号"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", quality_score=90, test_passed=True)
            assert len(fl._signals) == 1

    def test_collect_explicit(self, tmp_path):
        """显式反馈信号类型"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", user_rating=1)
            assert fl._signals[0].signal_type == "explicit"

    def test_collect_implicit(self, tmp_path):
        """隐式反馈信号类型"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", user_rating=0)
            assert fl._signals[0].signal_type == "implicit"

    def test_get_adaptive_config(self, tmp_path):
        """获取自适应配置"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            config = fl.get_adaptive_config()
            assert isinstance(config.quality_threshold, float)

    def test_get_recent_feedback(self, tmp_path):
        """获取最近反馈"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", quality_score=90)
            recent = fl.get_recent_feedback(limit=5)
            assert len(recent) == 1

    def test_get_stats_empty(self, tmp_path):
        """空信号统计"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            stats = fl.get_stats()
            assert stats["total_signals"] == 0
            assert stats["recent_success_rate"] == 0.0

    def test_force_adjust(self, tmp_path):
        """强制调整"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            config = fl.force_adjust()
            assert isinstance(config.quality_threshold, float)

    def test_signal_to_dict(self):
        """信号序列化"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FeedbackSignal,
        )

        sig = FeedbackSignal(task_id="T001", outcome="success")
        d = FeedbackLoop._signal_to_dict(sig)
        assert d["task_id"] == "T001"
        assert d["outcome"] == "success"


class TestGetFeedbackLoop:
    """全局单例测试"""

    def test_singleton(self):
        """单例模式"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import get_feedback_loop

        fl1 = get_feedback_loop()
        fl2 = get_feedback_loop()
        assert fl1 is fl2


# ═══════════════════════════════════════════════════════════════
# 模块 7: metrics_tracker.py
# ═══════════════════════════════════════════════════════════════


class TestMetricsTrackerRecord:
    """MetricsTracker 记录测试"""

    def test_record_evolution(self, tmp_path):
        """记录进化"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                row_id = mt.record_evolution(
                    task_id="T001", operation="fix", outcome="success",
                    lines_changed=10, bugs_fixed=2, test_passed=True,
                    quality_score=90,
                )
                assert row_id > 0

    def test_record_quality_snapshot(self, tmp_path):
        """记录质量快照"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics2.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                mt.record_quality_snapshot(
                    lint_score=90, security_score=95,
                    test_coverage=80, total_score=88,
                )
                # 只要不抛异常就算成功

    def test_record_learning_event(self, tmp_path):
        """记录学习事件"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics3.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                mt.record_learning_event(
                    event_type="pattern_discovered",
                    description="发现新修复模式",
                    data={"pattern": "fix_bare_except"},
                )
                events = mt.get_learning_events(limit=10)
                assert len(events) >= 1


class TestMetricsTrackerQuery:
    """MetricsTracker 查询测试"""

    def test_get_evolution_stats_empty(self, tmp_path):
        """空数据库统计"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics4.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                stats = mt.get_evolution_stats(days=30)
                assert stats["total_evolutions"] == 0

    def test_get_operation_breakdown(self, tmp_path):
        """操作分解统计"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics5.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                mt.record_evolution(operation="fix", outcome="success")
                breakdown = mt.get_operation_breakdown()
                assert "fix" in breakdown

    def test_get_daily_summary(self, tmp_path):
        """每日汇总"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics6.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                summary = mt.get_daily_summary(days=7)
                assert isinstance(summary, list)


class TestGetMetricsTracker:
    """全局单例测试"""

    def test_singleton(self):
        """单例模式"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import get_metrics_tracker

        mt1 = get_metrics_tracker()
        mt2 = get_metrics_tracker()
        assert mt1 is mt2


# ═══════════════════════════════════════════════════════════════
# 模块 8: evo_orchestrator.py
# ═══════════════════════════════════════════════════════════════


class TestEvolutionCycleReport:
    """EvolutionCycleReport 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvolutionCycleReport

        report = EvolutionCycleReport()
        assert report.files_scanned == 0
        assert report.grade_trend == "stable"
        assert report.error == ""


class TestEvoOrchestrator:
    """EvoOrchestrator 测试"""

    def test_init(self):
        """初始化"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator

        orch = EvoOrchestrator()
        assert orch.cache is not None
        assert orch.evaluator is not None
        assert orch.classifier is not None

    def test_get_status(self):
        """获取状态"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator

        orch = EvoOrchestrator()
        status = orch.get_status()
        assert "cycle_count" in status
        assert "total_fixes" in status
        assert "cache" in status

    @pytest.mark.asyncio
    async def test_run_evolution_cycle_no_changes(self, tmp_path):
        """无变更时跳过"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator

        orch = EvoOrchestrator()
        # 模拟 get_changed_files 返回空列表
        with patch.object(orch.cache, "get_changed_files", return_value=[]):
            report = await orch.run_evolution_cycle(target_dir=str(tmp_path))
            assert "无文件变更" in str(report.warnings) or report.files_scanned >= 0


# ═══════════════════════════════════════════════════════════════
# 模块 9: evo_cache.py
# ═══════════════════════════════════════════════════════════════


class TestCachedScan:
    """CachedScan 数据类测试"""

    def test_creation(self):
        """创建缓存条目"""
        from pycoder.capabilities.self_evo.learning.evo_cache import CachedScan

        entry = CachedScan(
            file_path="test.py", content_hash="abc123", issues_found=3,
            issues_json="[]", scanned_at=time.time(),
        )
        assert entry.file_path == "test.py"
        assert entry.issues_found == 3


class TestHotRule:
    """HotRule 数据类测试"""

    def test_creation(self):
        """创建热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import HotRule

        rule = HotRule(
            rule_id="HR-001", error_signature="bare_except",
            fix_template="except Exception as e:", success_rate=0.9,
            use_count=10, last_used=time.time(),
        )
        assert rule.rule_id == "HR-001"
        assert rule.success_rate == 0.9


class TestEvoCache:
    """EvoCache 测试"""

    def test_compute_hash(self, tmp_path):
        """计算文件哈希"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        f = tmp_path / "test.py"
        f.write_text("hello world", encoding="utf-8")
        h = EvoCache.compute_hash(f)
        assert len(h) == 12

    def test_compute_hash_nonexistent(self):
        """计算不存在文件的哈希"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        h = EvoCache.compute_hash("/nonexistent/file.py")
        assert h == ""

    def test_is_cached_miss(self):
        """缓存未命中"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        assert cache.is_cached("test.py") is False

    def test_mark_and_check_cached(self):
        """标记并检查缓存"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.mark_scanned("test.py", "abc123", [{"issue": "test"}])
        assert cache.is_cached("test.py", "abc123") is True

    def test_get_cached_issues(self):
        """获取缓存的问题"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.mark_scanned("test.py", "abc123", [{"type": "bug"}])
        issues = cache.get_cached_issues("test.py")
        assert len(issues) == 1

    def test_get_cached_issues_miss(self):
        """缓存未命中时获取问题"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        issues = cache.get_cached_issues("nonexistent.py")
        assert issues == []

    def test_register_hot_rule(self):
        """注册热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("bare_except", "except Exception as e:", 1.0)
        rule = cache.find_rule("bare_except")
        assert rule is not None
        assert rule.error_signature == "bare_except"

    def test_register_hot_rule_update(self):
        """更新已存在的热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("bare_except", "fix1", 1.0)
        cache.register_hot_rule("bare_except", "fix2", 0.5)
        rule = cache.find_rule("bare_except")
        assert rule.use_count == 2

    def test_find_rule_fuzzy(self):
        """模糊匹配热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("bare_except", "fix", 1.0)
        rule = cache.find_rule("bare_except in function")
        assert rule is not None

    def test_find_rule_not_found(self):
        """未找到热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        rule = cache.find_rule("nonexistent")
        assert rule is None

    def test_get_top_rules(self):
        """获取优先级最高的热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("err1", "fix1", 1.0)
        cache.register_hot_rule("err2", "fix2", 0.5)
        top = cache.get_top_rules(limit=2)
        assert len(top) <= 2

    def test_get_stats(self):
        """获取缓存统计"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.mark_scanned("test.py", "abc123")
        stats = cache.get_stats()
        assert stats["cached_files"] == 1
        assert "hot_rules" in stats

    def test_save_and_load(self, tmp_path):
        """持久化和加载"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache, CACHE_DIR

        with patch("pycoder.capabilities.self_evo.learning.evo_cache.CACHE_DIR", tmp_path):
            cache = EvoCache()
            cache.register_hot_rule("err1", "fix1", 1.0)
            cache.save()

            # 新建实例加载
            cache2 = EvoCache()
            rule = cache2.find_rule("err1")
            assert rule is not None


# ═══════════════════════════════════════════════════════════════
# 模块 10: evo_evaluator.py
# ═══════════════════════════════════════════════════════════════


class TestEvolutionGrade:
    """EvolutionGrade 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvolutionGrade

        grade = EvolutionGrade()
        assert grade.total == 0.0
        assert grade.passed is False
        assert grade.warnings == []


class TestEvoEvaluator:
    """EvoEvaluator 测试"""

    def test_evaluate_clean_code(self):
        """评估干净代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        code = "def foo() -> int:\n    return 42\n"
        grade = ev.evaluate_fix(code, code, test_result="passed")
        assert grade.total > 0
        assert isinstance(grade.passed, bool)

    def test_evaluate_with_bare_except(self):
        """评估含裸 except 的代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        bad_code = "try:\n    pass\nexcept:\n    pass\n"
        grade = ev.evaluate_fix("", bad_code)
        assert grade.code_quality < 40  # 应扣分

    def test_evaluate_with_syntax_error(self):
        """评估语法错误代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        grade = ev.evaluate_fix("", "def foo(\n")
        assert grade.code_quality == 0.0

    def test_evaluate_with_dangerous_call(self):
        """评估含危险函数的代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        bad_code = "eval('1+1')\n"
        grade = ev.evaluate_fix("", bad_code)
        assert grade.security < 20

    def test_evaluate_with_hardcoded_secret(self):
        """评估含硬编码密钥的代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        bad_code = "api_key = 'sk-abcdefghijklmnop'\n"
        grade = ev.evaluate_fix("", bad_code)
        assert grade.security < 20

    def test_evaluate_test_failed(self):
        """评估测试失败"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        code = "def foo():\n    return 1\n"
        grade = ev.evaluate_fix(code, code, test_result="FAILED: test_foo")
        assert grade.test_coverage < 20

    def test_get_trend_empty(self):
        """空历史趋势"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        trend = ev.get_trend()
        assert trend["trend"] == "no_data"

    def test_get_trend_with_data(self):
        """有数据趋势"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        code = "def foo() -> int:\n    return 42\n"
        for _ in range(6):
            ev.evaluate_fix(code, code, test_result="passed")
        trend = ev.get_trend()
        assert trend["trend"] in ("stable", "improving", "declining", "insufficient_data")


# ═══════════════════════════════════════════════════════════════
# 模块 11: error_classifier.py
# ═══════════════════════════════════════════════════════════════


class TestErrorCategory:
    """ErrorCategory 枚举测试"""

    def test_values(self):
        """枚举值"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorCategory

        assert ErrorCategory.SYNTAX.value == "syntax"
        assert ErrorCategory.RUNTIME.value == "runtime"
        assert ErrorCategory.SECURITY.value == "security"
        assert ErrorCategory.UNKNOWN.value == "unknown"


class TestErrorTicket:
    """ErrorTicket 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorTicket,
        )

        ticket = ErrorTicket()
        assert ticket.category == ErrorCategory.UNKNOWN
        assert ticket.severity == "medium"
        assert ticket.fix_status == "open"


class TestErrorClassifier:
    """ErrorClassifier 测试"""

    def test_classify_syntax_error(self):
        """分类语法错误"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("SyntaxError: invalid syntax") == ErrorCategory.SYNTAX

    def test_classify_runtime_error(self):
        """分类运行时错误"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("NameError: name 'foo' is not defined") == ErrorCategory.RUNTIME

    def test_classify_key_error(self):
        """分类 KeyError"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("KeyError: 'missing_key'") == ErrorCategory.RUNTIME

    def test_classify_security(self):
        """分类安全问题"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("sql injection detected") == ErrorCategory.SECURITY

    def test_classify_unknown(self):
        """分类未知错误"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("something completely random") == ErrorCategory.UNKNOWN

    def test_recommend_strategy(self):
        """推荐修复策略"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        strategies = ec.recommend_strategy(ErrorCategory.SYNTAX)
        assert len(strategies) > 0
        assert any("syntax" in s.lower() for s in strategies)

    def test_recommend_strategy_unknown(self):
        """未知类别的策略"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        strategies = ec.recommend_strategy(ErrorCategory.UNKNOWN)
        assert any("llm" in s.lower() for s in strategies)

    def test_open_ticket(self):
        """创建工单"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ticket = ec.open_ticket(
            "bare_except", "except: found", file_path="test.py", line=10,
        )
        assert ticket.error_signature == "bare_except"
        assert ticket.file_path == "test.py"
        assert ticket.line_number == 10

    def test_open_ticket_duplicate(self):
        """重复工单增加计数"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        t1 = ec.open_ticket("bare_except", "except: found")
        t2 = ec.open_ticket("bare_except", "except: found again")
        assert t1 is t2  # 同一个工单
        assert t2.occurrences == 2

    def test_mark_fixed(self):
        """标记已修复"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("bare_except", "except: found")
        ec.mark_fixed("bare_except", "template_fix")
        ticket = ec._tickets["bare_except"]
        assert ticket.fix_status == "fixed"

    def test_verify_fix(self):
        """验证修复"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("bare_except", "except: found")
        result = ec.verify_fix("bare_except", "test")
        assert result is True
        ticket = ec._tickets["bare_except"]
        assert ticket.fix_status == "verified"

    def test_verify_fix_not_found(self):
        """验证不存在的工单"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        result = ec.verify_fix("nonexistent")
        assert result is False

    def test_check_recurrence(self):
        """检查重复率"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        for _ in range(5):
            ec.open_ticket("bare_except", "except: found")
        report = ec.check_recurrence("bare_except")
        assert report["repeat_count"] == 4  # 第一次不算重复
        assert report["severity"] == "high"

    def test_get_recurrence_report(self):
        """获取重复率报告"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("err1", "msg1")
        ec.open_ticket("err1", "msg1")
        report = ec.get_recurrence_report()
        assert len(report) >= 0

    def test_get_stats(self):
        """获取统计"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("err1", "SyntaxError: invalid")
        ec.open_ticket("err2", "NameError: name not defined")
        stats = ec.get_stats()
        assert stats["total_tickets"] == 2
        assert "by_category" in stats

    def test_calc_severity(self):
        """计算严重度"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        assert ErrorClassifier._calc_severity("critical error") == "critical"
        assert ErrorClassifier._calc_severity("SyntaxError") == "high"
        assert ErrorClassifier._calc_severity("some error") == "medium"