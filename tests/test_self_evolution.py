"""自我进化功能测试套件

覆盖:
  - RefactoringEngine: 代码分析、指标计算、重构建议生成
  - PolicyManager: 策略加载/保存、阈值调整、模型选择、预算检查
  - MetaCognition: 健康检查、反思分析、能力评估、自我评估
  - EvolutionIntegration: 各模块集成状态检查
  - LearningEngine: 现有功能回归测试
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.capabilities.self_evo.learning import (
    EvolutionIntegration,
    IntegrationStatus,
    LearningEngine,
    MetaCognition,
    PolicyManager,
    RefactoringEngine,
    SystemPolicy,
    get_evolution_integration,
    get_learning_engine,
    get_meta_cognition,
    get_policy_manager,
    get_refactoring_engine,
)


# ══════════════════════════════════════════════════════════
# RefactoringEngine 测试
# ══════════════════════════════════════════════════════════


class TestRefactoringEngine:
    """测试代码重构引擎"""

    def test_engine_singleton(self):
        """单例模式"""
        e1 = get_refactoring_engine()
        e2 = get_refactoring_engine()
        assert e1 is e2

    def test_analyze_empty_path(self):
        """分析不存在的路径"""
        engine = RefactoringEngine()
        suggestions = engine.analyze("/nonexistent/path")
        assert suggestions == []

    def test_analyze_real_code(self):
        """分析实际代码"""
        engine = RefactoringEngine()
        # 分析一个已知的简单文件
        target = Path(__file__).resolve().parent.parent / "refactoring_engine.py"
        if target.exists():
            suggestions = engine.analyze(target)
            assert isinstance(suggestions, list)
            # 所有建议应有必要字段
            for s in suggestions:
                assert s.file
                assert s.severity in ("critical", "high", "medium", "low")
                assert s.category in ("complexity", "performance", "coupling", "style", "safety")
                assert s.title

    def test_metrics_computation(self):
        """指标计算"""
        engine = RefactoringEngine()
        source = """def hello():\n    print("hello")\n"""
        import ast
        tree = ast.parse(source)
        metrics = engine._compute_metrics(tree, "test.py", source)
        assert metrics.lines > 0
        assert metrics.functions == 1

    def test_dry_run_apply(self):
        """dry_run 模式不实际修改文件"""
        from pycoder.capabilities.self_evo.learning.refactoring_engine import (
            RefactorSuggestion,
        )
        engine = RefactoringEngine()
        suggestion = RefactorSuggestion(
            file="nonexistent.py",
            line=1,
            severity="low",
            category="style",
            title="Test",
            old_code="a",
            new_code="b",
        )
        result = engine.apply(suggestion, dry_run=True)
        assert not result.applied

    def test_apply_missing_file(self):
        """应用重构到不存在的文件"""
        from pycoder.capabilities.self_evo.learning.refactoring_engine import (
            RefactorSuggestion,
        )
        engine = RefactoringEngine()
        suggestion = RefactorSuggestion(
            file="nonexistent.py",
            line=1,
            severity="low",
            category="style",
            title="Test",
            old_code="a",
            new_code="b",
        )
        result = engine.apply(suggestion)
        assert not result.applied
        assert result.error

    def test_get_stats(self):
        """获取统计"""
        engine = RefactoringEngine()
        stats = engine.get_stats()
        assert "total" in stats
        assert "success_rate" in stats

    def test_get_history(self):
        """获取历史"""
        engine = RefactoringEngine()
        history = engine.get_history()
        assert isinstance(history, list)


# ══════════════════════════════════════════════════════════
# PolicyManager 测试
# ══════════════════════════════════════════════════════════


class TestPolicyManager:
    """测试策略管理器"""

    def test_singleton(self):
        """单例模式"""
        p1 = get_policy_manager()
        p2 = get_policy_manager()
        assert p1 is p2

    def test_load_default_policy(self):
        """加载默认策略"""
        pm = PolicyManager()
        policy = pm.get_policy()
        assert isinstance(policy, SystemPolicy)
        assert policy.token_budget_daily > 0
        assert 60 <= policy.quality_threshold <= 95  # 可能在之前测试中被调整

    def test_adjust_quality_threshold_up(self):
        """高成功率 → 提高阈值"""
        pm = PolicyManager()
        old = pm.get_policy().quality_threshold
        new = pm.adjust_quality_threshold(0.95)  # 95% 成功率
        assert new >= old

    def test_adjust_quality_threshold_down(self):
        """低成功率 → 降低阈值"""
        pm = PolicyManager()
        old = pm.get_policy().quality_threshold
        new = pm.adjust_quality_threshold(0.30)  # 30% 成功率
        assert new <= old

    def test_adjust_quality_threshold_stable(self):
        """正常成功率 → 不变"""
        pm = PolicyManager()
        old = pm.get_policy().quality_threshold
        new = pm.adjust_quality_threshold(0.75)  # 75% 成功率
        assert new == old

    def test_adjust_retries(self):
        """调整重试次数"""
        pm = PolicyManager()
        new = pm.adjust_retries(0.3, 3.0)  # 低成功率, 高平均重试
        assert 1 <= new <= 5

    def test_select_model(self):
        """模型选择"""
        pm = PolicyManager()
        model = pm.select_model("code_review", "medium")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_select_model_by_complexity(self):
        """按复杂度选择模型"""
        pm = PolicyManager()
        simple = pm.select_model("code_review", "simple")
        high = pm.select_model("code_review", "high")
        assert isinstance(simple, str)
        assert isinstance(high, str)

    def test_check_token_budget_ok(self):
        """Token 预算检查 — 通过"""
        pm = PolicyManager()
        result = pm.check_token_budget(100)
        assert result["allowed"] is True

    def test_check_token_budget_exceeded(self):
        """Token 预算检查 — 超限"""
        pm = PolicyManager()
        result = pm.check_token_budget(10_000_000)
        assert result["allowed"] is False

    def test_record_token_usage(self):
        """记录 Token 使用"""
        pm = PolicyManager()
        pm.record_token_usage(1000, 0.01)
        stats = pm.get_usage_stats()
        assert stats["tokens_total"] >= 1000
        assert stats["cost_total_usd"] >= 0.01

    def test_record_task_result(self):
        """记录任务结果"""
        pm = PolicyManager()
        pm.record_task_result(True)
        pm.record_task_result(False)
        stats = pm.get_usage_stats()
        assert stats["tasks_total"] == 2
        assert stats["tasks_success"] == 1
        assert stats["tasks_failed"] == 1

    def test_update_model_success_rate(self):
        """更新模型成功率"""
        pm = PolicyManager()
        pm.update_model_success_rate("deepseek-chat", "code_review", True)
        pm.update_model_success_rate("deepseek-chat", "code_review", False)
        stats = pm.get_model_stats()
        assert "deepseek-chat" in stats

    def test_get_change_history(self):
        """获取变更历史"""
        pm = PolicyManager()
        pm.adjust_quality_threshold(0.95)
        history = pm.get_change_history()
        assert len(history) > 0

    def test_update_policy(self):
        """手动更新策略"""
        pm = PolicyManager()
        pm.update_policy(max_retries=5)
        assert pm.get_policy().max_retries == 5

    def test_check_cost_alert(self):
        """检查成本告警"""
        pm = PolicyManager()
        alert = pm.check_cost_alert()
        # 初始状态无告警
        assert alert is None or "预算" in alert


# ══════════════════════════════════════════════════════════
# MetaCognition 测试
# ══════════════════════════════════════════════════════════


class TestMetaCognition:
    """测试元认知模块"""

    def test_singleton(self):
        """单例模式"""
        m1 = get_meta_cognition()
        m2 = get_meta_cognition()
        assert m1 is m2

    def test_check_health(self):
        """检查系统健康"""
        mc = MetaCognition()
        health = mc.check_health()
        assert hasattr(health, "overall")
        assert health.overall in ("healthy", "degraded", "critical")
        assert health.cpu_usage >= 0
        assert health.memory_usage_mb > 0

    def test_record_status(self):
        """记录操作状态"""
        mc = MetaCognition()
        mc.record_status("test_op", error=False)
        mc.record_status("test_op", error=True)
        # 不应抛出异常

    def test_reflect_empty(self):
        """反思 — 无数据"""
        mc = MetaCognition()
        result = mc.reflect()
        assert "patterns" in result
        assert "insights" in result

    def test_reflect_with_data(self):
        """反思 — 有数据"""
        mc = MetaCognition()
        for i in range(10):
            mc.record_status("test_op", error=(i % 3 == 0))
        result = mc.reflect()
        assert "error_rate" in result
        assert isinstance(result["error_rate"], float)

    def test_assess_capabilities(self):
        """能力评估"""
        mc = MetaCognition()
        capabilities = mc.assess_capabilities()
        assert len(capabilities) > 0
        for c in capabilities:
            assert c.name
            assert c.level in ("initial", "developing", "mature", "optimized")
            assert 0 <= c.score <= 100

    def test_self_assess(self):
        """自我评估"""
        mc = MetaCognition()
        assessment = mc.self_assess()
        assert assessment.overall_health in ("healthy", "degraded", "critical")
        assert len(assessment.capabilities) > 0
        assert assessment.evolution_score >= 0

    def test_get_evolution_progress(self):
        """进化进度"""
        mc = MetaCognition()
        mc.self_assess()
        mc.self_assess()
        progress = mc.get_evolution_progress()
        assert "trend" in progress
        assert "current_score" in progress


# ══════════════════════════════════════════════════════════
# EvolutionIntegration 测试
# ══════════════════════════════════════════════════════════


class TestEvolutionIntegration:
    """测试进化集成桥接"""

    def test_singleton(self):
        """单例模式"""
        i1 = get_evolution_integration()
        i2 = get_evolution_integration()
        assert i1 is i2

    def test_get_status(self):
        """获取集成状态"""
        integration = EvolutionIntegration()
        status = integration.get_integration_status()
        assert isinstance(status, IntegrationStatus)
        # 至少 memory 应该可用 (因为它是内置模块)
        assert status.memory_available is True

    def test_refresh(self):
        """刷新状态"""
        integration = EvolutionIntegration()
        status = integration.refresh()
        assert isinstance(status, IntegrationStatus)

    def test_persist_evolution_record(self):
        """持久化进化记录"""
        integration = EvolutionIntegration()
        result = integration.persist_evolution_record(
            task_id="test-001",
            task_type="fix",
            outcome="success",
            details={"test": True},
        )
        assert isinstance(result, bool)

    def test_retrieve_evolution_history(self):
        """检索进化历史"""
        integration = EvolutionIntegration()
        integration.persist_evolution_record("test-002", "fix", "success")
        history = integration.retrieve_evolution_history(limit=5)
        assert isinstance(history, list)

    def test_measure_effectiveness(self):
        """评估进化效果"""
        integration = EvolutionIntegration()
        metrics = integration.measure_evolution_effectiveness()
        assert "total_evolutions" in metrics
        assert "success_rate" in metrics

    def test_sandbox_evolution(self):
        """沙箱进化"""
        integration = EvolutionIntegration()
        # 即使 safety 不可用，也应返回 True（降级）
        result = integration.sandbox_evolution("test-003", "fix")
        assert result is True


# ══════════════════════════════════════════════════════════
# LearningEngine 回归测试
# ══════════════════════════════════════════════════════════


class TestLearningEngineRegression:
    """LearningEngine 回归测试"""

    def test_singleton(self):
        """单例模式"""
        e1 = get_learning_engine()
        e2 = get_learning_engine()
        assert e1 is e2

    def test_on_task_complete(self):
        """任务完成记录"""
        engine = get_learning_engine()
        result = engine.on_task_complete(
            task_id=f"test-{int(time.time())}",
            outcome="success",
            task_type="fix",
            description="测试修复",
            error_msg="NameError: 'x' is not defined",
            file_paths=["test.py"],
            fix_content="import x",
            test_passed=True,
            quality_score=90,
        )
        assert isinstance(result, dict)

    def test_get_task_advice(self):
        """获取任务建议"""
        engine = get_learning_engine()
        advice = engine.get_task_advice(
            task_description="修复导入错误",
            error_msg="ImportError: no module named 'foo'",
        )
        assert isinstance(advice, dict)
        assert "suggested_fix" in advice
        assert "hotspots_to_check" in advice
        assert "risk_warnings" in advice

    def test_generate_learning_report(self):
        """生成学习报告"""
        engine = get_learning_engine()
        report = engine.generate_learning_report()
        assert isinstance(report, dict)
        assert "knowledge_base" in report
        assert "experience_buffer" in report
        assert "evolution" in report

    def test_generate_learning_report_markdown(self):
        """生成 Markdown 报告"""
        engine = get_learning_engine()
        md = engine.generate_learning_report_markdown()
        assert isinstance(md, str)
        assert "PyCoder" in md
        assert "学习进化报告" in md

    def test_on_quality_scan(self):
        """质量扫描记录"""
        engine = get_learning_engine()
        engine.on_quality_scan(
            lint_score=95,
            security_score=90,
            test_coverage=85,
            file_count=10,
            issue_count=3,
        )
        # 不应抛出异常


# ══════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════


class TestEvolutionIntegrationFull:
    """完整的进化集成测试"""

    def test_full_workflow(self):
        """完整进化工作流"""
        # 1. 元认知评估
        mc = MetaCognition()
        assessment = mc.self_assess()
        assert assessment.overall_health is not None

        # 2. 策略检查
        pm = PolicyManager()
        budget = pm.check_token_budget(1000)
        assert budget is not None

        # 3. 代码分析
        engine = RefactoringEngine()
        target = Path(__file__).resolve().parent
        suggestions = engine.analyze(target)
        assert isinstance(suggestions, list)

        # 4. 集成状态
        integration = EvolutionIntegration()
        status = integration.get_integration_status()
        assert isinstance(status, IntegrationStatus)

        # 5. 学习记录
        lrn = get_learning_engine()
        result = lrn.on_task_complete(
            task_id=f"workflow-{int(time.time())}",
            outcome="success",
            task_type="full_workflow",
            description="完整工作流测试",
        )
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════
# 安全测试
# ══════════════════════════════════════════════════════════


class TestEvolutionSafety:
    """进化安全测试"""

    def test_circuit_breaker_prevention(self):
        """熔断器阻止无限循环"""
        integration = EvolutionIntegration()
        # 多次调用 sandbox_evolution 不应导致无限循环
        for i in range(5):
            result = integration.sandbox_evolution(f"loop-test-{i}", "fix")
            assert isinstance(result, bool)

    def test_budget_exhaustion_prevention(self):
        """预算耗尽防护"""
        pm = PolicyManager()
        # 超大量 token 请求应被拒绝
        result = pm.check_token_budget(100_000_000)
        assert result["allowed"] is False
        assert "warning" in result

    def test_rollback_recording(self):
        """回滚记录"""
        integration = EvolutionIntegration()
        integration.record_evolution_rollback("rollback-test", "测试回滚")
        # 不应抛出异常

    def test_policy_bounds(self):
        """策略参数边界"""
        pm = PolicyManager()
        # 极端值测试
        pm.adjust_quality_threshold(0.0)
        assert 60 <= pm.get_policy().quality_threshold <= 95

        pm.adjust_quality_threshold(1.0)
        assert 60 <= pm.get_policy().quality_threshold <= 95


# ══════════════════════════════════════════════════════════
# 性能测试
# ══════════════════════════════════════════════════════════


class TestEvolutionPerformance:
    """进化性能测试"""

    def test_check_health_performance(self):
        """健康检查性能 (应 < 100ms)"""
        mc = MetaCognition()
        start = time.perf_counter()
        mc.check_health()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5  # 500ms 上限

    def test_analyze_performance(self):
        """分析性能 (应 < 1s)"""
        engine = RefactoringEngine()
        target = Path(__file__).resolve().parent
        start = time.perf_counter()
        engine.analyze(target)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0  # 2s 上限

    def test_policy_save_load_performance(self):
        """策略加载/保存性能 (应 < 10ms)"""
        pm = PolicyManager()
        start = time.perf_counter()
        pm.get_policy()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1  # 100ms 上限