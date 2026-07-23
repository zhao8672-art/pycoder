"""
标准化执行报告 — 借鉴 Hermes 铁律报告制度

每次任务完成后输出统一格式的执行报告，包含:
  - 任务名称与执行结果
  - 关键数据（耗时/Token/成本/改动文件数）
  - 产出清单（改了什么/做了什么）
  - 异常记录（未预料的错误/回退/重试）
  - 下一步建议

报告模板:
  ├─ 任务名称
  ├─ 执行结果: success/failure/partial
  ├─ 关键数据: 耗时 / Token消耗 / 成本 / 改动文件数
  ├─ 产出清单
  │  ├─ 改了什么（文件+行号）
  │  └─ 做了什么（操作摘要）
  ├─ 异常记录: 未预料的错误/回退/重试
  └─ 下一步建议

用法:
  from pycoder.brain.execution_report import ExecutionReport, ReportBuilder

  builder = ReportBuilder()
  report = builder.build(pipeline_result)
  print(report.to_markdown())
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReportStatus(StrEnum):
    """报告状态"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass
class FileChange:
    """文件变更记录"""
    file_path: str
    change_type: str = "modified"  # created/modified/deleted
    lines_added: int = 0
    lines_removed: int = 0
    description: str = ""


@dataclass
class OperationSummary:
    """操作摘要"""
    operation: str
    status: str = "success"
    details: str = ""
    duration_ms: float = 0.0


@dataclass
class ExecutionReport:
    """标准化执行报告"""
    report_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_name: str = ""
    status: ReportStatus = ReportStatus.SUCCESS
    created_at: float = field(default_factory=time.time)

    # 关键数据
    duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    files_changed: int = 0
    agents_involved: list[str] = field(default_factory=list)
    model_used: str = ""

    # 产出清单
    file_changes: list[FileChange] = field(default_factory=list)
    operations: list[OperationSummary] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)

    # 质量指标
    test_coverage: float = 0.0
    quality_score: float = 0.0
    code_review_grade: str = ""

    # 异常记录
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retries: list[dict[str, Any]] = field(default_factory=list)
    rollbacks: list[str] = field(default_factory=list)

    # 下一步建议
    recommendations: list[str] = field(default_factory=list)
    lessons_learned: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "task_name": self.task_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "key_metrics": {
                "duration_ms": self.duration_ms,
                "total_tokens": self.total_tokens,
                "total_cost": self.total_cost,
                "files_changed": self.files_changed,
                "agents_involved": self.agents_involved,
                "model_used": self.model_used,
            },
            "deliverables": {
                "file_changes": [
                    {"file": f.file_path, "type": f.change_type,
                     "+lines": f.lines_added, "-lines": f.lines_removed,
                     "desc": f.description}
                    for f in self.file_changes
                ],
                "operations": [
                    {"op": o.operation, "status": o.status,
                     "details": o.details, "duration_ms": o.duration_ms}
                    for o in self.operations
                ],
                "deliverables": self.deliverables,
            },
            "quality": {
                "test_coverage": self.test_coverage,
                "quality_score": self.quality_score,
                "code_review_grade": self.code_review_grade,
            },
            "anomalies": {
                "errors": self.errors,
                "warnings": self.warnings,
                "retries": self.retries,
                "rollbacks": self.rollbacks,
            },
            "recommendations": self.recommendations,
            "lessons_learned": self.lessons_learned,
        }

    def to_markdown(self) -> str:
        """生成 Markdown 格式报告"""
        lines = [
            f"# PyCoder 执行报告",
            f"",
            f"**报告 ID**: {self.report_id}",
            f"**任务名称**: {self.task_name}",
            f"**执行结果**: {self._status_icon()} {self.status.value}",
            f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.created_at))}",
            f"",
            f"## 关键数据",
            f"",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 总耗时 | {self.duration_ms:.0f}ms ({self.duration_ms / 1000:.1f}s) |",
            f"| Token 消耗 | {self.total_tokens:,} |",
            f"| 成本 | ${self.total_cost:.4f} |",
            f"| 改动文件数 | {self.files_changed} |",
            f"| 参与 Agent | {', '.join(self.agents_involved) if self.agents_involved else 'N/A'} |",
            f"| 使用模型 | {self.model_used or 'N/A'} |",
            f"",
            f"## 产出清单",
            f"",
        ]

        if self.file_changes:
            lines.append("### 文件变更")
            lines.append("")
            for fc in self.file_changes:
                lines.append(f"- `{fc.file_path}` ({fc.change_type}): {fc.description}")
            lines.append("")

        if self.operations:
            lines.append("### 操作摘要")
            lines.append("")
            for op in self.operations:
                icon = "[OK]" if op.status == "success" else "[FAIL]"
                lines.append(f"- {icon} {op.operation}: {op.details} ({op.duration_ms:.0f}ms)")
            lines.append("")

        if self.deliverables:
            lines.append("### 交付物")
            lines.append("")
            for d in self.deliverables:
                lines.append(f"- {d}")
            lines.append("")

        lines.append("## 质量指标")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 测试覆盖率 | {self.test_coverage:.1f}% |")
        lines.append(f"| 质量评分 | {self.quality_score:.1f}/100 |")
        lines.append(f"| 代码审查等级 | {self.code_review_grade or 'N/A'} |")
        lines.append("")

        if self.errors or self.warnings:
            lines.append("## 异常记录")
            lines.append("")
            for err in self.errors:
                lines.append(f"- [ERROR] {err}")
            for warn in self.warnings:
                lines.append(f"- [WARN] {warn}")
            lines.append("")

        if self.recommendations:
            lines.append("## 下一步建议")
            lines.append("")
            for r in self.recommendations:
                lines.append(f"- {r}")
            lines.append("")

        if self.lessons_learned:
            lines.append("## 经验教训")
            lines.append("")
            for ll in self.lessons_learned:
                lines.append(f"- {ll}")
            lines.append("")

        return "\n".join(lines)

    def _status_icon(self) -> str:
        if self.status == ReportStatus.SUCCESS:
            return "[OK]"
        elif self.status == ReportStatus.FAILURE:
            return "[FAIL]"
        return "[WARN]"


