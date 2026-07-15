"""
进化变更报告生成模块 — Codex 风格综合变更报告

实现 Codex 风格的进化变更报告，包括：
  - 文件变更追踪（FileChange）
  - 测试结果记录（TestResult）
  - 综合进化报告（EvolutionReport）
  - 报告生成器（ReportGenerator）— 支持从闭环结果、Git diff 生成报告
  - Markdown / JSON 格式导出
  - 能力总线注册

用法:
    from pycoder.server.services.evolution_report import (
        EvolutionReport, ReportGenerator, FileChange, TestResult,
        register_capabilities,
    )

    generator = ReportGenerator(workspace=Path("."))
    report = await generator.generate_from_closed_loop(result)
    print(generator.to_markdown(report))
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

# ── 可选依赖：闭环引擎 ──────────────────────────────────
try:
    from pycoder.server.services.closed_loop_engine import ClosedLoopResult

    _HAS_CLOSED_LOOP = True
except ImportError:
    _HAS_CLOSED_LOOP = False
    ClosedLoopResult = None  # type: ignore

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════

# 默认报告存储目录
DEFAULT_REPORT_DIR = Path.home() / ".pycoder" / "evolution_reports"

# 风险等级映射
RISK_LEVELS: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "none": 4,
}


# ══════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════


@dataclass
class FileChange:
    """文件变更记录 — 追踪单个文件的修改详情

    Attributes:
        file_path: 文件路径（相对于工作区根目录）
        change_type: 变更类型（added / modified / deleted）
        lines_added: 新增行数
        lines_deleted: 删除行数
        description: 变更描述
        risk_level: 风险等级（critical / high / medium / low / none）
    """

    file_path: str
    change_type: str = "modified"  # added | modified | deleted
    lines_added: int = 0
    lines_deleted: int = 0
    description: str = ""
    risk_level: str = "low"  # critical | high | medium | low | none

    @property
    def net_lines(self) -> int:
        """净增行数 = 新增 - 删除"""
        return self.lines_added - self.lines_deleted

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "net_lines": self.net_lines,
            "description": self.description,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileChange:
        """从字典反序列化"""
        return cls(
            file_path=data.get("file_path", ""),
            change_type=data.get("change_type", "modified"),
            lines_added=data.get("lines_added", 0),
            lines_deleted=data.get("lines_deleted", 0),
            description=data.get("description", ""),
            risk_level=data.get("risk_level", "low"),
        )


@dataclass
class TestResult:
    """测试结果记录 — 单个测试用例的执行结果

    Attributes:
        test_name: 测试名称
        status: 测试状态（passed / failed / skipped）
        duration: 执行耗时（秒）
        error_message: 错误信息（失败时）
    """

    test_name: str
    status: str = "passed"  # passed | failed | skipped
    duration: float = 0.0  # 秒
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "test_name": self.test_name,
            "status": self.status,
            "duration": round(self.duration, 3),
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestResult:
        """从字典反序列化"""
        return cls(
            test_name=data.get("test_name", ""),
            status=data.get("status", "passed"),
            duration=data.get("duration", 0.0),
            error_message=data.get("error_message", ""),
        )


@dataclass
class EvolutionReport:
    """进化变更报告 — Codex 风格综合变更报告

    包含完整的变更记录、测试结果、风险分析和经验教训。

    Attributes:
        task_id: 任务唯一标识
        summary: 报告摘要
        created_at: 创建时间
        duration_seconds: 总耗时（秒）
        changes: 文件变更列表
        test_results: 测试结果列表
        risk_analysis: 风险分析（Codex 风格）
        rollback_plan: 回退计划
        lessons_learned: 经验教训
        success: 整体是否成功
        metrics: 执行指标
    """

    task_id: str = ""
    summary: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_seconds: float = 0.0
    changes: list[FileChange] = field(default_factory=list)
    test_results: list[TestResult] = field(default_factory=list)
    risk_analysis: str = ""
    rollback_plan: str = ""
    lessons_learned: list[str] = field(default_factory=list)
    success: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """初始化后处理：自动生成 task_id"""
        if not self.task_id:
            self.task_id = f"EVO-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    # ── 计算属性 ────────────────────────────────────

    @property
    def total_files_changed(self) -> int:
        """变更文件总数"""
        return len(self.changes)

    @property
    def total_lines_added(self) -> int:
        """总新增行数"""
        return sum(c.lines_added for c in self.changes)

    @property
    def total_lines_deleted(self) -> int:
        """总删除行数"""
        return sum(c.lines_deleted for c in self.changes)

    @property
    def net_lines(self) -> int:
        """净增行数"""
        return self.total_lines_added - self.total_lines_deleted

    @property
    def tests_passed(self) -> int:
        """通过的测试数"""
        return sum(1 for t in self.test_results if t.status == "passed")

    @property
    def tests_failed(self) -> int:
        """失败的测试数"""
        return sum(1 for t in self.test_results if t.status == "failed")

    @property
    def tests_skipped(self) -> int:
        """跳过的测试数"""
        return sum(1 for t in self.test_results if t.status == "skipped")

    @property
    def total_tests(self) -> int:
        """测试总数"""
        return len(self.test_results)

    @property
    def pass_rate(self) -> float:
        """测试通过率"""
        if self.total_tests == 0:
            return 0.0
        return self.tests_passed / self.total_tests

    @property
    def highest_risk(self) -> str:
        """最高风险等级"""
        if not self.changes:
            return "none"
        for level in ("critical", "high", "medium", "low", "none"):
            if any(c.risk_level == level for c in self.changes):
                return level
        return "none"

    # ── 序列化方法 ──────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "task_id": self.task_id,
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
            "duration_seconds": round(self.duration_seconds, 2),
            "total_files_changed": self.total_files_changed,
            "total_lines_added": self.total_lines_added,
            "total_lines_deleted": self.total_lines_deleted,
            "net_lines": self.net_lines,
            "changes": [c.to_dict() for c in self.changes],
            "test_results": [t.to_dict() for t in self.test_results],
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_skipped": self.tests_skipped,
            "total_tests": self.total_tests,
            "pass_rate": round(self.pass_rate, 4),
            "highest_risk": self.highest_risk,
            "risk_analysis": self.risk_analysis,
            "rollback_plan": self.rollback_plan,
            "lessons_learned": self.lessons_learned,
            "success": self.success,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolutionReport:
        """从字典反序列化"""
        created_at_str = data.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except (ValueError, TypeError):
            created_at = datetime.now(UTC)

        return cls(
            task_id=data.get("task_id", ""),
            summary=data.get("summary", ""),
            created_at=created_at,
            duration_seconds=data.get("duration_seconds", 0.0),
            changes=[
                FileChange.from_dict(c) for c in data.get("changes", [])
            ],
            test_results=[
                TestResult.from_dict(t) for t in data.get("test_results", [])
            ],
            risk_analysis=data.get("risk_analysis", ""),
            rollback_plan=data.get("rollback_plan", ""),
            lessons_learned=data.get("lessons_learned", []),
            success=data.get("success", False),
            metrics=data.get("metrics", {}),
        )


# ══════════════════════════════════════════════════════════
# ReportGenerator — 报告生成器
# ══════════════════════════════════════════════════════════


class ReportGenerator:
    """进化报告生成器 — Codex 风格综合变更报告

    支持多种报告生成方式：
      - 从闭环验证结果生成
      - 从 Git diff 生成
      - 导出为 Markdown / JSON 格式
      - 持久化存储和检索

    用法:
        generator = ReportGenerator(workspace=Path("."))
        report = await generator.generate_from_closed_loop(result)
        md = generator.to_markdown(report)
        await generator.save_report(report, Path("report.md"))
    """

    def __init__(self, workspace: Path | None = None) -> None:
        """初始化报告生成器

        Args:
            workspace: 工作区根目录，用于 Git 操作和路径解析
        """
        self._workspace = workspace or Path.cwd()
        self._report_dir = DEFAULT_REPORT_DIR
        self._report_dir.mkdir(parents=True, exist_ok=True)
        logger.info("报告生成器已初始化: workspace=%s", self._workspace)

    # ── 从闭环结果生成报告 ───────────────────────────

    async def generate_from_closed_loop(
        self, result: Any
    ) -> EvolutionReport:
        """从闭环验证结果生成进化报告

        将 ClosedLoopResult 转换为结构化的 EvolutionReport，
        提取变更详情、测试结果、风险分析和经验教训。

        Args:
            result: ClosedLoopResult 实例（闭环验证结果）

        Returns:
            EvolutionReport — 进化变更报告
        """
        t0 = time.time()
        logger.info("从闭环结果生成进化报告: task_id=%s", getattr(result, "task_id", "unknown"))

        # 提取基本信息
        task_id = getattr(result, "task_id", "")
        success = getattr(result, "success", False)
        duration = getattr(result, "duration", 0.0)

        # 转换文件变更
        changes: list[FileChange] = []
        raw_changes = getattr(result, "changes", []) or []
        for raw in raw_changes:
            if isinstance(raw, dict):
                changes.append(
                    FileChange(
                        file_path=raw.get("file", raw.get("file_path", "")),
                        change_type=raw.get("action", raw.get("change_type", "modified")),
                        lines_added=raw.get("lines_added", raw.get("original_lines", 0)),
                        lines_deleted=raw.get("lines_deleted", 0),
                        description=raw.get("reason", raw.get("description", "")),
                        risk_level=raw.get("risk_level", self._estimate_risk(raw)),
                    )
                )
            elif isinstance(raw, FileChange):
                changes.append(raw)

        # 转换测试结果
        test_results: list[TestResult] = []
        raw_tests = getattr(result, "test_results", []) or []
        for raw in raw_tests:
            if isinstance(raw, dict):
                test_results.append(
                    TestResult(
                        test_name=raw.get("test_name", raw.get("name", "")),
                        status=raw.get("status", "passed"),
                        duration=raw.get("duration", raw.get("duration_ms", 0.0) / 1000),
                        error_message=raw.get("error_message", raw.get("error", "")),
                    )
                )
            elif isinstance(raw, TestResult):
                test_results.append(raw)

        # 提取风险分析
        risk_data = getattr(result, "risk_analysis", []) or []
        risk_analysis = self._format_risk_analysis(risk_data)

        # 提取回退计划
        rollback_data = getattr(result, "rollback_plan", {}) or {}
        rollback_plan = self._format_rollback_plan(rollback_data)

        # 提取经验教训
        lessons = getattr(result, "lessons_learned", []) or []
        if isinstance(lessons, str):
            lessons = [lessons]
        lessons = [str(l) for l in lessons]

        # 构建执行指标
        metrics: dict[str, Any] = {
            "steps_completed": getattr(result, "steps_completed", 0),
            "self_heal_attempts": getattr(result, "self_heal_attempts", 0),
            "final_status": getattr(result, "final_status", "unknown"),
            "files_changed": len(changes),
            "tests_run": len(test_results),
            "generated_at": datetime.now(UTC).isoformat(),
        }

        # 生成摘要
        summary = self._generate_summary(success, changes, test_results, duration)

        report = EvolutionReport(
            task_id=task_id,
            summary=summary,
            duration_seconds=duration,
            changes=changes,
            test_results=test_results,
            risk_analysis=risk_analysis,
            rollback_plan=rollback_plan,
            lessons_learned=lessons,
            success=success,
            metrics=metrics,
        )

        elapsed = time.time() - t0
        logger.info(
            "进化报告生成完成: task_id=%s, 文件变更=%d, 测试=%d, 耗时=%.2fs",
            report.task_id,
            report.total_files_changed,
            report.total_tests,
            elapsed,
        )
        return report

    # ── 从 Git diff 生成报告 ─────────────────────────

    async def generate_from_git_diff(
        self, base_branch: str = "master"
    ) -> EvolutionReport:
        """从 Git diff 生成进化报告

        对比当前分支与 base_branch 的差异，生成结构化的变更报告。

        Args:
            base_branch: 基准分支名称（默认 master）

        Returns:
            EvolutionReport — 基于 Git diff 的进化变更报告
        """
        t0 = time.time()
        logger.info("从 Git diff 生成报告: base_branch=%s", base_branch)

        task_id = f"EVO-DIFF-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        changes: list[FileChange] = []
        test_results: list[TestResult] = []
        lessons: list[str] = []

        try:
            # 获取变更文件列表
            diff_output = subprocess.run(
                ["git", "diff", "--stat", base_branch],
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if diff_output.returncode != 0 and diff_output.stderr:
                logger.warning("Git diff 执行警告: %s", diff_output.stderr.strip())

            stat_lines = diff_output.stdout.strip().splitlines()
            if not stat_lines:
                logger.info("Git diff 无变更")

            # 解析 diff --stat 输出
            for line in stat_lines:
                if not line.strip():
                    continue
                # 格式: "path/to/file.py | 10 ++++----"
                parts = line.split("|")
                if len(parts) < 2:
                    continue
                file_path = parts[0].strip()
                stats_part = parts[1].strip()

                # 解析变更统计
                lines_added = 0
                lines_deleted = 0
                import re
                # 匹配 "N ++++" 和 "N ----"
                added_match = re.search(r"(\d+)\s*\+", stats_part)
                deleted_match = re.search(r"(\d+)\s*\-", stats_part)
                if added_match:
                    lines_added = int(added_match.group(1))
                if deleted_match:
                    lines_deleted = int(deleted_match.group(1))

                # 判断变更类型
                if lines_added > 0 and lines_deleted == 0:
                    change_type = "added"
                elif lines_deleted > 0 and lines_added == 0:
                    change_type = "deleted"
                else:
                    change_type = "modified"

                # 估算风险等级
                risk_level = "low"
                if lines_added + lines_deleted > 100:
                    risk_level = "high"
                elif lines_added + lines_deleted > 50:
                    risk_level = "medium"

                changes.append(
                    FileChange(
                        file_path=file_path,
                        change_type=change_type,
                        lines_added=lines_added,
                        lines_deleted=lines_deleted,
                        description=f"Git diff vs {base_branch}",
                        risk_level=risk_level,
                    )
                )

            success = True
            summary = (
                f"Git diff 分析（vs {base_branch}）：共 {len(changes)} 个文件变更，"
                f"+{sum(c.lines_added for c in changes)} / "
                f"-{sum(c.lines_deleted for c in changes)} 行"
            )

        except subprocess.TimeoutExpired:
            logger.error("Git diff 命令超时")
            success = False
            summary = "Git diff 分析超时"
            lessons.append("Git diff 命令执行超时，请检查仓库大小和网络状况")
        except FileNotFoundError:
            logger.error("Git 命令不可用")
            success = False
            summary = "Git 命令不可用，无法生成 diff 报告"
            lessons.append("Git 未安装或不在 PATH 中")
        except Exception as e:
            logger.error("Git diff 分析异常: %s", e)
            success = False
            summary = f"Git diff 分析失败: {e}"
            lessons.append(f"Git diff 分析异常: {e}")

        # 风险分析
        risk_analysis = self._build_diff_risk_analysis(changes, success)

        # 回退计划
        rollback_plan = (
            f"执行 `git checkout {base_branch}` 或 `git revert` 回退当前变更"
        )

        report = EvolutionReport(
            task_id=task_id,
            summary=summary,
            duration_seconds=time.time() - t0,
            changes=changes,
            test_results=test_results,
            risk_analysis=risk_analysis,
            rollback_plan=rollback_plan,
            lessons_learned=lessons,
            success=success,
            metrics={
                "base_branch": base_branch,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "Git diff 报告生成完成: %d 个文件变更, 成功=%s",
            len(changes),
            success,
        )
        return report

    # ── 格式导出 ─────────────────────────────────────

    def to_markdown(self, report: EvolutionReport) -> str:
        """将报告格式化为 Markdown

        Args:
            report: 进化变更报告

        Returns:
            Markdown 格式字符串
        """
        status_emoji = "✅" if report.success else "❌"
        risk_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "none": "⚪",
        }

        lines: list[str] = [
            f"# 📊 进化变更报告: {report.task_id}",
            "",
            f"**状态**: {status_emoji} {'成功' if report.success else '失败'}",
            f"**生成时间**: {report.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**耗时**: {report.duration_seconds:.1f}s",
            "",
            "---",
            "",
            "## 📋 摘要",
            "",
            report.summary,
            "",
            "---",
            "",
            "## 📁 文件变更",
            "",
            "| 文件 | 类型 | +行 | -行 | 净增 | 风险 | 说明 |",
            "|------|------|-----|-----|------|------|------|",
        ]

        if report.changes:
            for c in report.changes:
                r_emoji = risk_emoji.get(c.risk_level, "⚪")
                lines.append(
                    f"| `{c.file_path}` | {c.change_type} | {c.lines_added} | "
                    f"{c.lines_deleted} | {c.net_lines:+d} | {r_emoji} {c.risk_level} | "
                    f"{c.description[:50]} |"
                )
        else:
            lines.append("| *(无变更)* | - | - | - | - | - | - |")

        lines.extend([
            "",
            f"**总计**: {report.total_files_changed} 个文件, "
            f"+{report.total_lines_added}/-{report.total_lines_deleted} 行, "
            f"净增 {report.net_lines:+d} 行",
            "",
            "---",
            "",
            "## 🧪 测试结果",
            "",
        ])

        if report.test_results:
            lines.extend([
                "| 测试名称 | 状态 | 耗时 | 错误信息 |",
                "|----------|------|------|----------|",
            ])
            for t in report.test_results:
                t_emoji = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}.get(t.status, "❓")
                error = t.error_message[:80] if t.error_message else "-"
                lines.append(
                    f"| `{t.test_name}` | {t_emoji} {t.status} | "
                    f"{t.duration:.2f}s | {error} |"
                )
            lines.extend([
                "",
                f"**通过率**: {report.pass_rate:.1%} "
                f"({report.tests_passed}/{report.total_tests})",
            ])
        else:
            lines.append("*(无测试结果)*")

        lines.extend([
            "",
            "---",
            "",
            "## ⚠️ 风险分析",
            "",
            report.risk_analysis or "*(无风险分析)*",
            "",
            "---",
            "",
            "## ↩️ 回退计划",
            "",
            report.rollback_plan or "*(无回退计划)*",
            "",
            "---",
            "",
            "## 📚 经验教训",
            "",
        ])

        if report.lessons_learned:
            for lesson in report.lessons_learned:
                lines.append(f"- 💡 {lesson}")
        else:
            lines.append("*(无经验教训)*")

        lines.extend([
            "",
            "---",
            "",
            "## 📊 执行指标",
            "",
            "| 指标 | 值 |",
            "|------|-----|",
        ])

        for key, value in report.metrics.items():
            lines.append(f"| {key} | {value} |")

        lines.extend([
            "",
            f"*报告由 PyCoder Evolution Reporter 生成于 "
            f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        ])

        return "\n".join(lines)

    def to_json(self, report: EvolutionReport) -> str:
        """将报告格式化为 JSON

        Args:
            report: 进化变更报告

        Returns:
            JSON 格式字符串（美化输出）
        """
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)

    # ── 持久化 ───────────────────────────────────────

    async def save_report(
        self, report: EvolutionReport, path: Path | None = None
    ) -> Path:
        """保存报告到文件

        Args:
            report: 进化变更报告
            path: 保存路径（可选，默认使用报告目录）

        Returns:
            实际保存的文件路径
        """
        if path is None:
            path = self._report_dir / f"{report.task_id}.md"

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        # 根据扩展名选择格式
        if p.suffix.lower() == ".json":
            content = self.to_json(report)
        else:
            content = self.to_markdown(report)

        p.write_text(content, encoding="utf-8")
        logger.info("报告已保存: %s (%d 字节)", p, len(content.encode("utf-8")))
        return p

    async def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出最近的报告

        Args:
            limit: 最大返回数量

        Returns:
            报告摘要列表（按修改时间降序）
        """
        reports: list[dict[str, Any]] = []

        if not self._report_dir.exists():
            return reports

        # 收集所有报告文件
        report_files = sorted(
            self._report_dir.glob("EVO-*.{md,json}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        for f in report_files[:limit]:
            stat = f.stat()
            reports.append({
                "file_name": f.name,
                "path": str(f),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=UTC
                ).isoformat(),
                "format": f.suffix.lstrip("."),
            })

        logger.info("列出 %d 个报告（限制=%d）", len(reports), limit)
        return reports

    async def get_report(self, task_id: str) -> EvolutionReport | None:
        """根据 task_id 获取指定报告

        Args:
            task_id: 任务 ID

        Returns:
            EvolutionReport 或 None（未找到）
        """
        # 尝试匹配 .md 和 .json 文件
        for ext in (".md", ".json"):
            file_path = self._report_dir / f"{task_id}{ext}"
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if ext == ".json":
                        data = json.loads(content)
                        return EvolutionReport.from_dict(data)
                    else:
                        # Markdown 格式无法反序列化，返回基本信息
                        logger.warning(
                            "Markdown 格式报告无法反序列化: %s", file_path
                        )
                        return None
                except (json.JSONDecodeError, OSError) as e:
                    logger.error("读取报告失败: %s - %s", file_path, e)
                    return None

        logger.warning("未找到报告: task_id=%s", task_id)
        return None

    # ── 辅助方法 ─────────────────────────────────────

    def _estimate_risk(self, change: dict[str, Any]) -> str:
        """根据变更数据估算风险等级"""
        lines_added = change.get("lines_added", change.get("original_lines", 0))
        lines_deleted = change.get("lines_deleted", 0)
        total = lines_added + lines_deleted

        if total > 200:
            return "critical"
        elif total > 100:
            return "high"
        elif total > 50:
            return "medium"
        elif total > 10:
            return "low"
        return "none"

    def _format_risk_analysis(self, risk_data: list[dict[str, Any]]) -> str:
        """格式化风险分析数据为 Markdown 字符串"""
        if not risk_data:
            return "未提供风险分析数据"

        lines: list[str] = []
        for item in risk_data:
            if isinstance(item, dict):
                risk = item.get("risk", "")
                severity = item.get("severity", "low")
                mitigation = item.get("mitigation", "")
                detail = item.get("detail", "")

                sev_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }.get(severity, "⚪")

                lines.append(f"- {sev_emoji} **{severity.upper()}**: {risk}")
                if mitigation:
                    lines.append(f"  - 缓解措施: {mitigation}")
                if detail:
                    lines.append(f"  - 详情: {detail}")
            elif isinstance(item, str):
                lines.append(f"- {item}")

        return "\n".join(lines) if lines else "无风险项"

    def _format_rollback_plan(self, rollback_data: dict[str, Any]) -> str:
        """格式化回退计划数据为 Markdown 字符串"""
        if not rollback_data:
            return "未提供回退计划"

        lines: list[str] = []

        strategy = rollback_data.get("strategy", "")
        if strategy:
            lines.append(f"**策略**: {strategy}")

        steps = rollback_data.get("steps", [])
        if steps:
            lines.append("**回退步骤**:")
            for step in steps:
                lines.append(f"  {step}")

        auto = rollback_data.get("auto_rollback", False)
        lines.append(f"**自动回退**: {'是' if auto else '否'}")

        trigger = rollback_data.get("trigger_condition", "")
        if trigger:
            lines.append(f"**触发条件**: {trigger}")

        return "\n".join(lines) if lines else "无回退计划详情"

    def _generate_summary(
        self,
        success: bool,
        changes: list[FileChange],
        test_results: list[TestResult],
        duration: float,
    ) -> str:
        """生成报告摘要"""
        status_text = "成功" if success else "失败"
        parts = [
            f"闭环验证任务执行{status_text}",
            f"耗时 {duration:.1f}s",
            f"变更 {len(changes)} 个文件 "
            f"(+{sum(c.lines_added for c in changes)}/"
            f"-{sum(c.lines_deleted for c in changes)} 行)",
        ]

        if test_results:
            passed = sum(1 for t in test_results if t.status == "passed")
            failed = sum(1 for t in test_results if t.status == "failed")
            parts.append(f"测试 {passed}/{len(test_results)} 通过")
            if failed:
                parts.append(f"{failed} 个测试失败")

        return "，".join(parts) + "。"

    def _build_diff_risk_analysis(
        self, changes: list[FileChange], success: bool
    ) -> str:
        """根据 diff 变更构建风险分析"""
        if not success:
            return "Git diff 分析失败，无法评估风险"

        if not changes:
            return "🟢 **无变更** — 当前分支与基准分支一致，无风险"

        high_risk = [c for c in changes if c.risk_level in ("critical", "high")]
        medium_risk = [c for c in changes if c.risk_level == "medium"]

        lines: list[str] = []
        if high_risk:
            lines.append(
                f"🔴 **高风险**: {len(high_risk)} 个文件变更量较大，建议仔细审查:"
            )
            for c in high_risk:
                lines.append(f"  - `{c.file_path}` (+{c.lines_added}/-{c.lines_deleted})")
        if medium_risk:
            lines.append(
                f"🟡 **中风险**: {len(medium_risk)} 个文件需要关注"
            )

        if not high_risk and not medium_risk:
            lines.append("🟢 **低风险** — 变更量较小，风险可控")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 能力注册
