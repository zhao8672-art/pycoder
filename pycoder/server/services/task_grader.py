"""
任务难度自动分级系统 — Codex 动态算力风格

根据需求描述自动评估任务复杂度，将任务分为三个档位，并返回最佳推理参数：
  - LIGHT:  5-10 步，快速推理，temperature=0.3, max_tokens=4096
  - MEDIUM: 15-25 步，标准推理，temperature=0.2, max_tokens=8192
  - HEAVY:  30-120 步，深度推理，temperature=0.15, max_tokens=16384

分级逻辑基于:
  1. 关键词匹配（简单关键词 → LIGHT; api/crud/refactor → MEDIUM; migrate/system/architecture → HEAVY）
  2. 描述长度（短 → LIGHT, 长 → HEAVY）
  3. 提及的文件数量（1 文件 → LIGHT, 2-5 → MEDIUM, 5+ → HEAVY）
  4. 任务类型检测（bug_fix, feature, refactor, migration, architecture）

用法:
    from pycoder.server.services.task_grader import TaskGrader, register_capabilities

    grader = TaskGrader()
    grade = grader.grade("重构整个微服务架构，迁移到 FastAPI")
    # grade = TaskGrade(level='HEAVY', max_steps=120, ...)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 难度关键词
# ══════════════════════════════════════════════════════════

LIGHT_KEYWORDS: list[str] = [
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
    "修复拼写",
    "改个注释",
    "加个打印",
    "改个名字",
    "格式化",
    # 英文
    "hello",
    "example",
    "quick",
    "simple",
    "tiny",
    "single file",
    "one-liner",
    "sample",
    "fix typo",
    "format",
    "rename",
    "comment",
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
    "重构",
    "优化",
    "性能",
    "接口",
    "端点",
    "路由",
    "认证",
    "登录",
    "注册",
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
    "refactor",
    "optimize",
    "performance",
    "auth",
    "login",
    "register",
]

HEAVY_KEYWORDS: list[str] = [
    # 中文
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
    "企业级",
    "生产环境",
    "容器化",
    "部署",
    "集群",
    "负载均衡",
    # 英文
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
    "kubernetes",
    "docker",
    "deploy",
    "cluster",
    "microservice",
]

# 任务类型关键词映射
TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "bug_fix": ["fix", "bug", "修复", "错误", "error", "崩溃", "crash", "异常", "exception"],
    "feature": ["feature", "新增", "添加", "实现", "开发", "创建", "功能", "add", "implement", "create"],
    "refactor": ["refactor", "重构", "优化", "improve", "改造", "改进", "enhance"],
    "migration": ["migrate", "迁移", "升级", "upgrade", "搬迁", "切换"],
    "architecture": ["architecture", "架构", "design", "设计", "系统", "system", "platform", "平台"],
}


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class TaskGradeConfig:
    """单个难度级别的配置"""

    level: str  # "LIGHT" | "MEDIUM" | "HEAVY"
    label: str  # 中文标签
    min_steps: int  # 最小步数
    max_steps: int  # 最大步数
    temperature: float  # 推理温度
    max_tokens: int  # 最大输出 token 数
    reasoning_depth: str  # 推理深度: "fast" | "standard" | "deep"
    description: str  # 级别描述

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "label": self.label,
            "min_steps": self.min_steps,
            "max_steps": self.max_steps,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning_depth": self.reasoning_depth,
            "description": self.description,
        }


@dataclass
class TaskGrade:
    """任务难度分级结果"""

    level: str  # "LIGHT" | "MEDIUM" | "HEAVY"
    max_steps: int  # 最大执行步数
    temperature: float  # 推理温度
    max_tokens: int  # 最大输出 token 数
    reasoning_depth: str  # 推理深度
    description: str  # 级别描述
    score: int = 0  # 复杂度评分 (0-100)
    detected_types: list[str] = field(default_factory=list)  # 检测到的任务类型

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "max_steps": self.max_steps,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning_depth": self.reasoning_depth,
            "description": self.description,
            "score": self.score,
            "detected_types": self.detected_types,
        }


# ══════════════════════════════════════════════════════════
# 三档配置
# ══════════════════════════════════════════════════════════

LIGHT_CONFIG = TaskGradeConfig(
    level="LIGHT",
    label="轻量",
    min_steps=5,
    max_steps=10,
    temperature=0.3,
    max_tokens=4096,
    reasoning_depth="fast",
    description="简单任务，快速推理即可完成",
)

MEDIUM_CONFIG = TaskGradeConfig(
    level="MEDIUM",
    label="中等",
    min_steps=15,
    max_steps=25,
    temperature=0.2,
    max_tokens=8192,
    reasoning_depth="standard",
    description="中等复杂度任务，需要标准推理能力",
)

HEAVY_CONFIG = TaskGradeConfig(
    level="HEAVY",
    label="重量级",
    min_steps=30,
    max_steps=120,
    temperature=0.15,
    max_tokens=16384,
    reasoning_depth="deep",
    description="复杂长程任务，需要深度推理和大量计算资源",
)

# 级别到配置的映射
LEVEL_CONFIG_MAP: dict[str, TaskGradeConfig] = {
    "LIGHT": LIGHT_CONFIG,
    "MEDIUM": MEDIUM_CONFIG,
    "HEAVY": HEAVY_CONFIG,
}


# ══════════════════════════════════════════════════════════
# TaskGrader — 任务难度自动分级器
# ══════════════════════════════════════════════════════════


class TaskGrader:
    """任务难度自动分级器

    根据需求描述自动评估任务复杂度，返回最佳执行参数。
    对标 Codex 动态算力分配机制。
    """

    def grade(self, description: str) -> TaskGrade:
        """根据任务描述自动评估难度

        Args:
            description: 任务描述文本

        Returns:
            TaskGrade 分级结果，包含级别和推荐执行参数
        """
        score = self._calc_score(description)
        detected_types = self._detect_task_types(description)
        config = self._score_to_config(score)

        return TaskGrade(
            level=config.level,
            max_steps=config.max_steps,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            reasoning_depth=config.reasoning_depth,
            description=config.description,
            score=score,
            detected_types=detected_types,
        )

    def get_execution_params(self, grade: TaskGrade) -> dict[str, Any]:
        """根据分级结果获取执行参数

        Args:
            grade: 任务分级结果

        Returns:
            包含所有执行参数的字典，可直接传递给执行引擎
        """
        return {
            "level": grade.level,
            "max_steps": grade.max_steps,
            "temperature": grade.temperature,
            "max_tokens": grade.max_tokens,
            "reasoning_depth": grade.reasoning_depth,
            "score": grade.score,
            "detected_types": grade.detected_types,
            "stop_sequences": self._get_stop_sequences(grade.level),
            "top_p": self._get_top_p(grade.level),
            "frequency_penalty": self._get_frequency_penalty(grade.level),
        }

    # ── 内部实现 ──────────────────────────────────────

    def _calc_score(self, description: str) -> int:
        """计算复杂度评分 0-100"""
        desc = description.lower()
        score = 0

        # 1. 关键词匹配
        for kw in HEAVY_KEYWORDS:
            if kw in desc:
                score += 8
        for kw in MEDIUM_KEYWORDS:
            if kw in desc:
                score += 6
        for kw in LIGHT_KEYWORDS:
            if kw in desc:
                score -= 5  # 简单关键词降低分数

        # 2. 描述长度分析
        desc_len = len(description)
        if desc_len < 50:
            score -= 3  # 很短的描述 → 简单任务
        elif desc_len < 150:
            score += 0  # 中等长度
        elif desc_len < 500:
            score += 5  # 较长描述
        else:
            score += 10  # 很长描述 → 复杂任务

        # 3. 文件数量分析
        file_pattern = re.compile(
            r"(?:文件|file|模块|module|组件|component)\s*(?:数|数量|count|\d+)|"
            r"(\d+)\s*(?:个|份|处)\s*(?:文件|file|模块|module)",
            re.IGNORECASE,
        )
        file_matches = file_pattern.findall(desc)
        # 也尝试匹配直接提到的文件数量
        file_count = 0
        for m in re.finditer(r"(\d+)\s*(?:个|份|处)\s*(?:文件|file)", desc):
            try:
                file_count = max(file_count, int(m.group(1)))
            except ValueError:
                pass

        if file_count == 1:
            score -= 5  # 单文件
        elif 2 <= file_count <= 5:
            score += 5  # 2-5 文件
        elif file_count > 5:
            score += 15  # 5+ 文件

        # 4. 任务类型基础分
        task_type_scores = {
            "bug_fix": 10,
            "feature": 15,
            "refactor": 20,
            "migration": 30,
            "architecture": 35,
        }
        for task_type, keywords in TASK_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in desc:
                    score += task_type_scores[task_type] // len(keywords)
                    break

        # 5. 项目结构线索
        if re.search(r"(?:多文件|跨文件|多模块|multi|多个|大规模|全栈)", desc):
            score += 15

        if re.search(r"(?:微服务|分布式|高并发|高可用|集群|容器)", desc):
            score += 20

        # clamp 0-100
        return max(0, min(100, score))

    def _detect_task_types(self, description: str) -> list[str]:
        """检测任务类型"""
        desc = description.lower()
        detected: list[str] = []
        for task_type, keywords in TASK_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in desc:
                    detected.append(task_type)
                    break
        return detected if detected else ["unknown"]

    def _score_to_config(self, score: int) -> TaskGradeConfig:
        """将评分映射到三个档位"""
        if score < 15:
            return LIGHT_CONFIG
        elif score < 50:
            return MEDIUM_CONFIG
        else:
            return HEAVY_CONFIG

    @staticmethod
    def _get_stop_sequences(level: str) -> list[str]:
        """根据级别返回停止序列"""
        if level == "LIGHT":
            return ["\n\n\n", "---END---"]
        elif level == "MEDIUM":
            return ["\n\n\n", "---END---", "```\n\n"]
        else:
            return ["\n\n\n", "---END---"]

    @staticmethod
    def _get_top_p(level: str) -> float:
        """根据级别返回 top_p 值"""
        if level == "LIGHT":
            return 0.95
        elif level == "MEDIUM":
            return 0.9
        else:
            return 0.85

    @staticmethod
    def _get_frequency_penalty(level: str) -> float:
        """根据级别返回频率惩罚"""
        if level == "LIGHT":
            return 0.0
        elif level == "MEDIUM":
            return 0.1
        else:
            return 0.2


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_grader_instance: TaskGrader | None = None


def get_task_grader() -> TaskGrader:
    """获取 TaskGrader 单例"""
    global _grader_instance
    if _grader_instance is None:
        _grader_instance = TaskGrader()
    return _grader_instance


# ══════════════════════════════════════════════════════════
# 能力注册
# ══════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> list[CapabilityDefinition]:
    """向 V2 能力总线注册任务分级能力

    注册的能力:
      - task.grade   — 对任务描述进行难度分级
      - task.config  — 获取指定级别的执行配置

    Args:
        registry: CapabilityRegistry 实例

    Returns:
        已注册的能力定义列表
    """
    grader = get_task_grader()

    definitions: list[CapabilityDefinition] = []

    # ── task.grade ────────────────────────────────

    async def _handle_grade(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """任务难度分级处理器"""
        description = params.get("description", "")
        if not description:
            return {"error": "缺少 description 参数", "success": False}
        grade = grader.grade(description)
        logger.info("任务分级完成: %s → %s (评分: %d)", description[:80], grade.level, grade.score)
        return grade.to_dict()

    def_grade = CapabilityDefinition(
        id="task.grade",
        name="任务难度分级",
        description="根据任务描述自动评估难度，返回 LIGHT/MEDIUM/HEAVY 三级和推荐推理参数",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="2.0.0",
        timeout_ms=5000,
        tags=["task", "grade", "difficulty", "auto"],
    )
    definitions.append(def_grade)
    registry.register(def_grade, handler=_handle_grade)

    # ── task.config ───────────────────────────────

    async def _handle_config(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """获取执行配置处理器"""
        level = params.get("level", "MEDIUM").upper()
        if level not in LEVEL_CONFIG_MAP:
            return {"error": f"无效级别: {level}，有效值为 LIGHT/MEDIUM/HEAVY", "success": False}
        config = LEVEL_CONFIG_MAP[level]
        return config.to_dict()

    def_config = CapabilityDefinition(
        id="task.config",
        name="获取分级执行配置",
        description="获取指定难度级别 (LIGHT/MEDIUM/HEAVY) 的推理执行配置",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="2.0.0",
        timeout_ms=3000,
        tags=["task", "config", "execution", "params"],
    )
    definitions.append(def_config)
    registry.register(def_config, handler=_handle_config)

    logger.info("任务分级能力已注册到 V2 总线: %d 个能力", len(definitions))
    return definitions


# ══════════════════════════════════════════════════════════
# 导出
# ══════════════════════════════════════════════════════════

__all__ = [
    "TaskGrade",
    "TaskGradeConfig",
    "TaskGrader",
    "LIGHT_CONFIG",
    "MEDIUM_CONFIG",
    "HEAVY_CONFIG",
    "LEVEL_CONFIG_MAP",
    "register_capabilities",
    "get_task_grader",
]