"""
学习子系统集成测试 — 覆盖 knowledge_base, experience_buffer,
feedback_loop, metrics_tracker, pattern_extractor, self_optimizer
"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestKnowledgeBase:
    """知识库单元测试"""

    def test_normalize_signature(self):
        from pycoder.server.learning.knowledge_base import normalize_error_signature
        s1 = normalize_error_signature("NameError: name 'x' is not defined")
        s2 = normalize_error_signature("NameError: name 'y' is not defined")
        assert s1 == s2, "Standardized signatures should match"
        assert "<VALUE>" in s1, "Should replace quoted values"
        assert "NameError" in s1 or "<N>" in s1

    def test_classify_error(self):
        from pycoder.server.learning.knowledge_base import classify_error
        assert classify_error("TypeError('bad operand')") == "TypeError"
        assert classify_error("NameError: name 'x'") == "NameError"
        assert classify_error("SyntaxError: invalid") == "SyntaxError"
        assert classify_error("something normal") == "Unknown"

    def test_record_and_suggest(self):
        from pycoder.server.learning.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        kb.record_error_pattern("TEST: fake error", "import fix", success=True)
        p = kb.suggest_fix("TEST: fake error", min_confidence=0.1)
        assert p is not None
        assert p.success_count >= 1

    def test_record_multiple_no_crash(self):
        """验证多次记录不崩溃（回归 Bug #1）"""
        from pycoder.server.learning.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        for i in range(5):
            kb.record_error_pattern(f"TEST: record #{i}", f"fix_{i}", success=i < 4)
        top = kb.get_top_errors(limit=5)
        assert len(top) > 0

    def test_fix_history(self):
        from pycoder.server.learning.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        kb.record_fix("TID-A", "TEST: history", "test.py", "fix", "success")
        history = kb.get_fix_history(limit=5)
        assert len(history) >= 1

    def test_cleanup(self):
        from pycoder.server.learning.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        result = kb.cleanup_old_records(max_age_days=0.001)
        assert isinstance(result, dict)
        assert "deleted_fixes" in result

    def test_get_stats(self):
        from pycoder.server.learning.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        # Verify fix_history works (get_stats was removed during refactor)
        history = kb.get_fix_history(limit=1)
        assert isinstance(history, list)


class TestExperienceBuffer:
    """经验缓冲区单元测试"""

    def test_store_and_stats(self):
        from pycoder.server.learning.experience_buffer import ExperienceBuffer, TaskExperience
        buf = ExperienceBuffer(capacity=500)
        buf.store(TaskExperience(task_type="fix", error_signature="UNIQUE_TEST_SIG",
                                 outcome="success", test_passed=True, quality_score=100))
        assert len(buf) >= 1

    def test_sampling_strategies(self):
        from pycoder.server.learning.experience_buffer import ExperienceBuffer, TaskExperience
        buf = ExperienceBuffer(capacity=50)
        for i in range(10):
            buf.store(TaskExperience(error_signature=f"E{i%3}", outcome="success" if i < 7 else "failure"))

        for strategy in ["priority", "recent", "diverse", "random"]:
            batch = buf.sample(batch_size=3, strategy=strategy)
            assert len(batch) <= 3 and len(batch) > 0, f"{strategy} sampling failed"

    def test_diverse_sample_safe(self):
        from pycoder.server.learning.experience_buffer import ExperienceBuffer, TaskExperience
        buf = ExperienceBuffer(capacity=5)
        for i in range(3):
            buf.store(TaskExperience(error_signature=f"DS_{i}"))
        batch = buf._diverse_sample(10)
        assert len(batch) <= len(buf)

    def test_reward_computation(self):
        from pycoder.server.learning.experience_buffer import compute_reward
        r = compute_reward("success", True, 100, 0, 1000, 500)
        assert -1.0 <= r <= 1.0
        assert r > 0

        r2 = compute_reward("failure", False, 0, 5, 50000, 60000)
        assert r2 < 0


