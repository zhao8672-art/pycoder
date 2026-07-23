"""
进化报告生成器 — 对标 Codex 变更报告

自动生成结构化工程变更报告，包含:
  - 执行摘要 (executive_summary)
  - 文件变更清单 (file_changes)
  - 测试结果 (test_results)
  - 风险分析 (risk_analysis)
  - 回滚方案 (rollback_plan)
  - 经验沉淀 (lessons_learned)
  - 性能影响 (performance_impact)
  - 依赖变更 (dependency_changes)

支持多种输出格式:
  - dict: 结构化字典
  - markdown: Markdown 格式报告
  - json: JSON 序列化

用法:
    from pycoder.server.services.evolution_report import (
        EvolutionReport, ReportGenerator, generate_change_report,
    )

    report = generate_change_report(
        task="实现用户登录模块",
        changes=[{"file": "src/auth.py", "action": "created", "lines": 120}],
        test_results={"passed": 15, "failed": 0, "skipped": 2},
    )
    print(report.to_markdown())
"""

from __future__ import annotations

import json
import logging
import time
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

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FileChange:
    """单个文件变更记录"""

    file_path: str
    action: str  # created, modified, deleted, renamed
    lines_added: int = 0
    lines_removed: int = 0
    description: str = ""
    old_path: str = ""  # 重命名时的旧路径

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "action": self.action,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "net_change": self.lines_added - self.lines_removed,
            "description": self.description,
            "old_path": self.old_path,
        }


@dataclass
class TestSummary:
    """测试结果摘要"""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    coverage_pct: float = 0.0
    failed_tests: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 100.0
        return round(self.passed / self.total * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "total": self.total,
            "pass_rate": self.pass_rate,
            "duration_ms": round(self.duration_ms, 1),
            "coverage_pct": self.coverage_pct,
            "failed_tests": self.failed_tests[:10],
        }


@dataclass
class RiskItem:
    """单个风险项"""

    risk: str
    severity: str  # low, medium, high, critical
    mitigation: str = ""
    probability: float = 0.0  # 0.0-1.0
    impact: str = "medium"  # low, medium, high

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "severity": self.severity,
            "mitigation": self.mitigation,
            "probability": self.probability,
            "impact": self.impact,
        }


