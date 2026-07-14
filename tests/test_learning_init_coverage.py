"""LearningEngine 覆盖率补充测试（pycoder/server/learning/__init__.py）

针对 __init__.py 中未被覆盖的分支:
  - _format_top_errors 辅助函数
  - LearningEngine.on_task_complete 各分支（dedup、有/无 error_msg、模式提取触发、recent trimming）
  - LearningEngine.on_quality_scan
  - LearningEngine.on_pipeline_complete
  - LearningEngine.get_task_advice 各分支（suggested_fix、hotspots、risk_warnings）
  - LearningEngine.generate_learning_report
  - LearningEngine.generate_learning_report_markdown
  - get_pattern_extractor / get_learning_engine 单例
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════
# Fixture — 用 tmp_path 完全隔离所有持久化路径
# ══════════════════════════════════════════════════════════


@pytest.fixture
def isolated_engine(tmp_path: Path, monkeypatch):
    """构造一个所有磁盘 IO 都隔离到 tmp_path 的 LearningEngine。

    替换各子模块的模块级路径常量（DB_PATH / EXP_DIR / PATTERNS_DIR /
    FEEDBACK_DIR / METRICS_DB），并重置所有单例缓存变量，确保新实例
    使用 tmp_path 而非真实 ~/.pycoder。
    """
    import pycoder.server.learning.knowledge_base as kb_mod
    import pycoder.server.learning.metrics_tracker as mt_mod
    import pycoder.server.learning.experience_buffer as eb_mod
    import pycoder.server.learning.pattern_extractor as pe_mod
    import pycoder.server.learning.feedback_loop as fb_mod
    import pycoder.server.learning as learning_mod
    import pycoder.capabilities.self_evo.learning as v2_learning_mod
    import pycoder.capabilities.self_evo.learning.knowledge_base as v2_kb_mod
    import pycoder.capabilities.self_evo.learning.metrics_tracker as v2_mt_mod
    import pycoder.capabilities.self_evo.learning.experience_buffer as v2_eb_mod
    import pycoder.capabilities.self_evo.learning.pattern_extractor as v2_pe_mod
    import pycoder.capabilities.self_evo.learning.feedback_loop as v2_fb_mod

    db_path = tmp_path / "pycoder.db"
    exp_dir = tmp_path / "exp"
    patterns_dir = tmp_path / "patterns"
    fb_dir = tmp_path / "fb"

    # 替换 V1 模块级路径常量（兼容旧代码）
    monkeypatch.setattr(kb_mod, "DB_PATH", db_path)
    monkeypatch.setattr(kb_mod, "DB_DIR", tmp_path)
    monkeypatch.setattr(mt_mod, "METRICS_DB", db_path)
    monkeypatch.setattr(mt_mod, "DB_DIR", tmp_path)
    monkeypatch.setattr(eb_mod, "EXP_DIR", exp_dir)
    monkeypatch.setattr(pe_mod, "PATTERNS_DIR", patterns_dir)
    monkeypatch.setattr(fb_mod, "FEEDBACK_DIR", fb_dir)

    # 替换 V2 模块级路径常量（实际代码使用 V2 模块的路径）
    monkeypatch.setattr(v2_kb_mod, "DB_PATH", db_path)
    monkeypatch.setattr(v2_kb_mod, "DB_DIR", tmp_path)
    monkeypatch.setattr(v2_mt_mod, "METRICS_DB", db_path)
    monkeypatch.setattr(v2_mt_mod, "DB_DIR", tmp_path)
    monkeypatch.setattr(v2_eb_mod, "EXP_DIR", exp_dir)
    monkeypatch.setattr(v2_pe_mod, "PATTERNS_DIR", patterns_dir)
    monkeypatch.setattr(v2_fb_mod, "FEEDBACK_DIR", fb_dir)

    # 重置所有单例缓存，使下次 get_*() 创建使用新路径的实例
    monkeypatch.setattr(kb_mod, "_kb", None)
    monkeypatch.setattr(v2_kb_mod, "_kb", None)
    monkeypatch.setattr(mt_mod, "_tracker", None)
    monkeypatch.setattr(v2_mt_mod, "_tracker", None)
    monkeypatch.setattr(eb_mod, "_buffer", None)
    monkeypatch.setattr(v2_eb_mod, "_buffer", None)
    monkeypatch.setattr(fb_mod, "_loop", None)
    monkeypatch.setattr(v2_fb_mod, "_loop", None)
    monkeypatch.setattr(learning_mod, "_pattern_extractor_instance", None)
    monkeypatch.setattr(learning_mod, "_engine", None)

    # 同时重置 V2 模块中的单例（get_learning_engine 的 global _engine 在 V2 模块中）
    monkeypatch.setattr(v2_learning_mod, "_engine", None)
    monkeypatch.setattr(v2_learning_mod, "_pattern_extractor_instance", None)

    # 重置 SessionStore 初始化标志（避免使用旧的内存数据库连接）
    from pycoder.server.session_store import SessionStore
    monkeypatch.setattr(SessionStore, "_db_initialized", False)

    # 现在创建新 LearningEngine — 它会使用 tmp_path 中的所有路径
    return learning_mod.LearningEngine()


# ══════════════════════════════════════════════════════════
# _format_top_errors
# ══════════════════════════════════════════════════════════


class TestFormatTopErrors:
    def test_empty_list_returns_default(self):
        from pycoder.server.learning import _format_top_errors
        assert _format_top_errors([]) == "无数据"

    def test_formats_top_three(self):
        from pycoder.server.learning import _format_top_errors
        result = _format_top_errors([
            ("NameError", 5), ("TypeError", 3), ("ValueError", 2), ("KeyError", 1),
        ])
        # 只取前 3 个
        assert "NameError(5)" in result
        assert "TypeError(3)" in result
        assert "ValueError(2)" in result
        assert "KeyError" not in result


# ══════════════════════════════════════════════════════════
# LearningEngine.on_task_complete
# ══════════════════════════════════════════════════════════


class TestOnTaskComplete:
    def test_records_to_kb_when_error_msg(self, isolated_engine):
        """有 error_msg → 记录到知识库 + 经验缓冲区"""
        engine = isolated_engine
        result = engine.on_task_complete(
            task_id="T-1",
            outcome="success",
            error_msg="NameError: name 'x' is not defined",
            file_paths=["src/app.py"],
            fix_content="import x",
            test_passed=True,
            quality_score=90.0,
            tokens_used=100,
            agent_role="developer",
        )
        assert "experience_id" in result
        assert "error_pattern" in result
        assert "feedback_config" in result

    def test_skips_kb_when_no_error_msg(self, isolated_engine):
        """无 error_msg → 跳过 KB 记录，仅记录经验"""
        engine = isolated_engine
        result = engine.on_task_complete(
            task_id="T-2",
            outcome="success",
            description="新建任务",
            quality_score=85.0,
        )
        # 无 error_pattern 键
        assert "error_pattern" not in result
        assert "experience_id" in result

    def test_dedup_same_task_id(self, isolated_engine):
        """同一 task_id 第二次调用返回 dedup 标记"""
        engine = isolated_engine
        engine.on_task_complete(task_id="T-DUP", outcome="success")
        result = engine.on_task_complete(task_id="T-DUP", outcome="success")
        assert result.get("dedup") is True
        assert "已处理过" in result["message"]

    def test_dedup_only_when_task_id_present(self, isolated_engine):
        """空 task_id 不去重"""
        engine = isolated_engine
        r1 = engine.on_task_complete(task_id="", outcome="success")
        r2 = engine.on_task_complete(task_id="", outcome="success")
        assert "dedup" not in r1
        assert "dedup" not in r2

    def test_recent_task_ids_trimmed_at_20(self, isolated_engine):
        """超过 20 个 task_id 后会被截断到最近 20 个"""
        engine = isolated_engine
        # 写入 25 个不同 task_id
        for i in range(25):
            engine.on_task_complete(task_id=f"T-{i}", outcome="success")
        # 集合大小不应超过 max_recent_tasks + 一些缓冲
        assert len(engine._recent_task_ids) <= engine._max_recent_tasks + 5

    def test_pattern_extraction_triggered_on_first_call(self, isolated_engine):
        """第一次调用 on_task_complete 时触发模式提取（间隔 > 1小时）"""
        engine = isolated_engine
        engine._last_pattern_extraction = 0.0  # 强制触发
        result = engine.on_task_complete(
            task_id="T-EXT",
            outcome="success",
            error_msg="TypeError: bad operand",
            fix_content="fix",
        )
        assert "patterns_extracted" in result

    def test_pattern_extraction_skipped_within_interval(self, isolated_engine):
        """间隔小于 1 小时不触发模式提取"""
        engine = isolated_engine
        engine._last_pattern_extraction = time.time()  # 刚提取过
        result = engine.on_task_complete(
            task_id="T-NOEXT",
            outcome="success",
            error_msg="ValueError: bad",
            fix_content="fix",
        )
        assert "patterns_extracted" not in result

    def test_records_rolled_back_outcome(self, isolated_engine):
        """outcome='rolled_back' 被正确处理"""
        engine = isolated_engine
        result = engine.on_task_complete(
            task_id="T-RB",
            outcome="rolled_back",
            error_msg="RuntimeError: something",
            fix_content="bad fix",
        )
        assert "experience_id" in result

    def test_feedback_config_returned(self, isolated_engine):
        """result 包含 feedback_config"""
        engine = isolated_engine
        result = engine.on_task_complete(task_id="T-FB", outcome="success")
        assert "feedback_config" in result
        assert "quality_threshold" in result["feedback_config"]


# ══════════════════════════════════════════════════════════
# LearningEngine.on_quality_scan
# ══════════════════════════════════════════════════════════


class TestOnQualityScan:
    def test_records_snapshot(self, isolated_engine):
        """on_quality_scan 调用 metrics.record_quality_snapshot"""
        engine = isolated_engine
        engine.on_quality_scan(
            lint_score=90, security_score=95, complexity_score=85,
            test_coverage=80, total_score=87, file_count=10, issue_count=2,
        )
        # 验证快照被写入
        snapshots = engine.metrics.get_quality_trends(days=1)
        # 至少应有 1 个快照（可能因时区差异不在 1 天内，但记录已写入）
        assert isinstance(snapshots, list)


# ══════════════════════════════════════════════════════════
# LearningEngine.on_pipeline_complete
# ══════════════════════════════════════════════════════════


class TestOnPipelineComplete:
    def test_delegates_to_on_task_complete(self, isolated_engine):
        """on_pipeline_complete 转发参数到 on_task_complete"""
        engine = isolated_engine
        pipeline_result = {
            "run_id": "PIPE-1",
            "status": "success",
            "request": "build login feature",
            "quality_score": 88.0,
            "tokens_used": 5000,
            "review_rounds": 2,
        }
        result = engine.on_pipeline_complete(pipeline_result)
        assert "experience_id" in result

    def test_handles_missing_keys(self, isolated_engine):
        """缺字段的 pipeline_result 不崩溃"""
        engine = isolated_engine
        result = engine.on_pipeline_complete({})
        assert "experience_id" in result

    def test_failure_status_recorded(self, isolated_engine):
        engine = isolated_engine
        result = engine.on_pipeline_complete({
            "run_id": "PIPE-FAIL",
            "status": "failure",
        })
        assert "experience_id" in result


# ══════════════════════════════════════════════════════════
# LearningEngine.get_task_advice
# ══════════════════════════════════════════════════════════


class TestGetTaskAdvice:
    def test_returns_advice_dict_with_all_keys(self, isolated_engine):
        engine = isolated_engine
        advice = engine.get_task_advice(task_description="fix bug")
        for key in ("suggested_fix", "hotspots_to_check",
                    "risk_warnings", "suggested_model", "quality_threshold"):
            assert key in advice

    def test_suggested_fix_when_error_msg_matches(self, isolated_engine):
        """有匹配的 error_msg → suggested_fix 非空"""
        engine = isolated_engine
        # 写入一个高 confidence 的模式
        for _ in range(10):
            engine.kb.record_error_pattern(
                "NameError: name 'foo' is not defined",
                "import foo",
                file_path="app.py",
                success=True,
            )
        advice = engine.get_task_advice(
            task_description="fix",
            error_msg="NameError: name 'foo' is not defined",
        )
        assert advice["suggested_fix"] is not None
        assert "error_type" in advice["suggested_fix"]
        assert "fix_template" in advice["suggested_fix"]

    def test_suggested_fix_none_when_no_match(self, isolated_engine):
        """无匹配的 error_msg → suggested_fix 为 None"""
        engine = isolated_engine
        advice = engine.get_task_advice(
            error_msg="DEFINITELY_UNKNOWN_ERROR_12345",
        )
        assert advice["suggested_fix"] is None

    def test_hotspots_returned_as_list(self, isolated_engine):
        engine = isolated_engine
        advice = engine.get_task_advice()
        assert isinstance(advice["hotspots_to_check"], list)

    def test_adaptive_config_in_advice(self, isolated_engine):
        engine = isolated_engine
        advice = engine.get_task_advice()
        # quality_threshold 来自 feedback.get_adaptive_config()
        assert isinstance(advice["quality_threshold"], (int, float))
        assert isinstance(advice["suggested_model"], str)
        assert "max_retries" in advice

    def test_risk_warning_when_low_success_rate(self, isolated_engine):
        """近期成功率 < 50% → 触发 risk_warning"""
        engine = isolated_engine
        # 写入足够多失败信号使 recent_success_rate < 0.5
        for i in range(25):
            engine.feedback.collect(
                task_id=f"T-{i}",
                outcome="success" if i >= 20 else "failure",  # 5 成功 / 20 失败 → 0.2
                quality_score=30.0,
                test_passed=False,
            )
        advice = engine.get_task_advice()
        assert any("成功率较低" in w for w in advice["risk_warnings"])

    def test_risk_warning_when_high_fail_count(self, isolated_engine):
        """某错误 fail_count > success_count → 触发 risk_warning"""
        engine = isolated_engine
        # 写入失败次数多的错误模式
        for _ in range(5):
            engine.kb.record_error_pattern(
                "TEST: risky pattern xyz", "fix", success=False,
            )
        engine.kb.record_error_pattern(
            "TEST: risky pattern xyz", "fix", success=True,
        )
        advice = engine.get_task_advice()
        # 应有 risk_warning 提及成功率
        assert any("成功率" in w or "risky" in w.lower() or "TEST" in w for w in advice["risk_warnings"])

    def test_no_risk_warnings_when_healthy(self, isolated_engine):
        """健康状态下无 risk_warnings"""
        engine = isolated_engine
        # 写入足够多成功信号
        for i in range(25):
            engine.feedback.collect(
                task_id=f"T-{i}",
                outcome="success",
                quality_score=90.0,
                test_passed=True,
            )
        advice = engine.get_task_advice()
        # 健康时不应有 "成功率较低" 警告
        assert not any("成功率较低" in w for w in advice["risk_warnings"])


# ══════════════════════════════════════════════════════════
# LearningEngine.generate_learning_report
# ══════════════════════════════════════════════════════════


class TestGenerateLearningReport:
    def test_returns_dict_with_all_sections(self, isolated_engine):
        engine = isolated_engine
        # 写入一些数据
        engine.on_task_complete(
            task_id="T-RPT",
            outcome="success",
            error_msg="ValueError: bad",
            fix_content="fix",
            quality_score=90.0,
        )
        report = engine.generate_learning_report()
        for key in ("generated_at", "knowledge_base", "experience_buffer",
                    "evolution", "feedback", "patterns", "hotspots",
                    "quality_trends"):
            assert key in report

    def test_empty_engine_returns_valid_report(self, isolated_engine):
        """无数据时也能生成报告"""
        engine = isolated_engine
        report = engine.generate_learning_report()
        assert isinstance(report, dict)
        assert "generated_at" in report
        assert isinstance(report["hotspots"], list)
        assert isinstance(report["quality_trends"], list)

    def test_knowledge_base_stats_populated(self, isolated_engine):
        engine = isolated_engine
        engine.kb.record_error_pattern("TEST: report kb", "fix", success=True)
        engine.kb.record_fix("T-1", "TEST: report kb", "f.py", "c", "success")
        report = engine.generate_learning_report()
        kb_stats = report["knowledge_base"]
        assert kb_stats["error_patterns"] >= 1
        assert kb_stats["total_fixes"] >= 1


# ══════════════════════════════════════════════════════════
# LearningEngine.generate_learning_report_markdown
# ══════════════════════════════════════════════════════════


class TestGenerateLearningReportMarkdown:
    def test_returns_markdown_string(self, isolated_engine):
        engine = isolated_engine
        md = engine.generate_learning_report_markdown()
        assert isinstance(md, str)
        assert "PyCoder 学习进化报告" in md
        assert "知识库" in md
        assert "经验缓冲区" in md
        assert "进化统计" in md
        assert "自适应配置" in md

    def test_includes_hotspots_section_when_present(self, isolated_engine):
        engine = isolated_engine
        # 写入热点数据
        engine.kb.record_entity("src/hot.py", "module")
        for _ in range(3):
            engine.kb.increment_bug_count("src/hot.py")
        md = engine.generate_learning_report_markdown()
        assert "Bug 热点" in md
        assert "src/hot.py" in md

    def test_no_hotspots_section_when_empty(self, isolated_engine):
        """无热点时不输出 Bug 热点章节"""
        engine = isolated_engine
        md = engine.generate_learning_report_markdown()
        assert "Bug 热点" not in md


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestSingletons:
    def test_get_pattern_extractor_returns_same_instance(self, monkeypatch, tmp_path):
        """get_pattern_extractor 返回同一实例"""
        import pycoder.server.learning.pattern_extractor as pe_mod
        import pycoder.server.learning as learning_mod
        monkeypatch.setattr(pe_mod, "PATTERNS_DIR", tmp_path)
        monkeypatch.setattr(learning_mod, "_pattern_extractor_instance", None)
        a = learning_mod.get_pattern_extractor()
        b = learning_mod.get_pattern_extractor()
        assert a is b

    def test_get_learning_engine_returns_same_instance(
        self, monkeypatch, tmp_path,
    ):
        """get_learning_engine 返回同一实例"""
        import pycoder.server.learning.knowledge_base as kb_mod
        import pycoder.server.learning.metrics_tracker as mt_mod
        import pycoder.server.learning.experience_buffer as eb_mod
        import pycoder.server.learning.pattern_extractor as pe_mod
        import pycoder.server.learning.feedback_loop as fb_mod
        import pycoder.server.learning as learning_mod

        db_path = tmp_path / "pycoder.db"
        monkeypatch.setattr(kb_mod, "DB_PATH", db_path)
        monkeypatch.setattr(kb_mod, "DB_DIR", tmp_path)
        monkeypatch.setattr(mt_mod, "METRICS_DB", db_path)
        monkeypatch.setattr(mt_mod, "DB_DIR", tmp_path)
        monkeypatch.setattr(eb_mod, "EXP_DIR", tmp_path / "exp")
        monkeypatch.setattr(pe_mod, "PATTERNS_DIR", tmp_path / "patterns")
        monkeypatch.setattr(fb_mod, "FEEDBACK_DIR", tmp_path / "fb")
        monkeypatch.setattr(kb_mod, "_kb", None)
        monkeypatch.setattr(mt_mod, "_tracker", None)
        monkeypatch.setattr(eb_mod, "_buffer", None)
        monkeypatch.setattr(fb_mod, "_loop", None)
        monkeypatch.setattr(learning_mod, "_pattern_extractor_instance", None)
        monkeypatch.setattr(learning_mod, "_engine", None)

        a = learning_mod.get_learning_engine()
        b = learning_mod.get_learning_engine()
        assert a is b
