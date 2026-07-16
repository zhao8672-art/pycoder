"""
进化变更报告模块单元测试 — 覆盖 EvolutionReport 及相关组件

测试范围:
  - FileChange / TestResult 数据类验证
  - EvolutionReport 字段与计算属性
  - ReportGenerator 报告生成（闭环结果、Git diff）
  - Markdown / JSON 格式输出
  - 文件变更追踪
  - 测试结果聚合
  - 风险等级分类
  - 回退计划生成
  - 空报告处理
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.evolution_report import (
    RISK_LEVELS,
    EvolutionReport,
    FileChange,
    ReportGenerator,
    TestResult,
    register_capabilities,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def sample_file_change() -> FileChange:
    """创建示例文件变更记录"""
    return FileChange(
        file_path="src/main.py",
        change_type="modified",
        lines_added=25,
        lines_deleted=10,
        description="重构用户认证逻辑",
        risk_level="medium",
    )


@pytest.fixture
def sample_test_result() -> TestResult:
    """创建示例测试结果"""
    return TestResult(
        test_name="test_user_login",
        status="passed",
        duration=0.35,
        error_message="",
    )


@pytest.fixture
def generator(tmp_path: Path) -> ReportGenerator:
    """创建使用临时目录的 ReportGenerator 实例"""
    return ReportGenerator(workspace=tmp_path)


# ── FileChange 测试 ──────────────────────────────────────


class TestFileChange:
    """FileChange 数据类测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        fc = FileChange(file_path="test.py")
        assert fc.change_type == "modified"
        assert fc.lines_added == 0
        assert fc.lines_deleted == 0
        assert fc.description == ""
        assert fc.risk_level == "low"

    def test_net_lines(self) -> None:
        """测试净增行数计算"""
        fc = FileChange(
            file_path="test.py",
            lines_added=50,
            lines_deleted=20,
        )
        assert fc.net_lines == 30

    def test_net_lines_negative(self) -> None:
        """测试净增行数为负数（删除多于新增）"""
        fc = FileChange(
            file_path="test.py",
            lines_added=5,
            lines_deleted=30,
        )
        assert fc.net_lines == -25

    def test_to_dict(self) -> None:
        """测试序列化为字典"""
        fc = FileChange(
            file_path="src/main.py",
            change_type="added",
            lines_added=100,
            lines_deleted=0,
            description="新增模块",
            risk_level="high",
        )
        d = fc.to_dict()
        assert d["file_path"] == "src/main.py"
        assert d["change_type"] == "added"
        assert d["lines_added"] == 100
        assert d["lines_deleted"] == 0
        assert d["net_lines"] == 100
        assert d["description"] == "新增模块"
        assert d["risk_level"] == "high"

    def test_from_dict(self) -> None:
        """测试从字典反序列化"""
        data = {
            "file_path": "src/app.py",
            "change_type": "deleted",
            "lines_added": 0,
            "lines_deleted": 200,
            "description": "移除废弃模块",
            "risk_level": "critical",
        }
        fc = FileChange.from_dict(data)
        assert fc.file_path == "src/app.py"
        assert fc.change_type == "deleted"
        assert fc.lines_deleted == 200
        assert fc.risk_level == "critical"

    def test_from_dict_defaults(self) -> None:
        """测试 from_dict 对缺失字段使用默认值"""
        fc = FileChange.from_dict({"file_path": "x.py"})
        assert fc.change_type == "modified"
        assert fc.lines_added == 0
        assert fc.risk_level == "low"

    def test_risk_level_validation(self) -> None:
        """测试所有风险等级均可设置"""
        for level in RISK_LEVELS:
            fc = FileChange(file_path="test.py", risk_level=level)
            assert fc.risk_level == level


# ── TestResult 测试 ──────────────────────────────────────


