"""
执行报告系统 — 借鉴好运助手铁律报告制度，所有 Agent 任务完成后必须产出标准化报告。

报告模板:
  ├─ 任务名称
  ├─ 执行结果: success/failure/partial
  ├─ 关键数据: 耗时 / Token消耗 / 成本 / 改动文件数
  ├─ 产出清单: 改了什么（文件+行号）/ 做了什么（操作摘要）
  ├─ 异常记录: 未预料的错误/回退/重试
  └─ 下一步建议

用法:
  from pycoder.server.services.execution_report import ExecutionReport, ReportBuilder

  report = ExecutionReport(
      task_name="修复API 500错误",
      status="success",
      duration_seconds=45.2,
      tokens_used={"deepseek-chat": 15234},
      cost_usd=0.0042,
      files_changed=["backend/api.py:32-35", "backend/models.py:18"],
  )
  print(report.to_markdown())
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class FileChange:
    """文件变更记录"""

    path: str
    change_type: str = "modified"  # created | modified | deleted
    lines: str = ""  # 如 "32-35, 40"
    summary: str = ""  # 改动说明


@dataclass
class OperationStep:
    """操作步骤"""

    step: str  # 步骤描述
    status: str = "done"  # done | failed | skipped
    duration_ms: float = 0.0  # 耗时毫秒
    detail: str = ""  # 详细信息


@dataclass
class ExecutionReport:
    """标准化执行报告 — 对标好运助手报告模板"""

    # 基本信息
    task_name: str = ""
    task_id: str = ""
    status: str = "pending"  # success | failure | partial
    agent_count: int = 0  # 参与 Agent 数量

    # 关键数据
    duration_seconds: float = 0.0
    tokens_used: dict[str, int] = field(default_factory=dict)  # {model: tokens}
    cost_usd: float = 0.0
    api_calls: int = 0

    # 产出清单
    files_changed: list[FileChange] = field(default_factory=list)
    operations: list[OperationStep] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)  # 交付物清单

    # 异常记录
    errors: list[str] = field(default_factory=list)
    retry_events: list[str] = field(default_factory=list)
    rollbacks: list[str] = field(default_factory=list)

    # 时间戳
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    _duration_set: bool = False  # 外部是否已设 duration
    next_steps: str = ""

    def __post_init__(self):
        # Bug #5: 不要自动设 completed_at，让 ReportBuilder.done() 或外部调用者负责
        if not self._duration_set and self.duration_seconds > 0:
            self.completed_at = self.started_at + self.duration_seconds
        if not self.task_id:
            self.task_id = f"RPT-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens_used.values())

    @property
    def file_count(self) -> int:
        return len(self.files_changed)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def model_list(self) -> list[str]:
        """去重后的模型列表"""
        return sorted(set(self.tokens_used.keys()))

    def add_file_change(
        self,
        path: str,
        change_type: str = "modified",
        lines: str = "",
        summary: str = "",
    ) -> None:
        """添加文件变更"""
        self.files_changed.append(
            FileChange(
                path=path,
                change_type=change_type,
                lines=lines,
                summary=summary,
            )
        )

    def add_operation(
        self,
        step: str,
        status: str = "done",
        duration_ms: float = 0.0,
        detail: str = "",
    ) -> None:
        """添加操作步骤"""
        self.operations.append(
            OperationStep(
                step=step,
                status=status,
                duration_ms=duration_ms,
                detail=detail,
            )
        )

    def add_error(self, error: str) -> None:
        """添加错误记录"""
        self.errors.append(error)
        if self.status == "success":
            self.status = "partial"

    def add_retry(self, stage: str, reason: str) -> None:
        """添加重试记录"""
        self.retry_events.append(f"[{stage}] {reason}")

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "task_name": self.task_name,
            "task_id": self.task_id,
            "status": self.status,
            "agent_count": self.agent_count,
            "duration_seconds": round(self.duration_seconds, 1),
            "tokens_used": self.tokens_used,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "api_calls": self.api_calls,
            "file_count": self.file_count,
            "files_changed": [
                {
                    "path": f.path,
                    "type": f.change_type,
                    "lines": f.lines,
                    "summary": f.summary,
                }
                for f in self.files_changed
            ],
            "operations": [
                {
                    "step": o.step,
                    "status": o.status,
                    "duration_ms": round(o.duration_ms, 0),
                    "detail": o.detail,
                }
                for o in self.operations
            ],
            "deliverables": self.deliverables,
            "errors": self.errors,
            "retry_events": self.retry_events,
            "rollbacks": self.rollbacks,
            "next_steps": self.next_steps,
            "started_at": datetime.fromtimestamp(self.started_at, tz=UTC).isoformat(),
            "completed_at": datetime.fromtimestamp(self.completed_at, tz=UTC).isoformat(),
        }

    def to_markdown(self) -> str:
        """生成 Markdown 格式报告"""
        status_emoji = {
            "success": "✅",
            "failure": "❌",
            "partial": "⚠️",
            "pending": "⏳",
        }
        emoji = status_emoji.get(self.status, "❓")

        lines = [
            f"# 📊 执行报告: {self.task_name}",
            "",
            "| 项目 | 内容 |",
            "|------|------|",
            f"| 任务ID | `{self.task_id}` |",
            f"| 执行结果 | {emoji} **{self.status.upper()}** |",
            f"| 耗时 | {self.duration_seconds:.1f}s |",
            f"| Token消耗 | {self.total_tokens:,} ({', '.join(self.model_list)}) |",
            f"| 成本 | ${self.cost_usd:.6f} |",
            f"| API调用 | {self.api_calls}次 |",
            f"| Agent数 | {self.agent_count} |",
            f"| 改动文件 | {self.file_count}个 |",
        ]

        # 产出清单
        if self.files_changed:
            lines.extend(["", "## 📁 文件变更"])
            for f in self.files_changed:
                icon = {"created": "➕", "modified": "✏️", "deleted": "🗑️"}.get(f.change_type, "📄")
                line_info = f" (行 {f.lines})" if f.lines else ""
                summary_info = f" — {f.summary}" if f.summary else ""
                lines.append(f"- {icon} `{f.path}`{line_info}{summary_info}")

        # 操作步骤
        if self.operations:
            lines.extend(["", "## 🔧 操作步骤"])
            for o in self.operations:
                icon = {"done": "✅", "failed": "❌", "skipped": "⏭️"}.get(o.status, "❓")
                line = f"- {icon} {o.step}"
                if o.duration_ms > 0:
                    line += f" ({o.duration_ms:.0f}ms)"
                if o.detail:
                    line += f" — {o.detail}"
                lines.append(line)

        # 交付物
        if self.deliverables:
            lines.extend(["", "## 📦 交付物"])
            for d in self.deliverables:
                lines.append(f"- ✅ {d}")

        # 异常记录
        if self.errors or self.retry_events or self.rollbacks:
            lines.extend(["", "## ⚠️ 异常记录"])
            for e in self.errors:
                lines.append(f"- ❌ {e}")
            for r in self.retry_events:
                lines.append(f"- 🔄 {r}")
            for b in self.rollbacks:
                lines.append(f"- ↩️ {b}")

        # 下一步
        if self.next_steps:
            lines.extend(["", "## 🚀 下一步建议", f"{self.next_steps}"])

        lines.extend(
            [
                "",
                "---",
                f"*报告生成时间: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
            ]
        )
        return "\n".join(lines)

    def to_json(self) -> str:
        """转为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: str | Path | None = None) -> Path:
        """保存报告到文件"""
        if path is None:
            import os

            report_dir = Path(
                os.environ.get(
                    "PYCODER_REPORT_DIR",
                    str(Path.home() / ".pycoder" / "reports"),
                )
            )
            report_dir.mkdir(parents=True, exist_ok=True)
            path = report_dir / f"{self.task_id}.md"
        p = Path(path)
        p.write_text(self.to_markdown(), encoding="utf-8")
        return p


