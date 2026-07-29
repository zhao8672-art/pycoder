"""
技能市场月报生成器 — Phase 2

功能:
1. 基于生命周期数据和技能排名生成 Markdown 报告
2. 趋势摘要、新兴技能预警、衰退技能提醒
3. 分类分布统计
"""

from __future__ import annotations

import time
from pathlib import Path

from pycoder.core.services.log import log


class SkillsReportGenerator:
    """技能市场报告生成器

    基于生命周期引擎数据和技能排名生成结构化报告。
    报告格式: Markdown (可导出为 HTML/PDF)
    """

    def __init__(self, report_dir: str | Path | None = None):
        if report_dir is None:
            report_dir = Path.home() / ".pycoder" / "reports"
        self._report_dir = Path(report_dir)
        self._report_dir.mkdir(parents=True, exist_ok=True)

    def generate_markdown(
        self,
        lifecycle_stats: dict,
        trending: list[dict],
        emerging: list[dict],
        so_trends: list[dict],
        so_stats: dict,
    ) -> str:
        """生成完整月报 Markdown"""
        now = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        lines = [
            "# 🚀 PyCoder 技能市场月报",
            "",
            f"**生成时间**: {now}",
            "**数据来源**: OSSInsight + GitHub Search + Stack Overflow 调查",
            "",
            "---",
            "",
            "## 📊 核心指标",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
        ]

        if so_stats:
            lines.append(f"| Stack Overflow 技术追踪 | {so_stats.get('technologies', 0)} 项 |")
            lines.append(f"| 其中上升技术 | {so_stats.get('rising', 0)} 项 |")
            lines.append(f"| 其中下降技术 | {so_stats.get('declining', 0)} 项 |")

        if lifecycle_stats:
            for cat, stages in lifecycle_stats.items():
                total = sum(s["count"] for s in stages)
                stage_summary = ", ".join(f"{s['stage']}: {s['count']}" for s in stages)
                lines.append(f"| {cat} ({total}) | {stage_summary} |")

        lines += [
            "",
            "---",
            "",
            "## 🔥 新兴技能 TOP 10",
            "",
            "| 排名 | 技能名称 | 分类 | 28天 Stars | 增长率 |",
            "|------|----------|------|-----------|--------|",
        ]

        for i, skill in enumerate(emerging[:10], 1):
            name = skill.get("skill_name", skill.get("name", ""))
            cat = skill.get("category", "")
            stars = skill.get("stars_28d", 0)
            rate = skill.get("growth_rate_28d", 0)
            lines.append(f"| {i} | {name} | {cat} | {stars} | {rate:.1%} |")

        lines += [
            "",
            "---",
            "",
            "## 📈 趋势上升 TOP 10",
            "",
            "| 排名 | 技能名称 | 分类 | 28天 Stars | 动量 |",
            "|------|----------|------|-----------|------|",
        ]

        for i, skill in enumerate(trending[:10], 1):
            name = skill.get("skill_name", skill.get("name", ""))
            cat = skill.get("category", "")
            stars = skill.get("stars_28d", 0)
            momentum = skill.get("momentum", 0)
            lines.append(f"| {i} | {name} | {cat} | {stars} | {momentum:+.2%} |")

        if so_trends:
            lines += [
                "",
                "---",
                "",
                "## 📊 Stack Overflow 热点变迁 (2024→2025)",
                "",
                "| 技术 | 2024 采用率 | 2025 采用率 | 变化 | 阶段 |",
                "|------|-----------|-----------|------|------|",
            ]
            for t in so_trends[:15]:
                lines.append(
                    f"| {t['technology']} | {t['adoption_2024']:.1f}% | "
                    f"{t['adoption_2025']:.1f}% | "
                    f"{t['growth_rate']:+.1%} | {t['stage']} |"
                )

        lines += [
            "",
            "---",
            "",
            "## 📝 分析摘要",
            "",
        ]

        # 自动生成摘要
        if emerging:
            top_emerging = emerging[0]
            lines.append(
                f"- 🔥 **最热新兴技能**:"
                f" `{top_emerging.get('skill_name', top_emerging.get('name', ''))}`"
                f" 在 {top_emerging.get('category', '')} 分类中"
                f" 以 {top_emerging.get('stars_28d', 0)} 颗 28天 Star 领跑"
            )

        if so_trends:
            rising = [t for t in so_trends if t["growth_rate"] > 0.1]
            declining = [t for t in so_trends if t["growth_rate"] < -0.05]
            if rising:
                names = ", ".join(t["technology"] for t in rising[:5])
                lines.append(f"- 📈 **快速上升**: {names}")
            if declining:
                names = ", ".join(t["technology"] for t in declining[:5])
                lines.append(f"- 📉 **持续下降**: {names}")

        lines += [
            "",
            "---",
            "",
            f"*PyCoder 技能市场自动生成 | {now}*",
            "",
        ]

        return "\n".join(lines)

    def save_report(self, content: str, name: str = "") -> str:
        """保存报告到文件

        Args:
            content: Markdown 内容
            name: 文件名 (不含扩展名)

        Returns:
            文件绝对路径
        """
        if not name:
            name = f"skills-report-{time.strftime('%Y%m')}"
        file_path = self._report_dir / f"{name}.md"
        file_path.write_text(content, encoding="utf-8")
        log.info("skills_report_saved", path=str(file_path), size=len(content))
        return str(file_path)