class TestTestResult:
    """TestResult 数据类测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        tr = TestResult(test_name="test_foo")
        assert tr.status == "passed"
        assert tr.duration == 0.0
        assert tr.error_message == ""

    def test_to_dict(self) -> None:
        """测试序列化为字典"""
        tr = TestResult(
            test_name="test_auth",
            status="failed",
            duration=1.25,
            error_message="AssertionError: expected True",
        )
        d = tr.to_dict()
        assert d["test_name"] == "test_auth"
        assert d["status"] == "failed"
        assert d["duration"] == 1.25
        assert "AssertionError" in d["error_message"]

    def test_from_dict(self) -> None:
        """测试从字典反序列化"""
        data = {
            "test_name": "test_db",
            "status": "skipped",
            "duration": 0.0,
            "error_message": "DB not available",
        }
        tr = TestResult.from_dict(data)
        assert tr.test_name == "test_db"
        assert tr.status == "skipped"
        assert tr.error_message == "DB not available"

    def test_from_dict_defaults(self) -> None:
        """测试 from_dict 默认值"""
        tr = TestResult.from_dict({"test_name": "t"})
        assert tr.status == "passed"
        assert tr.duration == 0.0


# ── EvolutionReport 测试 ─────────────────────────────────


class TestEvolutionReport:
    """EvolutionReport 数据类测试"""

    def test_auto_generate_task_id(self) -> None:
        """测试自动生成 task_id"""
        report = EvolutionReport()
        assert report.task_id.startswith("EVO-")
        assert len(report.task_id) > 8

    def test_preserve_provided_task_id(self) -> None:
        """测试保留显式提供的 task_id"""
        report = EvolutionReport(task_id="EVO-MYID-123")
        assert report.task_id == "EVO-MYID-123"

    def test_default_values(self) -> None:
        """测试默认值"""
        report = EvolutionReport()
        assert report.summary == ""
        assert report.duration_seconds == 0.0
        assert report.changes == []
        assert report.test_results == []
        assert report.risk_analysis == ""
        assert report.rollback_plan == ""
        assert report.lessons_learned == []
        assert report.success is False
        assert report.metrics == {}

    def test_total_files_changed(self) -> None:
        """测试变更文件总数"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py"),
                FileChange(file_path="b.py"),
                FileChange(file_path="c.py"),
            ]
        )
        assert report.total_files_changed == 3

    def test_total_lines_added(self) -> None:
        """测试总新增行数"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", lines_added=10, lines_deleted=2),
                FileChange(file_path="b.py", lines_added=20, lines_deleted=5),
            ]
        )
        assert report.total_lines_added == 30
        assert report.total_lines_deleted == 7
        assert report.net_lines == 23

    def test_test_stats(self) -> None:
        """测试测试统计属性"""
        report = EvolutionReport(
            test_results=[
                TestResult(test_name="t1", status="passed"),
                TestResult(test_name="t2", status="passed"),
                TestResult(test_name="t3", status="failed"),
                TestResult(test_name="t4", status="skipped"),
                TestResult(test_name="t5", status="passed"),
            ]
        )
        assert report.tests_passed == 3
        assert report.tests_failed == 1
        assert report.tests_skipped == 1
        assert report.total_tests == 5
        assert report.pass_rate == 0.6

    def test_pass_rate_zero_tests(self) -> None:
        """测试无测试时的通过率"""
        report = EvolutionReport()
        assert report.pass_rate == 0.0

    def test_highest_risk_no_changes(self) -> None:
        """测试无变更时最高风险等级"""
        report = EvolutionReport()
        assert report.highest_risk == "none"

    def test_highest_risk_returns_critical_first(self) -> None:
        """测试最高风险等级返回 critical"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", risk_level="low"),
                FileChange(file_path="b.py", risk_level="critical"),
                FileChange(file_path="c.py", risk_level="high"),
            ]
        )
        assert report.highest_risk == "critical"

    def test_highest_risk_returns_high(self) -> None:
        """测试最高风险等级返回 high"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", risk_level="medium"),
                FileChange(file_path="b.py", risk_level="high"),
            ]
        )
        assert report.highest_risk == "high"

    def test_highest_risk_returns_medium(self) -> None:
        """测试最高风险等级返回 medium"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", risk_level="low"),
                FileChange(file_path="b.py", risk_level="medium"),
            ]
        )
        assert report.highest_risk == "medium"

    def test_highest_risk_returns_low(self) -> None:
        """测试最高风险等级返回 low（无 higher）"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", risk_level="low"),
                FileChange(file_path="b.py", risk_level="none"),
            ]
        )
        assert report.highest_risk == "low"

    def test_to_dict(self) -> None:
        """测试完整序列化为字典"""
        report = EvolutionReport(
            task_id="EVO-TEST-001",
            summary="测试摘要",
            duration_seconds=12.5,
            changes=[
                FileChange(file_path="a.py", lines_added=10, lines_deleted=2),
            ],
            test_results=[
                TestResult(test_name="t1", status="passed"),
            ],
            risk_analysis="低风险",
            rollback_plan="git revert",
            lessons_learned=["重要教训"],
            success=True,
            metrics={"key": "value"},
        )
        d = report.to_dict()
        assert d["task_id"] == "EVO-TEST-001"
        assert d["summary"] == "测试摘要"
        assert d["success"] is True
        assert d["total_files_changed"] == 1
        assert d["total_tests"] == 1
        assert d["pass_rate"] == 1.0
        assert d["highest_risk"] == "low"
        assert len(d["changes"]) == 1
        assert len(d["test_results"]) == 1
        assert d["lessons_learned"] == ["重要教训"]

    def test_from_dict(self) -> None:
        """测试从字典反序列化"""
        data = {
            "task_id": "EVO-FROM-001",
            "summary": "从字典恢复",
            "created_at": "2025-01-15T10:30:00+00:00",
            "duration_seconds": 5.0,
            "changes": [
                {
                    "file_path": "x.py",
                    "change_type": "modified",
                    "lines_added": 20,
                    "lines_deleted": 5,
                    "description": "desc",
                    "risk_level": "medium",
                }
            ],
            "test_results": [
                {
                    "test_name": "t1",
                    "status": "passed",
                    "duration": 0.5,
                    "error_message": "",
                }
            ],
            "success": True,
            "metrics": {"m": 1},
        }
        report = EvolutionReport.from_dict(data)
        assert report.task_id == "EVO-FROM-001"
        assert report.summary == "从字典恢复"
        assert report.success is True
        assert report.total_files_changed == 1
        assert report.total_tests == 1

    def test_from_dict_invalid_date(self) -> None:
        """测试无效日期格式时回退到当前时间"""
        report = EvolutionReport.from_dict({"created_at": "invalid-date"})
        assert isinstance(report.created_at, datetime)

    def test_roundtrip_serialization(self) -> None:
        """测试序列化反序列化往返"""
        original = EvolutionReport(
            task_id="EVO-RT-001",
            summary="往返测试",
            changes=[
                FileChange(file_path="a.py", lines_added=10, lines_deleted=3),
                FileChange(file_path="b.py", lines_added=5, lines_deleted=0),
            ],
            test_results=[
                TestResult(test_name="t1", status="passed"),
                TestResult(test_name="t2", status="failed", error_message="boom"),
            ],
            risk_analysis="风险分析",
            rollback_plan="回退计划",
            lessons_learned=["经验1", "经验2"],
            success=True,
            metrics={"steps": 3},
        )
        restored = EvolutionReport.from_dict(original.to_dict())
        assert restored.task_id == original.task_id
        assert restored.summary == original.summary
        assert restored.total_files_changed == original.total_files_changed
        assert restored.total_tests == original.total_tests
        assert restored.tests_passed == original.tests_passed
        assert restored.tests_failed == original.tests_failed
        assert restored.risk_analysis == original.risk_analysis
        assert restored.rollback_plan == original.rollback_plan
        assert restored.lessons_learned == original.lessons_learned
        assert restored.success == original.success


# ── ReportGenerator 测试 ─────────────────────────────────


class TestReportGeneratorInit:
    """ReportGenerator 初始化测试"""

    def test_default_workspace(self) -> None:
        """测试默认工作区"""
        gen = ReportGenerator()
        assert gen._workspace is not None

    def test_custom_workspace(self, tmp_path: Path) -> None:
        """测试自定义工作区"""
        gen = ReportGenerator(workspace=tmp_path)
        assert gen._workspace == tmp_path


class TestReportGeneration:
    """报告生成测试"""

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_success(self, generator: ReportGenerator) -> None:
        """测试从闭环结果生成成功报告"""
        result = MagicMock()
        result.task_id = "EVO-TASK-001"
        result.success = True
        result.duration = 3.5
        result.changes = [
            {
                "file": "src/auth.py",
                "action": "modified",
                "lines_added": 50,
                "lines_deleted": 20,
                "reason": "重构认证逻辑",
                "risk_level": "medium",
            },
            {
                "file": "src/models.py",
                "action": "added",
                "lines_added": 100,
                "lines_deleted": 0,
                "reason": "新增数据模型",
                "risk_level": "low",
            },
        ]
        result.test_results = [
            {
                "test_name": "test_login",
                "status": "passed",
                "duration": 0.5,
                "error_message": "",
            },
            {
                "test_name": "test_logout",
                "status": "failed",
                "duration": 0.2,
                "error_message": "AssertionError",
            },
        ]
        result.risk_analysis = []
        result.rollback_plan = {}
        result.lessons_learned = []
        result.steps_completed = 3
        result.self_heal_attempts = 0
        result.final_status = "completed"

        report = await generator.generate_from_closed_loop(result)

        assert report.task_id == "EVO-TASK-001"
        assert report.success is True
        assert report.total_files_changed == 2
        assert report.total_tests == 2
        assert report.tests_passed == 1
        assert report.tests_failed == 1
        assert "成功" in report.summary
        assert len(report.changes) == 2
        assert report.changes[0].file_path == "src/auth.py"

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_with_file_path_key(
        self, generator: ReportGenerator
    ) -> None:
        """测试从闭环结果生成报告 — 使用 file_path key"""
        result = MagicMock()
        result.task_id = "EVO-TASK-002"
        result.success = False
        result.duration = 1.0
        result.changes = [
            {
                "file_path": "src/broken.py",
                "change_type": "modified",
                "lines_added": 5,
                "lines_deleted": 5,
                "description": "有 bug 的修改",
                "risk_level": "high",
            }
        ]
        result.test_results = []
        result.risk_analysis = []
        result.rollback_plan = {}
        result.lessons_learned = []
        result.steps_completed = 1
        result.self_heal_attempts = 2
        result.final_status = "failed"

        report = await generator.generate_from_closed_loop(result)

        assert report.success is False
        assert "失败" in report.summary
        assert report.changes[0].risk_level == "high"

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_with_file_change_objects(
        self, generator: ReportGenerator
    ) -> None:
        """测试从闭环结果生成报告 — 已有 FileChange 对象"""
        result = MagicMock()
        result.task_id = ""
        result.success = True
        result.duration = 0.0
        result.changes = [
            FileChange(file_path="a.py", lines_added=10, lines_deleted=2),
            FileChange(file_path="b.py", lines_added=5, lines_deleted=0),
        ]
        result.test_results = []
        result.risk_analysis = []
        result.rollback_plan = {}
        result.lessons_learned = []
        result.steps_completed = 0
        result.self_heal_attempts = 0
        result.final_status = "unknown"

        report = await generator.generate_from_closed_loop(result)
        assert report.total_files_changed == 2

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_with_risk_analysis(
        self, generator: ReportGenerator
    ) -> None:
        """测试从闭环结果生成报告 — 包含风险分析"""
        result = MagicMock()
        result.task_id = "EVO-RISK-001"
        result.success = True
        result.duration = 2.0
        result.changes = []
        result.test_results = []
        result.risk_analysis = [
            {
                "risk": "SQL 注入风险",
                "severity": "critical",
                "mitigation": "使用参数化查询",
                "detail": "在 user_query 函数中发现字符串拼接",
            }
        ]
        result.rollback_plan = {}
        result.lessons_learned = []
        result.steps_completed = 0
        result.self_heal_attempts = 0
        result.final_status = "completed"

        report = await generator.generate_from_closed_loop(result)
        assert "SQL 注入" in report.risk_analysis
        assert "参数化查询" in report.risk_analysis

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_with_rollback_plan(
        self, generator: ReportGenerator
    ) -> None:
        """测试从闭环结果生成报告 — 包含回退计划"""
        result = MagicMock()
        result.task_id = "EVO-RB-001"
        result.success = True
        result.duration = 1.0
        result.changes = []
        result.test_results = []
        result.risk_analysis = []
        result.rollback_plan = {
            "strategy": "git revert",
            "steps": ["git revert HEAD", "重新部署"],
            "auto_rollback": True,
            "trigger_condition": "测试失败率 > 50%",
        }
        result.lessons_learned = []
        result.steps_completed = 0
        result.self_heal_attempts = 0
        result.final_status = "completed"

        report = await generator.generate_from_closed_loop(result)
        assert "git revert" in report.rollback_plan
        assert "自动回退" in report.rollback_plan
        assert "是" in report.rollback_plan

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_with_lessons(
        self, generator: ReportGenerator
    ) -> None:
        """测试从闭环结果生成报告 — 包含经验教训"""
        result = MagicMock()
        result.task_id = "EVO-LESSON-001"
        result.success = True
        result.duration = 1.0
        result.changes = []
        result.test_results = []
        result.risk_analysis = []
        result.rollback_plan = {}
        result.lessons_learned = ["单元测试应该更早编写", "代码审查发现了一个隐藏 bug"]
        result.steps_completed = 0
        result.self_heal_attempts = 0
        result.final_status = "completed"

        report = await generator.generate_from_closed_loop(result)
        assert len(report.lessons_learned) == 2
        assert "单元测试" in report.lessons_learned[0]

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_lessons_as_string(
        self, generator: ReportGenerator
    ) -> None:
        """测试从闭环结果生成报告 — 经验教训为字符串"""
        result = MagicMock()
        result.task_id = "EVO-STR-001"
        result.success = True
        result.duration = 1.0
        result.changes = []
        result.test_results = []
        result.risk_analysis = []
        result.rollback_plan = {}
        result.lessons_learned = "单个经验教训字符串"
        result.steps_completed = 0
        result.self_heal_attempts = 0
        result.final_status = "completed"

        report = await generator.generate_from_closed_loop(result)
        assert len(report.lessons_learned) == 1
        assert "单个经验教训字符串" in report.lessons_learned

    @pytest.mark.asyncio
    async def test_generate_from_closed_loop_empty(self, generator: ReportGenerator) -> None:
        """测试从闭环结果生成空报告"""
        result = MagicMock()
        result.task_id = ""
        result.success = False
        result.duration = 0.0
        result.changes = None
        result.test_results = None
        result.risk_analysis = None
        result.rollback_plan = None
        result.lessons_learned = None
        result.steps_completed = 0
        result.self_heal_attempts = 0
        result.final_status = "unknown"

        report = await generator.generate_from_closed_loop(result)
        assert report.total_files_changed == 0
        assert report.total_tests == 0
        assert report.highest_risk == "none"
        assert report.success is False


class TestReportFormatOutput:
    """报告格式输出测试"""

    @pytest.mark.asyncio
    async def test_to_markdown_success(self, generator: ReportGenerator) -> None:
        """测试成功报告的 Markdown 输出"""
        report = EvolutionReport(
            task_id="EVO-MD-001",
            summary="测试摘要",
            success=True,
            changes=[
                FileChange(
                    file_path="src/main.py",
                    change_type="modified",
                    lines_added=10,
                    lines_deleted=5,
                    description="修复 bug",
                    risk_level="low",
                )
            ],
            test_results=[
                TestResult(test_name="test_foo", status="passed", duration=0.1),
            ],
            risk_analysis="低风险",
            rollback_plan="git revert",
            lessons_learned=["经验教训"],
            metrics={"steps": 1},
        )
        md = generator.to_markdown(report)
        assert "EVO-MD-001" in md
        assert "✅" in md
        assert "成功" in md
        assert "src/main.py" in md
        assert "test_foo" in md
        assert "低风险" in md
        assert "git revert" in md
        assert "经验教训" in md

    @pytest.mark.asyncio
    async def test_to_markdown_failure(self, generator: ReportGenerator) -> None:
        """测试失败报告的 Markdown 输出"""
        report = EvolutionReport(
            task_id="EVO-MD-FAIL",
            summary="失败摘要",
            success=False,
            test_results=[
                TestResult(
                    test_name="test_broken",
                    status="failed",
                    duration=0.5,
                    error_message="Something went wrong",
                ),
            ],
        )
        md = generator.to_markdown(report)
        assert "❌" in md
        assert "失败" in md
        assert "test_broken" in md
        assert "Something went wrong" in md

    @pytest.mark.asyncio
    async def test_to_markdown_empty_changes(self, generator: ReportGenerator) -> None:
        """测试空变更时的 Markdown 输出"""
        report = EvolutionReport(task_id="EVO-EMPTY")
        md = generator.to_markdown(report)
        assert "无变更" in md
        assert "无测试结果" in md

    @pytest.mark.asyncio
    async def test_to_markdown_risk_emojis(self, generator: ReportGenerator) -> None:
        """测试 Markdown 中风险等级 emoji"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", risk_level="critical"),
                FileChange(file_path="b.py", risk_level="high"),
                FileChange(file_path="c.py", risk_level="medium"),
                FileChange(file_path="d.py", risk_level="low"),
                FileChange(file_path="e.py", risk_level="none"),
            ]
        )
        md = generator.to_markdown(report)
        assert "🔴" in md
        assert "🟠" in md
        assert "🟡" in md
        assert "🟢" in md
        assert "⚪" in md

    @pytest.mark.asyncio
    async def test_to_markdown_test_emojis(self, generator: ReportGenerator) -> None:
        """测试 Markdown 中测试状态 emoji"""
        report = EvolutionReport(
            test_results=[
                TestResult(test_name="t1", status="passed"),
                TestResult(test_name="t2", status="failed"),
                TestResult(test_name="t3", status="skipped"),
            ]
        )
        md = generator.to_markdown(report)
        assert "✅" in md
        assert "❌" in md
        assert "⏭️" in md

    @pytest.mark.asyncio
    async def test_to_markdown_pass_rate(self, generator: ReportGenerator) -> None:
        """测试 Markdown 中的通过率显示"""
        report = EvolutionReport(
            test_results=[
                TestResult(test_name="t1", status="passed"),
                TestResult(test_name="t2", status="passed"),
                TestResult(test_name="t3", status="failed"),
                TestResult(test_name="t4", status="passed"),
            ]
        )
        md = generator.to_markdown(report)
        assert "75.0%" in md

    @pytest.mark.asyncio
    async def test_to_json(self, generator: ReportGenerator) -> None:
        """测试 JSON 格式输出"""
        report = EvolutionReport(
            task_id="EVO-JSON-001",
            summary="JSON 测试",
            success=True,
            changes=[
                FileChange(file_path="a.py", lines_added=10, lines_deleted=5),
            ],
            test_results=[
                TestResult(test_name="t1", status="passed"),
            ],
        )
        json_str = generator.to_json(report)
        data = json.loads(json_str)
        assert data["task_id"] == "EVO-JSON-001"
        assert data["success"] is True
        assert len(data["changes"]) == 1
        assert len(data["test_results"]) == 1

    @pytest.mark.asyncio
    async def test_to_json_empty_report(self, generator: ReportGenerator) -> None:
        """测试空报告的 JSON 输出"""
        report = EvolutionReport()
        json_str = generator.to_json(report)
        data = json.loads(json_str)
        assert data["total_files_changed"] == 0
        assert data["total_tests"] == 0
        assert data["success"] is False


