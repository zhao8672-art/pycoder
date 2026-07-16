"""
智能 Agent 选择器 — 基于语义理解的 Agent 匹配

替代现有的关键词匹配方案，通过多维评分实现精准 Agent 选择。

决策维度:
  - 技术领域匹配 (30%): Agent 擅长的技术栈是否匹配
  - 任务类型匹配 (25%): Agent 角色是否适合当前任务类型
  - 复杂度匹配 (20%): Agent 能力是否能处理该复杂度
  - 历史成功率 (15%): 同类任务中该 Agent 的历史表现
  - 响应速度要求 (10%): 用户是否期望快速响应
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from pycoder.brain.intent_analyzer import IntentAnalysis

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class AgentSelection:
    """Agent 选择结果"""

    primary_agent: str  # 主 Agent ID (none 表示无需 Agent)
    secondary_agents: list[str] = field(default_factory=list)
    selection_reason: str = ""
    confidence: float = 0.0
    model_tier: str = "standard"  # premium/standard/economy
    estimated_tokens: int = 0
    selection_method: str = "rule"  # rule/llm/hybrid


# ══════════════════════════════════════════════════════════
# Agent 能力矩阵
# ══════════════════════════════════════════════════════════

# 每个 Agent 的领域/任务类型/复杂度适配
AGENT_CAPABILITY_MATRIX: dict[str, dict] = {
    "none": {
        "name": "直接回答",
        "description": "无需 Agent 介入，直接 LLM 回答",
        "domains": ["general"],
        "task_types": ["qa"],
        "complexity_range": (0, 15),
        "model_tier": "economy",
        "suitable_for": "简单问答、解释概念、对比分析",
    },
    "developer": {
        "name": "开发工程师",
        "description": "编写高质量代码实现",
        "domains": ["python", "js", "go", "rust", "general"],
        "task_types": ["code_gen", "refactor"],
        "complexity_range": (10, 60),
        "model_tier": "standard",
        "suitable_for": "代码生成、功能实现、API 开发",
    },
    "debugger": {
        "name": "调试专家",
        "description": "深度定位和修复复杂 Bug，进行根因分析",
        "domains": ["python", "js", "go", "rust", "general"],
        "task_types": ["debug"],
        "complexity_range": (25, 80),
        "model_tier": "premium",
        "suitable_for": "复杂 Bug 修复、根因分析、异常排查、性能问题",
    },
    "fixer": {
        "name": "缺陷修复师",
        "description": "快速精准修复已知缺陷，最小化改动",
        "domains": ["python", "js", "go", "rust"],
        "task_types": ["debug", "refactor"],
        "complexity_range": (10, 40),
        "model_tier": "standard",
        "suitable_for": "精准补丁、已知错误修复、小范围重构",
    },
    "architect": {
        "name": "架构师",
        "description": "设计系统架构和技术方案",
        "domains": ["python", "js", "go", "rust", "devops", "general"],
        "task_types": ["architect", "refactor"],
        "complexity_range": (30, 100),
        "model_tier": "premium",
        "suitable_for": "架构设计、技术选型、模块划分",
    },
    "reviewer": {
        "name": "代码审查员",
        "description": "审查代码质量",
        "domains": ["python", "js", "go", "rust", "general"],
        "task_types": ["review"],
        "complexity_range": (10, 50),
        "model_tier": "standard",
        "suitable_for": "代码审查、质量检查",
    },
    "qa": {
        "name": "质量保证",
        "description": "测试和质量保证",
        "domains": ["python", "js", "go", "rust"],
        "task_types": ["review"],
        "complexity_range": (15, 60),
        "model_tier": "standard",
        "suitable_for": "测试用例、代码审查、质量评分",
    },
    "security": {
        "name": "安全专家",
        "description": "安全审计和加固",
        "domains": ["security", "python", "js"],
        "task_types": ["review", "debug"],
        "complexity_range": (20, 80),
        "model_tier": "premium",
        "suitable_for": "安全审计、漏洞修复、权限检查",
    },
    "devops": {
        "name": "运维工程师",
        "description": "部署和 CI/CD",
        "domains": ["devops", "python", "js"],
        "task_types": ["deploy"],
        "complexity_range": (15, 70),
        "model_tier": "standard",
        "suitable_for": "Docker 化、CI/CD 配置、部署脚本",
    },
    "documenter": {
        "name": "文档工程师",
        "description": "编写文档和注释",
        "domains": ["general"],
        "task_types": ["qa"],
        "complexity_range": (0, 30),
        "model_tier": "economy",
        "suitable_for": "文档生成、注释补全、README 编写",
    },
    "optimizer": {
        "name": "性能优化师",
        "description": "性能分析和优化",
        "domains": ["python", "js", "go", "rust"],
        "task_types": ["refactor", "debug"],
        "complexity_range": (25, 80),
        "model_tier": "premium",
        "suitable_for": "性能分析、内存优化、并发优化",
    },
    "orchestrator": {
        "name": "团队协调者",
        "description": "多 Agent 团队协调",
        "domains": ["general"],
        "task_types": ["architect", "mixed"],
        "complexity_range": (50, 100),
        "model_tier": "premium",
        "suitable_for": "复杂工程、多模块开发、全栈项目",
    },
}


# ══════════════════════════════════════════════════════════
# AgentSelector
# ══════════════════════════════════════════════════════════


class AgentSelector:
    """智能 Agent 选择器

    根据意图分析结果，通过多维评分选择最合适的 Agent。
    支持 FeedbackLoop 自适应权重，持续优化选择准确性。
    """

    def __init__(self, adaptive_weights: dict | None = None) -> None:
        self._success_history: dict[str, dict[str, int]] = {}  # agent_id -> {total, success}
        self._success_lock = threading.Lock()
        self._capability_matrix = AGENT_CAPABILITY_MATRIX

        # 自适应权重（可从 FeedbackLoop 注入）
        if adaptive_weights:
            self._weight_domain = adaptive_weights.get("domain", 0.30)
            self._weight_task_type = adaptive_weights.get("task_type", 0.25)
            self._weight_complexity = adaptive_weights.get("complexity", 0.20)
            self._weight_history = adaptive_weights.get("history", 0.15)
            self._weight_speed = adaptive_weights.get("speed", 0.10)
        else:
            self._weight_domain = 0.30
            self._weight_task_type = 0.25
            self._weight_complexity = 0.20
            self._weight_history = 0.15
            self._weight_speed = 0.10

    def set_adaptive_weights(self, weights: dict) -> None:
        """设置自适应权重（从 FeedbackLoop 获取）

        Args:
            weights: 包含 domain/task_type/complexity/history/speed 的权重字典
        """
        self._weight_domain = weights.get("domain", self._weight_domain)
        self._weight_task_type = weights.get("task_type", self._weight_task_type)
        self._weight_complexity = weights.get("complexity", self._weight_complexity)
        self._weight_history = weights.get("history", self._weight_history)
        self._weight_speed = weights.get("speed", self._weight_speed)

    def get_adaptive_weights(self) -> dict[str, float]:
        """获取当前自适应权重"""
        return {
            "domain": self._weight_domain,
            "task_type": self._weight_task_type,
            "complexity": self._weight_complexity,
            "history": self._weight_history,
            "speed": self._weight_speed,
        }

    def select(self, intent: IntentAnalysis) -> AgentSelection:
        """根据意图分析结果选择 Agent

        Args:
            intent: 意图分析结果

        Returns:
            AgentSelection 选择结果
        """
        # 简单问候/元问题 → 无需 Agent
        if intent.complexity == "trivial" and intent.task_type == "qa":
            return AgentSelection(
                primary_agent="none",
                selection_reason="简单问答，无需 Agent 介入",
                confidence=1.0,
                model_tier="economy",
                estimated_tokens=500,
                selection_method="rule",
            )

        # 需要追问用户 → 无需 Agent
        if intent.needs_clarification:
            return AgentSelection(
                primary_agent="none",
                selection_reason="需要先澄清用户意图",
                confidence=0.9,
                model_tier="economy",
                estimated_tokens=300,
                selection_method="rule",
            )

        # 多维评分选择
        scored = self._score_agents(intent)
        if not scored:
            return AgentSelection(
                primary_agent="developer",
                selection_reason="无匹配 Agent，使用默认开发者",
                confidence=0.5,
                model_tier="standard",
                estimated_tokens=2000,
                selection_method="rule",
            )

        best = scored[0]
        primary = best[0]
        primary_score = best[1]["total"]

        # 辅助 Agent (得分 > 60% 的其他 Agent)
        threshold = primary_score * 0.6
        secondaries = [
            agent_id
            for agent_id, scores in scored[1:]
            if scores["total"] >= threshold
        ][:2]  # 最多 2 个辅助

        return AgentSelection(
            primary_agent=primary,
            secondary_agents=secondaries,
            selection_reason=best[1]["reason"],
            confidence=min(0.95, primary_score / 100),
            model_tier=AGENT_CAPABILITY_MATRIX.get(primary, {}).get("model_tier", "standard"),
            estimated_tokens=self._estimate_tokens(intent, primary),
            selection_method="rule",
        )

    def _score_agents(self, intent: IntentAnalysis) -> list[tuple[str, dict]]:
        """对每个 Agent 进行多维评分"""
        results: list[tuple[str, dict]] = []

        for agent_id, capability in self._capability_matrix.items():
            if agent_id == "none":
                continue

            scores = self._calculate_scores(intent, agent_id, capability)
            total = (
                scores["domain"] * self._weight_domain
                + scores["task_type"] * self._weight_task_type
                + scores["complexity"] * self._weight_complexity
                + scores["history"] * self._weight_history
                + scores["speed"] * self._weight_speed
            )
            scores["total"] = total
            scores["reason"] = self._build_reason(intent, agent_id, capability, scores)

            results.append((agent_id, scores))

        # 按总分降序排列
        results.sort(key=lambda x: x[1]["total"], reverse=True)
        return results

    def _calculate_scores(self, intent: IntentAnalysis, agent_id: str, capability: dict) -> dict[str, float]:
        """计算各维度得分"""
        scores: dict[str, float] = {}

        # 1. 技术领域匹配 (0-100)
        domain_match = 0
        if intent.technical_domain in capability.get("domains", []):
            domain_match = 100
        elif "general" in capability.get("domains", []):
            domain_match = 50
        scores["domain"] = domain_match

        # 2. 任务类型匹配 (0-100)
        task_match = 0
        if intent.task_type in capability.get("task_types", []):
            task_match = 100
        elif "mixed" in capability.get("task_types", []):
            task_match = 60
        scores["task_type"] = task_match

        # 3. 复杂度匹配 (0-100)
        complexity_range = capability.get("complexity_range", (0, 100))
        if complexity_range[0] <= intent.complexity_score <= complexity_range[1]:
            # 在范围内，越接近中心得分越高
            center = (complexity_range[0] + complexity_range[1]) / 2
            distance = abs(intent.complexity_score - center)
            range_size = (complexity_range[1] - complexity_range[0]) / 2
            scores["complexity"] = max(20, 100 - (distance / max(range_size, 1)) * 80)
        else:
            # 超出范围，根据偏离程度扣分
            if intent.complexity_score < complexity_range[0]:
                distance = complexity_range[0] - intent.complexity_score
            else:
                distance = intent.complexity_score - complexity_range[1]
            scores["complexity"] = max(5, 40 - distance * 2)

        # 4. 历史成功率 (0-100)
        scores["history"] = self._get_history_score(agent_id, intent)

        # 5. 响应速度 (0-100)
        speed_scores = {"premium": 60, "standard": 85, "economy": 100}
        scores["speed"] = speed_scores.get(capability.get("model_tier", "standard"), 70)

        return scores

    def _get_history_score(self, agent_id: str, intent: IntentAnalysis) -> float:
        """获取历史成功率得分（线程安全）"""
        with self._success_lock:
            history = self._success_history.get(agent_id)
            if not history or history.get("total", 0) < 3:
                return 50  # 无足够数据，默认中等
            total = history["total"]
            success = history["success"]
            return (success / total) * 100

    def _build_reason(self, intent: IntentAnalysis, agent_id: str, capability: dict, scores: dict) -> str:
        """构建选择理由"""
        parts = []
        agent_name = capability.get("name", agent_id)

        if scores["domain"] >= 80:
            parts.append(f"技术领域匹配({intent.technical_domain})")
        if scores["task_type"] >= 80:
            parts.append(f"任务类型匹配({intent.task_type})")
        if scores["complexity"] >= 70:
            parts.append("复杂度匹配")

        if not parts:
            parts.append("综合评分最高")

        return f"{agent_name}: {' + '.join(parts)}"

    def _estimate_tokens(self, intent: IntentAnalysis, agent_id: str) -> int:
        """估算 Token 消耗"""
        base = 500
        per_complexity = intent.complexity_score * 30
        tier_multiplier = {"premium": 2.0, "standard": 1.0, "economy": 0.5}
        multiplier = tier_multiplier.get(
            self._capability_matrix.get(agent_id, {}).get("model_tier", "standard"), 1.0
        )
        return int((base + per_complexity) * multiplier)

    def record_result(self, agent_id: str, success: bool) -> None:
        """记录 Agent 执行结果，用于历史成功率计算（线程安全）"""
        with self._success_lock:
            if agent_id not in self._success_history:
                self._success_history[agent_id] = {"total": 0, "success": 0}
            self._success_history[agent_id]["total"] += 1
            if success:
                self._success_history[agent_id]["success"] += 1

    def get_agent_info(self, agent_id: str) -> dict | None:
        """获取 Agent 能力信息"""
        return self._capability_matrix.get(agent_id)

    def list_agents(self) -> list[dict]:
        """列出所有可用 Agent"""
        return [
            {"id": agent_id, "name": cap["name"], "description": cap["description"],
             "suitable_for": cap.get("suitable_for", "")}
            for agent_id, cap in self._capability_matrix.items()
            if agent_id != "none"
        ]

    def register_agent(self, agent_id: str, capability: dict) -> None:
        """注册新的 Agent（可扩展性）"""
        self._capability_matrix[agent_id] = capability
        logger.info("agent_registered: %s", agent_id)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_selector_instance: AgentSelector | None = None


def get_agent_selector() -> AgentSelector:
    """获取全局 Agent 选择器"""
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = AgentSelector()
    return _selector_instance