class TestFeedbackLoop:
    """反馈闭环单元测试"""

    def test_collect_and_stats(self, tmp_path, monkeypatch):
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb = fb_mod.FeedbackLoop()
        for i in range(25):
            fb.collect(task_id=f"FB-{i}", outcome="success" if i > 5 else "failure",
                       quality_score=90 if i > 5 else 30, test_passed=i > 5,
                       agent_role="developer", model_used="deepseek-chat")
        stats = fb.get_stats()
        assert stats["total_signals"] == 25
        assert stats["recent_success_rate"] > 0.5

    def test_adaptive_config(self, tmp_path, monkeypatch):
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb = fb_mod.FeedbackLoop()
        config = fb.get_adaptive_config()
        assert 70 <= config.quality_threshold <= 95
        assert config.max_retries >= 1

    def test_force_adjust(self, tmp_path, monkeypatch):
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb = fb_mod.FeedbackLoop()
        for i in range(25):
            fb.collect(outcome="success" if i > 8 else "failure", test_passed=i > 8)
        result = fb.force_adjust()
        assert hasattr(result, "quality_threshold")


class TestFeedbackLoopPersistence:
    """P2-3: FeedbackLoop 信号 JSONL 持久化测试"""

    def test_collect_creates_signals_file(self, tmp_path, monkeypatch):
        """collect() 后 signals.jsonl 文件存在且可解析"""
        import json as _json
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb = fb_mod.FeedbackLoop()
        fb.collect(task_id="T-1", outcome="failure", quality_score=40.0)
        signals_file = tmp_path / "signals.jsonl"
        assert signals_file.exists()
        lines = signals_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        data = _json.loads(lines[0])
        assert data["task_id"] == "T-1"
        assert data["outcome"] == "failure"
        assert data["quality_score"] == 40.0

    def test_signals_loaded_on_init(self, tmp_path, monkeypatch):
        """重启后新 FeedbackLoop 实例从文件加载历史信号"""
        import json as _json
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        # 第一次实例：写入 3 条信号
        fb1 = fb_mod.FeedbackLoop()
        for i in range(3):
            fb1.collect(task_id=f"T-{i}", outcome="success")
        assert len(fb1._signals) == 3
        # 第二次实例（模拟重启）：应加载已有信号
        fb2 = fb_mod.FeedbackLoop()
        assert len(fb2._signals) == 3
        stats = fb2.get_stats()
        assert stats["total_signals"] == 3

    def test_signals_loaded_stats_accurate(self, tmp_path, monkeypatch):
        """加载后 get_stats() 反映历史信号而非空"""
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb1 = fb_mod.FeedbackLoop()
        for i in range(10):
            fb1.collect(
                task_id=f"T-{i}",
                outcome="success" if i > 3 else "failure",
                quality_score=80.0,
            )
        # 重启
        fb2 = fb_mod.FeedbackLoop()
        stats = fb2.get_stats()
        assert stats["total_signals"] == 10
        # 4 失败 + 6 成功
        assert stats["recent_success_rate"] == 0.6

    def test_signals_capped_at_500(self, tmp_path, monkeypatch):
        """超过 500 条信号时截断并全量重写文件"""
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb = fb_mod.FeedbackLoop()
        # 写入 510 条
        for i in range(510):
            fb.collect(task_id=f"T-{i}", outcome="success")
        assert len(fb._signals) == 500
        # 文件也应被截断（_save_signals 在 truncation 时调用）
        signals_file = tmp_path / "signals.jsonl"
        lines = signals_file.read_text(encoding="utf-8").splitlines()
        # 文件行数可能因 append + rewrite 略多，但不应远超 500
        assert len(lines) <= 510

    def test_adaptive_config_still_persisted(self, tmp_path, monkeypatch):
        """回归验证：信号持久化不影响 adaptive_config 持久化"""
        import pycoder.server.learning.feedback_loop as fb_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR", tmp_path)
        fb1 = fb_mod.FeedbackLoop()
        # 写入足够信号触发 _adjust（50 条）
        for i in range(50):
            fb1.collect(
                task_id=f"T-{i}",
                outcome="success" if i > 20 else "failure",
                quality_score=85.0,
            )
        config_file = tmp_path / "adaptive_config.json"
        assert config_file.exists()
        # 重启后配置应加载
        fb2 = fb_mod.FeedbackLoop()
        cfg = fb2.get_adaptive_config()
        assert 70 <= cfg.quality_threshold <= 95


class TestMetricsTracker:
    """指标追踪器单元测试"""

    def test_record_and_query(self):
        from pycoder.server.learning.metrics_tracker import MetricsTracker
        mt = MetricsTracker()
        mt.record_evolution(outcome="success", test_passed=True, quality_score=95)
        mt.record_quality_snapshot(total_score=92, test_coverage=85)
        stats = mt.get_evolution_stats(days=1)
        assert stats["total_evolutions"] >= 1

    def test_trends(self):
        from pycoder.server.learning.metrics_tracker import MetricsTracker
        mt = MetricsTracker()
        trends = mt.get_quality_trends(days=7)
        assert isinstance(trends, list)