class ReportBuilder:
    """报告构建器

    从流水线执行结果构建标准化报告。
    """

    def build(self, pipeline_result: Any) -> ExecutionReport:
        """从流水线结果构建报告

        Args:
            pipeline_result: PipelineResult 对象

        Returns:
            ExecutionReport 标准化报告
        """
        report = ExecutionReport(
            task_name=pipeline_result.task[:200],
            duration_ms=pipeline_result.total_duration_ms,
            total_tokens=pipeline_result.total_tokens,
            total_cost=pipeline_result.total_cost,
            files_changed=len(pipeline_result.deliverables),
            deliverables=pipeline_result.deliverables,
        )

        # 状态映射
        if hasattr(pipeline_result, 'status'):
            status_val = str(pipeline_result.status)
            if status_val == "done":
                report.status = ReportStatus.SUCCESS
            elif status_val == "failed":
                report.status = ReportStatus.FAILURE
            else:
                report.status = ReportStatus.PARTIAL

        # 错误
        if hasattr(pipeline_result, 'errors'):
            report.errors = pipeline_result.errors

        # 质量指标
        if hasattr(pipeline_result, 'grade') and pipeline_result.grade:
            report.quality_score = pipeline_result.grade.score

        return report

    def build_from_dict(self, data: dict[str, Any]) -> ExecutionReport:
        """从字典构建报告"""
        report = ExecutionReport(
            report_id=data.get("report_id", ""),
            task_name=data.get("task_name", ""),
            status=ReportStatus(data.get("status", "success")),
            created_at=data.get("created_at", time.time()),
        )

        metrics = data.get("key_metrics", {})
        report.duration_ms = metrics.get("duration_ms", 0.0)
        report.total_tokens = metrics.get("total_tokens", 0)
        report.total_cost = metrics.get("total_cost", 0.0)
        report.files_changed = metrics.get("files_changed", 0)
        report.agents_involved = metrics.get("agents_involved", [])
        report.model_used = metrics.get("model_used", "")

        deliverables = data.get("deliverables", {})
        for fc in deliverables.get("file_changes", []):
            report.file_changes.append(FileChange(
                file_path=fc.get("file", ""),
                change_type=fc.get("type", "modified"),
                lines_added=fc.get("+lines", 0),
                lines_removed=fc.get("-lines", 0),
                description=fc.get("desc", ""),
            ))

        quality = data.get("quality", {})
        report.test_coverage = quality.get("test_coverage", 0.0)
        report.quality_score = quality.get("quality_score", 0.0)
        report.code_review_grade = quality.get("code_review_grade", "")

        anomalies = data.get("anomalies", {})
        report.errors = anomalies.get("errors", [])
        report.warnings = anomalies.get("warnings", [])

        report.recommendations = data.get("recommendations", [])
        report.lessons_learned = data.get("lessons_learned", [])

        return report

    def save_report(self, report: ExecutionReport, path: Path | None = None) -> Path:
        """保存报告到文件"""
        save_path = path or Path.home() / ".pycoder" / "reports" / f"{report.report_id}.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 同时保存 Markdown 版本
        md_path = save_path.with_suffix(".md")
        md_path.write_text(report.to_markdown(), encoding="utf-8")

        logger.info("报告已保存: %s", save_path)
        return save_path


# 全局单例
_report_builder: ReportBuilder | None = None


def get_report_builder() -> ReportBuilder:
    """获取全局报告构建器"""
    global _report_builder
    if _report_builder is None:
        _report_builder = ReportBuilder()
    return _report_builder