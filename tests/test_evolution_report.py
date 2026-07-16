"""
进化变更报告模块单元测试 — 覆盖 EvolutionReport 及相关组件

测试范围:
  - FileChange / TestSummary / RiskItem 数据类验证
  - EvolutionReport 字段与序列化
  - ReportGenerator 报告生成
  - Markdown / JSON 格式输出
  - 风险自动分析
  - 回滚方案生成
  - 空报告处理
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycoder.server.services.evolution_report import (
    EvolutionReport,
    FileChange,
    ReportGenerator,
    RiskItem,
    TestSummary,
    generate_change_report,
    register_capabilities,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def sample_file_change() -> FileChange:
    """创建示例文件变更记录"""
    return FileChange(
        file_path="src/main.py",
        action="modified",
        lines_added=25,
        lines_removed=10,
        description="重构用户认证逻辑",
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
        fc = FileChange(file_path="test.py", action="modified")
        assert fc.action == "modified"
        assert fc.lines_added == 0
        assert fc.lines_removed == 0
        assert fc.description == ""
        assert fc.old_path == ""

    def test_net_change_positive(self) -> None:
        """测试净增行数为正"""
        fc = FileChange(
            file_path="test.py",
            action="modified",
            lines_added=50,
            lines_removed=20,
        )
        assert fc.lines_added - fc.lines_removed == 30

    def test_net_change_negative(self) -> None:
        """测试净增行数为负数（删除多于新增）"""
        fc = FileChange(
            file_path="test.py",
            action="modified",
            lines_added=5,
            lines_removed=30,
        )
        assert fc.lines_added - fc.lines_removed == -25

    def test_to_dict(self) -> None:
        """测试序列化为字典"""
        fc = FileChange(
            file_path="src/main.py",
            action="added",
            lines_added=100,
            lines_removed=0,
            description="新增模块",
        )
        d = fc.to_dict()
        assert d["file_path"] == "src/main.py"
        assert d["action"] == "added"
        assert d["lines_added"] == 100
        assert d["lines_removed"] == 0
        assert d["net_change"] == 100
        assert d["description"] == "新增模块"

    def test_deleted_file(self) -> None:
        """测试删除文件"""
        fc = FileChange(
            file_path="old.py",
            action="deleted",
            lines_added=0,
            lines_removed=100,
        )
        assert fc.action == "deleted"
        assert fc.lines_added - fc.lines_removed == -100

    def test_renamed_file(self) -> None:
        """测试重命名文件"""
        fc = FileChange(
            file_path="new.py",
            action="renamed",
            old_path="old.py",
        )
        assert fc.old_path == "old.py"


# ── TestSummary 测试 ─────────────────────────────────────


class TestTestSummary:
    """TestSummary 数据类测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        ts = TestSummary()
        assert ts.passed == 0
        assert ts.failed == 0
        assert ts.skipped == 0
        assert ts.errors == 0
        assert ts.total == 0

    def test_total(self) -> None:
        """测试总数计算"""
        ts = TestSummary(passed=10, failed=2, skipped=1, errors=1)
        assert ts.total == 14

    def test_pass_rate_all_passed(self) -> None:
        """测试全部通过率"""
        ts = TestSummary(passed=10, failed=0, skipped=0, errors=0)
        assert ts.pass_rate == 100.0

    def test_pass_rate_mixed(self) -> None:
        """测试混合通过率"""
        ts = TestSummary(passed=7, failed=3, skipped=0, errors=0)
        assert ts.pass_rate == 70.0

    def test_pass_rate_zero_tests(self) -> None:
        """测试无测试时的通过率"""
        ts = TestSummary()
        assert ts.pass_rate == 100.0

    def test_to_dict(self) -> None:
        """测试序列化为字典"""
        ts = TestSummary(
            passed=5,
            failed=1,
            skipped=2,
            errors=0,
            duration_ms=150.0,
            coverage_pct=85.0,
            failed_tests=["test_a", "test_b"],
        )
        d = ts.to_dict()
        assert d["passed"] == 5
        assert d["failed"] == 1
        assert d["total"] == 8
        assert d["pass_rate"] == 62.5
        assert d["coverage_pct"] == 85.0
        assert len(d["failed_tests"]) == 2


