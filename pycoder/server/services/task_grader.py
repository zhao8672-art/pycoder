"""
任务难度自动分级引擎 — 对标智谱Agent三级推理档位/Codex动态算力

根据需求描述自动评估任务复杂度，返回最佳执行参数：
  - low:      简单任务，5步，economy模型，低推理强度
  - medium:   中等任务，15步，standard模型，中推理强度
  - high:     复杂长程任务，50步，premium模型，满推理+沉思反思全开

用法:
    from pycoder.server.services.task_grader import TaskGrader

    grader = TaskGrader()
    grade = grader.grade("重构 app.py 为多模块架构")
    # grade = TaskGrade(level='high', max_steps=50, ...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ══════════════════════════════════════════════════════════
# 难度关键词
# ══════════════════════════════════════════════════════════

SIMPLE_KEYWORDS: list[str] = [
    # 中文
    "hello world",
    "示例",
    "demo",
    "举例",
    "测试",
    "快速",
    "简单",
    "小工具",
    "单文件",
    "脚本",
    "一句话",
    # 英文
    "hello",
    "example",
    "quick",
    "simple",
    "tiny",
    "single file",
    "one-liner",
    "sample",
]

MEDIUM_KEYWORDS: list[str] = [
    # 中文
    "api",
    "crud",
    "增删改查",
    "页面",
    "网站",
    "界面",
    "报表",
    "报告",
    "生成",
    "批量",
    "爬虫",
    "中间件",
    "数据库",
    "缓存",
    "队列",
    "模块",
    "组件",
    "功能",
    # 英文
    "rest",
    "endpoint",
    "router",
    "middleware",
    "cli",
    "database",
    "cache",
    "migration",
    "batch",
    "generator",
    "crawler",
    "scraper",
]

COMPLEX_KEYWORDS: list[str] = [
    # 中文
    "重构",
    "迁移",
    "升级",
    "改造",
    "大型",
    "全栈",
    "系统",
    "架构",
    "设计",
    "多模块",
    "微服务",
    "分布式",
    "高并发",
    "高可用",
    "多线程",
    "安全",
    "权限",
    "鉴权",
    "审计",
    "流水线",
    "管道",
    "工作流",
    "编排",
    "重构为",
    "迁移到",
    "大规模",
    # 英文
    "refactor",
    "migrate",
    "restructure",
    "redesign",
    "system",
    "architecture",
    "enterprise",
    "production",
    "multi-module",
    "monorepo",
    "distributed",
    "pipeline",
    "orchestration",
    "workflow",
    "scalable",
    "high-availability",
]


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class TaskGrade:
    """任务难度分级结果"""

    level: str  # "low" | "medium" | "high"
    label: str  # "轻量" | "中等" | "复杂长程"
    max_steps: int  # 最大执行步数
    model_tier: str  # "economy" | "standard" | "premium"
    reasoning_effort: str  # "low" | "medium" | "max"
    temperature: float  # 温度
    enable_rumination: bool  # 是否强制开启沉思反思
    enable_review: bool  # 是否强制审查
    enable_report: bool  # 是否生成复盘报告
    score: int = 0  # 复杂度评分(0-100)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "label": self.label,
            "max_steps": self.max_steps,
            "model_tier": self.model_tier,
            "reasoning_effort": self.reasoning_effort,
            "temperature": self.temperature,
            "enable_rumination": self.enable_rumination,
            "enable_review": self.enable_review,
            "enable_report": self.enable_report,
            "score": self.score,
        }


# ══════════════════════════════════════════════════════════
# 分级配置
# ══════════════════════════════════════════════════════════

LOW_GRADE = TaskGrade(
    level="low",
    label="轻量",
    max_steps=5,
    model_tier="economy",
    reasoning_effort="low",
    temperature=0.7,
    enable_rumination=False,
    enable_review=True,
    enable_report=False,
)

MEDIUM_GRADE = TaskGrade(
    level="medium",
    label="中等",
    max_steps=15,
    model_tier="standard",
    reasoning_effort="medium",
    temperature=0.3,
    enable_rumination=True,
    enable_review=True,
    enable_report=True,
)

HIGH_GRADE = TaskGrade(
    level="high",
    label="复杂长程",
    max_steps=50,
    model_tier="premium",
    reasoning_effort="max",
    temperature=0.15,
    enable_rumination=True,
    enable_review=True,
    enable_report=True,
)


# ══════════════════════════════════════════════════════════
# 分级器
# ══════════════════════════════════════════════════════════


class TaskGrader:
    """任务难度自动分级器"""

    def grade(self, description: str, target_files: list[str] | None = None) -> TaskGrade:
        """根据任务描述和目标文件自动评估难度

        Args:
            description: 任务描述
            target_files: 涉及的目标文件（可选，用于辅助判断）

        Returns:
            TaskGrade 配置
        """
        score = self._calc_score(description)
        grade = self._score_to_grade(score)
        grade.score = score
        return grade

    def grade_from_kwargs(
        self,
        task_type: str,
        target: str,
        custom: str,
        files: list[str] | None = None,
    ) -> TaskGrade:
        """从 evolve() 的关键词参数评分"""
        desc = custom or task_type or ""
        if target:
            desc += f" {' '.join(target.split(','))}"
        return self.grade(desc, files)

    # ── 内部实现 ──────────────────────────────────────

    def _calc_score(self, description: str) -> int:
        """计算复杂度评分 0-100"""
        desc = description.lower()
        score = 0

        # 1. 任务类型基础分
        if "fix" in desc or "bug" in desc or "error" in desc:
            score += 10
        if "optimize" in desc or "performance" in desc or "优化" in desc:
            score += 15
        if "refactor" in desc or "重构" in desc or "migrate" in desc or "迁移" in desc:
            score += 30
        if "security" in desc or "安全" in desc:
            score += 20

        # 2. 复杂关键词
        for kw in COMPLEX_KEYWORDS:
            if kw in desc:
                score += 8
        for kw in MEDIUM_KEYWORDS:
            if kw in desc:
                score += 4
        for kw in SIMPLE_KEYWORDS:
            if kw in desc:
                score -= 5  # 简单关键词降低分数

        # 3. 规模线索
        file_count = len(re.findall(r"(?:文件|file|模块|module)\s*(?:数|数量|count|\d+)", desc))
        score += file_count * 5

        # 4. 项目结构线索
        if re.search(r"(?:多文件|跨文件|多模块|multi|多个)", desc):
            score += 15

        # clamp 0-100
        return max(0, min(100, score))

    def _score_to_grade(self, score: int) -> TaskGrade:
        """将评分映射到三个档位"""
        if score < 15:
            return LOW_GRADE
        elif score < 45:
            return MEDIUM_GRADE
        else:
            return HIGH_GRADE


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_grader_instance: TaskGrader | None = None


def get_task_grader() -> TaskGrader:
    global _grader_instance
    if _grader_instance is None:
        _grader_instance = TaskGrader()
    return _grader_instance
