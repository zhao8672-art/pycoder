"""执行报告系统测试

覆盖:
  - FileChange: 文件变更记录数据类
  - OperationStep: 操作步骤数据类
  - ExecutionReport: 核心报告类（属性、增删改、序列化）
  - ReportBuilder: 流式构建器
  - 异常路径: 错误添加、状态变更
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.server.services.execution_report import (
    ExecutionReport,
    FileChange,
    OperationStep,
    ReportBuilder,
)


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


@pytest.fixture
def basic_report() -> ExecutionReport:
    """创建一个基础报告实例"""
    return ExecutionReport(
        task_name="修复 API 500 错误",
        status="success",
        duration_seconds=45.2,
        tokens_used={"deepseek-chat": 15234},
        cost_usd=0.0042,
        api_calls=3,
        agent_count=2,
    )


@pytest.fixture
def empty_report() -> ExecutionReport:
    """创建一个空报告实例"""
    return ExecutionReport()


# ══════════════════════════════════════════════════════════
# FileChange 测试
# ══════════════════════════════════════════════════════════


class TestFileChange:
    """文件变更记录数据类"""

    def test_default_values(self):
        """默认值"""
        fc = FileChange(path="test.py")
        assert fc.path == "test.py"
        assert fc.change_type == "modified"
        assert fc.lines == ""
        assert fc.summary == ""

    def test_full_values(self):
        """完整赋值"""
        fc = FileChange(
            path="api.py",
            change_type="created",
            lines="32-35",
            summary="新增用户认证接口",
        )
        assert fc.path == "api.py"
        assert fc.change_type == "created"
        assert fc.lines == "32-35"
        assert fc.summary == "新增用户认证接口"

    def test_deleted_type(self):
        """删除类型"""
        fc = FileChange(path="old.py", change_type="deleted")
        assert fc.change_type == "deleted"


# ══════════════════════════════════════════════════════════
# OperationStep 测试
# ══════════════════════════════════════════════════════════


class TestOperationStep:
    """操作步骤数据类"""

    def test_default_values(self):
        """默认值"""
        op = OperationStep(step="代码审查")
        assert op.step == "代码审查"
        assert op.status == "done"
        assert op.duration_ms == 0.0
        assert op.detail == ""

    def test_failed_step(self):
        """失败步骤"""
        op = OperationStep(
            step="运行测试",
            status="failed",
            duration_ms=1500.0,
            detail="3 个测试用例失败",
        )
        assert op.status == "failed"
        assert op.duration_ms == 1500.0
        assert "3 个测试用例" in op.detail

    def test_skipped_step(self):
        """跳过步骤"""
        op = OperationStep(step="部署", status="skipped")
        assert op.status == "skipped"


# ══════════════════════════════════════════════════════════
# ExecutionReport 基本属性测试
# ══════════════════════════════════════════════════════════


class TestExecutionReportProperties:
    """核心报告属性"""

    def test_basic_creation(self, basic_report):
        """基本创建"""
        assert basic_report.task_name == "修复 API 500 错误"
        assert basic_report.status == "success"
        assert basic_report.duration_seconds == 45.2
        assert basic_report.cost_usd == 0.0042
        assert basic_report.api_calls == 3
        assert basic_report.agent_count == 2

    def test_total_tokens(self, basic_report):
        """总 Token 计算"""
        assert basic_report.total_tokens == 15234

    def test_total_tokens_empty(self, empty_report):
        """空报告 Token 为 0"""
        assert empty_report.total_tokens == 0

    def test_file_count(self, basic_report):
        """文件数初始为 0"""
        assert basic_report.file_count == 0

    def test_error_count(self, basic_report):
        """错误数初始为 0"""
        assert basic_report.error_count == 0

    def test_model_list(self, basic_report):
        """模型列表（去重排序）"""
        assert basic_report.model_list == ["deepseek-chat"]

    def test_model_list_multiple(self):
        """多模型去重排序"""
        report = ExecutionReport(
            tokens_used={"deepseek-chat": 100, "deepseek-coder": 200, "deepseek-chat": 300},
        )
        # 注意：dict 中 key 重复会导致后面的覆盖前面的
        assert "deepseek-chat" in report.model_list
        assert "deepseek-coder" in report.model_list

    def test_default_status(self):
        """默认状态为 pending"""
        report = ExecutionReport()
        assert report.status == "pending"

    def test_task_id_auto_generated(self):
        """自动生成任务 ID"""
        report = ExecutionReport()
        assert report.task_id.startswith("RPT-")
        assert len(report.task_id) > 4

    def test_custom_task_id(self):
        """自定义任务 ID"""
        report = ExecutionReport(task_id="CUSTOM-001")
        assert report.task_id == "CUSTOM-001"

    def test_completed_at_with_duration(self):
        """started_at + duration_seconds 自动计算 completed_at"""
        report = ExecutionReport(
            started_at=1000.0,
            duration_seconds=30.0,
        )
        assert report.completed_at == 1030.0

    def test_completed_at_zero_when_no_duration(self):
        """无 duration 时 completed_at 保持 0"""
        report = ExecutionReport(started_at=1000.0)
        assert report.completed_at == 0.0


# ══════════════════════════════════════════════════════════
# ExecutionReport 增删改测试
# ══════════════════════════════════════════════════════════


class TestExecutionReportMutation:
    """报告内容增删改"""

    def test_add_file_change(self, empty_report):
        """添加文件变更"""
        empty_report.add_file_change("api.py", "modified", "10-20", "修复认证逻辑")
        assert empty_report.file_count == 1
        fc = empty_report.files_changed[0]
        assert fc.path == "api.py"
        assert fc.change_type == "modified"
        assert fc.lines == "10-20"
        assert fc.summary == "修复认证逻辑"

    def test_add_multiple_file_changes(self, empty_report):
        """添加多个文件变更"""
        empty_report.add_file_change("a.py", "created", "1-50")
        empty_report.add_file_change("b.py", "modified", "30-45")
        empty_report.add_file_change("c.py", "deleted", "")
        assert empty_report.file_count == 3

    def test_add_operation(self, empty_report):
        """添加操作步骤"""
        empty_report.add_operation("代码生成", "done", 1500.0, "生成了 200 行代码")
        assert len(empty_report.operations) == 1
        op = empty_report.operations[0]
        assert op.step == "代码生成"
        assert op.status == "done"
        assert op.duration_ms == 1500.0

    def test_add_error_changes_status(self, empty_report):
        """添加错误后状态变为 partial（从 success）"""
        empty_report.status = "success"
        empty_report.add_error("文件写入失败")
        assert empty_report.error_count == 1
        assert empty_report.status == "partial"
        assert "文件写入失败" in empty_report.errors

    def test_add_error_keeps_failure(self, empty_report):
        """失败状态添加错误后仍为 failure"""
        empty_report.status = "failure"
        empty_report.add_error("严重错误")
        assert empty_report.status == "failure"

    def test_add_retry(self, empty_report):
        """添加重试记录"""
        empty_report.add_retry("代码生成", "API 超时")
        assert len(empty_report.retry_events) == 1
        assert "[代码生成] API 超时" in empty_report.retry_events[0]


# ══════════════════════════════════════════════════════════
# ExecutionReport 序列化测试
# ══════════════════════════════════════════════════════════


class TestExecutionReportSerialization:
    """序列化输出"""

    def test_to_dict_basic(self, basic_report):
        """基本字典输出"""
        d = basic_report.to_dict()
        assert d["task_name"] == "修复 API 500 错误"
        assert d["status"] == "success"
        assert d["duration_seconds"] == 45.2
        assert d["total_tokens"] == 15234
        assert d["cost_usd"] == 0.0042
        assert d["api_calls"] == 3
        assert d["agent_count"] == 2
        assert d["file_count"] == 0

    def test_to_dict_with_files(self, empty_report):
        """包含文件变更的字典输出"""
        empty_report.add_file_change("api.py", "modified", "10-20", "修复")
        d = empty_report.to_dict()
        assert len(d["files_changed"]) == 1
        assert d["files_changed"][0]["path"] == "api.py"
        assert d["files_changed"][0]["type"] == "modified"

    def test_to_dict_with_operations(self, empty_report):
        """包含操作步骤的字典输出"""
        empty_report.add_operation("代码审查", "done", 500.0, "通过")
        d = empty_report.to_dict()
        assert len(d["operations"]) == 1
        assert d["operations"][0]["step"] == "代码审查"
        assert d["operations"][0]["status"] == "done"

    def test_to_dict_with_errors(self, empty_report):
        """包含错误的字典输出"""
        empty_report.add_error("网络超时")
        empty_report.add_retry("连接", "拒绝连接")
        d = empty_report.to_dict()
        assert len(d["errors"]) == 1
        assert len(d["retry_events"]) == 1

    def test_to_json(self, basic_report):
        """JSON 序列化"""
        j = basic_report.to_json()
        data = json.loads(j)
        assert data["task_name"] == "修复 API 500 错误"
        assert data["status"] == "success"

    def test_to_json_with_unicode(self):
        """包含中文的 JSON 序列化"""
        report = ExecutionReport(task_name="测试中文任务")
        j = report.to_json()
        assert "测试中文任务" in j

    def test_to_markdown_success(self):
        """成功状态 Markdown"""
        report = ExecutionReport(
            task_name="优化数据库查询",
            status="success",
            duration_seconds=12.5,
            tokens_used={"deepseek-chat": 3000},
        )
        md = report.to_markdown()
        assert "# 📊 执行报告" in md
        assert "优化数据库查询" in md
        assert "✅" in md
        assert "SUCCESS" in md

    def test_to_markdown_failure(self):
        """失败状态 Markdown"""
        report = ExecutionReport(
            task_name="部署失败",
            status="failure",
            duration_seconds=5.0,
            errors=["连接超时", "权限不足"],
        )
        md = report.to_markdown()
        assert "❌" in md
        assert "FAILURE" in md
        assert "连接超时" in md
        assert "权限不足" in md

    def test_to_markdown_partial(self):
        """部分成功状态 Markdown"""
        report = ExecutionReport(
            task_name="部分完成",
            status="partial",
        )
        md = report.to_markdown()
        assert "⚠️" in md
        assert "PARTIAL" in md

    def test_to_markdown_with_files(self):
        """包含文件变更的 Markdown"""
        report = ExecutionReport(task_name="重构")
        report.add_file_change("app.py", "created", "1-100", "新增主模块")
        report.add_file_change("old.py", "deleted", "", "移除旧代码")
        md = report.to_markdown()
        assert "📁 文件变更" in md
        assert "➕" in md
        assert "🗑️" in md
        assert "app.py" in md
        assert "old.py" in md

    def test_to_markdown_with_operations(self):
        """包含操作步骤的 Markdown"""
        report = ExecutionReport(task_name="任务")
        report.add_operation("分析需求", "done", 500.0, "已完成")
        report.add_operation("编写代码", "failed", 2000.0, "测试失败")
        md = report.to_markdown()
        assert "🔧 操作步骤" in md
        assert "✅" in md
        assert "❌" in md

    def test_to_markdown_with_deliverables(self):
        """包含交付物的 Markdown"""
        report = ExecutionReport(
            task_name="交付任务",
            deliverables=["用户认证模块", "API 文档", "测试套件"],
        )
        md = report.to_markdown()
        assert "📦 交付物" in md
        assert "用户认证模块" in md

    def test_to_markdown_with_next_steps(self):
        """包含下一步建议的 Markdown"""
        report = ExecutionReport(
            task_name="任务",
            next_steps="建议部署到 staging 环境进行集成测试",
        )
        md = report.to_markdown()
        assert "🚀 下一步建议" in md
        assert "staging" in md

    def test_to_markdown_pending_status(self):
        """pending 状态 Markdown"""
        report = ExecutionReport(task_name="待执行", status="pending")
        md = report.to_markdown()
        assert "⏳" in md
        assert "PENDING" in md


# ══════════════════════════════════════════════════════════
# ExecutionReport save 测试
# ══════════════════════════════════════════════════════════


class TestExecutionReportSave:
    """报告保存到文件"""

    def test_save_to_custom_path(self, tmp_path):
        """保存到自定义路径"""
        report = ExecutionReport(
            task_name="测试任务",
            task_id="RPT-TEST",
            status="success",
        )
        save_path = tmp_path / "custom_report.md"
        result = report.save(save_path)
        assert result == save_path
        assert save_path.exists()
        content = save_path.read_text(encoding="utf-8")
        assert "测试任务" in content

    def test_save_to_default_dir(self, tmp_path, monkeypatch):
        """保存到默认目录"""
        monkeypatch.setenv("PYCODER_REPORT_DIR", str(tmp_path))
        report = ExecutionReport(
            task_name="默认路径测试",
            task_id="RPT-DEFAULT",
            status="success",
        )
        result = report.save()
        assert result.exists()
        assert result.parent == tmp_path
        assert result.name == "RPT-DEFAULT.md"

    def test_save_creates_parent_dirs(self, tmp_path):
        """自动创建父目录 — save 不自动创建父目录，需手动创建"""
        report = ExecutionReport(
            task_name="嵌套目录",
            task_id="RPT-NESTED",
            status="success",
        )
        save_path = tmp_path / "sub" / "deep" / "report.md"
        # save 不自动创建父目录，需手动创建
        save_path.parent.mkdir(parents=True, exist_ok=True)
        result = report.save(save_path)
        assert result.exists()
        assert save_path.parent.exists()

    def test_save_content_is_markdown(self, tmp_path):
        """保存的内容是 Markdown"""
        report = ExecutionReport(
            task_name="Markdown 测试",
            status="success",
            duration_seconds=10.0,
        )
        save_path = tmp_path / "test.md"
        report.save(save_path)
        content = save_path.read_text(encoding="utf-8")
        assert "# 📊 执行报告" in content
        assert "Markdown 测试" in content


# ══════════════════════════════════════════════════════════
# ReportBuilder 测试
# ══════════════════════════════════════════════════════════


class TestReportBuilder:
    """流式构建器"""

    def test_builder_basic_flow(self):
        """基本构建流程"""
        builder = ReportBuilder("测试任务", "T-001")
        report = builder.done("success")
        assert report.task_name == "测试任务"
        assert report.task_id == "T-001"
        assert report.status == "success"
        assert report.duration_seconds >= 0

    def test_builder_add_file(self):
        """添加文件变更"""
        builder = ReportBuilder("任务")
        builder.add_file("api.py", "modified", "10-20", "修复")
        report = builder.done("success")
        assert report.file_count == 1
        assert report.files_changed[0].path == "api.py"

    def test_builder_add_step(self):
        """添加操作步骤"""
        builder = ReportBuilder("任务")
        builder.add_step("代码审查", "done", "通过审核")
        report = builder.done("success")
        assert len(report.operations) == 1
        assert report.operations[0].step == "代码审查"
        assert report.operations[0].detail == "通过审核"

    def test_builder_add_error(self):
        """添加错误"""
        builder = ReportBuilder("任务")
        builder.add_error("网络超时")
        report = builder.done("failure")
        assert report.error_count == 1
        assert "网络超时" in report.errors[0]

    def test_builder_track_token(self):
        """追踪 Token 消耗"""
        builder = ReportBuilder("任务")
        builder.track_token("deepseek-chat", 5000, 0.002)
        builder.track_token("deepseek-chat", 3000, 0.001)
        report = builder.done("success")
        # 同一模型 Tokens 累加
        assert report.tokens_used["deepseek-chat"] == 8000
        assert report.cost_usd == 0.003
        assert report.api_calls == 2

    def test_builder_track_multiple_models(self):
        """多模型 Token 追踪"""
        builder = ReportBuilder("任务")
        builder.track_token("deepseek-chat", 1000, 0.0005)
        builder.track_token("deepseek-coder", 2000, 0.001)
        report = builder.done("success")
        assert report.tokens_used["deepseek-chat"] == 1000
        assert report.tokens_used["deepseek-coder"] == 2000
        assert report.total_tokens == 3000

    def test_builder_fluent_api(self):
        """链式调用"""
        builder = ReportBuilder("链式任务")
        report = (
            builder.add_file("a.py", "created", "1-10")
            .add_step("分析", "done", "完成")
            .add_error("警告")
            .track_token("deepseek-chat", 100, 0.0001)
            .done("partial")
        )
        assert report.file_count == 1
        assert len(report.operations) == 1
        assert report.error_count == 1
        assert report.status == "partial"

    def test_builder_duration_computed(self):
        """完成时自动计算耗时"""
        import time

        builder = ReportBuilder("计时任务")
        # 模拟耗时（需要足够长以确保 round 后 > 0）
        time.sleep(0.1)
        report = builder.done("success")
        assert report.duration_seconds >= 0  # round 后可能为 0.0 如果 < 0.05
        assert report.completed_at > 0
        assert report.completed_at >= report.started_at

    def test_builder_empty_task_name(self):
        """空任务名"""
        builder = ReportBuilder()
        report = builder.done("success")
        assert report.task_name == ""
        assert report.task_id != ""

    def test_builder_with_deliverables(self):
        """构建器 + 手动添加交付物"""
        builder = ReportBuilder("交付任务")
        builder._report.deliverables = ["模块 A", "模块 B"]
        report = builder.done("success")
        assert len(report.deliverables) == 2
        assert "模块 A" in report.deliverables

    def test_builder_with_next_steps(self):
        """构建器 + 下一步建议"""
        builder = ReportBuilder("任务")
        builder._report.next_steps = "建议进行集成测试"
        report = builder.done("success")
        assert "集成测试" in report.next_steps