# ── RiskItem 测试 ────────────────────────────────────────


class TestRiskItem:
    """RiskItem 数据类测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        ri = RiskItem(risk="测试风险", severity="medium")
        assert ri.severity == "medium"
        assert ri.mitigation == ""
        assert ri.probability == 0.0
        assert ri.impact == "medium"

    def test_to_dict(self) -> None:
        """测试序列化"""
        ri = RiskItem(
            risk="SQL 注入",
            severity="critical",
            mitigation="使用参数化查询",
            probability=0.8,
            impact="high",
        )
        d = ri.to_dict()
        assert d["risk"] == "SQL 注入"
        assert d["severity"] == "critical"
        assert d["mitigation"] == "使用参数化查询"
        assert d["probability"] == 0.8
        assert d["impact"] == "high"


# ── EvolutionReport 测试 ─────────────────────────────────


class TestEvolutionReport:
    """EvolutionReport 数据类测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        report = EvolutionReport()
        assert report.report_id == ""
        assert report.task == ""
        assert report.executive_summary == ""
        assert report.duration_seconds == 0.0
        assert report.file_changes == []
        assert report.risk_analysis == []
        assert report.rollback_plan == {}
        assert report.lessons_learned == []
        assert report.success is False
        assert report.metadata == {}

    def test_total_lines_added(self) -> None:
        """测试总新增行数（通过 ReportGenerator 生成时自动计算）"""
        gen = ReportGenerator()
        report = gen.generate(
            task="test",
            changes=[
                {"file": "a.py", "action": "modified", "lines_added": 10, "lines_removed": 2},
                {"file": "b.py", "action": "modified", "lines_added": 20, "lines_removed": 5},
            ],
        )
        assert report.total_lines_added == 30
        assert report.total_lines_removed == 7

    def test_file_changes_count(self) -> None:
        """测试变更文件数"""
        report = EvolutionReport(
            file_changes=[
                FileChange(file_path="a.py", action="modified"),
                FileChange(file_path="b.py", action="modified"),
                FileChange(file_path="c.py", action="modified"),
            ]
        )
        assert len(report.file_changes) == 3

    def test_test_results(self) -> None:
        """测试测试结果统计"""
        report = EvolutionReport(
            test_results=TestSummary(passed=3, failed=1, skipped=1, errors=0)
        )
        assert report.test_results.passed == 3
        assert report.test_results.failed == 1
        assert report.test_results.total == 5
        assert report.test_results.pass_rate == 60.0

    def test_to_dict(self) -> None:
        """测试完整序列化为字典"""
        report = EvolutionReport(
            report_id="EVO-TEST-001",
            task="测试任务",
            duration_seconds=12.5,
            executive_summary="测试摘要",
            success=True,
            steps_completed=3,
            total_steps=5,
            total_lines_added=10,
            total_lines_removed=2,
            file_changes=[
                FileChange(file_path="a.py", action="modified", lines_added=10, lines_removed=2),
            ],
            test_results=TestSummary(passed=1, failed=0),
            risk_analysis=[RiskItem(risk="测试风险", severity="medium")],
            rollback_plan={"strategy": "git revert"},
            lessons_learned=["重要教训"],
            metadata={"key": "value"},
        )
        d = report.to_dict()
        assert d["report_id"] == "EVO-TEST-001"
        assert d["task"] == "测试任务"
        assert d["success"] is True
        assert d["steps_completed"] == 3
        assert d["total_steps"] == 5
        assert d["total_lines_added"] == 10
        assert d["total_lines_removed"] == 2
        assert len(d["file_changes"]) == 1
        assert len(d["risk_analysis"]) == 1
        assert len(d["lessons_learned"]) == 1

    def test_to_json(self) -> None:
        """测试 JSON 序列化"""
        report = EvolutionReport(
            report_id="EVO-JSON-001",
            task="JSON 测试",
            success=True,
            file_changes=[
                FileChange(file_path="a.py", action="modified", lines_added=10, lines_removed=5),
            ],
            test_results=TestSummary(passed=1, failed=0),
        )
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["report_id"] == "EVO-JSON-001"
        assert data["success"] is True
        assert len(data["file_changes"]) == 1
        assert len(data["test_results"]) > 0

    def test_to_markdown(self) -> None:
        """测试 Markdown 输出"""
        report = EvolutionReport(
            report_id="EVO-MD-001",
            task="测试任务",
            success=True,
            file_changes=[
                FileChange(
                    file_path="src/main.py",
                    action="modified",
                    lines_added=10,
                    lines_removed=5,
                    description="修复 bug",
                )
            ],
            test_results=TestSummary(passed=1, failed=0),
            risk_analysis=[RiskItem(risk="低风险", severity="low")],
            rollback_plan={"strategy": "git revert HEAD"},
            lessons_learned=["经验教训"],
        )
        md = report.to_markdown()
        assert "EVO-MD-001" in md
        assert "测试任务" in md
        assert "成功" in md
        assert "src/main.py" in md
        assert "经验教训" in md

    def test_to_markdown_failure(self) -> None:
        """测试失败报告的 Markdown 输出"""
        report = EvolutionReport(
            report_id="EVO-MD-FAIL",
            task="失败任务",
            success=False,
            test_results=TestSummary(passed=0, failed=1, failed_tests=["test_broken"]),
        )
        md = report.to_markdown()
        assert "失败" in md

    def test_to_markdown_empty(self) -> None:
        """测试空报告的 Markdown 输出"""
        report = EvolutionReport(task="空任务")
        md = report.to_markdown()
        assert "空任务" in md
        assert "无文件变更" in md

    def test_roundtrip_serialization(self) -> None:
        """测试 JSON 序列化往返"""
        original = EvolutionReport(
            report_id="EVO-RT-001",
            task="往返测试",
            success=True,
            file_changes=[
                FileChange(file_path="a.py", action="modified", lines_added=10, lines_removed=3),
                FileChange(file_path="b.py", action="modified", lines_added=5, lines_removed=0),
            ],
            test_results=TestSummary(passed=2, failed=0),
            lessons_learned=["经验1", "经验2"],
        )
        data = original.to_dict()
        rebuilt = EvolutionReport(
            report_id=data["report_id"],
            task=data["task"],
            success=data["success"],
            total_lines_added=data["total_lines_added"],
            total_lines_removed=data["total_lines_removed"],
            lessons_learned=data["lessons_learned"],
        )
        assert rebuilt.report_id == original.report_id
        assert rebuilt.task == original.task
        assert rebuilt.success == original.success


