"""P3: 多模型路由优化 — 能力矩阵 + 任务感知路由

解决"一刀切"模型选择问题：
  - 代码任务应优先 code 专用模型（如 deepseek-coder）
  - 推理任务应优先 reasoning 能力强的模型
  - 简单对话用 fast 模型降本
  - 视觉任务必须选支持 vision 的模型

策略:
  1. ModelCapabilityMatrix — 基于 capabilities + 价格 + context_window 计算能力评分
  2. TaskClassifier — 基于规则识别任务类型（零延迟）
  3. ModelRouter — 任务感知路由，选择最佳模型

使用方式:
    from pycoder.server.services.model_router import get_model_router
    router = get_model_router()
    recommended = router.route("实现一个 FastAPI 路由")
    # recommended.model_id == "deepseek-coder"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pycoder.python.model_config import MODEL_REGISTRY, ModelInfo

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 任务类型
# ══════════════════════════════════════════════════════════

TaskType = Literal[
    "code_gen",  # 代码生成/修改
    "code_review",  # 代码审查
    "reasoning",  # 深度推理/分析
    "chat",  # 普通对话
    "vision",  # 视觉/图像
    "translation",  # 翻译
]


@dataclass
class TaskProfile:
    """任务画像"""

    task_type: TaskType = "chat"
    complexity: str = "medium"  # low | medium | high
    requires_reasoning: bool = False
    requires_code: bool = False
    requires_vision: bool = False
    estimated_tokens: int = 1000
    keywords_matched: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 任务分类器（基于规则，零延迟）
# ══════════════════════════════════════════════════════════

# 任务关键词映射
_TASK_KEYWORDS: dict[TaskType, list[str]] = {
    "vision": [
        "图片",
        "图像",
        "截图",
        "image",
        "screenshot",
        "photo",
        "看这张",
        "识别图",
    ],
    "code_gen": [
        "实现",
        "创建",
        "修改",
        "编写",
        "重构",
        "开发",
        "添加",
        "删除",
        "修复",
        "实现",
        "生成代码",
        "写一个",
        "新建文件",
        "implement",
        "create",
        "modify",
        "refactor",
        "write",
    ],
    "code_review": [
        "审查",
        "检查",
        "review",
        "code review",
        "评估代码",
        "找出问题",
        "代码质量",
        "lint",
        "audit",
    ],
    "reasoning": [
        "为什么",
        "分析",
        "设计",
        "如何",
        "原理",
        "推导",
        "权衡",
        "对比",
        "为什么",
        "决策",
        "why",
        "analyze",
        "design",
        "architecture",
    ],
    "translation": [
        "翻译",
        "translate",
        "convert to",
        "转成",
    ],
}

# 复杂度关键词
_HIGH_COMPLEXITY_KEYWORDS = [
    "完整",
    "全面",
    "系统",
    "架构",
    "pipeline",
    "端到端",
    "comprehensive",
    "full",
    "system",
]
_LOW_COMPLEXITY_KEYWORDS = [
    "简单",
    "快速",
    "一句话",
    "brief",
    "quick",
    "simple",
]


class TaskClassifier:
    """基于规则的任务分类器"""

    def classify(self, message: str) -> TaskProfile:
        """识别任务类型和复杂度"""
        if not message or not message.strip():
            return TaskProfile()

        text = message.lower()
        profile = TaskProfile()

        # 匹配关键词
        for task_type, keywords in _TASK_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text:
                    profile.keywords_matched.append(kw)
                    if task_type == "vision":
                        profile.requires_vision = True
                    elif task_type == "code_gen":
                        profile.requires_code = True
                    elif task_type == "reasoning":
                        profile.requires_reasoning = True
                    # 设置主任务类型（优先级：vision > code_gen > reasoning > review > translation）
                    priority = ["vision", "code_gen", "reasoning", "code_review", "translation"]
                    if (
                        task_type in priority
                        and priority.index(task_type) < priority.index(profile.task_type)
                        if profile.task_type != "chat"
                        else True
                    ):
                        profile.task_type = task_type
                    elif profile.task_type == "chat":
                        profile.task_type = task_type

        # 复杂度评估
        if any(kw in text for kw in _HIGH_COMPLEXITY_KEYWORDS):
            profile.complexity = "high"
        elif any(kw in text for kw in _LOW_COMPLEXITY_KEYWORDS):
            profile.complexity = "low"
        elif len(message) > 500:
            profile.complexity = "high"
        elif len(message) < 50:
            profile.complexity = "low"

        # token 估算（粗略：每 4 字符约 1 token）
        profile.estimated_tokens = max(100, len(message) // 4)

        return profile


# ══════════════════════════════════════════════════════════
# 模型能力矩阵
# ══════════════════════════════════════════════════════════


@dataclass
class ModelCapability:
    """模型能力评分（0-100）"""

    model_id: str
    provider: str
    code_score: int = 50  # 代码能力
    reasoning_score: int = 50  # 推理能力
    speed_score: int = 50  # 速度
    vision_score: int = 0  # 视觉能力
    cost_score: int = 50  # 性价比（越高越便宜）
    context_window: int = 4096
    is_recommended: bool = False


class ModelCapabilityMatrix:
    """模型能力矩阵 — 基于 ModelInfo 计算能力评分"""

    def __init__(self):
        self._capabilities: dict[str, ModelCapability] = {}
        self._build_matrix()

    def _build_matrix(self):
        """从 MODEL_REGISTRY 构建能力矩阵"""
        for _provider_id, provider_info in MODEL_REGISTRY.items():
            for model in provider_info.models:
                cap = self._score_model(model)
                self._capabilities[model.id] = cap

    def _score_model(self, model: ModelInfo) -> ModelCapability:
        """为单个模型计算能力评分"""
        caps = model.capabilities
        # 基础评分
        code_score = 50
        reasoning_score = 50
        speed_score = 50
        vision_score = 0

        # 基于 capabilities 提升
        if "code" in caps:
            code_score = 75
        if "chat" in caps:
            code_score = max(code_score, 60)
            reasoning_score = max(reasoning_score, 60)
        if "vision" in caps:
            vision_score = 90
        if "reasoning" in caps:
            reasoning_score = 90

        # 模型名启发式
        name_lower = model.id.lower()
        if "coder" in name_lower or "code" in name_lower:
            code_score = 95
        if "reasoner" in name_lower or "reason" in name_lower:
            reasoning_score = 95
        if "flash" in name_lower or "lite" in name_lower or "mini" in name_lower:
            speed_score = 90
            code_score = max(40, code_score - 15)
        if "pro" in name_lower or "max" in name_lower:
            reasoning_score = min(100, reasoning_score + 10)
            code_score = min(100, code_score + 5)

        # 价格评分（越高越便宜）— 归一化到 0-100
        # 假设 input_price 范围 0-2.0 $/M
        cost_score = max(10, min(100, int(100 - model.input_price * 50)))

        return ModelCapability(
            model_id=model.id,
            provider=model.provider,
            code_score=code_score,
            reasoning_score=reasoning_score,
            speed_score=speed_score,
            vision_score=vision_score,
            cost_score=cost_score,
            context_window=model.context_window,
            is_recommended=model.recommended,
        )

    def get(self, model_id: str) -> ModelCapability | None:
        return self._capabilities.get(model_id)

    def list_models(self) -> list[ModelCapability]:
        return list(self._capabilities.values())


# ══════════════════════════════════════════════════════════
# 模型路由器
# ══════════════════════════════════════════════════════════


@dataclass
class RouteResult:
    """路由结果"""

    model_id: str
    provider: str
    task_type: TaskType
    reason: str
    score: float = 0.0


class ModelRouter:
    """任务感知模型路由器"""

    # 任务类型 → 能力维度权重
    _TASK_WEIGHTS: dict[TaskType, dict[str, float]] = {
        "code_gen": {
            "code_score": 0.5,
            "speed_score": 0.2,
            "cost_score": 0.2,
            "reasoning_score": 0.1,
        },
        "code_review": {"code_score": 0.4, "reasoning_score": 0.4, "cost_score": 0.2},
        "reasoning": {"reasoning_score": 0.6, "code_score": 0.2, "cost_score": 0.2},
        "chat": {"speed_score": 0.4, "cost_score": 0.4, "code_score": 0.2},
        "vision": {"vision_score": 1.0},
        "translation": {"reasoning_score": 0.4, "speed_score": 0.3, "cost_score": 0.3},
    }

    def __init__(
        self,
        matrix: ModelCapabilityMatrix | None = None,
        classifier: TaskClassifier | None = None,
    ):
        self.matrix = matrix or ModelCapabilityMatrix()
        self.classifier = classifier or TaskClassifier()

    def route(self, message: str, *, prefer_model: str = "") -> RouteResult:
        """根据消息内容推荐最佳模型

        Args:
            message: 用户消息
            prefer_model: 用户显式指定的模型（优先级最高）

        Returns:
            RouteResult — 包含 model_id, provider, task_type, reason
        """
        # 用户显式指定优先
        if prefer_model:
            cap = self.matrix.get(prefer_model)
            if cap:
                return RouteResult(
                    model_id=prefer_model,
                    provider=cap.provider,
                    task_type="chat",
                    reason="用户显式指定",
                    score=100.0,
                )

        profile = self.classifier.classify(message)
        weights = self._TASK_WEIGHTS.get(profile.task_type, self._TASK_WEIGHTS["chat"])

        # 视觉任务必须选支持 vision 的模型
        if profile.requires_vision:
            vision_models = [m for m in self.matrix.list_models() if m.vision_score > 0]
            if vision_models:
                best = max(vision_models, key=lambda m: m.vision_score)
                return RouteResult(
                    model_id=best.model_id,
                    provider=best.provider,
                    task_type=profile.task_type,
                    reason="视觉任务，选择支持 vision 的模型",
                    score=best.vision_score,
                )

        # 综合评分
        best_model: ModelCapability | None = None
        best_score = -1.0
        for cap in self.matrix.list_models():
            score = self._score_model_for_task(cap, weights, profile)
            if score > best_score:
                best_score = score
                best_model = cap

        if best_model is None:
            # 回退到 deepseek-chat
            return RouteResult(
                model_id="deepseek-chat",
                provider="deepseek",
                task_type=profile.task_type,
                reason="无可用模型，回退到默认",
                score=0.0,
            )

        return RouteResult(
            model_id=best_model.model_id,
            provider=best_model.provider,
            task_type=profile.task_type,
            reason=self._explain_choice(profile.task_type, best_model),
            score=round(best_score, 1),
        )

    def _score_model_for_task(
        self,
        cap: ModelCapability,
        weights: dict[str, float],
        profile: TaskProfile,
    ) -> float:
        """计算模型对任务的匹配评分"""
        score = 0.0
        score += cap.code_score * weights.get("code_score", 0)
        score += cap.reasoning_score * weights.get("reasoning_score", 0)
        score += cap.speed_score * weights.get("speed_score", 0)
        score += cap.cost_score * weights.get("cost_score", 0)
        score += cap.vision_score * weights.get("vision_score", 0)

        # 推荐模型加分（信任人工标注）
        if cap.is_recommended:
            score += 5

        # context_window 不足惩罚
        if cap.context_window < profile.estimated_tokens * 4:
            score -= 20

        # 高复杂度任务偏好高能力模型
        if profile.complexity == "high":
            score += (cap.reasoning_score + cap.code_score) * 0.1

        return score

    def _explain_choice(self, task_type: TaskType, cap: ModelCapability) -> str:
        """生成路由原因说明"""
        reasons = {
            "code_gen": f"代码任务，选择 code_score={cap.code_score} 的模型",
            "code_review": "审查任务，选择 code+reasoning 综合评分高的模型",
            "reasoning": f"推理任务，选择 reasoning_score={cap.reasoning_score} 的模型",
            "chat": "普通对话，选择 speed+cost 综合优的模型",
            "vision": f"视觉任务，选择 vision_score={cap.vision_score} 的模型",
            "translation": "翻译任务，选择 reasoning+speed 综合优的模型",
        }
        return reasons.get(task_type, "默认路由")


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_router_instance: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """获取全局 ModelRouter 单例"""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance


__all__ = [
    "TaskType",
    "TaskProfile",
    "TaskClassifier",
    "ModelCapability",
    "ModelCapabilityMatrix",
    "RouteResult",
    "ModelRouter",
    "get_model_router",
]
