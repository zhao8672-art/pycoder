"""
模型路由器 — 借鉴 Hermes 模型路由体系

根据任务复杂度自动选择模型层级:
  - premium: 深度推理任务（架构设计、复杂分析）
  - standard: 标准编码任务（代码生成、快速响应）
  - economy: 经济层任务（模式匹配、调度、测试、文档）
  - vision: 多模态任务（页面视觉、创意制作）
  - local: 本地兜底（所有 API 不可用时）

模型分配:
  | 层级 | 模型 | 用途 |
  | premium | deepseek-v4-pro | 架构设计/复杂分析 |
  | standard | deepseek-v4-flash | 标准编码/快速响应 |
  | economy | glm-4.7-flash | 调度/测试/质检/文档 |
  | vision | glm-4v-flash | 多模态/页面视觉 |
  | local | ollama/qwen3.5 | 本地兜底 |

用法:
  from pycoder.brain.model_router import ModelRouter, ModelTier

  router = ModelRouter()
  tier = router.resolve("实现一个用户认证系统")
  print(f"使用模型: {tier.model}, 层级: {tier.tier}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pycoder.server.services.task_grader import TaskGrader, GradeLevel, get_task_grader

logger = logging.getLogger(__name__)


class ModelTier(StrEnum):
    """模型层级"""
    PREMIUM = "premium"      # 深度推理
    STANDARD = "standard"    # 标准编码
    ECONOMY = "economy"      # 经济层
    VISION = "vision"        # 多模态
    LOCAL = "local"          # 本地兜底


@dataclass
class ModelRoute:
    """模型路由结果"""
    tier: ModelTier
    model: str
    fallback: str
    temperature: float = 0.2
    max_tokens: int = 8192
    thinking_enabled: bool = False
    stream: bool = True
    cost_per_1k_tokens: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "model": self.model,
            "fallback": self.fallback,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "thinking_enabled": self.thinking_enabled,
            "stream": self.stream,
            "cost_per_1k": self.cost_per_1k_tokens,
        }


class ModelRouter:
    """模型路由器

    根据任务难度自动选择最优模型层级，平衡成本与质量。

    路由规则:
      - LIGHT 难度 → economy 层 (快速响应，低成本)
      - MEDIUM 难度 → standard 层 (标准编码)
      - HEAVY 难度 → premium 层 (深度推理)
      - 多模态任务 → vision 层
      - API 不可用 → local 层 (兜底)
    """

    # 模型配置表
    MODELS: dict[ModelTier, ModelRoute] = {
        ModelTier.PREMIUM: ModelRoute(
            tier=ModelTier.PREMIUM,
            model="deepseek/deepseek-v4-pro",
            fallback="deepseek/deepseek-v4-flash",
            temperature=0.15,
            max_tokens=16384,
            thinking_enabled=True,
            stream=True,
            cost_per_1k_tokens=0.002,
        ),
        ModelTier.STANDARD: ModelRoute(
            tier=ModelTier.STANDARD,
            model="deepseek/deepseek-v4-flash",
            fallback="bigmodel/glm-4.7-flash",
            temperature=0.2,
            max_tokens=8192,
            thinking_enabled=False,
            stream=True,
            cost_per_1k_tokens=0.0005,
        ),
        ModelTier.ECONOMY: ModelRoute(
            tier=ModelTier.ECONOMY,
            model="bigmodel/glm-4.7-flash",
            fallback="deepseek/deepseek-v4-flash",
            temperature=0.25,
            max_tokens=4096,
            thinking_enabled=False,
            stream=True,
            cost_per_1k_tokens=0.0001,
        ),
        ModelTier.VISION: ModelRoute(
            tier=ModelTier.VISION,
            model="bigmodel/glm-4v-flash",
            fallback="deepseek/deepseek-v4-flash",
            temperature=0.3,
            max_tokens=4096,
            thinking_enabled=False,
            stream=True,
            cost_per_1k_tokens=0.0003,
        ),
        ModelTier.LOCAL: ModelRoute(
            tier=ModelTier.LOCAL,
            model="ollama/qwen3.5:9b",
            fallback="",
            temperature=0.3,
            max_tokens=2048,
            thinking_enabled=False,
            stream=False,
            cost_per_1k_tokens=0.0,
        ),
    }

    # 难度 → 模型层级映射
    GRADE_TO_TIER: dict[GradeLevel, ModelTier] = {
        GradeLevel.LIGHT: ModelTier.ECONOMY,
        GradeLevel.MEDIUM: ModelTier.STANDARD,
        GradeLevel.HEAVY: ModelTier.PREMIUM,
    }

    # Agent 角色 → 模型层级映射
    AGENT_TIER_MAP: dict[str, ModelTier] = {
        "architect": ModelTier.PREMIUM,
        "orchestrator": ModelTier.STANDARD,
        "developer": ModelTier.STANDARD,
        "devops": ModelTier.STANDARD,
        "evolutionist": ModelTier.PREMIUM,
        "security": ModelTier.STANDARD,
        "debugger": ModelTier.STANDARD,
        "optimizer": ModelTier.STANDARD,
        "tester": ModelTier.ECONOMY,
        "reviewer": ModelTier.ECONOMY,
        "documenter": ModelTier.ECONOMY,
    }

    # 多模态关键词
    VISION_KEYWORDS: list[str] = [
        "图片", "截图", "图像", "照片", "视频", "界面",
        "ui", "视觉", "页面设计", "样式", "前端组件",
        "image", "screenshot", "photo", "video", "visual",
    ]

    def __init__(self):
        self._grader = get_task_grader()
        self._routing_stats: dict[str, int] = {
            tier.value: 0 for tier in ModelTier
        }

    def resolve(
        self,
        task: str,
        agent_role: str = "",
        context: dict[str, Any] | None = None,
    ) -> ModelRoute:
        """解析任务，返回最优模型路由

        Args:
            task: 任务描述
            agent_role: Agent 角色（可选）
            context: 额外上下文

        Returns:
            ModelRoute 路由结果
        """
        ctx = context or {}

        # 1. 检查是否多模态任务
        if self._is_vision_task(task, ctx):
            route = self._clone_route(ModelTier.VISION)
            self._routing_stats["vision"] += 1
            return route

        # 2. 根据 Agent 角色确定层级
        if agent_role and agent_role in self.AGENT_TIER_MAP:
            tier = self.AGENT_TIER_MAP[agent_role]
            route = self._clone_route(tier)
            self._routing_stats[tier.value] += 1
            logger.debug("按角色路由: %s → %s", agent_role, tier.value)
            return route

        # 3. 根据任务难度确定层级
        grade = self._grader.assess(task, ctx)
        tier = self.GRADE_TO_TIER.get(grade.level, ModelTier.STANDARD)
        route = self._clone_route(tier)

        # 根据难度调整参数
        if grade.level == GradeLevel.HEAVY:
            route.temperature = 0.15
            route.max_tokens = 16384
            route.thinking_enabled = True
        elif grade.level == GradeLevel.LIGHT:
            route.temperature = 0.3
            route.max_tokens = 2048

        self._routing_stats[tier.value] += 1
        logger.debug(
            "按难度路由: %s (评分 %.1f) → %s",
            grade.level.name, grade.score, tier.value,
        )
        return route

    def resolve_for_agent(self, agent_role: str) -> ModelRoute:
        """为指定 Agent 角色解析模型

        Args:
            agent_role: Agent 角色名

        Returns:
            ModelRoute 路由结果
        """
        tier = self.AGENT_TIER_MAP.get(
            agent_role.lower(), ModelTier.STANDARD
        )
        return self._clone_route(tier)

    def get_fallback(self, tier: ModelTier) -> ModelRoute | None:
        """获取指定层级的回退模型"""
        route = self.MODELS.get(tier)
        if route and route.fallback:
            for t in ModelTier:
                if self.MODELS[t].model == route.fallback:
                    return self._clone_route(t)
        return None

    def get_local_fallback(self) -> ModelRoute:
        """获取本地兜底模型"""
        return self._clone_route(ModelTier.LOCAL)

    def get_stats(self) -> dict[str, Any]:
        """获取路由统计"""
        total = sum(self._routing_stats.values())
        return {
            "routing_counts": dict(self._routing_stats),
            "total_routes": total,
            "distribution": {
                tier: count / max(total, 1)
                for tier, count in self._routing_stats.items()
            },
            "available_tiers": [t.value for t in ModelTier],
        }

    def _is_vision_task(self, task: str, ctx: dict[str, Any]) -> bool:
        """判断是否为多模态任务"""
        task_lower = task.lower()

        # 显式标记
        if ctx.get("multimodal") or ctx.get("vision"):
            return True

        # 关键词匹配
        for kw in self.VISION_KEYWORDS:
            if kw in task_lower:
                return True

        return False

    def _clone_route(self, tier: ModelTier) -> ModelRoute:
        """克隆路由配置（避免修改原始配置）"""
        original = self.MODELS[tier]
        return ModelRoute(
            tier=original.tier,
            model=original.model,
            fallback=original.fallback,
            temperature=original.temperature,
            max_tokens=original.max_tokens,
            thinking_enabled=original.thinking_enabled,
            stream=original.stream,
            cost_per_1k_tokens=original.cost_per_1k_tokens,
        )


# 全局单例
_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """获取全局模型路由器"""
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter()
    return _model_router