# ── ReportGenerator 测试 ─────────────────────────────────


class TestReportGenerator:
    """ReportGenerator 测试"""

    def test_default_workspace(self) -> None:
        """测试默认工作区"""
        gen = ReportGenerator()
        assert gen._workspace is not None

    def test_custom_workspace(self, tmp_path: Path) -> None:
        """测试自定义工作区"""
        gen = ReportGenerator(workspace=tmp_path)
        assert gen._workspace == tmp_path

    def test_generate_basic(self, generator: ReportGenerator) -> None:
        """测试基本报告生成"""
        report = generator.generate(
            task="实现用户登录",
            changes=[
                {"file": "src/auth.py", "action": "created", "lines_added": 50, "lines_removed": 0},
            ],
            test_results={"passed": 10, "failed": 0},
            success=True,
            steps_completed=3,
            total_steps=5,
            duration_seconds=2.5,
        )
        assert report.task == "实现用户登录"
        assert report.success is True
        assert report.steps_completed == 3
        assert report.total_steps == 5
        assert report.duration_seconds == 2.5
        assert len(report.file_changes) == 1
        assert report.file_changes[0].file_path == "src/auth.py"
        assert report.total_lines_added == 50
        assert report.test_results.passed == 10

    def test_generate_with_file_path_key(self, generator: ReportGenerator) -> None:
        """测试使用 file_path key 的变更"""
        report = generator.generate(
            task="修复 bug",
            changes=[
                {
                    "file_path": "src/broken.py",
                    "action": "modified",
                    "lines_added": 5,
                    "lines_removed": 5,
                    "description": "有 bug 的修改",
                }
            ],
            success=False,
        )
        assert report.success is False
        assert report.file_changes[0].file_path == "src/broken.py"

    def test_generate_with_risks(self, generator: ReportGenerator) -> None:
        """测试包含风险分析的报告"""
        report = generator.generate(
            task="安全修复",
            risks=[
                {
                    "risk": "SQL 注入风险",
                    "severity": "critical",
                    "mitigation": "使用参数化查询",
                }
            ],
        )
        assert len(report.risk_analysis) == 1
        assert report.risk_analysis[0].risk == "SQL 注入风险"
        assert report.risk_analysis[0].severity == "critical"

    def test_generate_with_rollback_plan(self, generator: ReportGenerator) -> None:
        """测试包含回滚方案的报告"""
        report = generator.generate(
            task="部署",
            rollback_plan={
                "strategy": "git revert",
                "steps": ["git revert HEAD", "重新部署"],
            },
        )
        assert "git revert" in report.rollback_plan["strategy"]

    def test_generate_with_lessons(self, generator: ReportGenerator) -> None:
        """测试包含经验教训的报告"""
        report = generator.generate(
            task="重构",
            lessons=["单元测试很重要", "代码审查发现隐藏 bug"],
        )
        assert len(report.lessons_learned) == 2
        assert "单元测试" in report.lessons_learned[0]

    def test_generate_empty(self, generator: ReportGenerator) -> None:
        """测试空报告生成"""
        report = generator.generate(task="空任务")
        assert report.task == "空任务"
        assert len(report.file_changes) == 0
        assert report.test_results.total == 0
        assert report.success is True

    def test_generate_auto_risk_analysis(self, generator: ReportGenerator) -> None:
        """测试自动风险分析"""
        report = generator.generate(
            task="大范围变更",
            changes=[
                {"file": f"src/file_{i}.py", "action": "modified", "lines_added": 10, "lines_removed": 5}
                for i in range(15)
            ],
            success=False,
        )
        assert len(report.risk_analysis) > 0  # 应自动触发风险分析

    def test_generate_auto_risk_test_failures(self, generator: ReportGenerator) -> None:
        """测试失败测试触发风险分析"""
        report = generator.generate(
            task="测试失败任务",
            test_results={"passed": 5, "failed": 4, "coverage_pct": 50},
        )
        assert len(report.risk_analysis) > 0  # 失败测试触发风险

    def test_get_stats(self, generator: ReportGenerator) -> None:
        """测试统计信息"""
        generator.generate(task="task 1")
        generator.generate(task="task 2")
        stats = generator.get_stats()
        assert stats["total_reports"] == 2

    def test_default_rollback_plan(self, generator: ReportGenerator) -> None:
        """测试默认回滚方案"""
        plan = generator._default_rollback_plan()
        assert plan["strategy"] == "git_revert"
        assert "steps" in plan
        assert len(plan["steps"]) > 0

    def test_parse_file_changes(self, generator: ReportGenerator) -> None:
        """测试解析文件变更"""
        changes = [
            {"file": "a.py", "action": "added", "lines_added": 10, "lines_removed": 0, "description": "新文件"},
            {"file_path": "b.py", "action": "modified", "added": 5, "removed": 3, "desc": "修改"},
        ]
        result = generator._parse_file_changes(changes)
        assert len(result) == 2
        assert result[0].file_path == "a.py"
        assert result[0].action == "added"
        assert result[0].lines_added == 10
        assert result[1].file_path == "b.py"
        assert result[1].lines_added == 5
        assert result[1].lines_removed == 3

    def test_parse_test_results(self, generator: ReportGenerator) -> None:
        """测试解析测试结果"""
        results = {"passed": 10, "failed": 2, "skipped": 1, "errors": 0, "duration_ms": 500.0}
        ts = generator._parse_test_results(results)
        assert ts.passed == 10
        assert ts.failed == 2
        assert ts.total == 13

    def test_parse_risks(self, generator: ReportGenerator) -> None:
        """测试解析风险列表"""
        risks = [
            {"risk": "R1", "severity": "high", "mitigation": "M1"},
            {"description": "R2", "severity": "low"},
        ]
        result = generator._parse_risks(risks)
        assert len(result) == 2
        assert result[0].risk == "R1"
        assert result[1].risk == "R2"

    def test_generate_summary_success(self, generator: ReportGenerator) -> None:
        """测试成功摘要"""
        fc = generator._parse_file_changes([
            {"file": "a.py", "lines_added": 10, "lines_removed": 2}
        ])
        ts = TestSummary(passed=10, failed=0)
        summary = generator._generate_summary(
            task="测试任务",
            success=True,
            file_changes=fc,
            test_summary=ts,
            risk_items=[],
            steps_completed=3,
            total_steps=5,
        )
        assert "成功" in summary
        assert "测试任务" in summary
        assert "100.0%" in summary

    def test_generate_summary_failure(self, generator: ReportGenerator) -> None:
        """测试失败摘要"""
        fc = generator._parse_file_changes([
            {"file": "a.py", "lines_added": 5, "lines_removed": 0}
        ])
        ts = TestSummary(passed=1, failed=1)
        summary = generator._generate_summary(
            task="失败任务",
            success=False,
            file_changes=fc,
            test_summary=ts,
            risk_items=[],
            steps_completed=1,
            total_steps=3,
        )
        assert "未完全成功" in summary


