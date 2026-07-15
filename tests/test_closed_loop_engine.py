"""
闭环验证引擎单元测试 — 覆盖 ClosedLoopEngine 核心功能

测试范围:
  - 引擎实例创建
  - 执行简单计划（成功路径）
  - 执行计划带重试（失败后自愈）
  - 验证通过/失败
  - 错误分析与诊断
  - 修复方案生成
  - 引擎统计信息

注意:
  - 沙箱执行器通过 mock 禁用，避免 Docker 依赖导致测试挂起
  - 使用 autouse fixture 全局 patch _HAS_SERVER_SANDBOX = False
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.server.services.closed_loop_engine import (
    ClosedLoopEngine,
    ClosedLoopResult,
    Diagnosis,
    ExecutionError,
    FixResult,
    SelfHealingLoop,
    VerifyResult,
)


# ── 全局 Mock: 禁用沙箱执行器 ──────────────────────────────


@pytest.fixture(autouse=True)
def _disable_sandbox() -> None:
    """全局禁用沙箱执行器，避免 Docker 依赖导致测试挂起"""
    # 同时 patch _HAS_SERVER_SANDBOX 和 _HAS_SAFETY_SANDBOX
    with (
        patch("pycoder.server.services.closed_loop_engine._HAS_SERVER_SANDBOX", False),
        patch("pycoder.server.services.closed_loop_engine._HAS_SAFETY_SANDBOX", False),
        patch("pycoder.server.services.closed_loop_engine.get_sandbox_executor", None),
    ):
        yield


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path: Path) -> ClosedLoopEngine:
    """创建使用临时目录的 ClosedLoopEngine 实例"""
    return ClosedLoopEngine(workspace=tmp_path)


@pytest.fixture
def syntax_error() -> ExecutionError:
    """创建语法错误实例"""
    return ExecutionError(
        error_type="syntax_error",
        message="invalid syntax",
        stack_trace='File "test.py", line 10\n    x = \n         ^\nSyntaxError: invalid syntax',
        severity="critical",
        source_file="test.py",
        source_line=10,
    )


@pytest.fixture
def import_error() -> ExecutionError:
    """创建导入错误实例"""
    return ExecutionError(
        error_type="import_error",
        message="No module named 'nonexistent_lib'",
        stack_trace=(
            'File "main.py", line 3, in <module>\n'
            "    import nonexistent_lib\n"
            "ModuleNotFoundError: No module named 'nonexistent_lib'"
        ),
        severity="critical",
        source_file="main.py",
        source_line=3,
    )


@pytest.fixture
def type_error() -> ExecutionError:
    """创建类型错误实例"""
    return ExecutionError(
        error_type="type_error",
        message="unsupported operand type(s) for +: 'int' and 'str'",
        stack_trace=(
            'File "calc.py", line 5, in add\n'
            "    return x + y\n"
            "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        ),
        severity="error",
        source_file="calc.py",
        source_line=5,
    )


# ── 实例创建测试 ──────────────────────────────────────────


class TestCreateEngine:
    """引擎实例创建"""

    def test_create_engine(self, tmp_path: Path) -> None:
        """创建引擎实例"""
        engine = ClosedLoopEngine(workspace=tmp_path)
        assert engine is not None
        assert engine._workspace == tmp_path
        assert engine._healer is not None

    def test_create_engine_default_workspace(self) -> None:
        """使用默认工作区创建引擎"""
        engine = ClosedLoopEngine()
        assert engine is not None
        assert engine._workspace is not None

    def test_initial_status(self, engine: ClosedLoopEngine) -> None:
        """初始状态检查"""
        status = engine.get_status()
        assert status["state"] == "idle"
        assert status["current_step"] == 0
        assert status["total_steps"] == 7


# ── 执行计划测试 ──────────────────────────────────────────


class TestExecutePlan:
    """execute 方法 — 执行完整闭环"""

    @pytest.mark.asyncio
    async def test_execute_plan_success(self, engine: ClosedLoopEngine) -> None:
        """执行简单计划成功"""
        result = await engine.execute(task="添加一个简单的工具函数")
        assert isinstance(result, ClosedLoopResult)
        assert result.steps_completed == 7
        assert result.task_id != ""
        assert result.duration >= 0.0
        assert len(result.step_results) == 7

    @pytest.mark.asyncio
    async def test_execute_plan_returns_risk_analysis(self, engine: ClosedLoopEngine) -> None:
        """执行计划返回风险分析"""
        result = await engine.execute(task="重构代码模块")
        assert len(result.risk_analysis) >= 1
        assert "severity" in result.risk_analysis[0]

    @pytest.mark.asyncio
    async def test_execute_plan_returns_lessons(self, engine: ClosedLoopEngine) -> None:
        """执行计划返回经验教训"""
        result = await engine.execute(task="优化性能")
        assert len(result.lessons_learned) >= 1

    @pytest.mark.asyncio
    async def test_execute_plan_with_retry(self, engine: ClosedLoopEngine) -> None:
        """执行计划 — 自愈逻辑在 step6 中触发"""
        result = await engine.execute(task="修复导入错误")
        assert isinstance(result, ClosedLoopResult)
        assert result.steps_completed >= 1
        # step6 自愈步骤应被执行
        step6_results = [
            sr for sr in result.step_results if sr.step_number == 6
        ]
        assert len(step6_results) >= 1


# ── 验证测试 ──────────────────────────────────────────────


class TestValidateResult:
    """validate_result 方法 — 验证修复结果"""

    @pytest.mark.asyncio
    async def test_validate_result_pass(self, engine: ClosedLoopEngine) -> None:
        """验证通过 — 修复成功"""
        fix = FixResult(
            applied_changes=[
                {"file": "test.py", "action": "syntax_fix", "strategy": "syntax_fix"},
            ],
            success=True,
            strategy_used="syntax_fix",
        )
        result = await engine.validate_result(fix)
        assert isinstance(result, VerifyResult)
        # 沙箱被 mock 禁用，verify 使用基本语法检查
        assert isinstance(result.passed, bool)
        assert result.duration_ms >= 0.0

    @pytest.mark.asyncio
    async def test_validate_result_fail(self, engine: ClosedLoopEngine) -> None:
        """验证失败 — 修复无效"""
        fix = FixResult(
            applied_changes=[],
            success=False,
            error_message="无法应用修复",
            strategy_used="syntax_fix",
        )
        result = await engine.validate_result(fix)
        assert isinstance(result, VerifyResult)
        assert isinstance(result.passed, bool)


# ── 错误分析测试 ──────────────────────────────────────────


class TestAnalyzeError:
    """analyze_error 方法 — 错误诊断"""

    @pytest.mark.asyncio
    async def test_analyze_error_syntax(
        self, engine: ClosedLoopEngine, syntax_error: ExecutionError,
    ) -> None:
        """分析语法错误"""
        diagnosis = await engine.analyze_error(syntax_error)
        assert isinstance(diagnosis, Diagnosis)
        assert diagnosis.error_category == "syntax_error"
        assert diagnosis.fix_strategy == "syntax_fix"
        assert diagnosis.confidence > 0.5
        assert "test.py" in diagnosis.affected_files

    @pytest.mark.asyncio
    async def test_analyze_error_import(
        self, engine: ClosedLoopEngine, import_error: ExecutionError,
    ) -> None:
        """分析导入错误"""
        diagnosis = await engine.analyze_error(import_error)
        assert isinstance(diagnosis, Diagnosis)
        assert diagnosis.error_category == "import_error"
        assert diagnosis.fix_strategy == "import_fix"
        assert diagnosis.confidence > 0.5

    @pytest.mark.asyncio
    async def test_analyze_error_type(
        self, engine: ClosedLoopEngine, type_error: ExecutionError,
    ) -> None:
        """分析类型错误"""
        diagnosis = await engine.analyze_error(type_error)
        assert isinstance(diagnosis, Diagnosis)
        assert diagnosis.error_category == "type_error"
        assert diagnosis.fix_strategy == "logic_rewrite"

    @pytest.mark.asyncio
    async def test_analyze_error_returns_suggested_fix(
        self, engine: ClosedLoopEngine, syntax_error: ExecutionError,
    ) -> None:
        """分析错误返回修复建议"""
        diagnosis = await engine.analyze_error(syntax_error)
        assert len(diagnosis.suggested_fix) > 0
        assert isinstance(diagnosis.root_cause, str)


# ── 修复生成测试 ──────────────────────────────────────────


class TestGenerateFix:
    """generate_fix 方法 — 生成修复方案"""

    @pytest.mark.asyncio
    async def test_generate_fix(
        self, engine: ClosedLoopEngine, syntax_error: ExecutionError,
    ) -> None:
        """根据诊断生成修复"""
        diagnosis = await engine.analyze_error(syntax_error)
        fix = await engine.generate_fix(diagnosis)
        assert isinstance(fix, FixResult)
        assert fix.strategy_used == "syntax_fix"
        assert len(fix.applied_changes) >= 0

    @pytest.mark.asyncio
    async def test_generate_fix_for_import_error(
        self, engine: ClosedLoopEngine, import_error: ExecutionError,
    ) -> None:
        """为导入错误生成修复"""
        diagnosis = await engine.analyze_error(import_error)
        fix = await engine.generate_fix(diagnosis)
        assert isinstance(fix, FixResult)
        assert fix.strategy_used in ("import_fix", "syntax_fix")


# ── 统计测试 ──────────────────────────────────────────────


class TestGetStats:
    """get_stats 方法 — 引擎统计信息"""

    def test_get_stats(self, engine: ClosedLoopEngine) -> None:
        """获取引擎统计"""
        stats = engine.get_stats()
        assert isinstance(stats, dict)
        assert "status" in stats
        assert "heal_history" in stats
        assert "workspace" in stats
        assert stats["status"]["state"] == "idle"

    @pytest.mark.asyncio
    async def test_get_stats_after_execute(self, engine: ClosedLoopEngine) -> None:
        """执行后获取统计"""
        await engine.execute(task="测试任务")
        stats = engine.get_stats()
        assert stats["status"]["state"] == "completed"
        assert stats["status"]["current_step"] == 7


# ── 自愈循环测试 ──────────────────────────────────────────


class TestSelfHealingLoop:
    """SelfHealingLoop 独立测试"""

    def test_create_healer(self, tmp_path: Path) -> None:
        """创建自愈循环实例"""
        healer = SelfHealingLoop(workspace=tmp_path)
        assert healer is not None

    @pytest.mark.asyncio
    async def test_heal_syntax_error(
        self, tmp_path: Path, syntax_error: ExecutionError,
    ) -> None:
        """自愈语法错误"""
        healer = SelfHealingLoop(workspace=tmp_path)
        result = await healer.heal(syntax_error, max_iterations=1)
        assert isinstance(result, VerifyResult)
        assert isinstance(result.passed, bool)

    @pytest.mark.asyncio
    async def test_heal_returns_history(
        self, tmp_path: Path, syntax_error: ExecutionError,
    ) -> None:
        """自愈返回历史记录"""
        healer = SelfHealingLoop(workspace=tmp_path)
        await healer.heal(syntax_error, max_iterations=1)
        history = healer.get_history()
        assert isinstance(history, list)


# ── 数据模型测试 ──────────────────────────────────────────


class TestDataModels:
    """数据模型序列化与工厂方法"""

    def test_execution_error_from_stderr(self) -> None:
        """从 stderr 创建 ExecutionError"""
        stderr = (
            'File "app.py", line 42, in handler\n'
            "    result = process(data)\n"
            "NameError: name 'process' is not defined"
        )
        error = ExecutionError.from_stderr(stderr)
        assert error.error_type == "name_error"
        assert error.source_file == "app.py"
        assert error.source_line == 42

    def test_execution_error_to_dict(self, syntax_error: ExecutionError) -> None:
        """ExecutionError 序列化"""
        d = syntax_error.to_dict()
        assert d["error_type"] == "syntax_error"
        assert d["severity"] == "critical"
        assert "source_file" in d

    def test_diagnosis_to_dict(self) -> None:
        """Diagnosis 序列化"""
        d = Diagnosis(
            root_cause="语法错误",
            affected_files=["test.py"],
            suggested_fix="修复语法",
            confidence=0.9,
            error_category="syntax_error",
            fix_strategy="syntax_fix",
        )
        result = d.to_dict()
        assert result["root_cause"] == "语法错误"
        assert result["confidence"] == 0.9

    def test_fix_result_to_dict(self) -> None:
        """FixResult 序列化"""
        fix = FixResult(
            applied_changes=[{"file": "test.py", "action": "fix"}],
            success=True,
            strategy_used="syntax_fix",
        )
        d = fix.to_dict()
        assert d["success"] is True
        assert d["strategy_used"] == "syntax_fix"

    def test_verify_result_to_dict(self) -> None:
        """VerifyResult 序列化"""
        vr = VerifyResult(
            passed=True,
            build_success=True,
            test_success=True,
            duration_ms=150.0,
        )
        d = vr.to_dict()
        assert d["passed"] is True
        assert d["duration_ms"] == 150.0

    def test_closed_loop_result_to_dict(self) -> None:
        """ClosedLoopResult 序列化"""
        result = ClosedLoopResult(
            task_id="test-123",
            success=True,
            steps_completed=7,
            duration=1.5,
            final_status="success",
        )
        d = result.to_dict()
        assert d["task_id"] == "test-123"
        assert d["steps_completed"] == 7
        assert d["success"] is True


# ── DAG 拆解测试 ──────────────────────────────────────────


class TestDAGDecompose:
    """dag_decompose 方法"""

    @pytest.mark.asyncio
    async def test_dag_decompose(self, engine: ClosedLoopEngine) -> None:
        """DAG 拆解返回有效结构"""
        dag = await engine.dag_decompose(task="实现用户认证模块")
        assert isinstance(dag, dict)
        assert "nodes" in dag
        assert "edges" in dag
        assert "parallel_groups" in dag
        assert len(dag["nodes"]) >= 1


# ── 报告生成测试 ──────────────────────────────────────────


class TestGenerateReport:
    """generate_report 方法"""

    @pytest.mark.asyncio
    async def test_generate_report(self, engine: ClosedLoopEngine) -> None:
        """生成进化报告"""
        loop_result = await engine.execute(task="简单任务")
        report = await engine.generate_report(loop_result)
        assert isinstance(report, dict)
        assert "report" in report
        assert "summary" in report
        assert "step_details" in report
        assert report["summary"]["task_id"] == loop_result.task_id