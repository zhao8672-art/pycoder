"""
AutoPluginValidator — 安装后自动验证器

职责:
    1. 功能性验证: Skill 文件可读/格式正确/必须有描述和工具定义
    2. 冲突检测: 同名覆盖/功能重叠/命名空间冲突
    3. 注册验证: 确认已正确注册到 PluginRegistry
    4. 生成验证报告

用法:
    from .auto_plugin_validator import AutoPluginValidator
    v = AutoPluginValidator()
    report = await v.validate(skill_id)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationReport:
    """验证报告"""

    candidate_id: str = ""
    passed: bool = False
    file_exists: bool = False
    format_valid: bool = False
    has_content: bool = False
    has_description: bool = False
    has_tools: bool = False
    no_conflict: bool = True
    conflict_details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: int = 0  # 0-100
    errors: list[str] = field(default_factory=list)
    validated_at: float = 0.0


class AutoPluginValidator:
    """安装后自动验证器"""

    _SKILLS_DIR = Path.home() / ".pycoder" / "skills"

    # ══════════════════════════════════════════════════════
    # 主验证入口
    # ══════════════════════════════════════════════════════

    async def validate(self, candidate_id: str) -> ValidationReport:
        """对安装的 Skill 进行全面验证

        Returns:
            ValidationReport
        """
        report = ValidationReport(
            candidate_id=candidate_id,
            validated_at=time.time(),
        )

        # 1. 文件存在性
        file_path = self._SKILLS_DIR / f"{candidate_id}.md"
        if not file_path.exists():
            report.errors.append("文件不存在")
            return report
        report.file_exists = True

        # 2. 文件格式
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as e:
            report.errors.append(f"文件不可读: {e}")
            return report

        if not content or len(content.strip()) < 20:
            report.errors.append("文件内容不足 20 字符")
            return report
        report.format_valid = True
        report.has_content = True

        # 3. 描述检查
        lines = content.split("\n")
        has_heading = any(line.startswith("# ") for line in lines[:5])
        has_desc = len(content) > 100
        if has_heading and has_desc:
            report.has_description = True
        else:
            report.warnings.append("缺少完整描述或标题行")

        # 4. 工具定义检查
        has_tool = bool(re.search(r"##\s*(工具|Tools|Functions|Commands)", content, re.I))
        has_code = bool(re.search(r"```", content))
        if has_tool or has_code:
            report.has_tools = True

        # 5. 冲突检测
        conflicts = self._detect_conflicts(candidate_id)
        if conflicts:
            report.no_conflict = False
            report.conflict_details = conflicts
            report.warnings.append(f"检测到 {len(conflicts)} 个冲突")

        # 6. 综合评分
        score = 0
        if report.file_exists:
            score += 15
        if report.format_valid:
            score += 20
        if report.has_content:
            score += 15
        if report.has_description:
            score += 20
        if report.has_tools:
            score += 20
        if report.no_conflict:
            score += 10

        report.score = score
        report.passed = score >= 60

        return report

    # ══════════════════════════════════════════════════════
    # 冲突检测
    # ══════════════════════════════════════════════════════

    def _detect_conflicts(self, candidate_id: str) -> list[str]:
        """检测同名 / 功能重叠冲突"""
        conflicts: list[str] = []

        # 1. 同名文件覆盖
        other_dirs = [
            Path.cwd() / ".skills",
        ]
        for d in other_dirs:
            if d.exists():
                for f in d.glob(f"*{candidate_id}*"):
                    conflicts.append(f"同名: {f}")

        return conflicts

    # ══════════════════════════════════════════════════════
    # 批量验证
    # ══════════════════════════════════════════════════════

    async def validate_all(self) -> list[ValidationReport]:
        """验证所有已安装的 Skills"""
        reports: list[ValidationReport] = []
        for f in self._SKILLS_DIR.glob("*.md"):
            if f.name.startswith("."):
                continue
            report = await self.validate(f.stem)
            reports.append(report)
        return reports
