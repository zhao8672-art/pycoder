"""P2-3: 反馈应用器 — 将历史学习成果注入新任务上下文

将 ExperienceBuffer 中的历史失败经验转化为可直接拼入 LLM prompt 的字符串，
让 Agent 在执行新任务时"看到"过去的失败教训，避免重复犯错。

核心机制:
  1. 文本相似度匹配 — Jaccard 系数找相似的历史失败
  2. 上下文构建 — 将失败原因/文件/修复方案格式化为 Markdown 片段
  3. 长度受限 — 上下文上限 800 字符，避免 prompt 膨胀（与 P2-2 限制协调）

复用现有实现:
  - ExperienceBuffer.get_failures()  — 已持久化的失败经验查询
  - KnowledgeBase.suggest_fix()       — 已有的修复模式推荐

用法:
  from .feedback_applier import get_feedback_applier

  applier = get_feedback_applier()
  ctx = applier.build_context_for_task("fix", "修复登录页面 bug")
  if ctx:
      prompt = f"{ctx}\n\n{original_prompt}"
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 相似度阈值 — 低于此值视为不相关，不注入
SIMILARITY_THRESHOLD = 0.2
# 上下文字符上限 — 避免 prompt 膨胀
MAX_CONTEXT_LENGTH = 800
# 查询失败经验时的扫描窗口
FAILURE_SCAN_LIMIT = 50


class FeedbackApplier:
    """将历史学习成果应用于新任务 — 构建 prompt 注入上下文"""

    def __init__(self, experience_buffer: Any, knowledge_base: Any | None = None) -> None:
        self.buffer = experience_buffer
        self.kb = knowledge_base

    def get_similar_failures(
        self,
        task_type: str,
        description: str,
        limit: int = 5,
    ) -> list:
        """获取与当前任务描述相似的历史失败经验

        Args:
            task_type: 任务类型（fix/optimize/pipeline 等，目前仅作记录用）
            description: 当前任务描述
            limit: 返回的最大条数

        Returns:
            相似度 > SIMILARITY_THRESHOLD 的失败经验列表，按相似度降序
        """
        try:
            failures = self.buffer.get_failures(limit=FAILURE_SCAN_LIMIT)
        except Exception as e:
            logger.warning("feedback_get_failures_failed error=%s", e)
            return []

        if not failures:
            return []

        scored = [
            (exp, self._text_similarity(getattr(exp, "description", ""), description))
            for exp in failures
        ]
        scored.sort(key=lambda x: -x[1])
        return [exp for exp, sim in scored if sim > SIMILARITY_THRESHOLD][:limit]

    def build_context_for_task(self, task_type: str, description: str) -> str:
        """为新任务构建学习上下文字符串

        仅当存在相似历史失败时返回非空字符串，否则返回 ""（避免注入噪声）。

        Returns:
            可直接拼入 prompt 的 Markdown 字符串，或空串
        """
        failures = self.get_similar_failures(task_type, description, limit=3)
        if not failures:
            return ""

        lines = ["## 历史失败教训（避免重复犯错）"]
        for exp in failures:
            reason = (
                getattr(exp, "error_message", "") or getattr(exp, "description", "") or "未知原因"
            )
            files = getattr(exp, "file_paths", []) or []
            file_info = f" | 文件: {', '.join(files[:2])}" if files else ""
            # 单条教训一行，避免过长
            lesson = f"- 失败原因: {reason[:120]}{file_info}"
            lines.append(lesson)

        context = "\n".join(lines)
        if len(context) > MAX_CONTEXT_LENGTH:
            context = context[: MAX_CONTEXT_LENGTH - 3] + "..."
        return context

    def _text_similarity(self, a: str, b: str) -> float:
        """Jaccard 系数 — 词集合交集 / 并集

        空字符串返回 0.0。中文按字符分词（避免中文无空格导致相似度恒为 0）。
        """
        if not a or not b:
            return 0.0
        # 中文为主时按字符切分；英文词也可作为字符处理
        set_a = set(a.lower())
        set_b = set(b.lower())
        union = set_a | set_b
        if not union:
            return 0.0
        return len(set_a & set_b) / len(union)


# ══════════════════════════════════════════════════════════
# 全局单例 — 复用 LearningEngine 的 buffer / kb
# ══════════════════════════════════════════════════════════

_applier: FeedbackApplier | None = None


def get_feedback_applier() -> FeedbackApplier:
    """获取全局 FeedbackApplier 单例

    延迟初始化以避免循环导入。复用 get_learning_engine() 已初始化的
    ExperienceBuffer 和 KnowledgeBase 实例。
    """
    global _applier
    if _applier is None:
        from . import get_learning_engine

        engine = get_learning_engine()
        _applier = FeedbackApplier(
            experience_buffer=engine.buffer,
            knowledge_base=engine.kb,
        )
    return _applier


def reset_feedback_applier() -> None:
    """重置单例（测试用）"""
    global _applier
    _applier = None


__all__ = [
    "FeedbackApplier",
    "SIMILARITY_THRESHOLD",
    "MAX_CONTEXT_LENGTH",
    "get_feedback_applier",
    "reset_feedback_applier",
]
