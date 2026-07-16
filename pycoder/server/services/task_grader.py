"""
任务难度自适应分级 — 对标 Codex 动态算力自适应

根据任务特征自动评估难度等级，动态调整执行参数（步数、温度、超时等），
实现"简单任务快速响应，复杂任务深度推理"的算力分配策略。

3 档难度:
  - LIGHT:  简单问答/单文件修改，5-10 步，temperature=0.3
  - MEDIUM: 多文件修改/功能开发，15-25 步，temperature=0.2
  - HEAVY:  复杂工程/架构重构，30-120 步，temperature=0.15

评分维度:
  - 代码量 (code_volume):      涉及的文件数和行数
  - 依赖复杂度 (dep_complexity):  外部依赖数量和类型
  - 领域专业性 (domain_expertise): 技术领域深度
  - 变更范围 (change_scope):     影响范围（单文件 → 多模块 → 架构级）
  - 约束条件 (constraints):     性能/安全/兼容性等约束数量

用法:
    from pycoder.server.services.task_grader import TaskGrader, TaskGrade, GradeLevel

    grader = TaskGrader()
    grade = grader.assess(
        task="实现用户认证模块，包括 JWT 登录、OAuth2 集成、RBAC 权限控制",
        context={"files": 5, "dependencies": 3, "domain": "backend"},
    )
    print(f"难度: {grade.level.name}, 步数: {grade.max_iterations}, 温度: {grade.temperature}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import IntEnum
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
# 枚举与数据类
# ═══════════════════════════════════════════════════════════════════


class GradeLevel(IntEnum):
    """难度等级"""
    LIGHT = 1   # 简单
    MEDIUM = 2  # 中等
    HEAVY = 3   # 复杂


@dataclass
class TaskGrade:
    """任务难度评级结果"""

    level: GradeLevel = GradeLevel.MEDIUM
    score: float = 50.0  # 0-100 综合评分
    max_iterations: int = 20
    temperature: float = 0.2
    timeout_seconds: float = 300.0
    max_tokens: int = 4096
    dimensions: dict[str, float] = field(default_factory=dict)  # 各维度得分
    reasoning: list[str] = field(default_factory=list)  # 评级理由

    @property
    def label(self) -> str:
        """中文标签（兼容 self_evo/engine.py）"""
        return GRADE_CONFIG[self.level]["label"]

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "level": self.level.name,
            "level_value": int(self.level),
            "label": self.label,
            "score": round(self.score, 1),
            "max_iterations": self.max_iterations,
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "dimensions": {k: round(v, 1) for k, v in self.dimensions.items()},
            "reasoning": self.reasoning,
        }


# ═══════════════════════════════════════════════════════════════════
# 难度配置映射
# ═══════════════════════════════════════════════════════════════════

# 难度 → 执行参数映射
GRADE_CONFIG: dict[GradeLevel, dict[str, Any]] = {
    GradeLevel.LIGHT: {
        "max_iterations": (5, 10),
        "temperature": 0.3,
        "timeout_seconds": 120.0,
        "max_tokens": 2048,
        "label": "简单",
    },
    GradeLevel.MEDIUM: {
        "max_iterations": (15, 25),
        "temperature": 0.2,
        "timeout_seconds": 300.0,
        "max_tokens": 4096,
        "label": "中等",
    },
    GradeLevel.HEAVY: {
        "max_iterations": (30, 120),
        "temperature": 0.15,
        "timeout_seconds": 900.0,
        "max_tokens": 8192,
        "label": "复杂",
    },
}

# 评分阈值
SCORE_THRESHOLDS: dict[GradeLevel, tuple[float, float]] = {
    GradeLevel.LIGHT: (0.0, 35.0),
    GradeLevel.MEDIUM: (35.0, 70.0),
    GradeLevel.HEAVY: (70.0, 100.0),
}


# ═══════════════════════════════════════════════════════════════════
# TaskGrader — 任务难度评估器
# ═══════════════════════════════════════════════════════════════════


class TaskGrader:
    """任务难度自适应分级器

    评估维度（5 维加权评分）:
      1. 代码量 (code_volume)       — 权重 25%
      2. 依赖复杂度 (dep_complexity)  — 权重 20%
      3. 领域专业性 (domain_expertise) — 权重 20%
      4. 变更范围 (change_scope)      — 权重 20%
      5. 约束条件 (constraints)      — 权重 15%

    用法:
        grader = TaskGrader()
        grade = grader.assess("实现用户登录模块")
        # 根据 grade 动态调整执行参数
    """

    # 维度权重
    DEFAULT_WEIGHTS: dict[str, float] = {
        "code_volume": 0.25,
        "dep_complexity": 0.20,
        "domain_expertise": 0.20,
        "change_scope": 0.20,
        "constraints": 0.15,
    }

    # 技术领域映射（领域 → 基础难度分）
    DOMAIN_BASE_SCORES: dict[str, float] = {
        "frontend": 30.0,
        "backend": 45.0,
        "devops": 50.0,
        "security": 60.0,
        "data_science": 55.0,
        "machine_learning": 65.0,
        "database": 50.0,
        "api": 40.0,
        "cli": 25.0,
        "docs": 15.0,
        "testing": 35.0,
        "refactoring": 55.0,
        "architecture": 75.0,
        "performance": 60.0,
        "migration": 70.0,
        "bug_fix": 25.0,
        "feature": 45.0,
        "config": 20.0,
        "dependency": 30.0,
        "deployment": 50.0,
    }

    # 关键词 → 领域映射
    KEYWORD_DOMAIN_MAP: dict[str, str] = {
        "react": "frontend", "vue": "frontend", "angular": "frontend",
        "css": "frontend", "html": "frontend", "ui": "frontend",
        "组件": "frontend", "页面": "frontend", "样式": "frontend",
        "fastapi": "backend", "flask": "backend", "django": "backend",
        "认证": "security", "授权": "security", "加密": "security",
        "jwt": "security", "oauth": "security", "rbac": "security",
        "xss": "security", "sql注入": "security", "csrf": "security",
        "docker": "devops", "kubernetes": "devops", "k8s": "devops",
        "ci": "devops", "cd": "devops", "部署": "devops",
        "pandas": "data_science", "numpy": "data_science",
        "matplotlib": "data_science", "sklearn": "machine_learning",
        "pytorch": "machine_learning", "tensorflow": "machine_learning",
        "模型": "machine_learning", "训练": "machine_learning",
        "sql": "database", "数据库": "database", "orm": "database",
        "迁移": "migration", "重构": "refactoring",
        "架构": "architecture", "设计模式": "architecture",
        "性能": "performance", "优化": "performance",
        "测试": "testing", "pytest": "testing", "覆盖率": "testing",
        "修复": "bug_fix", "bug": "bug_fix", "错误": "bug_fix",
    }

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)
        self._stats: dict[str, Any] = {
            "total_assessments": 0,
            "level_distribution": {g.name: 0 for g in GradeLevel},
            "average_score": 0.0,
        }

    # ── 主评估方法 ──────────────────────────────────

    def assess(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> TaskGrade:
        """评估任务难度等级

        Args:
            task: 任务描述
            context: 额外上下文信息（可选）

        Returns:
            TaskGrade 包含难度等级和执行参数
        """
        ctx = context or {}

        # 1. 计算各维度得分
        dimensions = self._score_dimensions(task, ctx)

        # 2. 加权综合评分
        score = self._weighted_score(dimensions)

        # 3. 确定等级
        level = self._classify(score)

        # 4. 生成执行参数
        config = GRADE_CONFIG[level]
        max_iter = self._interpolate_iterations(score, config["max_iterations"])

        # 5. 生成评级理由
        reasoning = self._generate_reasoning(dimensions, level, score)

        # 6. 更新统计
        self._update_stats(level, score)

        grade = TaskGrade(
            level=level,
            score=score,
            max_iterations=max_iter,
            temperature=float(config["temperature"]),
            timeout_seconds=float(config["timeout_seconds"]),
            max_tokens=int(config["max_tokens"]),
            dimensions=dimensions,
            reasoning=reasoning,
        )

        logger.info(
            "任务难度评估: level=%s score=%.1f max_iter=%d task=%.80s",
            level.name, score, max_iter, task,
        )
        return grade

    # ── 维度评分 ────────────────────────────────────

    def _score_dimensions(
        self, task: str, ctx: dict[str, Any]
    ) -> dict[str, float]:
        """计算 5 个维度的得分（0-100）"""
        dims: dict[str, float] = {}

        # 1. 代码量
        dims["code_volume"] = self._score_code_volume(task, ctx)

        # 2. 依赖复杂度
        dims["dep_complexity"] = self._score_dep_complexity(task, ctx)

        # 3. 领域专业性
        dims["domain_expertise"] = self._score_domain_expertise(task, ctx)

        # 4. 变更范围
        dims["change_scope"] = self._score_change_scope(task, ctx)

        # 5. 约束条件
        dims["constraints"] = self._score_constraints(task, ctx)

        return dims

    def _score_code_volume(
        self, task: str, ctx: dict[str, Any]
    ) -> float:
        """评估代码量维度

        依据:
          - 显式指定文件数（ctx 中）
          - 任务描述中的文件/模块数量关键词
          - 预估代码行数
        """
        score = 20.0  # 基础分

        # 显式文件数
        files = ctx.get("files", 0)
        if isinstance(files, (int, float)) and files > 0:
            if files <= 2:
                score += 10
            elif files <= 5:
                score += 30
            elif files <= 10:
                score += 50
            else:
                score += 70

        # 预估行数
        lines = ctx.get("lines", ctx.get("estimated_lines", 0))
        if isinstance(lines, (int, float)) and lines > 0:
            if lines <= 100:
                score += 10
            elif lines <= 500:
                score += 30
            elif lines <= 2000:
                score += 50
            else:
                score += 70

        # 任务描述中的关键词
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["多个文件", "多文件", "多个模块", "多模块"]):
            score += 30
        if any(kw in task_lower for kw in ["整个项目", "全项目", "所有文件", "批量"]):
            score += 40
        if any(kw in task_lower for kw in ["新建", "创建", "搭建", "实现", "开发"]):
            score += 15

        return min(100.0, score)

    def _score_dep_complexity(
        self, task: str, ctx: dict[str, Any]
    ) -> float:
        """评估依赖复杂度

        依据:
          - 外部依赖数量
          - 任务描述中的集成/对接关键词
          - 跨服务依赖
        """
        score = 15.0

        # 显式依赖数
        deps = ctx.get("dependencies", ctx.get("deps", 0))
        if isinstance(deps, (int, float)) and deps > 0:
            if deps <= 2:
                score += 15
            elif deps <= 5:
                score += 35
            elif deps <= 10:
                score += 55
            else:
                score += 75

        task_lower = task.lower()
        # 集成/对接类关键词
        integration_keywords = [
            "集成", "对接", "接入", "整合", "集成到",
            "第三方", "外部服务", "微服务", "消息队列",
            "redis", "rabbitmq", "kafka", "celery",
            "数据库迁移", "数据迁移", "api对接",
        ]
        hits = sum(1 for kw in integration_keywords if kw in task_lower)
        score += hits * 15

        # 跨服务/跨系统
        if any(kw in task_lower for kw in ["跨服务", "跨系统", "跨模块", "rpc", "grpc"]):
            score += 25

        return min(100.0, score)

    def _score_domain_expertise(
        self, task: str, ctx: dict[str, Any]
    ) -> float:
        """评估领域专业性

        依据:
          - 识别技术领域
          - 领域基础分 + 多领域交叉加成
        """
        task_lower = task.lower()
        domains: set[str] = set()

        # 显式指定领域
        explicit_domain = ctx.get("domain", "")
        if explicit_domain and explicit_domain in self.DOMAIN_BASE_SCORES:
            domains.add(explicit_domain)

        # 关键词匹配
        for keyword, domain in self.KEYWORD_DOMAIN_MAP.items():
            if keyword in task_lower:
                domains.add(domain)

        if not domains:
            return 30.0  # 通用任务

        # 取最高领域分
        base_score = max(
            self.DOMAIN_BASE_SCORES.get(d, 30.0) for d in domains
        )

        # 多领域交叉加成
        if len(domains) >= 3:
            base_score += 20
        elif len(domains) >= 2:
            base_score += 10

        return min(100.0, base_score)

    def _score_change_scope(
        self, task: str, ctx: dict[str, Any]
    ) -> float:
        """评估变更范围

        依据:
          - 影响范围：单文件 → 单模块 → 多模块 → 架构级
          - 任务描述中的范围关键词
          - 是否涉及公共 API / 接口变更
        """
        score = 20.0

        task_lower = task.lower()

        # 范围关键词
        scope_keywords: dict[str, float] = {
            "单文件": 10, "单个文件": 10, "一个文件": 10,
            "单模块": 20, "单个模块": 20,
            "多模块": 40, "多个模块": 40, "跨模块": 45,
            "架构": 70, "架构重构": 80, "架构升级": 80,
            "全局": 60, "整个项目": 70, "整体": 55,
            "公共接口": 40, "api变更": 45, "接口变更": 45,
            "破坏性变更": 60, "不兼容": 55, "breaking": 60,
        }
        for kw, bonus in scope_keywords.items():
            if kw in task_lower:
                score = max(score, bonus + 20)

        # 显式指定范围
        scope = ctx.get("scope", "")
        if scope == "file":
            score = min(score + 10, 100)
        elif scope == "module":
            score = min(score + 25, 100)
        elif scope == "multi_module":
            score = min(score + 50, 100)
        elif scope == "architecture":
            score = min(score + 75, 100)

        # 是否涉及公开 API
        if ctx.get("public_api", False):
            score += 20

        return min(100.0, score)

    def _score_constraints(
        self, task: str, ctx: dict[str, Any]
    ) -> float:
        """评估约束条件

        依据:
          - 性能/安全/兼容性要求
          - 时间约束
          - 质量门禁
        """
        score = 10.0

        task_lower = task.lower()

        # 约束关键词
        constraint_keywords: dict[str, float] = {
            "性能": 15, "高性能": 25, "低延迟": 25, "高并发": 30,
            "安全": 20, "加密": 20, "xss": 20, "注入": 20,
            "兼容": 15, "向后兼容": 20, "向前兼容": 20,
            "稳定": 15, "高可用": 25, "容错": 20,
            "规范": 10, "标准": 10, "pep": 10,
            "测试覆盖率": 15, "覆盖率": 15, "90%": 15,
            "紧急": 20, "urgent": 20, "尽快": 15,
        }
        for kw, bonus in constraint_keywords.items():
            if kw in task_lower:
                score += bonus

        # 显式约束数
        explicit_constraints = ctx.get("constraints", [])
        if isinstance(explicit_constraints, list):
            score += len(explicit_constraints) * 10

        return min(100.0, score)

    # ── 加权与分类 ──────────────────────────────────

    def _weighted_score(self, dimensions: dict[str, float]) -> float:
        """加权综合评分"""
        total = 0.0
        for dim, weight in self._weights.items():
            total += dimensions.get(dim, 0.0) * weight
        return round(total, 1)

    def _classify(self, score: float) -> GradeLevel:
        """根据分数确定等级"""
        for level, (low, high) in SCORE_THRESHOLDS.items():
            if low <= score < high:
                return level
        return GradeLevel.HEAVY  # >= 70

    def _interpolate_iterations(
        self, score: float, iteration_range: tuple[int, int]
    ) -> int:
        """在迭代范围内按分数插值"""
        low, high = iteration_range
        if low == high:
            return low

        # 在当前等级范围内归一化
        for level, (t_low, t_high) in SCORE_THRESHOLDS.items():
            if t_low <= score < t_high:
                ratio = (score - t_low) / (t_high - t_low)
                return max(low, min(high, int(low + ratio * (high - low))))

        return high

    def _generate_reasoning(
        self,
        dimensions: dict[str, float],
        level: GradeLevel,
        score: float,
    ) -> list[str]:
        """生成评级理由"""
        reasons: list[str] = []

        label = GRADE_CONFIG[level]["label"]
        reasons.append(f"综合评分 {score:.1f}/100 → {label}难度")

        # 各维度贡献
        dim_labels = {
            "code_volume": "代码量",
            "dep_complexity": "依赖复杂度",
            "domain_expertise": "领域专业性",
            "change_scope": "变更范围",
            "constraints": "约束条件",
        }
        high_dims = [
            (dim_labels.get(d, d), v)
            for d, v in sorted(dimensions.items(), key=lambda x: -x[1])
            if v >= 50
        ]
        if high_dims:
            reasons.append(
                "主要难度来源: " + ", ".join(
                    f"{name}({val:.0f})" for name, val in high_dims[:3]
                )
            )

        if level == GradeLevel.HEAVY:
            reasons.append("建议启用深度推理模式，分配更多 Token 预算")
        elif level == GradeLevel.LIGHT:
            reasons.append("建议使用快速推理模式，减少 Token 消耗")

        return reasons

    # ── 统计 ────────────────────────────────────────

    def _update_stats(self, level: GradeLevel, score: float) -> None:
        """更新统计信息"""
        self._stats["total_assessments"] += 1
        self._stats["level_distribution"][level.name] += 1
        n = self._stats["total_assessments"]
        self._stats["average_score"] = (
            (self._stats["average_score"] * (n - 1) + score) / n
        )

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return dict(self._stats)

    def set_weights(self, weights: dict[str, float]) -> None:
        """动态调整维度权重（用于反馈学习）"""
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"权重之和必须为 1.0，当前: {total}")
        self._weights = weights
        logger.info("任务难度评估权重已更新: %s", weights)

    # ── 兼容现有代码的快捷方法 ──────────────────────

    # GradeLevel → 字符串映射（兼容 unified_agent / agent_strategies）
    _LEVEL_STR_MAP: dict[GradeLevel, str] = {
        GradeLevel.LIGHT: "low",
        GradeLevel.MEDIUM: "medium",
        GradeLevel.HEAVY: "high",
    }

    def grade(self, message: str) -> TaskGrade:
        """快捷评估方法 — 兼容 unified_agent.py 调用

        Args:
            message: 任务描述文本

        Returns:
            TaskGrade 评估结果（.level 为字符串 "low"/"medium"/"high"）
        """
        result = self.assess(message)
        # 将 level 转为字符串格式（兼容 resolve_iterations_for_grade）
        object.__setattr__(result, "level", self._LEVEL_STR_MAP.get(result.level, "medium"))
        return result

    def grade_from_kwargs(
        self,
        task_type: str = "",
        target: str = "",
        custom_prompt: str = "",
    ) -> TaskGrade:
        """从关键字参数评估难度 — 兼容 self_evo/engine.py 调用

        Args:
            task_type: 任务类型
            target: 目标文件/模块
            custom_prompt: 自定义提示

        Returns:
            TaskGrade 评估结果
        """
        # 组合任务描述
        parts: list[str] = []
        if task_type:
            parts.append(task_type)
        if target:
            parts.append(f"目标: {target}")
        if custom_prompt:
            parts.append(custom_prompt)
        task_desc = " ".join(parts) if parts else "通用任务"
        return self.grade(task_desc)


# ═══════════════════════════════════════════════════════════════════
# 单例工厂
# ═══════════════════════════════════════════════════════════════════

_grader_instance: TaskGrader | None = None


def get_task_grader() -> TaskGrader:
    """获取 TaskGrader 单例（兼容 unified_agent / task_api / self_evo 调用）

    Returns:
        TaskGrader 全局单例
    """
    global _grader_instance
    if _grader_instance is None:
        _grader_instance = TaskGrader()
    return _grader_instance


# ═══════════════════════════════════════════════════════════════════
# 能力注册
# ═══════════════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> list[CapabilityDefinition]:
    """向 V2 能力总线注册任务难度评估能力

    Args:
        registry: CapabilityRegistry 实例

    Returns:
        已注册的能力定义列表
    """
    grader = TaskGrader()

    definitions: list[CapabilityDefinition] = []

    # 1. task_grader.assess — 评估任务难度
    async def _handle_assess(params: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        task = params.get("task", "")
        context = params.get("context", {})
        grade = grader.assess(task, context)
        return grade.to_dict()

    def_assess = CapabilityDefinition(
        id="task_grader.assess",
        name="任务难度评估",
        description="根据任务描述和上下文自动评估难度等级（LIGHT/MEDIUM/HEAVY），返回执行参数建议",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="1.0.0",
        timeout_ms=5000,
        tags=["task_grader", "difficulty", "adaptive", "scoring"],
    )
    definitions.append(def_assess)
    registry.register(def_assess, handler=_handle_assess)

    # 2. task_grader.get_stats — 获取统计
    async def _handle_stats(params: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        return grader.get_stats()

    def_stats = CapabilityDefinition(
        id="task_grader.get_stats",
        name="难度评估统计",
        description="获取任务难度评估的统计信息（评估次数、等级分布、平均分）",
        category=CapabilityCategory.SELF_EVO,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="1.0.0",
        timeout_ms=3000,
        tags=["task_grader", "stats", "monitoring"],
    )
    definitions.append(def_stats)
    registry.register(def_stats, handler=_handle_stats)

    logger.info("任务难度评估能力已注册: %d 个能力", len(definitions))
    return definitions


# ═══════════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    "GradeLevel",
    "TaskGrade",
    "TaskGrader",
    "GRADE_CONFIG",
    "SCORE_THRESHOLDS",
    "get_task_grader",
    "register_capabilities",
]