# ── generate_change_report 便捷函数 ──────────────────────


class TestGenerateChangeReport:
    """便捷函数测试"""

    def test_basic(self) -> None:
        """测试基本用法"""
        report = generate_change_report(
            task="测试任务",
            changes=[
                {"file": "a.py", "action": "modified", "lines_added": 10, "lines_removed": 5},
            ],
            test_results={"passed": 10, "failed": 0},
            success=True,
        )
        assert report.task == "测试任务"
        assert report.success is True
        assert len(report.file_changes) == 1

    def test_with_risks(self) -> None:
        """测试带风险的报告"""
        report = generate_change_report(
            task="风险任务",
            risks=[{"risk": "R1", "severity": "high"}],
        )
        assert len(report.risk_analysis) == 1


# ── 空报告处理 ──────────────────────────────────────────


class TestEmptyReportHandling:
    """空报告处理测试"""

    def test_empty_report_markdown(self) -> None:
        """测试空报告的 Markdown 输出"""
        report = EvolutionReport(task="空任务")
        md = report.to_markdown()
        assert "空任务" in md
        assert "无文件变更" in md

    def test_empty_report_json(self) -> None:
        """测试空报告的 JSON 输出"""
        report = EvolutionReport()
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["file_changes"] == []
        assert data["lessons_learned"] == []

    def test_empty_risk_analysis_auto(self, generator: ReportGenerator) -> None:
        """测试空输入时自动风险分析"""
        report = generator.generate(task="空任务", success=True)
        # 空任务不应触发风险
        assert len(report.risk_analysis) == 0