def generate_skills_report(engine=None, report_generator=None) -> dict:
    """便捷函数: 生成并保存技能月报

    Args:
        engine: SkillLifecycleEngine 实例
        report_generator: SkillsReportGenerator 实例

    Returns:
        包含报告路径和摘要的字典
    """
    if engine is None:
        from pycoder.server.skills_lifecycle import get_lifecycle_engine

        engine = get_lifecycle_engine()

    if report_generator is None:
        report_generator = SkillsReportGenerator()

    # 1. 导入 SO 数据
    engine.import_so_survey()

    # 2. 获取生命周期分布
    lifecycle_stats = engine.get_lifecycle_by_category()

    # 3. 获取 SO 趋势
    so_trends = engine.get_so_trends()

    # 4. 计算 SO 统计
    so_stats = {
        "technologies": len(so_trends),
        "rising": sum(1 for t in so_trends if t["growth_rate"] > 0),
        "declining": sum(1 for t in so_trends if t["growth_rate"] < 0),
    }

    # 5. 获取生命周期标签中的新兴技能
    try:
        import sqlite3

        conn = sqlite3.connect(str(engine._db_path), timeout=5)
        cursor = conn.execute(
            "SELECT skill_id, skill_name, category, growth_rate_28d, "
            "       stars_28d, stars_total, momentum "
            "FROM lifecycle_labels "
            "WHERE stage = 'emerging' OR stage = 'growing' "
            "ORDER BY growth_rate_28d DESC LIMIT 50"
        )
        emerging_rows = cursor.fetchall()
        conn.close()
        emerging = [
            {
                "skill_id": r[0],
                "skill_name": r[1],
                "category": r[2],
                "growth_rate_28d": r[3],
                "stars_28d": r[4],
                "stars_total": r[5],
                "momentum": r[6],
            }
            for r in emerging_rows
        ]
    except Exception:
        emerging = []

    # 6. 从 top 生命周期标签取 trending
    try:
        conn = sqlite3.connect(str(engine._db_path), timeout=5)
        cursor = conn.execute(
            "SELECT skill_id, skill_name, category, growth_rate_28d, "
            "       stars_28d, stars_total, momentum "
            "FROM lifecycle_labels "
            "WHERE momentum > 0 "
            "ORDER BY momentum DESC LIMIT 50"
        )
        trending_rows = cursor.fetchall()
        conn.close()
        trending = [
            {
                "skill_id": r[0],
                "skill_name": r[1],
                "category": r[2],
                "growth_rate_28d": r[3],
                "stars_28d": r[4],
                "stars_total": r[5],
                "momentum": r[6],
            }
            for r in trending_rows
        ]
    except Exception:
        trending = []

    # 7. 生成 Markdown
    md = report_generator.generate_markdown(
        lifecycle_stats=lifecycle_stats,
        trending=trending,
        emerging=emerging,
        so_trends=so_trends,
        so_stats=so_stats,
    )

    # 8. 保存
    path = report_generator.save_report(md)

    return {
        "success": True,
        "report_path": path,
        "so_technologies": len(so_trends),
        "emerging_count": len(emerging),
        "trending_count": len(trending),
        "report_size": len(md),
    }
