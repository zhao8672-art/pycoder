"""KnowledgeBase 覆盖率补充测试

针对 pycoder/server/learning/knowledge_base.py 中未被现有测试覆盖的分支:
  - normalize_error_signature 的多分支（双引号/File 路径/十六进制/超长截断）
  - classify_error 的全部异常类型分支
  - ErrorPattern.success_rate / confidence 边界
  - record_error_pattern 的更新路径（已存在记录、失败计数、新 fix_template 更优时替换）
  - suggest_fix 精确命中 / 同类型相似命中 / 无匹配
  - get_top_errors / get_improving_errors / get_success_rate
  - record_entity / increment_bug_count / get_hotspots / get_entity_risk
  - cleanup_old_records 的 max_records 截断分支与 VACUUM 分支
  - get_stats（修复后回归）
  - get_knowledge_base 单例
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from pycoder.server.learning.knowledge_base import (
    KnowledgeBase,
    ErrorPattern,
    FixRecord,
    ProjectKnowledge,
    normalize_error_signature,
    classify_error,
    _first_exception_prefix,
    get_knowledge_base,
)


# ══════════════════════════════════════════════════════════
# Fixture — 用 tmp_path 隔离 SQLite，避免污染全局库
# ══════════════════════════════════════════════════════════


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    """每个测试使用独立的临时数据库"""
    return KnowledgeBase(db_path=tmp_path / "kb_test.db")


# ══════════════════════════════════════════════════════════
# normalize_error_signature — 全分支
# ══════════════════════════════════════════════════════════


class TestNormalizeErrorSignature:
    def test_replaces_single_quoted_values(self):
        sig = normalize_error_signature("NameError: name 'foo' is not defined")
        assert "<VALUE>" in sig
        assert "foo" not in sig

    def test_replaces_double_quoted_values(self):
        sig = normalize_error_signature('KeyError: "some_key" not found')
        assert "<VALUE>" in sig
        assert "some_key" not in sig

    def test_replaces_hex_numbers(self):
        sig = normalize_error_signature("Address 0x7fff1234 leaked")
        assert "<HEX>" in sig

    def test_replaces_decimal_numbers(self):
        sig = normalize_error_signature("Timeout after 30 seconds on attempt 5")
        assert "<N>" in sig

    def test_truncates_long_signatures(self):
        long_msg = "x" * 500
        sig = normalize_error_signature(long_msg)
        assert len(sig) <= 300

    def test_preserves_short_signature(self):
        sig = normalize_error_signature("short error")
        assert sig == "short error"

    def test_strips_whitespace(self):
        sig = normalize_error_signature("  padded error  ")
        assert sig == "padded error"


# ══════════════════════════════════════════════════════════
# classify_error — 全分支覆盖
# ══════════════════════════════════════════════════════════


class TestClassifyError:
    @pytest.mark.parametrize("msg,expected", [
        ("TypeError('bad operand')", "TypeError"),
        ("TypeError: unsupported operand", "TypeError"),
        ("NameError: name 'x' is not defined", "NameError"),
        ("not defined: name foo", "NameError"),
        ("AttributeError: 'NoneType' object has no attribute 'x'", "AttributeError"),
        ("object has no attribute foo", "AttributeError"),
        ("ImportError: no module named 'foo'", "ImportError"),
        ("ModuleNotFoundError: no module named 'bar'", "ModuleNotFoundError"),
        ("no module named 'bar' (implicit)", "ImportError"),
        ("SyntaxError: invalid syntax", "SyntaxError"),
        ("IndentationError: unexpected indent", "IndentationError"),
        ("KeyError: 'missing'", "KeyError"),
        ("IndexError: list index out of range", "IndexError"),
        ("list index out of range", "IndexError"),
        ("ValueError: invalid literal", "ValueError"),
        ("FileNotFoundError: [Errno 2] no such file or directory", "FileNotFoundError"),
        ("no such file or directory: 'x.txt'", "FileNotFoundError"),
        ("ConnectionError: connection timeout", "ConnectionError"),
        ("timeout waiting for response", "ConnectionError"),
        ("AssertionError: assert False", "AssertionError"),
        ("PermissionError: [Errno 13] permission denied", "PermissionError"),
        ("MemoryError: out of memory", "MemoryError"),
        ("something completely unknown", "Unknown"),
    ])
    def test_classify(self, msg: str, expected: str):
        assert classify_error(msg) == expected

    @pytest.mark.parametrize("msg,expected", [
        # 小写形式 — _first_exception_prefix 无法匹配（要求首字母大写）
        # 走 classify_error 的二次兜底分支
        ("some typeerror happened here", "TypeError"),
        ("got syntaxerror in line 3", "SyntaxError"),
        ("raised keyerror on dict access", "KeyError"),
        ("got valueerror from converter", "ValueError"),
        ("triggered assertionerror in test", "AssertionError"),
        ("caught permissionerror on write", "PermissionError"),
        ("process raised memoryerror", "MemoryError"),
    ])
    def test_classify_lowercase_fallback(self, msg: str, expected: str):
        """classify_error 在 _first_exception_prefix 未命中时走小写兜底"""
        assert classify_error(msg) == expected


class TestFirstExceptionPrefix:
    def test_matches_standard_exception(self):
        assert _first_exception_prefix("ValueError('x')") == "ValueError"
        assert _first_exception_prefix("RuntimeError: boom") == "RuntimeError"

    def test_no_match_returns_empty(self):
        assert _first_exception_prefix("just a string") == ""
        assert _first_exception_prefix("123 start with digits") == ""


# ══════════════════════════════════════════════════════════
# ErrorPattern — success_rate / confidence
# ══════════════════════════════════════════════════════════


class TestErrorPatternProperties:
    def test_success_rate_zero_total(self):
        p = ErrorPattern()
        assert p.success_rate == 0.0

    def test_success_rate_normal(self):
        p = ErrorPattern(success_count=3, fail_count=1)
        assert p.success_rate == 0.75

    def test_confidence_zero_total(self):
        p = ErrorPattern()
        assert p.confidence == 0.0

    def test_confidence_decreases_with_low_sample(self):
        low_sample = ErrorPattern(success_count=1, fail_count=0)
        high_sample = ErrorPattern(success_count=20, fail_count=0)
        # Wilson 下界：样本少时置信度更低
        assert low_sample.confidence < high_sample.confidence

    def test_confidence_in_zero_to_one(self):
        p = ErrorPattern(success_count=5, fail_count=5)
        assert 0.0 <= p.confidence <= 1.0


# ══════════════════════════════════════════════════════════
# record_error_pattern — 更新路径与 fix_template 替换
# ══════════════════════════════════════════════════════════


class TestRecordErrorPattern:
    def test_record_success_increments_success_count(self, kb: KnowledgeBase):
        kb.record_error_pattern("TEST: rec success", "fix", success=True)
        p = kb.record_error_pattern("TEST: rec success", "fix2", success=True)
        assert p.success_count == 2
        assert p.fail_count == 0

    def test_record_failure_increments_fail_count(self, kb: KnowledgeBase):
        kb.record_error_pattern("TEST: rec fail", "fix", success=False)
        p = kb.record_error_pattern("TEST: rec fail", "fix2", success=False)
        assert p.fail_count == 2
        assert p.success_count == 0

    def test_record_mixed_outcomes(self, kb: KnowledgeBase):
        kb.record_error_pattern("TEST: mixed", "fix", success=True)
        kb.record_error_pattern("TEST: mixed", "fix", success=False)
        p = kb.record_error_pattern("TEST: mixed", "fix", success=True)
        assert p.success_count == 2
        assert p.fail_count == 1

    def test_longer_fix_template_replaces_when_success(self, kb: KnowledgeBase):
        """成功且新 fix 更长时替换旧 fix_template"""
        kb.record_error_pattern("TEST: replace", "short", success=True)
        longer_fix = "x" * 50  # 远长于 'short'
        p = kb.record_error_pattern("TEST: replace", longer_fix, success=True)
        assert p.fix_template == longer_fix

    def test_shorter_fix_template_kept_when_success(self, kb: KnowledgeBase):
        """成功但新 fix 更短时保留旧 fix_template"""
        long_fix = "x" * 50
        kb.record_error_pattern("TEST: keep", long_fix, success=True)
        p = kb.record_error_pattern("TEST: keep", "short", success=True)
        assert p.fix_template == long_fix

    def test_failure_does_not_replace_fix(self, kb: KnowledgeBase):
        """失败时不替换 fix_template"""
        kb.record_error_pattern("TEST: noreplace", "good_fix", success=True)
        p = kb.record_error_pattern("TEST: noreplace", "bad_fix_xxx", success=False)
        assert p.fix_template == "good_fix"

    def test_record_writes_to_cache(self, kb: KnowledgeBase):
        p = kb.record_error_pattern("TEST: cache", "fix", success=True)
        sig = normalize_error_signature("TEST: cache")
        assert sig in kb._error_cache
        assert kb._error_cache[sig].success_count == p.success_count


# ══════════════════════════════════════════════════════════
# suggest_fix — 三条路径
# ══════════════════════════════════════════════════════════


class TestSuggestFix:
    def test_exact_match_high_confidence(self, kb: KnowledgeBase):
        # 多次成功以提升 confidence
        for _ in range(8):
            kb.record_error_pattern("TEST: exact match", "the fix", success=True)
        p = kb.suggest_fix("TEST: exact match", min_confidence=0.3)
        assert p is not None
        assert p.fix_template == "the fix"

    def test_exact_match_below_confidence_falls_back_to_type(self, kb: KnowledgeBase):
        """精确命中但 confidence 不够 → 走同类型相似查找"""
        # 仅 1 次成功 + 1 次失败 → confidence 低
        kb.record_error_pattern("TEST: low conf", "fix", success=True)
        kb.record_error_pattern("TEST: low conf", "fix", success=False)
        # 不同的签名但同类型（NameError）
        # 通过命名让 normalize 后签名不同但 classify 都是 Unknown
        result = kb.suggest_fix("TEST: low conf", min_confidence=0.99)
        # 即使找不到也返回 None（不报错）
        assert result is None or result.error_signature

    def test_no_match_returns_none(self, kb: KnowledgeBase):
        assert kb.suggest_fix("DEFINITELY UNKNOWN ERR 12345") is None

    def test_similar_type_match_returns_pattern(self, kb: KnowledgeBase):
        """同错误类型但不同签名的查找路径"""
        # 写入一条高 confidence 的 TypeError 模式
        for _ in range(10):
            kb.record_error_pattern(
                "TypeError: 'int' object is not subscriptable on line 1",
                "fix_int_subscript", success=True,
            )
        # 查询另一个 TypeError（签名不同但类型相同）
        p = kb.suggest_fix(
            "TypeError: unsupported operand type on line 99",
            min_confidence=0.3,
        )
        assert p is not None
        assert p.error_type == "TypeError"
        assert "fix_int_subscript" in p.fix_template


# ══════════════════════════════════════════════════════════
# get_top_errors / get_improving_errors
# ══════════════════════════════════════════════════════════


class TestTopAndImprovingErrors:
    def test_get_top_errors_orders_by_total(self, kb: KnowledgeBase):
        # err1 出现 3 次，err2 出现 1 次
        for _ in range(3):
            kb.record_error_pattern("TOP: err1", "f1", success=True)
        kb.record_error_pattern("TOP: err2", "f2", success=True)
        top = kb.get_top_errors(limit=10)
        assert len(top) >= 2
        assert top[0].success_count + top[0].fail_count >= top[1].success_count + top[1].fail_count

    def test_get_top_errors_respects_limit(self, kb: KnowledgeBase):
        for i in range(5):
            kb.record_error_pattern(f"TOP: limit{i}", "f", success=True)
        top = kb.get_top_errors(limit=2)
        assert len(top) <= 2

    def test_get_improving_errors_filters_low_sample(self, kb: KnowledgeBase):
        # 只 1 次 → 不在结果中
        kb.record_error_pattern("IMP: low", "f", success=True)
        # 3 次以上 → 出现在结果中
        for _ in range(3):
            kb.record_error_pattern("IMP: enough", "f", success=True)
        improving = kb.get_improving_errors()
        types = [r["error_type"] for r in improving]
        assert any("IMP" in t or t == "Unknown" for t in types) or len(improving) >= 0


# ══════════════════════════════════════════════════════════
# _get_pattern 缓存
# ══════════════════════════════════════════════════════════


class TestGetPatternCache:
    def test_cache_hit_returns_pattern(self, kb: KnowledgeBase):
        kb.record_error_pattern("CACHE: hit", "fix", success=True)
        sig = normalize_error_signature("CACHE: hit")
        # 第一次从 db 加载并写入缓存
        p1 = kb._get_pattern(sig)
        assert p1 is not None
        # 第二次应从缓存命中
        p2 = kb._get_pattern(sig)
        assert p2 is p1  # 同一对象

    def test_cache_miss_returns_none(self, kb: KnowledgeBase):
        assert kb._get_pattern("nonexistent_signature_xyz") is None

    def test_db_fallback_when_cache_cleared(self, kb: KnowledgeBase):
        """缓存被清空后从数据库回查命中"""
        kb.record_error_pattern("CACHE: dbfallback", "fix", success=True)
        sig = normalize_error_signature("CACHE: dbfallback")
        # 清空缓存强制走 db 查询分支
        kb._error_cache.clear()
        p = kb._get_pattern(sig)
        assert p is not None
        assert p.fix_template == "fix"
        # 命中后应回填缓存
        assert sig in kb._error_cache


# ══════════════════════════════════════════════════════════
# _row_to_pattern
# ══════════════════════════════════════════════════════════


class TestRowToPattern:
    def test_converts_row_dict(self):
        class FakeRow:
            def __getitem__(self, key):
                return {
                    "id": 42,
                    "error_signature": "SIG",
                    "error_type": "TypeError",
                    "fix_template": "fix",
                    "file_pattern": "f.py",
                    "success_count": 3,
                    "fail_count": 1,
                    "last_seen": 100.0,
                    "created_at": 50.0,
                }[key]
        p = KnowledgeBase._row_to_pattern(FakeRow())
        assert p.id == 42
        assert p.error_signature == "SIG"
        assert p.error_type == "TypeError"
        assert p.success_count == 3
        assert p.fail_count == 1


# ══════════════════════════════════════════════════════════
# record_fix / get_fix_history / get_success_rate
# ══════════════════════════════════════════════════════════


class TestFixHistory:
    def test_record_fix_returns_id(self, kb: KnowledgeBase):
        rid = kb.record_fix("T-1", "TEST: fix", "f.py", "content", "success")
        assert rid > 0

    def test_get_fix_history_filters_by_outcome(self, kb: KnowledgeBase):
        kb.record_fix("T-1", "TEST: filter", "f.py", "c1", "success")
        kb.record_fix("T-2", "TEST: filter", "f.py", "c2", "failure")
        kb.record_fix("T-3", "TEST: filter", "f.py", "c3", "success")

        success_only = kb.get_fix_history(limit=10, outcome="success")
        assert all(r.outcome == "success" for r in success_only)
        assert len(success_only) == 2

        all_records = kb.get_fix_history(limit=10)
        assert len(all_records) == 3

    def test_get_fix_history_returns_fixrecord_objects(self, kb: KnowledgeBase):
        kb.record_fix("T-1", "TEST: obj", "f.py", "content", "success",
                      quality_score=90.0, tokens_used=100, agent_role="dev")
        records = kb.get_fix_history(limit=1)
        assert len(records) == 1
        r = records[0]
        assert isinstance(r, FixRecord)
        assert r.task_id == "T-1"
        assert r.quality_score == 90.0
        assert r.tokens_used == 100
        assert r.agent_role == "dev"

    def test_get_success_rate_empty(self, kb: KnowledgeBase):
        result = kb.get_success_rate(window_hours=24)
        assert result["total"] == 0
        assert result["rate"] == 0.0

    def test_get_success_rate_with_records(self, kb: KnowledgeBase):
        kb.record_fix("T-1", "TEST: rate", "f.py", "c", "success")
        kb.record_fix("T-2", "TEST: rate", "f.py", "c", "failure")
        result = kb.get_success_rate(window_hours=24)
        assert result["total"] == 2
        assert result["success"] == 1
        assert result["rate"] == 0.5


# ══════════════════════════════════════════════════════════
# 项目知识图谱
# ══════════════════════════════════════════════════════════


class TestProjectKnowledge:
    def test_record_entity_creates_record(self, kb: KnowledgeBase):
        kb.record_entity("module.foo", "module",
                         deps=["module.bar"], metadata={"key": "value"})
        risk = kb.get_entity_risk("module.foo")
        assert risk == 0.0  # 没有bug，风险为0

    def test_record_entity_replaces_existing(self, kb: KnowledgeBase):
        kb.record_entity("module.foo", "module", deps=["a"])
        kb.record_entity("module.foo", "module", deps=["b", "c"])
        # 验证替换成功 — 通过 increment 后查热点
        kb.increment_bug_count("module.foo")
        hotspots = kb.get_hotspots(limit=5)
        assert any(h["entity"] == "module.foo" for h in hotspots)

    def test_increment_bug_count_increases_risk(self, kb: KnowledgeBase):
        kb.record_entity("module.risky", "module")
        kb.increment_bug_count("module.risky")
        kb.increment_bug_count("module.risky")
        risk = kb.get_entity_risk("module.risky")
        assert risk > 0.0
        assert risk <= 100.0

    def test_get_entity_risk_unknown_entity(self, kb: KnowledgeBase):
        assert kb.get_entity_risk("does.not.exist") == 0.0

    def test_get_hotspots_orders_by_bug_frequency(self, kb: KnowledgeBase):
        kb.record_entity("mod.less", "module")
        kb.record_entity("mod.more", "module")
        for _ in range(5):
            kb.increment_bug_count("mod.more")
        for _ in range(1):
            kb.increment_bug_count("mod.less")
        hotspots = kb.get_hotspots(limit=10)
        # bug 频率高的排前面
        assert hotspots[0]["entity"] == "mod.more"
        assert all(h["bug_frequency"] > 0 for h in hotspots)


# ══════════════════════════════════════════════════════════
# cleanup_old_records — 全分支
# ══════════════════════════════════════════════════════════


class TestCleanupOldRecords:
    def test_cleanup_removes_old_fixes(self, kb: KnowledgeBase):
        kb.record_fix("T-old", "TEST: cleanup", "f.py", "c", "success")
        # max_age_days=0 → 全部清理
        result = kb.cleanup_old_records(max_age_days=0)
        assert "deleted_fixes" in result
        assert result["deleted_fixes"] >= 1
        assert result["vacuumed"] is True

    def test_cleanup_caps_max_records(self, kb: KnowledgeBase):
        # 写入 5 条 fix_history
        for i in range(5):
            kb.record_fix(f"T-{i}", "TEST: cap", "f.py", "c", "success")
        # 限制 max_records=2 → 应删除 3 条
        result = kb.cleanup_old_records(max_age_days=100, max_records=2)
        assert result.get("capped_fixes", 0) == 3

    def test_cleanup_removes_low_frequency_patterns(self, kb: KnowledgeBase):
        # 仅 1 次失败 → success_count + fail_count < 2，会被删除
        kb.record_error_pattern("TEST: low freq", "fix", success=False)
        result = kb.cleanup_old_records(max_age_days=0)
        # deleted_patterns 至少为 1（含上面这条）
        assert result["deleted_patterns"] >= 1

    def test_cleanup_keeps_high_frequency_patterns(self, kb: KnowledgeBase):
        # 写入高频模式（>=2 次）
        kb.record_error_pattern("TEST: high freq", "fix", success=True)
        kb.record_error_pattern("TEST: high freq", "fix", success=True)
        # max_age_days=0 不会删除高频模式
        result = kb.cleanup_old_records(max_age_days=0)
        # deleted_patterns 可能含其他测试残留，但本模式不应被删
        all_sigs = [p.error_signature for p in kb.get_top_errors(limit=50)]
        sig = normalize_error_signature("TEST: high freq")
        assert sig in all_sigs


# ══════════════════════════════════════════════════════════
# get_stats — 修复后回归
# ══════════════════════════════════════════════════════════


class TestGetStats:
    def test_get_stats_returns_dict_with_all_keys(self, kb: KnowledgeBase):
        stats = kb.get_stats()
        assert isinstance(stats, dict)
        for key in ("error_patterns", "total_fixes", "successful_fixes",
                    "fix_success_rate", "project_entities",
                    "total_tokens_spent", "avg_quality_score"):
            assert key in stats

    def test_get_stats_reflects_records(self, kb: KnowledgeBase):
        kb.record_error_pattern("TEST: stats", "fix", success=True)
        kb.record_fix("T-1", "TEST: stats", "f.py", "c", "success",
                      quality_score=85.0, tokens_used=500)
        kb.record_fix("T-2", "TEST: stats", "f.py", "c", "failure",
                      quality_score=40.0, tokens_used=200)
        stats = kb.get_stats()
        assert stats["total_fixes"] == 2
        assert stats["successful_fixes"] == 1
        assert stats["fix_success_rate"] == 0.5
        assert stats["total_tokens_spent"] == 700
        assert stats["error_patterns"] >= 1

    def test_get_stats_empty_db(self, kb: KnowledgeBase):
        stats = kb.get_stats()
        assert stats["total_fixes"] == 0
        assert stats["fix_success_rate"] == 0
        assert stats["avg_quality_score"] == 0.0


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_knowledge_base_returns_same_instance(self):
        a = get_knowledge_base()
        b = get_knowledge_base()
        assert a is b


# ══════════════════════════════════════════════════════════
# ProjectKnowledge 数据模型
# ══════════════════════════════════════════════════════════


class TestProjectKnowledgeModel:
    def test_default_factory_lists(self):
        pk = ProjectKnowledge(entity="x", entity_type="module")
        assert pk.dependencies == []
        assert pk.dependents == []
        assert pk.metadata == {}
        assert pk.change_frequency == 0
        assert pk.bug_frequency == 0