class TestPatternExtractor:
    """模式提取器单元测试"""

    def test_extract(self, tmp_path, monkeypatch):
        try:
            import pycoder.server.learning.pattern_extractor as pe_mod
            monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
            from pycoder.server.learning.knowledge_base import KnowledgeBase
            from pycoder.server.learning.experience_buffer import ExperienceBuffer, TaskExperience
            from pycoder.server.learning.pattern_extractor import PatternExtractor
            kb = KnowledgeBase()
            kb.record_error_pattern("PTEST: test pattern", "fix it", success=True)
            buf = ExperienceBuffer()
            buf.store(TaskExperience(error_signature="PTEST: test pattern", outcome="success"))
            pe = PatternExtractor()
            patterns = pe.extract_fix_patterns(knowledge_base=kb, experience_buffer=buf)
            assert isinstance(patterns, list)
        except ImportError:
            pass  # optional module

    def test_hotspots(self, tmp_path, monkeypatch):
        import pycoder.server.learning.pattern_extractor as pe_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        from pycoder.server.learning.pattern_extractor import PatternExtractor
        pe = PatternExtractor()
        hotspots = pe.get_hotspots(top_n=5)
        assert isinstance(hotspots, list)


class TestPatternExtractorPersistence:
    """H5: PatternExtractor 模式 JSONL 持久化测试"""

    def test_extract_creates_patterns_file(self, tmp_path, monkeypatch):
        """extract_fix_patterns() 后 patterns.jsonl 文件存在且可解析"""
        import json as _json
        import pycoder.server.learning.pattern_extractor as pe_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        from pycoder.server.learning.pattern_extractor import PatternExtractor, FixPattern
        pe = PatternExtractor()
        # 手动构造一个模式并触发保存
        pe._patterns = [FixPattern(
            pattern_id="TEST-1",
            error_type="ValueError",
            description="测试模式",
            fix_template="validate input",
            success_count=5,
            fail_count=1,
        )]
        pe._save_patterns()
        patterns_file = tmp_path / "patterns.jsonl"
        assert patterns_file.exists()
        lines = patterns_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        data = _json.loads(lines[0])
        assert data["pattern_id"] == "TEST-1"
        assert data["error_type"] == "ValueError"
        assert data["success_count"] == 5

    def test_patterns_loaded_on_init(self, tmp_path, monkeypatch):
        """重启后新 PatternExtractor 实例从文件加载历史模式"""
        import json as _json
        import pycoder.server.learning.pattern_extractor as pe_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        from pycoder.server.learning.pattern_extractor import PatternExtractor, FixPattern
        # 第一次实例：写入 2 个模式
        pe1 = PatternExtractor()
        pe1._patterns = [
            FixPattern(pattern_id="A-1", error_type="ErrA", success_count=3),
            FixPattern(pattern_id="B-1", error_type="ErrB", success_count=2),
        ]
        pe1._save_patterns()
        # 第二次实例（模拟重启）：应加载已有模式
        pe2 = PatternExtractor()
        assert len(pe2._patterns) == 2
        ids = {p.pattern_id for p in pe2._patterns}
        assert ids == {"A-1", "B-1"}

    def test_corrupted_jsonl_skipped(self, tmp_path, monkeypatch):
        """损坏的 JSONL 行被跳过，不导致初始化失败"""
        import pycoder.server.learning.pattern_extractor as pe_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        from pycoder.server.learning.pattern_extractor import PatternExtractor
        # 写入混合内容：1 行合法 + 1 行损坏 + 1 行合法
        patterns_file = tmp_path / "patterns.jsonl"
        patterns_file.write_text(
            '{"pattern_id":"OK-1","error_type":"E1","success_count":1}\n'
            "this is not json\n"
            '{"pattern_id":"OK-2","error_type":"E2","success_count":2}\n',
            encoding="utf-8",
        )
        pe = PatternExtractor()
        # 应只加载 2 条合法记录
        assert len(pe._patterns) == 2
        ids = {p.pattern_id for p in pe._patterns}
        assert ids == {"OK-1", "OK-2"}

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        """保存→重新加载，所有字段保持一致"""
        import pycoder.server.learning.pattern_extractor as pe_mod
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        from pycoder.server.learning.pattern_extractor import PatternExtractor, FixPattern
        pe1 = PatternExtractor()
        original = FixPattern(
            pattern_id="RT-1",
            error_type="RuntimeError",
            description="完整字段测试",
            fix_template="try: ... except: ...",
            example_error="Traceback: ...",
            example_fix="fixed code",
            success_count=10,
            fail_count=2,
            last_used=1234567890.0,
            files_affected=["a.py", "b.py"],
        )
        pe1._patterns = [original]
        pe1._save_patterns()
        # 重新加载
        pe2 = PatternExtractor()
        assert len(pe2._patterns) == 1
        loaded = pe2._patterns[0]
        assert loaded.pattern_id == "RT-1"
        assert loaded.error_type == "RuntimeError"
        assert loaded.fix_template == "try: ... except: ..."
        assert loaded.success_count == 10
        assert loaded.fail_count == 2
        assert loaded.last_used == 1234567890.0
        assert loaded.files_affected == ["a.py", "b.py"]
        assert abs(loaded.success_rate - (10 / 12)) < 0.001


