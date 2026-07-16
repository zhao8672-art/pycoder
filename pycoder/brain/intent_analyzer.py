"""
深度意图分析器 — 正则快速过滤 + LLM 深度理解双层架构

Layer 1 (快速通道): 正则匹配，零 Token 消耗
  - 简单问候、元问题 → 直接 chat 模式
  - 文件路径引用 → 标记为工具操作
  - 高风险操作 → 提前标记

Layer 2 (深度理解): LLM 分析，处理歧义/复杂请求
  - 技术领域识别: Python/JS/Go/Rust/DevOps/Data/AI
  - 任务类型识别: 问答/代码生成/调试/重构/架构设计/部署
  - 复杂度评估: 简单/中等/复杂
  - 歧义检测: 模糊引用、缺失信息、矛盾需求
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class IntentAnalysis:
    """意图分析结果"""

    raw_input: str
    normalized_intent: str = ""  # 标准化后的意图描述

    # 领域分类
    technical_domain: str = "general"  # python/js/go/rust/devops/data/ai/general
    task_type: str = "qa"  # qa/code_gen/debug/refactor/architect/deploy/mixed

    # 复杂度
    complexity: str = "simple"  # trivial/simple/medium/complex
    complexity_score: int = 0  # 0-100

    # 特殊性
    has_file_references: bool = False
    has_risk: bool = False
    is_ambiguous: bool = False
    ambiguity_notes: list[str] = field(default_factory=list)

    # 交互需求
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    expected_response_type: str = "text"  # text/code/diff/report/mixed

    # 元数据
    analysis_method: str = "regex"  # regex/llm/hybrid
    confidence: float = 1.0  # 分析置信度 0-1


# ══════════════════════════════════════════════════════════
# Layer 1: 快速通道 — 正则规则库
# ══════════════════════════════════════════════════════════

# 技术领域关键词
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "python": ["python", "fastapi", "django", "flask", "pydantic", "pytest", "pip", "asyncio"],
    "js": ["javascript", "typescript", "react", "vue", "node", "npm", "express", "next"],
    "go": ["golang", "go mod", "goroutine", "go test"],
    "rust": ["rust", "cargo", "tokio", "actix", "serde"],
    "devops": ["docker", "k8s", "kubernetes", "ci/cd", "nginx", "deploy", "部署"],
    "data": ["pandas", "numpy", "matplotlib", "数据", "数据分析", "sql", "机器学习"],
    "ai": ["llm", "agent", "模型", "训练", "推理", "transformer", "gpt", "claude"],
    "security": ["安全", "漏洞", "加密", "认证", "授权", "注入", "xss", "csrf"],
}

# 任务类型关键词
TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "qa": ["是什么", "解释", "什么意思", "如何理解", "区别", "对比", "什么是"],
    "code_gen": ["写", "创建", "生成", "实现", "开发", "新建", "做一个"],
    "debug": ["修复", "bug", "错误", "异常", "崩溃", "不工作", "报错", "调试"],
    "refactor": ["重构", "优化", "改进", "整理", "拆分", "重命名"],
    "architect": ["设计", "架构", "方案", "规划", "技术选型", "模块划分"],
    "deploy": ["部署", "发布", "上线", "docker", "打包", "ci", "cd"],
    "review": ["审查", "检查", "review", "审计", "评审"],
}

# 简单问候/元问题 — 直接 chat，不需要工具
TRIVIAL_PATTERNS: list[str] = [
    r"^(你好|hi|hello|hey)[\s!！。.]*$",
    r"^(谢谢|感谢|thanks|thank)[\s!！。.]*$",
    r"^(再见|bye|拜拜)[\s!！。.]*$",
    r"^(你是谁|你能做什么|你会什么|帮助|help)$",
    r"^(什么是|what is)\s+\w+\s*\?*$",
    r"^(能不能|可以吗|有没有|是否)[\s\S]{0,20}$",
]

# 高风险操作
RISK_PATTERNS: list[str] = [
    r"rm\s+-rf",
    r"删除.*系统",
    r"format\s+/",
    r"chmod\s+777",
    r"DROP\s+TABLE",
    r"DELETE\s+FROM.*WHERE",
    r"shutdown",
    r"reboot",
]

# 歧义检测
AMBIGUITY_PATTERNS: dict[str, str] = {
    r"这个|那个|它|那个文件|刚才的|上面的|下面": "含模糊代词，缺少具体对象引用",
    r"修改|修复|优化|重构": "提到修改操作但未指定目标文件",
    r"写|生成|开发|创建.*项目|搭建": "涉及开发但未指定技术栈/框架",
}


# ══════════════════════════════════════════════════════════
# IntentAnalyzer
# ══════════════════════════════════════════════════════════


class IntentAnalyzer:
    """深度意图分析器

    双层架构:
      - Layer 1: 正则快速通道 (零 Token 消耗)
      - Layer 2: LLM 深度理解 (高歧义/复杂请求)
    """

    def __init__(self, llm_provider: Any = None) -> None:
        self._llm = llm_provider

    def set_llm(self, llm_provider: Any) -> None:
        """设置 LLM 提供商（用于深度分析）"""
        self._llm = llm_provider

    def analyze(self, message: str) -> IntentAnalysis:
        """分析用户意图

        Args:
            message: 用户原始消息

        Returns:
            IntentAnalysis 分析结果
        """
        if not message or not message.strip():
            return IntentAnalysis(raw_input=message or "", complexity="trivial")

        msg = message.strip()
        analysis = IntentAnalysis(raw_input=msg)

        # Layer 1: 快速通道
        analysis = self._fast_path(msg, analysis)

        # 如果快速通道置信度高，直接返回
        if analysis.confidence >= 0.9 and not analysis.is_ambiguous:
            return analysis

        # Layer 2: 深度分析（标记为需要 LLM 分析）
        analysis.analysis_method = "hybrid"
        analysis.confidence = min(analysis.confidence, 0.7)
        return analysis

    async def analyze_deep(self, message: str) -> IntentAnalysis:
        """使用 LLM 进行深度意图分析

        仅在快速通道置信度不足时调用。
        """
        analysis = self.analyze(message)
        if analysis.confidence >= 0.9:
            return analysis

        if self._llm is None:
            return analysis

        try:
            llm_result = await self._llm_analyze(message)
            analysis = self._merge_llm_result(analysis, llm_result)
            analysis.analysis_method = "llm"
            analysis.confidence = 0.95
        except Exception as e:
            logger.warning("intent_llm_analysis_failed: %s", e)

        return analysis

    # ── Layer 1: 快速通道 ──────────────────────────

    def _fast_path(self, msg: str, analysis: IntentAnalysis) -> IntentAnalysis:
        """正则快速通道分析"""
        msg_lower = msg.lower()

        # 1. 检测简单问候/元问题
        if self._is_trivial(msg_lower):
            analysis.complexity = "trivial"
            analysis.task_type = "qa"
            analysis.expected_response_type = "text"
            analysis.confidence = 1.0
            return analysis

        # 2. 检测技术领域
        analysis.technical_domain = self._detect_domain(msg_lower)

        # 3. 检测任务类型
        analysis.task_type = self._detect_task_type(msg_lower)

        # 4. 检测文件引用
        analysis.has_file_references = bool(
            re.search(r"\.\w{1,5}\b|/\S+|\\\S+|文件|file", msg)
        )

        # 5. 检测风险
        analysis.has_risk = self._detect_risk(msg)

        # 6. 检测歧义
        analysis.ambiguity_notes = self._detect_ambiguity(msg)
        analysis.is_ambiguous = len(analysis.ambiguity_notes) > 0
        analysis.needs_clarification = len(analysis.ambiguity_notes) >= 2

        # 7. 评估复杂度
        analysis.complexity_score = self._calc_complexity_score(msg, analysis)
        analysis.complexity = self._score_to_complexity(analysis.complexity_score)

        # 8. 预期响应类型
        analysis.expected_response_type = self._infer_response_type(analysis)

        # 9. 标准化意图
        analysis.normalized_intent = self._normalize(msg, analysis)

        # 10. 置信度
        analysis.confidence = self._calc_confidence(analysis)

        return analysis

    @staticmethod
    def _is_trivial(msg_lower: str) -> bool:
        """检测是否为简单问候/元问题"""
        for pattern in TRIVIAL_PATTERNS:
            if re.match(pattern, msg_lower):
                return True
        return len(msg_lower) < 5 and "?" not in msg_lower

    @staticmethod
    def _detect_domain(msg_lower: str) -> str:
        """检测技术领域"""
        scores: dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in msg_lower)
            if score > 0:
                scores[domain] = score
        if not scores:
            return "general"
        return max(scores, key=scores.get)

    @staticmethod
    def _detect_task_type(msg_lower: str) -> str:
        """检测任务类型"""
        scores: dict[str, int] = {}
        for ttype, keywords in TASK_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in msg_lower)
            if score > 0:
                scores[ttype] = score
        if not scores:
            return "qa"
        return max(scores, key=scores.get)

    @staticmethod
    def _detect_risk(msg: str) -> bool:
        """检测高风险操作"""
        return any(re.search(p, msg) for p in RISK_PATTERNS)

    @staticmethod
    def _detect_ambiguity(msg: str) -> list[str]:
        """检测歧义"""
        notes: list[str] = []
        for pattern, note in AMBIGUITY_PATTERNS.items():
            if re.search(pattern, msg):
                notes.append(note)
        return notes

    def _calc_complexity_score(self, msg: str, analysis: IntentAnalysis) -> int:
        """计算复杂度评分 0-100"""
        score = 0
        msg_len = len(msg)

        # 长度因子
        if msg_len < 30:
            score += 5
        elif msg_len < 100:
            score += 15
        elif msg_len < 300:
            score += 30
        else:
            score += 50

        # 任务类型因子
        type_scores = {
            "qa": 5, "review": 15, "code_gen": 25,
            "debug": 30, "refactor": 35, "deploy": 40,
            "architect": 45, "mixed": 50,
        }
        score += type_scores.get(analysis.task_type, 10)

        # 文件引用因子
        if analysis.has_file_references:
            score += 10

        # 歧义扣分
        score -= len(analysis.ambiguity_notes) * 5

        return max(0, min(100, score))

    @staticmethod
    def _score_to_complexity(score: int) -> str:
        """评分映射到复杂度级别"""
        if score < 15:
            return "trivial"
        elif score < 35:
            return "simple"
        elif score < 60:
            return "medium"
        else:
            return "complex"

    @staticmethod
    def _infer_response_type(analysis: IntentAnalysis) -> str:
        """推断预期响应类型"""
        if analysis.task_type == "qa":
            return "text"
        elif analysis.task_type in ("code_gen", "refactor", "debug"):
            return "code" if analysis.has_file_references else "mixed"
        elif analysis.task_type == "review":
            return "report"
        elif analysis.task_type in ("architect", "deploy"):
            return "mixed"
        return "text"

    def _normalize(self, msg: str, analysis: IntentAnalysis) -> str:
        """标准化意图描述"""
        normalized = msg.strip()
        if analysis.technical_domain != "general" and analysis.technical_domain not in normalized.lower():
            normalized = f"[{analysis.technical_domain}] {normalized}"
        return normalized

    @staticmethod
    def _calc_confidence(analysis: IntentAnalysis) -> float:
        """计算分析置信度"""
        confidence = 0.85
        if analysis.is_ambiguous:
            confidence -= 0.15 * len(analysis.ambiguity_notes)
        if analysis.complexity == "complex":
            confidence -= 0.1
        if analysis.technical_domain == "general" and analysis.complexity != "trivial":
            confidence -= 0.05
        return max(0.3, min(1.0, confidence))

    # ── Layer 2: LLM 深度分析 ──────────────────────

    async def _llm_analyze(self, message: str) -> dict[str, Any]:
        """使用 LLM 进行深度分析"""
        if self._llm is None:
            return {}

        prompt = f"""分析以下用户请求，返回 JSON 格式的分析结果。