class TestFileChangeTracking:
    """文件变更追踪测试"""

    def test_added_file(self) -> None:
        """测试新增文件类型"""
        fc = FileChange(file_path="new_file.py", change_type="added")
        assert fc.change_type == "added"
        assert fc.net_lines == 0

    def test_modified_file(self) -> None:
        """测试修改文件类型"""
        fc = FileChange(
            file_path="mod.py",
            change_type="modified",
            lines_added=30,
            lines_deleted=15,
        )
        assert fc.change_type == "modified"
        assert fc.net_lines == 15

    def test_deleted_file(self) -> None:
        """测试删除文件类型"""
        fc = FileChange(
            file_path="old.py",
            change_type="deleted",
            lines_added=0,
            lines_deleted=100,
        )
        assert fc.change_type == "deleted"
        assert fc.net_lines == -100

    def test_multiple_changes_in_report(self) -> None:
        """测试报告中多个变更的汇总"""
        report = EvolutionReport(
            changes=[
                FileChange(file_path="a.py", change_type="added", lines_added=50, lines_deleted=0),
                FileChange(file_path="b.py", change_type="modified", lines_added=20, lines_deleted=10),
                FileChange(file_path="c.py", change_type="deleted", lines_added=0, lines_deleted=30),
            ]
        )
        assert report.total_files_changed == 3
        assert report.total_lines_added == 70
        assert report.total_lines_deleted == 40
        assert report.net_lines == 30


