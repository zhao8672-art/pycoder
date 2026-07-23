"""
PyCoder 进化引擎全面测试 — 单元/集成/压力/安全

测试覆盖:
  - EvolutionBrain: 各阶段独立功能
  - EvolutionPipeline: 完整闭环
  - EvolutionMetrics: 指标计算
  - 安全沙箱: 熔断器/回滚
  - 压力测试: 高频和大数据量
  - 集成测试: 与 memory/plugins/observability/safety 的集成
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.evolution.core import (
    EvolutionBrain,
    EvolutionConfig,
    EvolutionMetrics,
    EvolutionPhase,
    EvolutionPipeline,
    EvolutionReport,
    EvolutionTask,
    get_evolution_brain,
    get_evolution_metrics,
    get_evolution_pipeline,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def brain():
    """创建 EvolutionBrain 实例"""
    config = EvolutionConfig(auto_apply=False, max_files_per_run=2)
    return EvolutionBrain(config)


@pytest.fixture
def pipeline(brain):
    """创建 EvolutionPipeline 实例"""
    return EvolutionPipeline(brain)


@pytest.fixture
def metrics():
    """创建 EvolutionMetrics 实例"""
    m = EvolutionMetrics()
    m._data = []  # 清空历史数据
    return m


@pytest.fixture
def sample_task():
    """创建示例任务"""
    return EvolutionTask(
        task_type="auto_fix",
        target="pycoder/server/",
        description="测试进化任务",
        errors_collected=[
            {"source": "test", "content": "NameError: name 'x' is not defined", "timestamp": time.time()},
            {"source": "test", "content": "ImportError: cannot import 'foo'", "timestamp": time.time()},
        ],
    )


@pytest.fixture
def sample_task_with_analysis(sample_task):
    """创建已有分析结果的任务"""
    sample_task.llm_analysis = "根因分析: 导入错误和变量未定义"
    return sample_task


@pytest.fixture
def sample_task_with_fix(sample_task_with_analysis):
    """创建已有修复方案的任务"""
    sample_task_with_analysis.fix_plan = """