用户请求: {message}

请分析并返回以下 JSON:
```json
{{
  "technical_domain": "python/js/go/rust/devops/data/ai/security/general",
  "task_type": "qa/code_gen/debug/refactor/architect/deploy/review/mixed",
  "complexity": "trivial/simple/medium/complex",
  "complexity_score": 0-100,
  "has_file_references": true/false,
  "has_risk": true/false,
  "is_ambiguous": true/false,
  "needs_clarification": true/false,
  "clarification_questions": ["问题1", "问题2"],
  "expected_response_type": "text/code/diff/report/mixed",
  "normalized_intent": "标准化后的意图描述"
}}
```
只返回 JSON，不要其他文字。"""
        try:
            response = await self._llm.generate(prompt=prompt, max_tokens=1024)
            import json
            content = response.content if hasattr(response, "content") else str(response)
            # 提取 JSON
            first = content.find("{")
            last = content.rfind("}")
            if first >= 0 and last > first:
                return json.loads(content[first:last + 1])
        except Exception as e:
            logger.debug("llm_analyze_parse_failed: %s", e)
        return {}

    def _merge_llm_result(self, analysis: IntentAnalysis, llm_result: dict[str, Any]) -> IntentAnalysis:
        """合并 LLM 分析结果"""
        if not llm_result:
            return analysis

        if "technical_domain" in llm_result:
            analysis.technical_domain = llm_result["technical_domain"]
        if "task_type" in llm_result:
            analysis.task_type = llm_result["task_type"]
        if "complexity" in llm_result:
            analysis.complexity = llm_result["complexity"]
        if "complexity_score" in llm_result:
            analysis.complexity_score = llm_result["complexity_score"]
        if "has_file_references" in llm_result:
            analysis.has_file_references = llm_result["has_file_references"]
        if "has_risk" in llm_result:
            analysis.has_risk = llm_result["has_risk"]
        if "is_ambiguous" in llm_result:
            analysis.is_ambiguous = llm_result["is_ambiguous"]
        if "needs_clarification" in llm_result:
            analysis.needs_clarification = llm_result["needs_clarification"]
        if "clarification_questions" in llm_result:
            analysis.clarification_questions = llm_result["clarification_questions"]
        if "expected_response_type" in llm_result:
            analysis.expected_response_type = llm_result["expected_response_type"]
        if "normalized_intent" in llm_result:
            analysis.normalized_intent = llm_result["normalized_intent"]

        return analysis


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_analyzer_instance: IntentAnalyzer | None = None


def get_intent_analyzer() -> IntentAnalyzer:
    """获取全局意图分析器"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = IntentAnalyzer()
    return _analyzer_instance