class TestTestResultAggregation:
    """测试结果聚合测试"""

    def test_all_passed(self) -> None:
        """测试全部通过"""
        report = EvolutionReport(
            test_results=[TestResult(test_name=f"t{i}", status="passed") for i in range(5)]
        )
        assert report.tests_passed == 5
        assert report.tests_failed == 0
        assert report.pass_rate == 1.0

    def test_all_failed(self) -> None:
        """测试全部失败"""
        report = EvolutionReport(
            test_results=[
                TestResult(test_name="t1", status="failed", error_message="err1"),
                TestResult(test_name="t2", status="failed", error_message="err2"),
            ]
        )
        assert report.tests_passed == 0
        assert report.tests_failed == 2
        assert report.pass_rate == 0.0

    def test_mixed_statuses(self) -> None:
        """测试混合状态"""
        report = EvolutionReport(
            test_results=[
                TestResult(test_name="t1", status="passed"),
                TestResult(test_name="t2", status="passed"),
                TestResult(test_name="t3", status="failed"),
                TestResult(test_name="t4", status="skipped"),
                TestResult(test_name="t5", status="passed"),
            ]
        )
        assert report.tests_passed == 3
        assert report.tests_failed == 1
        assert report.tests_skipped == 1
        assert report.pass_rate == 0.6

    def test_empty_test_results(self) -> None:
        """测试空测试结果"""
        report = EvolutionReport()
        assert report.total_tests == 0
        assert report.tests_passed == 0
        assert report.tests_failed == 0
        assert report.tests_skipped == 0