@dataclass
class EvolutionReport:
    """进化报告 — 对标 Codex 变更报告

    包含完整的工程变更记录、测试结果、风险分析和经验沉淀。
    """

    # 基础信息
    report_id: str = ""
    task: str = ""
    timestamp: str = ""
    duration_seconds: float = 0.0

    # 执行摘要
    executive_summary: str = ""
    success: bool = False
    steps_completed: int = 0
    total_steps: int = 0

    # 文件变更
    file_changes: list[FileChange] = field(default_factory=list)
    total_lines_added: int = 0
    total_lines_removed: int = 0

    # 测试结果
    test_results: TestSummary = field(default_factory=TestSummary)

    # 风险分析
    risk_analysis: list[RiskItem] = field(default_factory=list)

    # 回滚方案
    rollback_plan: dict[str, Any] = field(default_factory=dict)

    # 经验沉淀
    lessons_learned: list[str] = field(default_factory=list)

    # 性能影响
    performance_impact: dict[str, Any] = field(default_factory=dict)

    # 依赖变更
    dependency_changes: list[dict[str, Any]] = field(default_factory=list)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "report_id": self.report_id,
            "task": self.task,
            "timestamp": self.timestamp,
            "duration_seconds": round(self.duration_seconds, 2),
            "executive_summary": self.executive_summary,
            "success": self.success,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "file_changes": [fc.to_dict() for fc in self.file_changes],
            "total_lines_added": self.total_lines_added,
            "total_lines_removed": self.total_lines_removed,
            "test_results": self.test_results.to_dict(),
            "risk_analysis": [r.to_dict() for r in self.risk_analysis],
            "rollback_plan": self.rollback_plan,
            "lessons_learned": self.lessons_learned,
            "performance_impact": self.performance_impact,
            "dependency_changes": self.dependency_changes,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """JSON 序列化"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        """生成 Markdown 格式报告"""
        lines: list[str] = []

        # 标题
        lines.append(f"# 工程进化报告")
        lines.append("")
        lines.append(f"**任务**: {self.task}")
        lines.append(f"**报告 ID**: {self.report_id}")
        lines.append(f"**生成时间**: {self.timestamp}")
        lines.append(f"**总耗时**: {self.duration_seconds:.2f}s")
        lines.append(f"**状态**: {'✅ 成功' if self.success else '❌ 失败'}")
        lines.append("")

        # 执行摘要
        lines.append("## 执行摘要")
        lines.append("")
        lines.append(self.executive_summary or "无摘要")
        lines.append("")
        lines.append(f"- 完成步骤: {self.steps_completed}/{self.total_steps}")
        lines.append("")

        # 文件变更
        lines.append("## 文件变更")
        lines.append("")
        if self.file_changes:
            lines.append("| 文件 | 操作 | +行 | -行 | 净变化 | 说明 |")
            lines.append("|------|------|-----|-----|--------|------|")
            for fc in self.file_changes:
                lines.append(
                    f"| `{fc.file_path}` | {fc.action} | "
                    f"+{fc.lines_added} | -{fc.lines_removed} | "
                    f"{fc.lines_added - fc.lines_removed:+d} | "
                    f"{fc.description[:50]} |"
                )
            lines.append("")
            lines.append(f"**总计**: +{self.total_lines_added} / -{self.total_lines_removed}")
        else:
            lines.append("无文件变更")
        lines.append("")

        # 测试结果
        lines.append("## 测试结果")
        lines.append("")
        tr = self.test_results
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|----|")
        lines.append(f"| 通过 | {tr.passed} |")
        lines.append(f"| 失败 | {tr.failed} |")
        lines.append(f"| 跳过 | {tr.skipped} |")
        lines.append(f"| 错误 | {tr.errors} |")
        lines.append(f"| 总计 | {tr.total} |")
        lines.append(f"| 通过率 | {tr.pass_rate}% |")
        lines.append(f"| 覆盖率 | {tr.coverage_pct}% |")
        lines.append(f"| 耗时 | {tr.duration_ms:.0f}ms |")
        lines.append("")

        if tr.failed_tests:
            lines.append("### 失败测试")
            for t in tr.failed_tests[:10]:
                lines.append(f"- `{t}`")
            lines.append("")

        # 风险分析
        lines.append("## 风险分析")
        lines.append("")
        if self.risk_analysis:
            for r in self.risk_analysis:
                severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                    r.severity, "⚪"
                )
                lines.append(f"- {severity_icon} **[{r.severity.upper()}]** {r.risk}")
                if r.mitigation:
                    lines.append(f"  - 缓解措施: {r.mitigation}")
            lines.append("")
        else:
            lines.append("无风险项")
            lines.append("")

        # 回滚方案
        lines.append("## 回滚方案")
        lines.append("")
        if self.rollback_plan:
            strategy = self.rollback_plan.get("strategy", "未知")
            lines.append(f"**策略**: {strategy}")
            steps = self.rollback_plan.get("steps", [])
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
        else:
            lines.append("无回滚方案")
        lines.append("")

        # 经验教训
        lines.append("## 经验沉淀")
        lines.append("")
        if self.lessons_learned:
            for lesson in self.lessons_learned:
                lines.append(f"- {lesson}")
        else:
            lines.append("无经验记录")
        lines.append("")

        # 性能影响
        if self.performance_impact:
            lines.append("## 性能影响")
            lines.append("")
            for k, v in self.performance_impact.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

        # 依赖变更
        if self.dependency_changes:
            lines.append("## 依赖变更")
            lines.append("")
            for dc in self.dependency_changes:
                lines.append(f"- {dc.get('action', 'update')}: `{dc.get('name', '?')}`")
            lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# ReportGenerator — 报告生成器
# ═══════════════════════════════════════════════════════════════════


class ReportGenerator:
    """进化报告生成器

    从原始变更数据、测试结果、风险项等生成结构化 EvolutionReport。

    用法:
        gen = ReportGenerator()
        report = gen.generate(
            task="实现用户登录",
            changes=[{"file": "auth.py", "action": "created", "lines_added": 50}],
            test_results={"passed": 10, "failed": 0},
        )
    """

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace or Path.cwd()
        self._report_count = 0

    def generate(
        self,
        task: str,
        *,
        changes: list[dict[str, Any]] | None = None,
        test_results: dict[str, Any] | None = None,
        risks: list[dict[str, Any]] | None = None,
        rollback_plan: dict[str, Any] | None = None,
        lessons: list[str] | None = None,
        performance_impact: dict[str, Any] | None = None,
        dependency_changes: list[dict[str, Any]] | None = None,
        success: bool = True,
        steps_completed: int = 0,
        total_steps: int = 0,
        duration_seconds: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> EvolutionReport:
        """生成进化报告

        Args:
            task: 任务描述
            changes: 文件变更列表
            test_results: 测试结果
            risks: 风险列表
            rollback_plan: 回滚方案
            lessons: 经验教训
            performance_impact: 性能影响
            dependency_changes: 依赖变更
            success: 是否成功
            steps_completed: 完成步骤数
            total_steps: 总步骤数
            duration_seconds: 总耗时
            metadata: 额外元数据

        Returns:
            EvolutionReport 完整报告
        """
        self._report_count += 1
        report_id = f"evo-{self._report_count:04d}-{int(time.time())}"

        # 文件变更
        file_changes = self._parse_file_changes(changes or [])
        total_added = sum(fc.lines_added for fc in file_changes)
        total_removed = sum(fc.lines_removed for fc in file_changes)

        # 测试结果
        test_summary = self._parse_test_results(test_results or {})

        # 风险分析
        risk_items = self._parse_risks(risks or [])

        # 执行摘要
        summary = self._generate_summary(
            task=task,
            success=success,
            file_changes=file_changes,
            test_summary=test_summary,
            risk_items=risk_items,
            steps_completed=steps_completed,
            total_steps=total_steps,
        )

        # 自动分析风险
        if not risk_items:
            risk_items = self._auto_analyze_risks(
                file_changes=file_changes,
                test_summary=test_summary,
                success=success,
            )

        report = EvolutionReport(
            report_id=report_id,
            task=task,
            timestamp=datetime.now(UTC).isoformat(),
            duration_seconds=duration_seconds,
            executive_summary=summary,
            success=success,
            steps_completed=steps_completed,
            total_steps=total_steps,
            file_changes=file_changes,
            total_lines_added=total_added,
            total_lines_removed=total_removed,
            test_results=test_summary,
            risk_analysis=risk_items,
            rollback_plan=rollback_plan or self._default_rollback_plan(),
            lessons_learned=lessons or [],
            performance_impact=performance_impact or {},
            dependency_changes=dependency_changes or [],
            metadata=metadata or {},
        )

        logger.info(
            "进化报告已生成: id=%s 文件数=%d 测试通过率=%.1f%%",
            report_id,
            len(file_changes),
            test_summary.pass_rate,
        )
        return report

    # ── 内部解析方法 ──────────────────────────────

    def _parse_file_changes(
        self, changes: list[dict[str, Any]]
    ) -> list[FileChange]:
        """解析文件变更列表"""
        result: list[FileChange] = []
        for c in changes:
            result.append(
                FileChange(
                    file_path=c.get("file", c.get("file_path", "")),
                    action=c.get("action", "modified"),
                    lines_added=c.get("lines_added", c.get("added", 0)),
                    lines_removed=c.get("lines_removed", c.get("removed", 0)),
                    description=c.get("description", c.get("desc", "")),
                    old_path=c.get("old_path", ""),
                )
            )
        return result

    def _parse_test_results(
        self, results: dict[str, Any]
    ) -> TestSummary:
        """解析测试结果"""
        return TestSummary(
            passed=results.get("passed", 0),
            failed=results.get("failed", 0),
            skipped=results.get("skipped", 0),
            errors=results.get("errors", 0),
            duration_ms=results.get("duration_ms", 0.0),
            coverage_pct=results.get("coverage_pct", results.get("coverage", 0.0)),
            failed_tests=results.get("failed_tests", []),
        )

    def _parse_risks(
        self, risks: list[dict[str, Any]]
    ) -> list[RiskItem]:
        """解析风险列表"""
        return [
            RiskItem(
                risk=r.get("risk", r.get("description", "")),
                severity=r.get("severity", "medium"),
                mitigation=r.get("mitigation", ""),
                probability=r.get("probability", 0.0),
                impact=r.get("impact", "medium"),
            )
            for r in risks
        ]

    def _generate_summary(
        self,
        task: str,
        success: bool,
        file_changes: list[FileChange],
        test_summary: TestSummary,
        risk_items: list[RiskItem],
        steps_completed: int,
        total_steps: int,
    ) -> str:
        """生成执行摘要"""
        status = "成功完成" if success else "未完全成功"
        parts = [
            f"任务「{task[:100]}」{status}。",
            f"共修改 {len(file_changes)} 个文件",
        ]

        if file_changes:
            total_added = sum(fc.lines_added for fc in file_changes)
            total_removed = sum(fc.lines_removed for fc in file_changes)
            parts.append(f"（+{total_added}/-{total_removed} 行）")

        parts.append(f"，测试通过率 {test_summary.pass_rate}%")

        if steps_completed > 0:
            parts.append(f"，完成 {steps_completed}/{total_steps} 步骤")

        if risk_items:
            critical = sum(1 for r in risk_items if r.severity == "critical")
            high = sum(1 for r in risk_items if r.severity == "high")
            if critical > 0 or high > 0:
                parts.append(f"，发现 {critical} 个严重风险和 {high} 个高风险")

        return "".join(parts)

    def _auto_analyze_risks(
        self,
        file_changes: list[FileChange],
        test_summary: TestSummary,
        success: bool,
    ) -> list[RiskItem]:
        """自动分析风险"""
        risks: list[RiskItem] = []

        # 测试失败风险
        if test_summary.failed > 0:
            risks.append(
                RiskItem(
                    risk=f"存在 {test_summary.failed} 个测试失败",
                    severity="high" if test_summary.failed > 3 else "medium",
                    mitigation="检查失败测试并修复后再部署",
                    probability=1.0,
                )
            )

        # 大范围变更风险
        if len(file_changes) > 10:
            risks.append(
                RiskItem(
                    risk=f"变更涉及 {len(file_changes)} 个文件，影响范围较大",
                    severity="high" if len(file_changes) > 20 else "medium",
                    mitigation="分批部署，密切监控",
                    probability=0.7,
                )
            )

        # 覆盖率不足
        if test_summary.total > 0 and test_summary.coverage_pct < 80:
            risks.append(
                RiskItem(
                    risk=f"测试覆盖率仅 {test_summary.coverage_pct}%，低于 80% 门禁",
                    severity="medium",
                    mitigation="补充测试用例提高覆盖率",
                    probability=0.5,
                )
            )

        # 失败风险
        if not success:
            risks.append(
                RiskItem(
                    risk="任务未完全成功，可能存在未解决的问题",
                    severity="high",
                    mitigation="排查失败步骤，必要时回滚变更",
                    probability=0.8,
                )
            )

        return risks

    def _default_rollback_plan(self) -> dict[str, Any]:
        """默认回滚方案"""
        return {
            "strategy": "git_revert",
            "steps": [
                "1. git status 检查当前变更",
                "2. git stash 暂存或 git checkout 回退变更文件",
                "3. 重新运行测试确认恢复",
                "4. 通知相关人员",
            ],
            "auto_rollback": False,
            "trigger_condition": "测试失败或严重风险出现",
        }

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "total_reports": self._report_count,
            "workspace": str(self._workspace),
        }

    # ── 持久化工厂 ──────────────────────────────

    def _reports_dir(self) -> Path:
        """获取报告存储目录"""
        d = self._workspace / ".pycoder" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def save_report(self, report: EvolutionReport) -> Path:
        """保存报告到磁盘

        Args:
            report: 进化报告

        Returns:
            保存的文件路径
        """
        path = self._reports_dir() / f"{report.report_id}.json"
        path.write_text(report.to_json(), encoding="utf-8")
        logger.info("报告已保存: %s", path)
        return path

    async def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出最近的报告

        Args:
            limit: 最大返回数量

        Returns:
            报告元数据列表，按修改时间降序
        """
        reports_dir = self._reports_dir()
        files = sorted(
            reports_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        result: list[dict[str, Any]] = []
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append({
                    "report_id": data.get("report_id", f.stem),
                    "task": data.get("task", ""),
                    "timestamp": data.get("timestamp", ""),
                    "success": data.get("success", False),
                    "file_count": len(data.get("file_changes", [])),
                    "lines_added": data.get("total_lines_added", 0),
                    "lines_removed": data.get("total_lines_removed", 0),
                    "file_name": f.name,
                    "size_bytes": f.stat().st_size,
                })
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("report_parse_error", file=str(f), error=str(e))
        return result

    async def get_report(self, task_id: str) -> EvolutionReport | None:
        """获取指定报告

        Args:
            task_id: 报告 ID

        Returns:
            EvolutionReport 或 None
        """
        path = self._reports_dir() / f"{task_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("report_read_error", task_id=task_id, error=str(e))
            return None

    async def generate_from_closed_loop(self, result: Any) -> EvolutionReport:
        """从闭环验证结果生成报告

        Args:
            result: 闭环验证结果对象

        Returns:
            EvolutionReport
        """
        return self.generate(
            task=getattr(result, "task_id", "EVO-UNKNOWN"),
            changes=[
                {"file": c.get("file", c.get("path", "")), "action": c.get("action", "modified"),
                 "lines_added": c.get("lines_added", 0), "lines_removed": c.get("lines_removed", 0),
                 "description": c.get("description", "")}
                for c in (getattr(result, "changes", []) or [])
            ],
            test_results={
                "passed": sum(1 for t in (getattr(result, "test_results", []) or [])
                            if isinstance(t, dict) and t.get("passed", False)),
                "failed": sum(1 for t in (getattr(result, "test_results", []) or [])
                            if isinstance(t, dict) and not t.get("passed", False)),
            },
            risks=[
                {"risk": r.get("risk", r.get("description", "")), "severity": r.get("severity", "medium")}
                for r in (getattr(result, "risk_analysis", []) or [])
            ],
            rollback_plan=getattr(result, "rollback_plan", {}) or {},
            lessons=getattr(result, "lessons_learned", []) or [],
            success=getattr(result, "success", getattr(result, "final_status", "unknown") == "success"),
            steps_completed=getattr(result, "steps_completed", 0),
            total_steps=getattr(result, "steps_completed", 0),
            duration_seconds=getattr(result, "duration", 0.0),
        )

    async def generate_from_git_diff(self, base_branch: str = "master") -> EvolutionReport:
        """从 Git diff 生成报告

        Args:
            base_branch: 基准分支

        Returns:
            EvolutionReport
        """
        import subprocess

        changes: list[dict[str, Any]] = []
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", base_branch],
                capture_output=True, text=True, cwd=str(self._workspace),
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split("\n"):
                    if "|" in line:
                        parts = line.split("|")
                        file_path = parts[0].strip()
                        changes.append({
                            "file": file_path,
                            "action": "modified",
                            "lines_added": 0,
                            "lines_removed": 0,
                        })
        except Exception as e:
            logger.warning("git_diff_failed", error=str(e))

        return self.generate(
            task=f"Git diff: {base_branch} → HEAD",
            changes=changes,
            success=len(changes) > 0,
        )

    def _from_dict(self, data: dict[str, Any]) -> EvolutionReport:
        """从字典反序列化报告"""
        return EvolutionReport(
            report_id=data.get("report_id", ""),
            task=data.get("task", ""),
            timestamp=data.get("timestamp", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            executive_summary=data.get("executive_summary", ""),
            success=data.get("success", False),
            steps_completed=data.get("steps_completed", 0),
            total_steps=data.get("total_steps", 0),
            file_changes=[FileChange(**fc) for fc in data.get("file_changes", [])],
            total_lines_added=data.get("total_lines_added", 0),
            total_lines_removed=data.get("total_lines_removed", 0),
            test_results=TestSummary(**data.get("test_results", {})),
            risk_analysis=[RiskItem(**r) for r in data.get("risk_analysis", [])],
            rollback_plan=data.get("rollback_plan", {}),
            lessons_learned=data.get("lessons_learned", []),
            performance_impact=data.get("performance_impact", {}),
            dependency_changes=data.get("dependency_changes", []),
            metadata=data.get("metadata", {}),
        )


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════


def generate_change_report(
    task: str,
    changes: list[dict[str, Any]] | None = None,
    test_results: dict[str, Any] | None = None,
    risks: list[dict[str, Any]] | None = None,
    success: bool = True,
    **kwargs: Any,
) -> EvolutionReport:
    """便捷函数：快速生成变更报告

    Args:
        task: 任务描述
        changes: 文件变更列表
        test_results: 测试结果
        risks: 风险列表
        success: 是否成功
        **kwargs: 传递给 ReportGenerator.generate() 的其他参数

    Returns:
        EvolutionReport 报告
    """
    gen = ReportGenerator()
    return gen.generate(
        task=task,
        changes=changes,
        test_results=test_results,
        risks=risks,
        success=success,
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════════════
# 能力注册
# ═══════════════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> list[CapabilityDefinition]:
    """向 V2 能力总线注册进化报告能力

    Args:
        registry: CapabilityRegistry 实例

    Returns:
        已注册的能力定义列表
    """
    gen = ReportGenerator()

    definitions: list[CapabilityDefinition] = []

    # 1. evolution_report.generate — 生成进化报告
    async def _handle_generate(params: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        report = gen.generate(
            task=params.get("task", ""),
            changes=params.get("changes"),
            test_results=params.get("test_results"),
            risks=params.get("risks"),
            rollback_plan=params.get("rollback_plan"),
            lessons=params.get("lessons"),
            performance_impact=params.get("performance_impact"),
            dependency_changes=params.get("dependency_changes"),
            success=params.get("success", True),
            steps_completed=params.get("steps_completed", 0),
            total_steps=params.get("total_steps", 0),
            duration_seconds=params.get("duration_seconds", 0.0),
            metadata=params.get("metadata"),
        )
        return report.to_dict()

    def_generate = CapabilityDefinition(
        id="evolution_report.generate",
        name="生成进化报告",
        description="生成结构化工程变更报告，包含文件变更、测试结果、风险分析和经验沉淀",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="1.0.0",
        timeout_ms=10000,
        tags=["evolution_report", "report", "change", "summary"],
    )
    definitions.append(def_generate)
    registry.register(def_generate, handler=_handle_generate)

    # 2. evolution_report.get_stats — 获取统计
    async def _handle_stats(params: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        return gen.get_stats()

    def_stats = CapabilityDefinition(
        id="evolution_report.get_stats",
        name="报告生成统计",
        description="获取进化报告生成器的统计信息",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="1.0.0",
        timeout_ms=3000,
        tags=["evolution_report", "stats", "monitoring"],
    )
    definitions.append(def_stats)
    registry.register(def_stats, handler=_handle_stats)

    logger.info("进化报告能力已注册: %d 个能力", len(definitions))
    return definitions


# ═══════════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    "FileChange",
    "TestSummary",
    "RiskItem",
    "EvolutionReport",
    "ReportGenerator",
    "generate_change_report",
    "register_capabilities",
]