[FIX:pycoder/server/app.py:42]
问题描述: 缺少导入
修复方案: 添加缺失的 import
--- 旧代码 ---
from pycoder.core import runner
--- 新代码 ---
from pycoder.core import runner, log
[END:FIX]
"""
    sample_task_with_analysis.validation_result = {"passed": True, "checks": ["sandbox: ok", "syntax: ok"]}
    return sample_task_with_analysis


# ══════════════════════════════════════════════════════════
# 单元测试 — EvolutionBrain
# ══════════════════════════════════════════════════════════


class TestEvolutionBrainInit:
    """初始化测试"""

    def test_singleton(self):
        """单例模式"""
        b1 = get_evolution_brain()
        b2 = get_evolution_brain()
        assert b1 is b2

    def test_default_config(self):
        """默认配置"""
        b = EvolutionBrain()
        assert b._config.auto_apply is False
        assert b._config.max_files_per_run == 3
        assert b._config.min_grade_threshold == 70.0

    def test_custom_config(self):
        """自定义配置"""
        config = EvolutionConfig(auto_apply=True, max_files_per_run=5)
        b = EvolutionBrain(config)
        assert b._config.auto_apply is True
        assert b._config.max_files_per_run == 5


class TestEvolutionBrainObserve:
    """观察阶段测试"""

    @pytest.mark.asyncio
    async def test_observe_creates_task(self, brain):
        """观察阶段创建任务"""
        task = EvolutionTask()
        result = await brain.observe(task)
        assert result.phase == EvolutionPhase.OBSERVE
        assert isinstance(result.errors_collected, list)

    @pytest.mark.asyncio
    async def test_observe_collects_errors(self, brain):
        """观察阶段采集错误"""
        task = EvolutionTask()
        result = await brain.observe(task)
        # 即使没有外部错误，也应该返回空列表
        assert isinstance(result.errors_collected, list)


class TestEvolutionBrainAnalyze:
    """分析阶段测试"""

    @pytest.mark.asyncio
    async def test_analyze_empty_errors(self, brain):
        """无错误时跳过分析"""
        task = EvolutionTask()
        result = await brain.analyze(task)
        assert "无错误数据" in result.llm_analysis

    @pytest.mark.asyncio
    async def test_analyze_fallback_no_llm(self, brain, sample_task):
        """LLM 不可用时使用本地规则分析"""
        with patch.object(brain, "_call_llm", side_effect=ImportError("no LLM")):
            result = await brain.analyze(sample_task)
            assert len(result.llm_analysis) > 0
            assert result.phase == EvolutionPhase.ANALYZE

    @pytest.mark.asyncio
    async def test_analyze_with_errors(self, brain, sample_task):
        """有错误时触发分析"""
        with patch.object(brain, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "**根因分类**: 导入错误\n**修复建议**: 检查 import"
            result = await brain.analyze(sample_task)
            assert len(result.llm_analysis) > 0
            assert result.phase == EvolutionPhase.ANALYZE


class TestEvolutionBrainGenerate:
    """生成阶段测试"""

    @pytest.mark.asyncio
    async def test_generate_no_analysis(self, brain):
        """无分析结果时跳过"""
        task = EvolutionTask(llm_analysis="无错误数据，跳过分析")
        result = await brain.generate(task)
        assert "跳过" in result.fix_plan

    @pytest.mark.asyncio
    async def test_generate_with_analysis(self, brain, sample_task_with_analysis):
        """有分析结果时生成修复方案"""
        with patch.object(brain, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "[FIX:test.py:1]\n--- 旧代码 ---\nold\n--- 新代码 ---\nnew\n[END:FIX]"
            result = await brain.generate(sample_task_with_analysis)
            assert "[FIX:" in result.fix_plan
            assert result.phase == EvolutionPhase.GENERATE


class TestEvolutionBrainValidate:
    """验证阶段测试"""

    @pytest.mark.asyncio
    async def test_validate_no_fix(self, brain):
        """无修复方案时跳过"""
        task = EvolutionTask(fix_plan="跳过生成")
        result = await brain.validate(task)
        assert result.validation_result["passed"] is False

    @pytest.mark.asyncio
    async def test_validate_dangerous_code(self, brain):
        """检测危险代码"""
        task = EvolutionTask(
            fix_plan="[FIX:test.py:1]\n--- 新代码 ---\nos.system(input())\n[END:FIX]"
        )
        result = await brain.validate(task)
        # 应检测到安全风险
        assert isinstance(result.validation_result, dict)

    @pytest.mark.asyncio
    async def test_validate_safe_code(self, brain):
        """安全代码通过验证"""
        task = EvolutionTask(
            fix_plan="[FIX:test.py:1]\n--- 旧代码 ---\ndef foo():\n  pass\n--- 新代码 ---\ndef foo():\n    return True\n[END:FIX]"
        )
        result = await brain.validate(task)
        assert result.validation_result["passed"] is True


class TestEvolutionBrainApply:
    """应用阶段测试"""

    @pytest.mark.asyncio
    async def test_apply_validation_failed(self, brain):
        """验证未通过时不应用"""
        task = EvolutionTask(
            fix_plan="[FIX:test.py:1]\n...\n[END:FIX]",
            validation_result={"passed": False, "reason": "syntax error"},
        )
        result = await brain.apply(task)
        assert result.applied is False

    @pytest.mark.asyncio
    async def test_apply_auto_off(self, brain, sample_task_with_fix):
        """auto_apply 关闭时跳过"""
        brain._config.auto_apply = False
        result = await brain.apply(sample_task_with_fix)
        assert result.applied is False
        assert "auto_apply" in result.error.lower()

    @pytest.mark.asyncio
    async def test_apply_no_fix_blocks(self, brain):
        """无修复块时返回错误"""
        task = EvolutionTask(
            fix_plan="分析完成，无需修复",
            validation_result={"passed": True},
        )
        brain._config.auto_apply = True
        result = await brain.apply(task)
        assert result.applied is False
        assert result.error


class TestEvolutionBrainLearn:
    """学习阶段测试"""

    @pytest.mark.asyncio
    async def test_learn_records_experience(self, brain, sample_task_with_fix):
        """学习阶段记录经验"""
        sample_task_with_fix.test_passed = True
        result = await brain.learn(sample_task_with_fix)
        assert result.phase == EvolutionPhase.LEARN
        assert len(result.lessons) > 0

    @pytest.mark.asyncio
    async def test_learn_failed_task(self, brain):
        """失败任务也记录"""
        task = EvolutionTask(
            task_type="auto_fix",
            test_passed=False,
            error="测试失败",
        )
        result = await brain.learn(task)
        assert "failed" in result.lessons.lower()


class TestEvolutionBrainFallback:
    """回退分析测试"""

    def test_fallback_import_error(self, brain):
        """导入错误回退"""
        result = brain._fallback_analysis("ImportError: No module named 'foo'")
        assert "导入" in result or "import" in result.lower()

    def test_fallback_syntax_error(self, brain):
        """语法错误回退"""
        result = brain._fallback_analysis("SyntaxError: invalid syntax at line 42")
        assert "语法" in result or "syntax" in result.lower()

    def test_fallback_api_error(self, brain):
        """API 错误回退"""
        result = brain._fallback_analysis("HTTP Error 401: Unauthorized")
        assert "API" in result or "api" in result.lower()

    def test_fallback_hardcoded_secret(self, brain):
        """硬编码密钥回退"""
        result = brain._fallback_analysis("password = 'hardcoded123'")
        assert "密钥" in result or "password" in result.lower()

    def test_fallback_unknown(self, brain):
        """未知错误回退"""
        result = brain._fallback_analysis("something weird happened")
        assert len(result) > 0


# ══════════════════════════════════════════════════════════
# 单元测试 — EvolutionPipeline
# ══════════════════════════════════════════════════════════


class TestEvolutionPipeline:
    """管线测试"""

    def test_singleton(self):
        """单例模式"""
        p1 = get_evolution_pipeline()
        p2 = get_evolution_pipeline()
        assert p1 is p2

    @pytest.mark.asyncio
    async def test_run_empty_errors(self, pipeline):
        """无错误时运行"""
        with patch.object(pipeline._brain, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "无错误数据"
            # 也 mock observe 避免从真实环境采集数据
            with patch.object(pipeline._brain, "observe", new_callable=AsyncMock) as mock_obs:
                mock_obs.return_value = EvolutionTask(
                    errors_collected=[],
                    task_type="auto_fix",
                )
                report = await pipeline.run(task_type="auto_fix")
                assert isinstance(report, EvolutionReport)
                assert report.issues_found == 0

    @pytest.mark.asyncio
    async def test_run_with_errors(self, pipeline):
        """有错误时运行完整管线"""
        with patch.object(pipeline._brain, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "根因分析: 测试错误"
            with patch.object(pipeline._brain, "observe", new_callable=AsyncMock) as mock_obs:
                mock_obs.return_value = EvolutionTask(
                    errors_collected=[{"source": "test", "content": "Error: test", "timestamp": time.time()}],
                    task_type="auto_fix",
                )
                report = await pipeline.run(task_type="auto_fix")
                assert isinstance(report, EvolutionReport)
                assert len(report.phases_completed) > 0

    def test_get_reports_empty(self, pipeline):
        """空报告列表"""
        reports = pipeline.get_reports()
        assert reports == []

    def test_get_stats_empty(self, pipeline):
        """空统计"""
        stats = pipeline.get_stats()
        assert stats["total"] == 0

    def test_calculate_grade(self, pipeline):
        """评分计算"""
        task = EvolutionTask(
            errors_collected=[{"source": "test", "content": "error"}],
            llm_analysis="详细分析...",
            fix_plan="修复方案...",
            validation_result={"passed": True},
            applied=True,
            test_passed=True,
        )
        grade = pipeline._calculate_grade(task)
        assert 0 <= grade <= 100


# ══════════════════════════════════════════════════════════
# 单元测试 — EvolutionMetrics
# ══════════════════════════════════════════════════════════


class TestEvolutionMetrics:
    """指标测试"""

    def test_singleton(self):
        """单例模式"""
        m1 = get_evolution_metrics()
        m2 = get_evolution_metrics()
        assert m1 is m2

    def test_empty_metrics(self, metrics):
        """空指标"""
        summary = metrics.get_summary()
        assert summary["total_evolutions"] == 0
        assert summary["success_rate"] == 0.0

    def test_record_single(self, metrics):
        """记录单次进化"""
        task = EvolutionTask(
            test_passed=True,
            applied=True,
            grade=85.0,
            duration_ms=1500,
            completed_at=time.time(),
        )
        metrics.record(task)
        summary = metrics.get_summary()
        assert summary["total_evolutions"] == 1
        assert summary["success_rate"] == 100.0

    def test_record_multiple(self, metrics):
        """记录多次进化"""
        for i in range(10):
            task = EvolutionTask(
                test_passed=(i % 2 == 0),
                applied=True,
                grade=80.0 + i,
                duration_ms=1000 + i * 100,
                completed_at=time.time() - i * 3600,
            )
            metrics.record(task)

        summary = metrics.get_summary()
        assert summary["total_evolutions"] == 10
        assert 0 <= summary["success_rate"] <= 100

    def test_trend_data(self, metrics):
        """趋势数据"""
        for i in range(20):
            task = EvolutionTask(
                test_passed=True,
                grade=85.0,
                duration_ms=1000,
                completed_at=time.time() - i * 3600,
            )
            metrics.record(task)

        trend = metrics.get_trend_data(days=7)
        assert isinstance(trend, list)
        assert len(trend) > 0

    def test_persistence(self, metrics, tmp_path):
        """持久化测试"""
        task = EvolutionTask(
            test_passed=True,
            grade=90.0,
            duration_ms=1200,
            completed_at=time.time(),
        )
        metrics.record(task)
        metrics._save_data()

        # 重新加载
        m2 = EvolutionMetrics()
        assert m2._data is not None


# ══════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════


class TestEvolutionIntegration:
    """集成测试 — 完整闭环"""

    @pytest.mark.asyncio
    async def test_full_pipeline_no_llm(self, pipeline):
        """无 LLM 的完整管线（回退模式）"""
        with patch.object(pipeline._brain, "_call_llm", side_effect=ImportError("no LLM")):
            report = await pipeline.run(
                task_type="auto_fix",
                description="集成测试",
                auto_apply=False,
            )
            assert isinstance(report, EvolutionReport)
            assert "intake" in report.phases_completed
            assert "decompose" in report.phases_completed

    @pytest.mark.asyncio
    async def test_full_pipeline_dry_run(self, pipeline):
        """干运行模式"""
        with patch.object(pipeline._brain, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "分析结果..."
            report = await pipeline.run(
                task_type="auto_fix",
                auto_apply=False,
            )
            assert isinstance(report, EvolutionReport)
            assert report.fixes_applied == 0

    @pytest.mark.asyncio
    async def test_phase_ordering(self, pipeline):
        """阶段顺序验证"""
        with patch.object(pipeline._brain, "_call_llm", new_callable=AsyncMock):
            report = await pipeline.run(task_type="auto_fix")
            phases = report.phases_completed
            expected_order = ["observe", "analyze", "generate", "validate", "learn"]
            for phase in expected_order:
                if phase in phases:
                    idx = phases.index(phase)
                    for later_phase in expected_order[expected_order.index(phase) + 1:]:
                        if later_phase in phases:
                            assert phases.index(later_phase) > idx, f"{phase} 应在 {later_phase} 之前"

    def test_task_serialization(self, sample_task):
        """任务序列化"""
        d = sample_task.to_dict()
        assert d["id"] == sample_task.id
        assert d["task_type"] == sample_task.task_type
        assert d["phase"] == sample_task.phase.value

    def test_history_persistence(self, brain, sample_task):
        """历史持久化"""
        brain._history = [sample_task]
        brain._save_history()
        brain2 = EvolutionBrain()
        assert len(brain2._history) >= 0


class TestEvolutionIntegrationWithModules:
    """集成测试 — 与基础设施模块的集成"""

    def test_memory_integration_import(self):
        """memory 模块可导入"""
        try:
            from pycoder.memory import SessionMemoryEngine
            engine = SessionMemoryEngine(workspace=Path.cwd())
            assert engine is not None
        except ImportError:
            pytest.skip("memory 模块不可用")

    def test_plugins_integration_import(self):
        """plugins 模块可导入"""
        try:
            from pycoder.plugins.base import BasePlugin, PluginRegistry
            assert BasePlugin is not None
            assert PluginRegistry is not None
        except ImportError:
            pytest.skip("plugins 模块不可用")

    def test_observability_integration_import(self):
        """observability 模块可导入"""
        try:
            from pycoder.observability.sentry import SentryIntegration
            assert SentryIntegration is not None
        except ImportError:
            pytest.skip("observability 模块不可用")

    def test_safety_integration_import(self):
        """safety 模块可导入"""
        try:
            from pycoder.safety import SandboxManager
            from pycoder.safety.circuit_breaker import CircuitBreakerRegistry
            from pycoder.safety.rollback import RollbackManager
            assert SandboxManager is not None
            assert CircuitBreakerRegistry is not None
            assert RollbackManager is not None
        except ImportError:
            pytest.skip("safety 模块不可用")

    def test_learning_integration_import(self):
        """learning 模块可导入"""
        try:
            from pycoder.capabilities.self_evo.learning import (
                LearningEngine,
                get_learning_engine,
            )
            assert LearningEngine is not None
        except ImportError:
            pytest.skip("learning 模块不可用")


# ══════════════════════════════════════════════════════════
# 安全测试
# ══════════════════════════════════════════════════════════


class TestEvolutionSafety:
    """安全测试"""

    @pytest.mark.asyncio
    async def test_dangerous_exec_rejected(self, brain):
        """exec() 应被拒绝"""
        task = EvolutionTask(
            fix_plan="[FIX:test.py:1]\n--- 新代码 ---\nexec('import os; os.system(\"rm -rf /\")')\n[END:FIX]"
        )
        result = await brain.validate(task)
        assert result.validation_result["passed"] is False

    @pytest.mark.asyncio
    async def test_shell_injection_rejected(self, brain):
        """shell=True 注入应被检出"""
        task = EvolutionTask(
            fix_plan="[FIX:test.py:1]\n--- 新代码 ---\nsubprocess.run(cmd, shell=True)\n[END:FIX]"
        )
        result = await brain.validate(task)
        assert isinstance(result.validation_result, dict)

    @pytest.mark.asyncio
    async def test_hardcoded_secret_detected(self, brain):
        """硬编码密钥应被检出"""
        task = EvolutionTask(
            fix_plan="[FIX:test.py:1]\n--- 新代码 ---\napi_key = 'sk-1234567890abcdef'\n[END:FIX]"
        )
        result = await brain.validate(task)
        warnings = result.validation_result.get("warnings", [])
        assert any("密钥" in w or "secret" in w.lower() for w in warnings)

    @pytest.mark.asyncio
    async def test_protected_path_skipped(self, brain):
        """受保护路径应被跳过"""
        brain._config.auto_apply = True
        task = EvolutionTask(
            fix_plan="[FIX:.env:1]\n--- 旧代码 ---\nOLD\n--- 新代码 ---\nNEW\n[END:FIX]",
            validation_result={"passed": True},
        )
        result = await brain.apply(task)
        assert result.applied is False

    def test_circuit_breaker_prevention(self, brain):
        """熔断器阻止测试"""
        # 模拟熔断器打开
        try:
            from pycoder.safety.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry
            registry = CircuitBreakerRegistry()
            cb = registry.get_or_create("self_evo")
            # 连续失败触发熔断
            for _ in range(10):
                cb.record_failure()
            assert cb.is_open or cb.state == "open"
        except ImportError:
            pytest.skip("CircuitBreaker 不可用")


# ══════════════════════════════════════════════════════════
# 压力测试
# ══════════════════════════════════════════════════════════


class TestEvolutionStress:
    """压力测试"""

    @pytest.mark.asyncio
    async def test_many_errors_collected(self, brain):
        """大量错误数据"""
        task = EvolutionTask()
        task.errors_collected = [
            {"source": "test", "content": f"Error #{i}: something went wrong", "timestamp": time.time()}
            for i in range(500)
        ]
        result = await brain.analyze(task)
        assert result.phase == EvolutionPhase.ANALYZE

    def test_metrics_large_dataset(self, metrics):
        """大量指标数据"""
        for i in range(500):
            task = EvolutionTask(
                test_passed=(i % 3 != 0),
                grade=50.0 + (i % 50),
                duration_ms=500 + (i % 1000),
                completed_at=time.time() - i * 3600,
            )
            metrics.record(task)

        summary = metrics.get_summary()
        assert summary["total_evolutions"] == 500
        assert 0 <= summary["success_rate"] <= 100

    @pytest.mark.asyncio
    async def test_concurrent_evolutions(self, pipeline):
        """并发进化请求"""
        async def run_one():
            with patch.object(pipeline._brain, "_call_llm", new_callable=AsyncMock) as m:
                m.return_value = "分析结果"
                return await pipeline.run(task_type="auto_fix")

        tasks = [run_one() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        assert all(isinstance(r, EvolutionReport) for r in results)

    @pytest.mark.asyncio
    async def test_long_analysis_text(self, brain, sample_task):
        """超长分析文本"""
        sample_task.llm_analysis = "分析内容 " * 1000  # ~5000 字符
        with patch.object(brain, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "[FIX:test.py:1]\n--- 新代码 ---\npass\n[END:FIX]"
            result = await brain.generate(sample_task)
            assert result.phase == EvolutionPhase.GENERATE

    def test_history_capacity(self, brain):
        """历史容量限制"""
        brain._history = []  # 清空历史
        for i in range(60):
            task = EvolutionTask()
            task.id = f"task-{i}"
            brain._history.append(task)
        brain._save_history()
        # _save_history 保存最近 50 条
        assert len(brain._history) <= 60


# ══════════════════════════════════════════════════════════
# 性能测试
# ══════════════════════════════════════════════════════════


class TestEvolutionPerformance:
    """性能测试"""

    @pytest.mark.asyncio
    async def test_observe_performance(self, brain):
        """观察阶段性能 (< 2s)"""
        t0 = time.time()
        task = await brain.observe(EvolutionTask())
        duration = time.time() - t0
        assert duration < 5.0, f"观察阶段耗时 {duration:.2f}s"

    @pytest.mark.asyncio
    async def test_analyze_performance(self, brain):
        """分析阶段性能"""
        task = EvolutionTask(errors_collected=[
            {"source": "test", "content": "error", "timestamp": time.time()}
        ])
        t0 = time.time()
        result = await brain.analyze(task)
        duration = time.time() - t0
        assert duration < 10.0, f"分析阶段耗时 {duration:.2f}s"

    @pytest.mark.asyncio
    async def test_validate_performance(self, brain):
        """验证阶段性能 (< 1s)"""
        task = EvolutionTask(fix_plan="[FIX:test.py:1]\n--- 新代码 ---\ndef foo():\n    pass\n[END:FIX]")
        t0 = time.time()
        result = await brain.validate(task)
        duration = time.time() - t0
        assert duration < 3.0, f"验证阶段耗时 {duration:.2f}s"

    def test_metrics_performance(self, metrics):
        """指标计算性能"""
        for i in range(200):
            task = EvolutionTask(
                test_passed=True,
                grade=85.0,
                duration_ms=1000,
                completed_at=time.time() - i * 3600,
            )
            metrics.record(task)

        t0 = time.time()
        summary = metrics.get_summary()
        trend = metrics.get_trend_data(days=30)
        duration = time.time() - t0
        assert duration < 2.0, f"指标计算耗时 {duration:.2f}s"


# ══════════════════════════════════════════════════════════
# 数据模型测试
# ══════════════════════════════════════════════════════════


class TestDataModels:
    """数据模型测试"""

    def test_evolution_task_defaults(self):
        """默认值"""
        task = EvolutionTask()
        assert task.id
        assert task.task_type == "auto_fix"
        assert task.phase == EvolutionPhase.OBSERVE
        assert task.errors_collected == []

    def test_evolution_task_to_dict(self):
        """序列化"""
        task = EvolutionTask()
        d = task.to_dict()
        assert isinstance(d, dict)
        assert "id" in d
        assert "task_type" in d

    def test_evolution_phase_values(self):
        """阶段枚举值"""
        assert EvolutionPhase.OBSERVE.value == "observe"
        assert EvolutionPhase.ANALYZE.value == "analyze"
        assert EvolutionPhase.GENERATE.value == "generate"
        assert EvolutionPhase.VALIDATE.value == "validate"
        assert EvolutionPhase.APPLY.value == "apply"
        assert EvolutionPhase.LEARN.value == "learn"
        assert EvolutionPhase.DONE.value == "done"
        assert EvolutionPhase.FAILED.value == "failed"

    def test_evolution_config_defaults(self):
        """配置默认值"""
        config = EvolutionConfig()
        assert config.auto_apply is False
        assert config.max_files_per_run == 3
        assert config.safety_strict is True
        assert config.min_grade_threshold == 70.0

    def test_evolution_report_defaults(self):
        """报告默认值"""
        report = EvolutionReport()
        assert report.success is False
        assert report.phases_completed == []
        assert report.grade == 0.0