class TestRiskLevelClassification:
    """风险等级分类测试"""

    def test_risk_estimate_none(self) -> None:
        """测试风险估算 — none"""
        gen = ReportGenerator()
        assert gen._estimate_risk({"lines_added": 5, "lines_deleted": 3}) == "none"

    def test_risk_estimate_low(self) -> None:
        """测试风险估算 — low"""
        gen = ReportGenerator()
        assert gen._estimate_risk({"lines_added": 15, "lines_deleted": 5}) == "low"

    def test_risk_estimate_medium(self) -> None:
        """测试风险估算 — medium"""
        gen = ReportGenerator()
        assert gen._estimate_risk({"lines_added": 40, "lines_deleted": 20}) == "medium"

    def test_risk_estimate_high(self) -> None:
        """测试风险估算 — high"""
        gen = ReportGenerator()
        assert gen._estimate_risk({"lines_added": 80, "lines_deleted": 30}) == "high"

    def test_risk_estimate_critical(self) -> None:
        """测试风险估算 — critical"""
        gen = ReportGenerator()
        assert gen._estimate_risk({"lines_added": 150, "lines_deleted": 60}) == "critical"

    def test_risk_levels_order(self) -> None:
        """测试风险等级映射顺序"""
        assert RISK_LEVELS["critical"] == 0
        assert RISK_LEVELS["high"] == 1
        assert RISK_LEVELS["medium"] == 2
        assert RISK_LEVELS["low"] == 3
        assert RISK_LEVELS["none"] == 4


