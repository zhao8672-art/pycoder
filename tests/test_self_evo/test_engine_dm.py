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
# 模块 1: engine.py — 数据模型
# ═══════════════════════════════════════════════════════════════


class TestCodeIssue:
    """CodeIssue 数据类测试"""

    def test_minimal_creation(self):
        """最小字段创建"""
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(file="test.py", line=10, severity="high", issue_type="bug", title="裸 except")
        assert issue.file == "test.py"
        assert issue.line == 10
        assert issue.severity == "high"
        assert issue.issue_type == "bug"
        assert issue.title == "裸 except"
        assert issue.description == ""
        assert issue.suggestion == ""
        assert issue.code_snippet == ""

    def test_full_fields(self):
        """全部字段创建"""
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(
            file="app.py", line=42, severity="critical", issue_type="security",
            title="硬编码密钥", description="发现 API Key", suggestion="使用环境变量",
            code_snippet="KEY='sk-xxx'",
        )
        assert issue.description == "发现 API Key"
        assert issue.suggestion == "使用环境变量"
        assert issue.code_snippet == "KEY='sk-xxx'"


class TestScanReport:
    """ScanReport 数据类测试"""

    def test_default_fields(self):
        """默认字段"""
        from pycoder.capabilities.self_evo.engine import ScanReport

        report = ScanReport(path="pycoder", files_scanned=10, total_issues=5)
        assert report.path == "pycoder"
        assert report.files_scanned == 10
        assert report.total_issues == 5
        assert report.issues == []
        assert report.summary == ""
        assert report.duration_seconds == 0.0


class TestFixProposal:
    """FixProposal 数据类测试"""

    def test_creation(self):
        """创建修复方案"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path="a.py")
        assert proposal.action == "replace"
        assert proposal.risk_level == "low"
        assert proposal.old_code == ""

    def test_risk_level_default(self):
        """风险等级默认值"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="refactor", file_path="a.py", risk_level="high")
        assert proposal.risk_level == "high"


class TestFixResult:
    """FixResult 数据类测试"""

    def test_success(self):
        """成功结果"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal, FixResult

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path="a.py")
        result = FixResult(proposal=proposal, success=True, test_passed=True,
                           git_branch="evo/123", git_commit="abc123")
        assert result.success is True
        assert result.test_passed is True
        assert result.git_branch == "evo/123"
        assert result.error is None

    def test_failure_with_rollback(self):
        """失败且需要回滚"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal, FixResult

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path="a.py")
        result = FixResult(proposal=proposal, success=False, error="测试失败",
                           rollback_needed=True)
        assert result.success is False
        assert result.rollback_needed is True
        assert result.error == "测试失败"


class TestEvolutionRecord:
    """EvolutionRecord 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.engine import EvolutionRecord

        record = EvolutionRecord()
        assert record.action == ""
        assert record.success is False

    def test_full_record(self):
        """完整记录"""
        from pycoder.capabilities.self_evo.engine import EvolutionRecord

        record = EvolutionRecord(
            action="fix", issue_type="bug", file="a.py", success=True,
            fix_description="修复了裸 except", test_result="passed", lessons="使用except Exception",
        )
        assert record.action == "fix"
        assert record.success is True
        assert record.lessons == "使用except Exception"


class TestEvolutionTask:
    """EvolutionTask 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask

        task = EvolutionTask()
        assert task.status == "pending"
        assert task.type == "fix"
        assert len(task.id) == 8

    def test_to_dict(self):
        """to_dict 序列化"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask

        task = EvolutionTask(type="optimize", description="优化性能")
        d = task.to_dict()
        assert d["type"] == "optimize"
        assert d["status"] == "pending"
        assert d["id"] == task.id


class TestEvolutionStats:
    """EvolutionStats 数据类测试"""

    def test_success_rate_zero(self):
        """零任务时成功率为 0"""
        from pycoder.capabilities.self_evo.engine import EvolutionStats

        stats = EvolutionStats()
        assert stats.success_rate == 0.0

    def test_success_rate_calculation(self):
        """成功率计算"""
        from pycoder.capabilities.self_evo.engine import EvolutionStats

        stats = EvolutionStats(total_tasks=10, successful=7, failed=3)
        assert stats.success_rate == 0.7

    def test_to_dict(self):
        """to_dict 序列化"""
        from pycoder.capabilities.self_evo.engine import EvolutionStats

        stats = EvolutionStats(total_tasks=5, successful=4, failed=1, bugs_fixed=3, lines_changed=50)
        d = stats.to_dict()
        assert d["total_tasks"] == 5
        assert d["successful"] == 4
        assert d["bugs_fixed"] == 3
        assert "success_rate" in d


class TestBuildEvolutionReport:
    """_build_evolution_report 函数测试"""

    def test_basic_report(self):
        """基本报告"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask(type="fix", description="测试任务")
        report = _build_evolution_report(task)
        assert report["task_id"] == task.id
        assert report["task_type"] == "fix"
        assert report["status"] == "pending"

    def test_with_grade_info(self):
        """带 grade_info"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask()
        grade = {"task_type": "fix", "score": 85}
        report = _build_evolution_report(task, grade_info=grade)
        assert report["grade"] == grade

    def test_with_source_trace(self):
        """带 source_trace"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask()
        trace = {"source": "api"}
        report = _build_evolution_report(task, source_trace=trace)
        assert report["source_trace"] == trace

    def test_long_test_result_truncated(self):
        """测试结果截断"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask(test_result="x" * 500)
        report = _build_evolution_report(task)
        assert len(report["test_result"]) <= 200