# ══════════════════════════════════════════════════════════
# 便捷构建器
# ══════════════════════════════════════════════════════════


class ReportBuilder:
    """流式构建执行报告"""

    def __init__(self, task_name: str = "", task_id: str = ""):
        self._report = ExecutionReport(
            task_name=task_name,
            task_id=task_id,
            status="pending",
        )
        self._started = time.time()
        self._report.started_at = self._started

    def add_file(
        self, path: str, change_type: str = "modified", lines: str = "", summary: str = ""
    ) -> ReportBuilder:
        self._report.add_file_change(path, change_type, lines, summary)
        return self

    def add_step(self, step: str, status: str = "done", detail: str = "") -> ReportBuilder:
        dur = (time.time() - self._started) * 1000
        self._report.add_operation(step, status, dur, detail)
        return self

    def add_error(self, error: str) -> ReportBuilder:
        self._report.add_error(error)
        return self

    def track_token(self, model: str, tokens: int, cost: float) -> ReportBuilder:
        self._report.tokens_used[model] = self._report.tokens_used.get(model, 0) + tokens
        self._report.cost_usd += cost
        self._report.api_calls += 1
        return self

    def done(self, status: str = "success") -> ExecutionReport:
        """完成构建，返回报告"""
        self._report.status = status
        self._report.completed_at = time.time()
        self._report.duration_seconds = round(self._report.completed_at - self._started, 1)
        return self._report


__all__ = [
    "ExecutionReport",
    "FileChange",
    "OperationStep",
    "ReportBuilder",
]