class TestRollbackPlanGeneration:
    """回退计划生成测试"""

    def test_empty_rollback_default(self) -> None:
        """测试空回退数据的默认值"""
        gen = ReportGenerator()
        result = gen._format_rollback_plan({})
        assert "未提供回退计划" in result

    def test_rollback_with_strategy(self) -> None:
        """测试仅包含策略的回退计划"""
        gen = ReportGenerator()
        result = gen._format_rollback_plan({"strategy": "git revert HEAD"})
        assert "git revert HEAD" in result

    def test_rollback_with_steps(self) -> None:
        """测试包含步骤的回退计划"""
        gen = ReportGenerator()
        result = gen._format_rollback_plan({
            "strategy": "回滚部署",
            "steps": ["步骤1: 停止服务", "步骤2: 恢复数据库", "步骤3: 重启服务"],
        })
        assert "回滚部署" in result
        assert "步骤1" in result
        assert "步骤2" in result
        assert "步骤3" in result

    def test_rollback_auto_rollback(self) -> None:
        """测试自动回退标志"""
        gen = ReportGenerator()
        result = gen._format_rollback_plan({"auto_rollback": True})
        assert "是" in result

        result_no = gen._format_rollback_plan({"auto_rollback": False})
        assert "否" in result_no

    def test_rollback_with_trigger(self) -> None:
        """测试触发条件"""
        gen = ReportGenerator()
        result = gen._format_rollback_plan({
            "strategy": "回滚",
            "trigger_condition": "错误率 > 5%",
        })
        assert "错误率 > 5%" in result


