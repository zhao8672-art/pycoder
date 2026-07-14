"""
ContextManager — 智能上下文窗口管理器

职责：
    1. 滑窗管理：根据消息重要性评分智能保留/淘汰历史消息
    2. 上下文摘要：自动提取对话中的关键决策点和里程碑
    3. 链接算法：建立当前对话与历史消息的逻辑关联

与 chat_bridge._get_effective_messages 的集成：
    替换简单的 max_history_messages 截断，采用基于重要性的加权保留。
    保留 token 预算内的尽可能多的关键消息。

用法:
    ctx_mgr = ContextManager(max_context_tokens=8000)
    ctx_mgr.add_message(msg)  # 每次 LLM 调用后追加
    effective, summary = ctx_mgr.get_window_messages()
    bridge._messages = effective  # 注入到 ChatBridge
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass
class ContextScore:
    """消息重要性评分"""
    score: float = 0.0           # 0-1 综合重要性
    is_decision: bool = False    # 是否关键决策
    is_milestone: bool = False   # 是否阶段里程碑
    is_file_ref: bool = False    # 是否包含文件引用
    is_error: bool = False       # 是否错误信息
    tokens: int = 0              # 估算 token 数


class ContextWindowManager:
    """智能上下文窗口管理器

    核心算法：
        1. 消息加入时自动评分
        2. 超出 token 预算时，按重要性评分从低到高淘汰
        3. 始终保留关键决策和里程碑消息
        4. 淘汰的消息压缩为结构化摘要注入窗口头部
    """

    def __init__(self, max_context_tokens: int = 8000):
        self._max_tokens = max_context_tokens
        self._messages: list[dict] = []
        self._scores: dict[int, ContextScore] = {}  # index → score
        self._summary_lines: list[str] = []
        self._decision_log: list[str] = []
        self._milestones: list[str] = []
        self._last_summary_index: int = 0
        self._total_messages_seen: int = 0

    # ══════════════════════════════════════════════════════
    # 评分规则
    # ══════════════════════════════════════════════════════

    _DECISION_KEYWORDS = re.compile(
        r"决定|采用|选择|方案|架构|设计|确认|确定|最终|不再|改为|"
        r"decide|choose|select|final|confirm|agreed|switch|采用",
        re.IGNORECASE,
    )
    _MILESTONE_KEYWORDS = re.compile(
        r"完成|通过|成功|创建了|已实现|生成|安装|部署|启动|测试通过|"
        r"done|pass|success|created|generated|deployed|deploy",
        re.IGNORECASE,
    )
    _FILE_PATTERN = re.compile(r"(`[^`]+\.(py|ts|js|json|yml|yaml|toml|md|html|css)`)")
    _ERROR_KEYWORDS = re.compile(
        r"error|错误|exception|异常|traceback|失败|fail|timeout|超时",
        re.IGNORECASE,
    )

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略估算 token 数 (中文 1字≈1token, 英文 1词≈1.3token)"""
        chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
        words = len(re.findall(r"[a-zA-Z]+", text))
        digits = len(re.findall(r"\d+", text))
        return chinese + int(words * 1.3) + digits + int(len(text) * 0.05)

    def _score_message(self, msg: dict) -> ContextScore:
        """对单条消息计算重要性评分"""
        content = str(msg.get("content", ""))
        role = str(msg.get("role", "user"))

        score = ContextScore(tokens=self.estimate_tokens(content))
        base_score = 0.3

        # 用户消息基础分更高
        if role == "user":
            base_score += 0.15

        # 包含关键决策 → +0.3
        if self._DECISION_KEYWORDS.search(content):
            base_score += 0.3
            score.is_decision = True

        # 包含里程碑标记 → +0.25
        if self._MILESTONE_KEYWORDS.search(content):
            base_score += 0.25
            score.is_milestone = True

        # 包含文件引用 → +0.15
        if self._FILE_PATTERN.search(content):
            base_score += 0.15
            score.is_file_ref = True

        # 错误信息 → +0.2 (错误很重要，不能丢)
        if self._ERROR_KEYWORDS.search(content):
            base_score += 0.2
            score.is_error = True

        # 包含代码块 → +0.1
        if "```" in content:
            base_score += 0.1

        # 较长的消息 → +0.05 (可能是详细分析)
        if self.estimate_tokens(content) > 200:
            base_score += 0.05

        score.score = min(base_score, 1.0)
        return score

    # ══════════════════════════════════════════════════════
    # 消息管理
    # ══════════════════════════════════════════════════════

    def add_message(self, msg: dict) -> None:
        """追加一条消息并自动评分"""
        idx = len(self._messages)
        self._messages.append(msg)
        self._scores[idx] = self._score_message(msg)
        self._total_messages_seen += 1

        # 关键决策记录
        if self._scores[idx].is_decision:
            snippet = str(msg.get("content", ""))[:120]
            self._decision_log.append(
                f"[{time.strftime('%H:%M')}] {snippet}"
            )

        # 里程碑记录
        if self._scores[idx].is_milestone:
            snippet = str(msg.get("content", ""))[:100]
            self._milestones.append(snippet)

    def get_window_messages(self) -> tuple[list[dict], str]:
        """获取当前窗口内的消息和淘汰消息的摘要

        Returns:
            (保留的消息列表, 淘汰消息的结构化摘要)
        """
        if not self._messages:
            return [], ""

        # 计算当前总 token 数
        total_tokens = sum(s.tokens for s in self._scores.values())
        if total_tokens <= self._max_tokens:
            return list(self._messages), ""

        # 超出预算 → 按评分排序淘汰
        indexed = [(i, self._scores[i]) for i in range(len(self._messages))]
        # 按分数升序（低分在前，先淘汰）
        indexed.sort(key=lambda x: x[1].score)

        kept_indices: set[int] = set(range(len(self._messages)))
        current_tokens = total_tokens
        removed_content: list[str] = []

        for i, score in indexed:
            if current_tokens <= self._max_tokens:
                break
            # 关键消息永不淘汰（决策、错误、用户消息 high-score）
            if score.score >= 0.7:
                continue
            kept_indices.discard(i)
            current_tokens -= score.tokens
            # 收集淘汰消息的摘要
            content = str(self._messages[i].get("content", ""))[:150]
            role = str(self._messages[i].get("role", "?"))
            removed_content.append(f"[{role}] {content}")

        # 构建保留的消息列表（保持原始顺序）
        kept_messages = [
            self._messages[i] for i in range(len(self._messages))
            if i in kept_indices
        ]

        # 生成淘汰消息摘要
        summary = ""
        if removed_content:
            removed_count = len(removed_content)
            summary_lines = [
                f"## 上下文摘要 (已压缩 {removed_count} 条早期消息)",
            ]
            # 仅取前 5 条作为示意
            for line in removed_content[-5:]:
                summary_lines.append(f"- {line[:120]}")
            # 关键决策始终保留
            if self._decision_log:
                summary_lines.append("\n### 关键决策记录")
                for d in self._decision_log[-5:]:
                    summary_lines.append(f"- {d}")
            summary = "\n".join(summary_lines)

        return kept_messages, summary

    # ══════════════════════════════════════════════════════
    # 上下文链接
    # ══════════════════════════════════════════════════════

    def find_related_messages(
        self,
        current_content: str,
        max_results: int = 3,
    ) -> list[dict]:
        """在当前窗口中查找与给定内容相关的历史消息

        基于关键词重叠度的简单关联算法。
        """
        # 提取当前内容的关键词
        current_words = {
            w.lower()
            for w in re.findall(r"[\u4e00-\u9fff\w]{2,}", current_content)
        }

        if not current_words or not self._messages:
            return []

        scored: list[tuple[float, dict]] = []
        for _i, msg in enumerate(self._messages):
            content = str(msg.get("content", ""))
            msg_words = {
                w.lower()
                for w in re.findall(r"[\u4e00-\u9fff\w]{2,}", content)
            }
            if not msg_words:
                continue
            overlap = len(current_words & msg_words) / max(len(current_words), 1)
            if overlap > 0.15:
                scored.append((overlap, msg))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:max_results]]

    # ══════════════════════════════════════════════════════
    # 会话摘要导出
    # ══════════════════════════════════════════════════════

    def get_session_summary(self) -> str:
        """生成完整会话的结构化摘要"""
        parts: list[str] = []

        if self._decision_log:
            parts.append("### 关键决策\n" + "\n".join(
                f"- {d}" for d in self._decision_log[-5:]
            ))

        if self._milestones:
            parts.append("### 里程碑\n" + "\n".join(
                f"- {m}" for m in self._milestones[-5:]
            ))

        stats = (
            f"### 统计\n"
            f"- 总消息数: {len(self._messages)}\n"
            f"- 总处理消息: {self._total_messages_seen}\n"
            f"- 当前窗口 token 估算: "
            f"{sum(s.tokens for s in self._scores.values())}"
        )
        parts.append(stats)

        return "\n\n".join(parts)

    def reset(self) -> None:
        self._messages.clear()
        self._scores.clear()
        self._summary_lines.clear()
        self._decision_log.clear()
        self._milestones.clear()
        self._last_summary_index = 0