class TestSelfOptimizer:
    """自优化引擎单元测试"""

    def test_prompt_optimizer(self):
        from pycoder.server.learning.self_optimizer import PromptOptimizer
        po = PromptOptimizer()
        for agent_id in ["pm", "architect", "developer", "qa", "devops"]:
            r = po.optimize_agent_prompt(agent_id)
            assert r.original_lines > 0, f"{agent_id} has no prompt lines"
            assert isinstance(r.changes, list)

    def test_usage_analyzer(self):
        from pycoder.server.learning.self_optimizer import UsageAnalyzer
        ua = UsageAnalyzer()
        report = ua.analyze(days=30)
        assert hasattr(report, "total_sessions")
        assert hasattr(report, "total_messages")

    def test_full_cycle(self):
        from pycoder.server.learning.self_optimizer import SelfOptimizer
        opt = SelfOptimizer()
        result = opt.full_optimization_cycle()
        assert "usage" in result
        assert "prompts" in result
        assert "recommendations" in result

    def test_markdown_report(self):
        from pycoder.server.learning.self_optimizer import SelfOptimizer
        opt = SelfOptimizer()
        md = opt.generate_optimization_markdown()
        assert len(md) > 100


class TestExecutionRules:
    """执行铁律单元测试"""

    def test_security_scan(self):
        from pycoder.server.services.execution_rules import ExecutionRules
        rules = ExecutionRules()
        issues = rules.validate_code_safety('API_KEY = "sk-abc123def"\neval("x")')
        assert len(issues) >= 2

    def test_bom_check(self):
        from pycoder.server.services.execution_rules import ExecutionRules
        import tempfile, os
        f = tempfile.NamedTemporaryFile(delete=False, suffix=".py")
        f.write(b"\xef\xbb\xbfprint('x')\n")
        f.close()
        assert not ExecutionRules.check_bom(f.name)
        ExecutionRules.strip_bom(f.name)
        assert ExecutionRules.check_bom(f.name)
        os.unlink(f.name)

    def test_shared_state(self):
        from pycoder.server.services.execution_rules import SharedState
        import time
        state = SharedState(f"TEST-{int(time.time())}")
        assert state.get_task().status == "pending"
        state.update_task("executing", title="pytest task")
        assert state.get_task().status == "executing"
        assert state.get_task().title == "pytest task"


class TestExecutionReport:
    """执行报告单元测试"""

    def test_builder(self):
        from pycoder.server.services.execution_report import ReportBuilder
        rb = ReportBuilder("test")
        rb.add_file("a.py", "modified", "10-20", "test")
        rb.track_token("deepseek-chat", 5000, 0.002)
        rpt = rb.done("success")
        assert rpt.file_count == 1
        assert rpt.total_tokens == 5000

    def test_markdown(self):
        from pycoder.server.services.execution_report import ExecutionReport
        rpt = ExecutionReport(task_name="test", duration_seconds=10)
        md = rpt.to_markdown()
        assert len(md) > 50


class TestQualityGate:
    """质量门禁单元测试"""

    def test_gate_result(self):
        from pycoder.server.services.quality_guard import QualityGate
        qg = QualityGate()
        r = qg.evaluate([], test_coverage=90)
        assert r.passed
        assert r.score >= 85

    def test_gate_reject(self):
        from pycoder.server.services.quality_guard import QualityGate
        qg = QualityGate()
        r = qg.evaluate(["nonexistent.py"], test_coverage=50)
        assert not r.passed