# ══════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> list[CapabilityDefinition]:
    """向 V2 能力总线注册进化报告生成器能力

    注册的能力:
      - report.generate    — 生成进化报告（从闭环结果或 Git diff）
      - report.list        — 列出最近报告
      - report.get         — 获取指定报告

    Args:
        registry: CapabilityRegistry 实例

    Returns:
        已注册的能力定义列表
    """
    generator = ReportGenerator()

    definitions: list[CapabilityDefinition] = []

    # ── report.generate ──────────────────────────

    async def _handle_generate(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """处理报告生成请求

        支持两种模式:
          - closed_loop: 从闭环结果生成
          - git_diff: 从 Git diff 生成
        """
        mode = params.get("mode", "closed_loop")

        if mode == "git_diff":
            base_branch = params.get("base_branch", "master")
            report = await generator.generate_from_git_diff(base_branch=base_branch)
        else:
            # 从闭环结果生成
            result_data = params.get("result", {})
            if _HAS_CLOSED_LOOP and isinstance(result_data, dict):
                # 尝试从字典重建 ClosedLoopResult
                result = ClosedLoopResult(
                    task_id=result_data.get("task_id", ""),
                    success=result_data.get("success", False),
                    steps_completed=result_data.get("steps_completed", 0),
                    changes=result_data.get("changes", []),
                    test_results=result_data.get("test_results", []),
                    risk_analysis=result_data.get("risk_analysis", []),
                    rollback_plan=result_data.get("rollback_plan", {}),
                    lessons_learned=result_data.get("lessons_learned", []),
                    duration=result_data.get("duration", 0.0),
                )
            else:
                # 使用原始数据
                result = result_data

            report = await generator.generate_from_closed_loop(result)

        # 可选：保存报告
        save_path = params.get("save_path", "")
        if save_path:
            await generator.save_report(report, Path(save_path))

        format_type = params.get("format", "dict")
        if format_type == "markdown":
            return {"content": generator.to_markdown(report), "report": report.to_dict()}
        elif format_type == "json":
            return {"content": generator.to_json(report), "report": report.to_dict()}
        else:
            return report.to_dict()

    def_generate = CapabilityDefinition(
        id="report.generate",
        name="生成进化报告",
        description="生成 Codex 风格的进化变更报告，支持从闭环结果和 Git diff 两种模式",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ, SideEffect.FILE_WRITE],
        version="1.0.0",
        timeout_ms=120_000,
        tags=["report", "evolution", "codex", "generate", "self_evo"],
    )
    definitions.append(def_generate)
    registry.register(def_generate, handler=_handle_generate)

    # ── report.list ──────────────────────────────

    async def _handle_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 20)
        reports = await generator.list_reports(limit=limit)
        return {"reports": reports, "total": len(reports)}

    def_list = CapabilityDefinition(
        id="report.list",
        name="列出进化报告",
        description="列出最近的进化变更报告列表",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ],
        version="1.0.0",
        timeout_ms=10_000,
        tags=["report", "list", "evolution", "self_evo"],
    )
    definitions.append(def_list)
    registry.register(def_list, handler=_handle_list)

    # ── report.get ───────────────────────────────

    async def _handle_get(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id = params.get("task_id", "")
        if not task_id:
            return {"error": "缺少 task_id 参数", "report": None}

        report = await generator.get_report(task_id=task_id)
        if report is None:
            return {"error": f"未找到报告: {task_id}", "report": None}

        format_type = params.get("format", "dict")
        if format_type == "markdown":
            return {"content": generator.to_markdown(report), "report": report.to_dict()}
        elif format_type == "json":
            return {"content": generator.to_json(report), "report": report.to_dict()}
        else:
            return {"report": report.to_dict()}

    def_get = CapabilityDefinition(
        id="report.get",
        name="获取进化报告",
        description="根据 task_id 获取指定的进化变更报告",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ],
        version="1.0.0",
        timeout_ms=10_000,
        tags=["report", "get", "evolution", "self_evo"],
    )
    definitions.append(def_get)
    registry.register(def_get, handler=_handle_get)

    logger.info("进化报告生成器能力已注册到 V2 总线: %d 个能力", len(definitions))
    return definitions


# ══════════════════════════════════════════════════════════
# 导出
# ══════════════════════════════════════════════════════════

__all__ = [
    # 数据类
    "FileChange",
    "TestResult",
    "EvolutionReport",
    # 核心类
    "ReportGenerator",
    # 能力注册
    "register_capabilities",
    # 常量
    "DEFAULT_REPORT_DIR",
    "RISK_LEVELS",
]