class TestSummaryGeneration:
    """摘要生成测试"""

    def test_success_summary(self) -> None:
        """测试成功摘要"""
        gen = ReportGenerator()
        changes = [FileChange(file_path="a.py", lines_added=10, lines_deleted=2)]
        tests = [TestResult(test_name="t1", status="passed")]
        summary = gen._generate_summary(True, changes, tests, 3.0)
        assert "成功" in summary
        assert "3.0s" in summary
        assert "1 个文件" in summary
        assert "1/1 通过" in summary

    def test_failure_summary(self) -> None:
        """测试失败摘要"""
        gen = ReportGenerator()
        changes = [FileChange(file_path="a.py", lines_added=5, lines_deleted=0)]
        tests = [
            TestResult(test_name="t1", status="passed"),
            TestResult(test_name="t2", status="failed"),
        ]
        summary = gen._generate_summary(False, changes, tests, 2.0)
        assert "失败" in summary
        assert "1/2 通过" in summary
        assert "1 个测试失败" in summary

    def test_summary_no_tests(self) -> None:
        """测试无测试结果的摘要"""
        gen = ReportGenerator()
        changes = [FileChange(file_path="a.py", lines_added=10, lines_deleted=0)]
        summary = gen._generate_summary(True, changes, [], 1.5)
        assert "成功" in summary
        assert "1.5s" in summary


class TestEmptyReportHandling:
    """空报告处理测试"""

    @pytest.mark.asyncio
    async def test_empty_report_markdown(self, generator: ReportGenerator) -> None:
        """测试空报告的 Markdown 输出"""
        report = EvolutionReport()
        md = generator.to_markdown(report)
        assert "无变更" in md
        assert "无测试结果" in md
        assert "无风险分析" in md
        assert "无回退计划" in md
        assert "无经验教训" in md

    @pytest.mark.asyncio
    async def test_empty_report_json(self, generator: ReportGenerator) -> None:
        """测试空报告的 JSON 输出"""
        report = EvolutionReport()
        json_str = generator.to_json(report)
        data = json.loads(json_str)
        assert data["changes"] == []
        assert data["test_results"] == []
        assert data["lessons_learned"] == []

    def test_empty_risk_analysis(self) -> None:
        """测试空风险分析格式化"""
        gen = ReportGenerator()
        result = gen._format_risk_analysis([])
        assert "未提供风险分析数据" in result

    def test_empty_rollback_plan(self) -> None:
        """测试空回退计划格式化"""
        gen = ReportGenerator()
        result = gen._format_rollback_plan({})
        assert "未提供回退计划" in result


class TestRiskAnalysisFormatting:
    """风险分析格式化测试"""

    def test_format_with_dict_items(self) -> None:
        """测试格式化字典项的风险分析"""
        gen = ReportGenerator()
        risk_data = [
            {
                "risk": "XSS 漏洞",
                "severity": "high",
                "mitigation": "使用 HTML 转义",
                "detail": "在用户输入输出处发现未转义",
            }
        ]
        result = gen._format_risk_analysis(risk_data)
        assert "HIGH" in result
        assert "XSS 漏洞" in result
        assert "HTML 转义" in result
        assert "未转义" in result

    def test_format_with_string_items(self) -> None:
        """测试格式化字符串项的风险分析"""
        gen = ReportGenerator()
        risk_data = ["风险项1", "风险项2"]
        result = gen._format_risk_analysis(risk_data)
        assert "风险项1" in result
        assert "风险项2" in result

    def test_format_with_severity_emojis(self) -> None:
        """测试风险等级的 emoji 显示"""
        gen = ReportGenerator()
        risk_data = [
            {"risk": "r1", "severity": "critical"},
            {"risk": "r2", "severity": "high"},
            {"risk": "r3", "severity": "medium"},
            {"risk": "r4", "severity": "low"},
        ]
        result = gen._format_risk_analysis(risk_data)
        assert "🔴" in result
        assert "🟠" in result
        assert "🟡" in result
        assert "🟢" in result


