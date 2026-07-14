"""
缺陷聚合器 — 对标 Codex A5 兜底纠错 Agent

聚合来源:
  - QualityGuard 审查报告 (逻辑校验)
  - TestGenerator 测试缺陷
  - AcceptanceEngine 验收不通过项

输出:
  - 按文件分组的缺陷清单
  - 最小改动补丁列表
  - 修复优先级排序（L1 > L2 > L3）
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class AggregatedDefect:
    """聚合后的缺陷条目"""

    file_path: str
    line_range: tuple[int, int] | None = None
    severity: str = "l2_major"  # l1_blocking / l2_major / l3_minor
    source: str = "unknown"  # quality_guard / test / acceptance
    description: str = ""
    fix_suggestion: str = ""
    code_snippet: str = ""  # 关联的代码段


@dataclass
class PatchEntry:
    """修复补丁条目 — 对标 Codex A5 补丁格式"""

    file_path: str
    search: str  # 原始代码（必须精确匹配）
    replace: str  # 替换后的代码
    defect_refs: list[str] = field(default_factory=list)  # 关联的缺陷 ID
    status: str = "pending"  # pending / applied / failed / skipped


@dataclass
class PatchReport:
    """聚合报告"""

    total_defects: int = 0
    l1_count: int = 0
    l2_count: int = 0
    l3_count: int = 0
    patches: list[PatchEntry] = field(default_factory=list)
    grouped_by_file: dict[str, list[AggregatedDefect]] = field(
        default_factory=dict,
    )
    has_blocking: bool = False
    summary: str = ""


# ══════════════════════════════════════════════════════════
# 缺陷聚合器
# ══════════════════════════════════════════════════════════


class PatchAggregator:
    """缺陷聚合 + 补丁生成器"""

    def aggregate(
        self,
        quality_report: dict | None = None,
        test_result: dict | None = None,
        acceptance_result: dict | None = None,
    ) -> PatchReport:
        """聚合多个校验来源的缺陷"""
        all_defects: list[AggregatedDefect] = []

        # 1. 质量审查缺陷
        if quality_report:
            defects = self._extract_quality_defects(quality_report)
            all_defects.extend(defects)

        # 2. 测试缺陷
        if test_result:
            defects = self._extract_test_defects(test_result)
            all_defects.extend(defects)

        # 3. 验收缺陷
        if acceptance_result:
            defects = self._extract_acceptance_defects(acceptance_result)
            all_defects.extend(defects)

        # 聚合
        report = self._build_report(all_defects)
        return report

    def generate_patches(self, report: PatchReport) -> list[PatchEntry]:
        """根据聚合报告生成最小改动补丁

        注意: 此方法仅生成补丁元数据（占位），
        实际的 search/replace 需要 LLM 根据代码生成。
        """
        patches: list[PatchEntry] = []
        for severity in ("l1_blocking", "l2_major"):
            for file_path, defects in report.grouped_by_file.items():
                sev_defects = [d for d in defects if d.severity == severity]
                if not sev_defects:
                    continue

                # 合并同一文件的缺陷描述
                combined_desc = "\n".join(f"- [{d.severity}] {d.description}" for d in sev_defects)
                patches.append(
                    PatchEntry(
                        file_path=file_path,
                        search=f"# PATCH PLACEHOLDER: {file_path}",
                        replace=(
                            f"# PATCH PLACEHOLDER: {file_path}\n"
                            f"# 需要修复: {len(sev_defects)} 个缺陷\n"
                            f"{combined_desc}"
                        ),
                        defect_refs=[str(id(d)) for d in sev_defects],
                    )
                )
        report.patches = patches
        return patches

    # ── 提取方法 ────────────────────────────────────────

    def _extract_quality_defects(
        self,
        report: dict,
    ) -> list[AggregatedDefect]:
        """从质量审查报告中提取缺陷"""
        defects: list[AggregatedDefect] = []
        issues = report.get("issues", [])
        for issue in issues:
            sev_map = {
                "error": "l1_blocking",
                "warning": "l2_major",
                "info": "l3_minor",
            }
            severity = sev_map.get(issue.get("severity", ""), "l2_major")
            defects.append(
                AggregatedDefect(
                    file_path=issue.get("file", issue.get("path", "unknown")),
                    line_range=(
                        (issue.get("line", 0), issue.get("line", 0)) if issue.get("line") else None
                    ),
                    severity=severity,
                    source="quality_guard",
                    description=issue.get("message", str(issue))[:500],
                    fix_suggestion=issue.get("suggestion", ""),
                )
            )
        return defects

    def _extract_test_defects(
        self,
        result: dict,
    ) -> list[AggregatedDefect]:
        """从测试结果中提取缺陷"""
        defects: list[AggregatedDefect] = []
        failures = result.get("failures", []) or result.get("failed", [])
        for fail in failures:
            defects.append(
                AggregatedDefect(
                    file_path=fail.get("file", fail.get("test", "unknown")),
                    severity="l2_major",
                    source="test",
                    description=fail.get("message", str(fail))[:500],
                )
            )
        return defects

    def _extract_acceptance_defects(
        self,
        result: dict,
    ) -> list[AggregatedDefect]:
        """从验收结果中提取缺陷"""
        defects: list[AggregatedDefect] = []
        if not result.get("passed", False):
            report = result.get("report", {})
            items = report.get("items", []) if isinstance(report, dict) else []
            for item in items:
                if not item.get("passed", False):
                    defects.append(
                        AggregatedDefect(
                            file_path=item.get("file", item.get("requirement", "")),
                            severity="l2_major",
                            source="acceptance",
                            description=item.get("reason", item.get("name", ""))[:500],
                        )
                    )
        return defects

    def _build_report(
        self,
        defects: list[AggregatedDefect],
    ) -> PatchReport:
        """构建聚合报告"""
        report = PatchReport()
        report.total_defects = len(defects)

        # 按文件分组
        for d in defects:
            if d.file_path not in report.grouped_by_file:
                report.grouped_by_file[d.file_path] = []
            report.grouped_by_file[d.file_path].append(d)

        # 分级统计
        for d in defects:
            if d.severity == "l1_blocking":
                report.l1_count += 1
            elif d.severity == "l2_major":
                report.l2_count += 1
            elif d.severity == "l3_minor":
                report.l3_count += 1

        report.has_blocking = report.l1_count > 0
        report.summary = (
            f"共 {report.total_defects} 个缺陷"
            f"（L1={report.l1_count}, L2={report.l2_count}, L3={report.l3_count}）"
            + (" ⚠️ 含阻断级缺陷！" if report.has_blocking else "")
        )

        return report


# ══════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════


def aggregate_defects(
    quality_report: dict | None = None,
    test_result: dict | None = None,
    acceptance_result: dict | None = None,
) -> PatchReport:
    """单次调用的便捷聚合入口"""
    aggregator = PatchAggregator()
    return aggregator.aggregate(quality_report, test_result, acceptance_result)
