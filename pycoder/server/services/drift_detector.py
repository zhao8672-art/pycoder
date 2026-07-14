"""
DriftDetector — 任务偏离检测与自动校准

职责：
    1. 每 N 轮对话自动检测是否偏离任务目标
    2. 偏离时生成提醒锚点注入下轮 LLM 调用
    3. 支持手动触发任务回顾

工作原理：
    每次用户消息到达时，提取关键词并与任务目标做语义相似度对比。
    相似度低于阈值 → 标记为偏离 → 生成提醒文本。

用法:
    detector = DriftDetector()
    detector.set_goal("创建一个 FastAPI 用户认证系统")
    # 每轮对话
    is_drifting, warning = detector.check(message)
    if is_drifting:
        yield {"type": "drift_warning", "warning": warning}
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass
class DriftReport:
    """偏离检测报告"""

    is_drifting: bool
    similarity: float  # 0-1 与目标的语义相似度
    warning: str  # 提醒文本
    suggested_action: str  # 建议操作 (refocus/confirm_new_goal/self_correct)
    last_check_at: str  # 检查时间


class DriftDetector:
    """任务偏离检测器

    使用关键词重叠 + N-gram 相似度做轻量检测。
    不依赖 LLM（零 Token 消耗），在每次 user message 到达时执行。
    """

    def __init__(self, sensitivity: float = 0.25, check_every_n: int = 5):
        self._goal: str = ""
        self._goal_keywords: set[str] = set()
        self._sensitivity = sensitivity  # 相似度阈值，低于此值触发提醒
        self._check_every_n = check_every_n  # 每 N 轮检查一次
        self._round_count: int = 0
        self._drift_count: int = 0
        self._total_checks: int = 0
        self._last_user_messages: list[str] = []  # 最近 N 条用户消息
        self._last_check_time: float = 0.0
        self._session_start_time: float = 0.0

    def set_goal(self, goal: str) -> None:
        """设置当前任务目标"""
        self._goal = goal
        self._goal_keywords = self._extract_keywords(goal)
        self._round_count = 0
        self._drift_count = 0
        self._total_checks = 0
        self._session_start_time = time.monotonic()

    @property
    def drift_rate(self) -> float:
        """偏离率 = 偏离次数 / 总检查次数"""
        if self._total_checks == 0:
            return 0.0
        return self._drift_count / self._total_checks

    # ══════════════════════════════════════════════════════
    # 关键词提取
    # ══════════════════════════════════════════════════════

    _STOP_WORDS = {
        "的",
        "了",
        "是",
        "在",
        "和",
        "也",
        "都",
        "就",
        "但",
        "而",
        "及",
        "与",
        "或",
        "着",
        "过",
        "之",
        "从",
        "对",
        "被",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
    }

    @classmethod
    def _extract_keywords(cls, text: str) -> set[str]:
        """提取关键词（去停用词）"""
        words = re.findall(r"[\u4e00-\u9fff\w]{2,}", text.lower())
        return {w for w in words if w not in cls._STOP_WORDS}

    # ══════════════════════════════════════════════════════
    # 相似度计算
    # ══════════════════════════════════════════════════════

    def _calc_similarity(self, message: str) -> float:
        """计算消息与任务目标的关键词重叠度"""
        if not self._goal_keywords:
            return 1.0  # 无目标时不检测

        msg_keywords = self._extract_keywords(message)
        if not msg_keywords:
            return 0.5  # 空消息中性

        overlap = len(msg_keywords & self._goal_keywords)
        overlap_normalized = overlap / max(len(self._goal_keywords), 1)

        # N-gram 补充：2-gram 重叠
        goal_bigrams = self._extract_bigrams(self._goal)
        msg_bigrams = self._extract_bigrams(message)
        bigram_overlap = 0.0
        if goal_bigrams:
            common = len(msg_bigrams & goal_bigrams)
            bigram_overlap = common / max(len(goal_bigrams), 1)

        return max(overlap_normalized, bigram_overlap * 1.5)

    @staticmethod
    def _extract_bigrams(text: str) -> set[tuple]:
        """提取 2-gram 用于短语匹配"""
        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]+", text.lower())
        return {tuple(words[i : i + 2]) for i in range(len(words) - 1)}

    # ══════════════════════════════════════════════════════
    # 偏离检测
    # ══════════════════════════════════════════════════════

    def check(self, message: str) -> DriftReport:
        """检测当前消息是否偏离任务目标

        Args:
            message: 用户的当前消息

        Returns:
            DriftReport 偏离检测报告
        """
        self._round_count += 1
        self._last_user_messages.append(message)
        if len(self._last_user_messages) > self._check_every_n:
            self._last_user_messages.pop(0)

        # 只有每 check_every_n 轮才检测
        if self._round_count % self._check_every_n != 0:
            return DriftReport(
                is_drifting=False,
                similarity=1.0,
                warning="",
                suggested_action="",
                last_check_at=time.strftime("%H:%M:%S"),
            )

        self._total_checks += 1
        self._last_check_time = time.monotonic()

        # 综合最近 N 条消息计算
        combined = " ".join(self._last_user_messages)
        similarity = self._calc_similarity(combined)
        is_drifting = similarity < self._sensitivity

        if is_drifting:
            self._drift_count += 1
            warning = (
                f"⚠️ 当前对话可能偏离了任务目标「{self._goal[:80]}」\n"
                f"相似度: {similarity:.0%} (阈值: {self._sensitivity:.0%})\n"
                f"建议: 是否要回到原任务, 或确认新目标?"
            )
            action = "refocus"
        else:
            warning = ""
            action = ""

        return DriftReport(
            is_drifting=is_drifting,
            similarity=similarity,
            warning=warning,
            suggested_action=action,
            last_check_at=time.strftime("%H:%M:%S"),
        )

    # ══════════════════════════════════════════════════════
    # 任务回顾
    # ══════════════════════════════════════════════════════

    def generate_review_prompt(self) -> str:
        """生成任务回顾提示文本（注入 LLM 调用）"""
        elapsed = int(
            (time.monotonic() - self._session_start_time) if self._session_start_time > 0 else 0
        )
        lines = [
            "## 🔄 任务回顾",
            f"**原定目标**: {self._goal[:200]}",
            f"**当前轮次**: 第 {self._round_count} 轮",
            f"**已用时间**: {elapsed}s",
            f"**偏离率**: {self.drift_rate:.0%}",
        ]

        if self._drift_count > 0:
            lines.append(
                f"**⚠️ 偏离提醒**: 已检测到 {self._drift_count} 次偏离，"
                f"请确认当前方向是否仍然正确"
            )

        lines.append("请基于以上信息，输出当前任务的进展状态和下一步计划。")
        return "\n".join(lines)

    def reset(self) -> None:
        self._round_count = 0
        self._drift_count = 0
        self._total_checks = 0
        self._last_user_messages.clear()