class TestSaveReport:
    """报告持久化测试"""

    @pytest.mark.asyncio
    async def test_save_markdown(self, generator: ReportGenerator, tmp_path: Path) -> None:
        """测试保存 Markdown 格式报告"""
        report = EvolutionReport(
            task_id="EVO-SAVE-MD",
            summary="保存测试",
            success=True,
        )
        save_path = tmp_path / "report.md"
        result_path = await generator.save_report(report, save_path)
        assert result_path == save_path
        assert save_path.exists()
        content = save_path.read_text(encoding="utf-8")
        assert "EVO-SAVE-MD" in content

    @pytest.mark.asyncio
    async def test_save_json(self, generator: ReportGenerator, tmp_path: Path) -> None:
        """测试保存 JSON 格式报告"""
        report = EvolutionReport(
            task_id="EVO-SAVE-JSON",
            summary="JSON 保存测试",
            success=True,
        )
        save_path = tmp_path / "report.json"
        result_path = await generator.save_report(report, save_path)
        assert result_path == save_path
        assert save_path.exists()
        content = save_path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["task_id"] == "EVO-SAVE-JSON"

    @pytest.mark.asyncio
    async def test_save_default_path(self, generator: ReportGenerator) -> None:
        """测试使用默认路径保存"""
        report = EvolutionReport(task_id="EVO-DEFAULT")
        result_path = await generator.save_report(report)
        assert result_path.exists()
        assert result_path.name == "EVO-DEFAULT.md"


class TestMetricTracking:
    """执行指标追踪测试"""

    @pytest.mark.asyncio
    async def test_metrics_in_generated_report(self, generator: ReportGenerator) -> None:
        """测试生成的报告中包含指标"""
        result = MagicMock()
        result.task_id = "EVO-METRIC"
        result.success = True
        result.duration = 2.0
        result.changes = []
        result.test_results = []
        result.risk_analysis = []
        result.rollback_plan = {}
        result.lessons_learned = []
        result.steps_completed = 5
        result.self_heal_attempts = 2
        result.final_status = "completed"

        report = await generator.generate_from_closed_loop(result)
        assert report.metrics["steps_completed"] == 5
        assert report.metrics["self_heal_attempts"] == 2
        assert report.metrics["final_status"] == "completed"
        assert "generated_at" in report.metrics

    @pytest.mark.asyncio
    async def test_metrics_in_markdown(self, generator: ReportGenerator) -> None:
        """测试 Markdown 中包含指标"""
        report = EvolutionReport(
            task_id="EVO-MD-METRIC",
            metrics={"steps_completed": 3, "files_changed": 2},
        )
        md = generator.to_markdown(report)
        assert "steps_completed" in md
        assert "files_changed" in md


class TestGitDiffReport:
    """Git diff 报告生成测试"""

    @pytest.mark.asyncio
    async def test_generate_from_git_diff_success(
        self, generator: ReportGenerator, tmp_path: Path
    ) -> None:
        """测试从 Git diff 生成报告"""
        # 模拟 git diff --stat 输出
        mock_output = MagicMock()
        mock_output.returncode = 0
        mock_output.stdout = (
            " src/main.py       | 25 ++++++++++++----\n"
            " src/utils.py      | 10 ++++++\n"
            " tests/test.py     | 5 -----\n"
        )
        mock_output.stderr = ""

        with patch("subprocess.run", return_value=mock_output):
            report = await generator.generate_from_git_diff(base_branch="master")

        assert report.total_files_changed == 3
        assert report.success is True
        assert "master" in report.summary

    @pytest.mark.asyncio
    async def test_generate_from_git_diff_empty(
        self, generator: ReportGenerator, tmp_path: Path
    ) -> None:
        """测试无变更的 Git diff"""
        mock_output = MagicMock()
        mock_output.returncode = 0
        mock_output.stdout = ""
        mock_output.stderr = ""

        with patch("subprocess.run", return_value=mock_output):
            report = await generator.generate_from_git_diff()

        assert report.total_files_changed == 0
        assert report.success is True

    @pytest.mark.asyncio
    async def test_generate_from_git_diff_timeout(self, generator: ReportGenerator) -> None:
        """测试 Git diff 超时"""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            report = await generator.generate_from_git_diff()

        assert report.success is False
        assert "超时" in report.summary

    @pytest.mark.asyncio
    async def test_generate_from_git_diff_not_found(self, generator: ReportGenerator) -> None:
        """测试 Git 不可用"""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            report = await generator.generate_from_git_diff()

        assert report.success is False
        assert "不可用" in report.summary

    @pytest.mark.asyncio
    async def test_generate_from_git_diff_generic_error(
        self, generator: ReportGenerator
    ) -> None:
        """测试 Git diff 通用异常"""
        with patch("subprocess.run", side_effect=RuntimeError("磁盘满了")):
            report = await generator.generate_from_git_diff()

        assert report.success is False
        assert "失败" in report.summary