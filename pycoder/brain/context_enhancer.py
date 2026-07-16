"""
对话交互增强器 — 提升自然语言理解和上下文感知能力

解决当前对话"不好用"的问题:
  - 结构化上下文管理: 替代简单的上下文注入，实现分层上下文
  - 话题追踪: 检测话题切换，保持上下文连贯性
  - 引用消解: 处理"它"、"这个"、"那个"等模糊代词
  - 意图强化: 在上下文缺失时自动补充关键信息
  - 冗余消除: 减少不必要的交互步骤，直接给出答案
  - 连贯性保护: 确保多轮对话中的回答连贯相关

用法:
    enhancer = ContextEnhancer()
    ctx = enhancer.process_message("上次那个文件改好了吗？", session_history)
    enhanced_prompt = ctx.build_prompt()
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class ConversationTurn:
    """单轮对话记录"""

    role: str  # "user" | "assistant"
    content: str
    timestamp: float = 0.0
    intent: str = ""  # 简短意图标签
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)  # 提取的实体


@dataclass
class EnhancedContext:
    """增强后的上下文"""

    current_message: str
    resolved_message: str = ""  # 消歧后的消息
    current_topic: str = ""
    previous_topics: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    relevant_history: list[ConversationTurn] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    is_topic_shift: bool = False
    coherence_score: float = 1.0  # 与历史的连贯性 0-1

    def build_prompt(self) -> str:
        """构建增强后的上下文 prompt"""
        parts: list[str] = []

        if self.current_topic:
            parts.append(f"## 当前话题: {self.current_topic}")

        if self.key_entities:
            parts.append(f"## 关键实体: {', '.join(self.key_entities)}")

        if self.relevant_files:
            parts.append(f"## 相关文件: {', '.join(self.relevant_files)}")

        if self.relevant_history:
            parts.append("## 相关对话历史")
            for turn in self.relevant_history[-3:]:  # 最近3轮
                role_label = "用户" if turn.role == "user" else "助手"
                # 截断过长内容
                content = turn.content[:200] + ("..." if len(turn.content) > 200 else "")
                parts.append(f"- {role_label}: {content}")

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════
# 模糊引用消解
# ══════════════════════════════════════════════════════════

AMBIGUOUS_REFERENCES: list[tuple[str, str]] = [
    # (正则模式, 需要解析的类型)
    (r"^(这个|那个|它|他|她|这|那)\s*", "pronoun"),
    (r"(刚才|上次|之前|上面|前面|刚刚|上回)\s*(的|那个|这个)?", "temporal_ref"),
    (r"(那个文件|这个文件|刚才的文件|上面的文件|下面的文件)", "file_ref"),
    (r"(那个函数|这个函数|那个类|这个类|那个变量|这个变量)", "code_ref"),
    (r"(再|继续|接着|还)\s*(做|改|写|修复|优化|补充).*", "continuation"),
    (r"(还有|另外|顺便|额外|附加).*", "addendum"),
    (r"^(对|是的|没错|嗯|对的|好)\s*$", "confirmation"),
    (r"^(不对|不是|错了|改一下|换个|不要).*", "correction"),
]

# 从历史中提取实体
ENTITY_PATTERNS: list[tuple[str, str]] = [
    (r"([\w/\\-]+\.\w{1,5})", "file"),  # 文件路径
    (r"(?:函数|方法|class|类|模块)\s*[`\"]?(\w+)[`\"]?", "code_symbol"),
    (r"(?:文件|路径)\s*[`\"]?([^\s,，。`\"]+)[`\"]?", "file"),
    (r"(?:错误|bug|异常|error)\s*[：:]\s*(.+?)(?:$|\n)", "error"),
    (r"(?:修改|更改|需要)\s*(.+?)(?:$|\n)", "requirement"),
]


# ══════════════════════════════════════════════════════════
# 话题分类
# ══════════════════════════════════════════════════════════

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "代码开发": ["写", "创建", "生成", "实现", "开发", "代码", "函数", "类", "模块"],
    "调试修复": ["修复", "bug", "错误", "异常", "不工作", "报错", "调试", "排查"],
    "代码审查": ["审查", "检查", "review", "代码质量", "优化", "重构"],
    "部署运维": ["部署", "docker", "上线", "发布", "ci", "cd", "服务器", "环境"],
    "文档编写": ["文档", "readme", "注释", "说明", "api文档", "docstring"],
    "项目规划": ["架构", "设计", "方案", "规划", "技术选型", "需求"],
    "测试相关": ["测试", "test", "用例", "pytest", "覆盖率", "单元测试"],
    "问答咨询": ["是什么", "怎么", "如何", "解释", "区别", "对比", "帮我看看"],
    "Git操作": ["git", "commit", "push", "分支", "合并", "merge", "pull request"],
    "性能优化": ["性能", "优化", "加速", "慢", "内存", "并发", "瓶颈"],
}

# 话题转换检测词
TOPIC_SHIFT_INDICATORS: list[str] = [
    "还有个问题", "另外", "换个话题", "不说这个了",
    "回到", "之前说的", "回到刚才", "刚才那个",
    "对了", "想起来", "顺便问一下",
    "by the way", "btw", "another thing",
]


# ══════════════════════════════════════════════════════════
# ContextEnhancer
# ══════════════════════════════════════════════════════════


class ContextEnhancer:
    """对话交互增强器

    提升自然语言理解能力和上下文感知能力。
    处理模糊引用、追踪话题、管理对话历史。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[ConversationTurn]] = {}
        self._sessions_lock = threading.Lock()

    def process_message(
        self,
        message: str,
        session_id: str = "default",
        history: list[ConversationTurn] | None = None,
    ) -> EnhancedContext:
        """处理用户消息，生成增强上下文

        Args:
            message: 用户消息
            session_id: 会话 ID
            history: 对话历史

        Returns:
            EnhancedContext 增强后的上下文
        """
        ctx = EnhancedContext(current_message=message)

        # 获取历史
        history = history or self._sessions.get(session_id, [])

        # 1. 消解模糊引用
        ctx.resolved_message = self._resolve_references(message, history)

        # 2. 提取实体
        ctx.key_entities = self._extract_entities(message, history)

        # 3. 检测话题
        ctx.current_topic = self._detect_topic(message)
        if history:
            ctx.previous_topics = self._get_previous_topics(history)
            ctx.is_topic_shift = self._detect_topic_shift(message, ctx.current_topic, ctx.previous_topics)
            # 话题切换时，过滤只保留与新话题相关的历史（最近 2 轮）
            if ctx.is_topic_shift:
                history = self._filter_history_for_topic(history, ctx.current_topic)

        # 4. 提取相关文件
        ctx.relevant_files = self._extract_relevant_files(message, history)

        # 5. 获取相关历史
        ctx.relevant_history = self._get_relevant_history(message, history, ctx.current_topic)

        # 6. 计算连贯性
        ctx.coherence_score = self._calc_coherence(message, history)

        # 7. 检测是否需要追问
        clarification = self._check_clarification_needed(message, history)
        ctx.needs_clarification = clarification["needed"]
        ctx.clarification_questions = clarification["questions"]

        # 记录本轮
        turn = ConversationTurn(
            role="user",
            content=message,
            intent=ctx.current_topic,
            topics=[ctx.current_topic],
            entities=ctx.key_entities,
        )
        self._add_turn(session_id, turn)

        return ctx

    def record_assistant_response(
        self,
        session_id: str,
        content: str,
        topic: str = "",
    ) -> None:
        """记录助手回复"""
        turn = ConversationTurn(
            role="assistant",
            content=content,
            topics=[topic] if topic else [],
        )
        self._add_turn(session_id, turn)

    def get_session_context(self, session_id: str, max_turns: int = 10) -> str:
        """获取会话上下文摘要"""
        history = self._sessions.get(session_id, [])
        if not history:
            return ""

        recent = history[-max_turns:]
        lines = ["## 对话历史"]
        for turn in recent:
            role = "用户" if turn.role == "user" else "助手"
            content = turn.content[:300] + ("..." if len(turn.content) > 300 else "")
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def clear_session(self, session_id: str) -> None:
        """清除会话（线程安全）"""
        with self._sessions_lock:
            self._sessions.pop(session_id, None)

    # ── 内部实现 ──────────────────────────────────────

    def _resolve_references(self, message: str, history: list[ConversationTurn]) -> str:
        """消解模糊引用"""
        resolved = message

        for pattern, ref_type in AMBIGUOUS_REFERENCES:
            match = re.search(pattern, message)
            if not match:
                continue

            if ref_type == "pronoun" and history:
                # 尝试从最近一轮历史中提取主语
                last_user = self._get_last_user_message(history)
                if last_user:
                    subject = self._extract_subject(last_user)
                    if subject:
                        resolved = resolved.replace(match.group(1), subject, 1)

            elif ref_type == "file_ref" and history:
                # 从历史中提取最近的文件引用
                recent_files = self._extract_recent_files(history)
                if recent_files:
                    resolved = resolved.replace(
                        match.group(0), recent_files[0], 1
                    )

            elif ref_type == "temporal_ref" and history:
                last_assistant = self._get_last_assistant_message(history)
                if last_assistant:
                    summary = last_assistant[:100]
                    resolved = f"{resolved}\n(上下文: 上一轮讨论了「{summary}...」)"

            elif ref_type == "continuation":
                last_user = self._get_last_user_message(history)
                if last_user:
                    resolved = f"继续之前的要求: {last_user}\n当前: {resolved}"

            elif ref_type == "correction":
                last_user = self._get_last_user_message(history)
                if last_user:
                    resolved = f"纠正上一轮: {last_user}\n新要求: {resolved}"

        return resolved

    def _extract_entities(self, message: str, history: list[ConversationTurn]) -> list[str]:
        """提取关键实体"""
        entities: list[str] = []

        for pattern, entity_type in ENTITY_PATTERNS:
            for m in re.finditer(pattern, message):
                entity = m.group(1).strip()
                if entity and len(entity) > 1:
                    entities.append(entity)

        # 从历史中补充
        if not entities and history:
            for turn in reversed(history[-3:]):
                for pattern, entity_type in ENTITY_PATTERNS:
                    for m in re.finditer(pattern, turn.content):
                        entity = m.group(1).strip()
                        if entity and len(entity) > 1:
                            entities.append(entity)

        # 去重
        seen: set[str] = set()
        result: list[str] = []
        for e in entities:
            if e.lower() not in seen:
                seen.add(e.lower())
                result.append(e)

        return result[:5]  # 最多 5 个

    def _detect_topic(self, message: str) -> str:
        """检测当前话题"""
        msg_lower = message.lower()
        scores: dict[str, int] = {}

        for topic, keywords in TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in msg_lower)
            if score > 0:
                scores[topic] = score

        if not scores:
            return "一般对话"

        return max(scores, key=scores.get)

    def _get_previous_topics(self, history: list[ConversationTurn]) -> list[str]:
        """获取最近话题"""
        topics: list[str] = []
        for turn in reversed(history[-5:]):
            if turn.topics:
                for t in turn.topics:
                    if t not in topics:
                        topics.append(t)
        return topics

    def _detect_topic_shift(self, message: str, current: str, previous: list[str]) -> bool:
        """检测话题转换"""
        # 1. 检查显式转换词
        if any(indicator in message.lower() for indicator in TOPIC_SHIFT_INDICATORS):
            return True

        # 2. 检查话题不匹配
        if previous and current != previous[-1] and current != "一般对话":
            return True

        return False

    def _extract_relevant_files(self, message: str, history: list[ConversationTurn]) -> list[str]:
        """提取相关文件"""
        files: list[str] = []

        # 从当前消息提取
        file_pattern = re.compile(r"([\w/\\-]+\.\w{1,5})")
        for m in file_pattern.finditer(message):
            f = m.group(1)
            if "." in f and not f.startswith("."):
                files.append(f)

        # 从历史提取
        if not files and history:
            for turn in reversed(history[-3:]):
                for m in file_pattern.finditer(turn.content):
                    f = m.group(1)
                    if "." in f and not f.startswith("."):
                        files.append(f)

        return list(dict.fromkeys(files))[:5]  # 去重，最多 5 个

    def _get_relevant_history(
        self,
        message: str,
        history: list[ConversationTurn],
        current_topic: str,
    ) -> list[ConversationTurn]:
        """获取相关历史对话"""
        if not history:
            return []

        relevant: list[ConversationTurn] = []

        # 找出与当前话题相关的历史轮次
        for turn in reversed(history):
            if current_topic in (turn.topics or []):
                relevant.append(turn)
            elif any(kw in turn.content.lower() for kw in self._get_topic_keywords(current_topic)):
                relevant.append(turn)

        # 如果话题相关不足，回退到最近 3 轮
        if len(relevant) < 2:
            relevant = list(history[-3:])

        # 倒序恢复正序
        return list(reversed(relevant[-5:]))

    def _calc_coherence(self, message: str, history: list[ConversationTurn]) -> float:
        """计算与历史的连贯性"""
        if not history:
            return 1.0

        score = 0.5  # 基础分

        # 1. 检查关键词重叠
        last_turn = history[-1]
        msg_words = set(message.lower().split())
        last_words = set(last_turn.content.lower().split())
        overlap = len(msg_words & last_words)
        if overlap > 3:
            score += 0.3
        elif overlap > 0:
            score += 0.15

        # 2. 检查话题连续性
        if history:
            last_topic = self._detect_topic(last_turn.content)
            current_topic = self._detect_topic(message)
            if last_topic == current_topic:
                score += 0.2

        # 3. 检查引用
        if any(ref in message.lower() for ref in ["这个", "那个", "它", "刚才", "上面"]):
            score -= 0.1  # 依赖上下文，但可能不连贯

        return min(1.0, max(0.0, score))

    def _check_clarification_needed(
        self,
        message: str,
        history: list[ConversationTurn],
    ) -> dict:
        """检测是否需要追问"""
        result = {"needed": False, "questions": []}

        msg_lower = message.lower()

        # 短消息 + 无历史 → 可能需要追问
        if len(message) < 10 and not history:
            result["needed"] = True
            result["questions"] = ["请问您想做什么？请提供更多细节。"]
            return result

        # 模糊引用 + 无历史
        if any(ref in msg_lower for ref in ["这个", "那个", "它"]) and not history:
            result["needed"] = True
            result["questions"] = ["请问您指的是什么？请具体说明。"]
            return result

        # 修改操作 + 无目标文件
        has_modify = any(kw in msg_lower for kw in ["修改", "修复", "改", "优化", "重构"])
        has_file = bool(re.search(r"\.\w{1,5}\b", message))
        if has_modify and not has_file and not history:
            result["needed"] = True
            result["questions"] = ["请问需要修改哪个文件？请提供文件路径。"]
            return result

        return result

    def _add_turn(self, session_id: str, turn: ConversationTurn) -> None:
        """添加对话轮次（线程安全）"""
        with self._sessions_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            self._sessions[session_id].append(turn)

            # 限制历史长度
            if len(self._sessions[session_id]) > 50:
                self._sessions[session_id] = self._sessions[session_id][-50:]

    @staticmethod
    def _get_last_user_message(history: list[ConversationTurn]) -> str:
        """获取最近用户消息"""
        for turn in reversed(history):
            if turn.role == "user":
                return turn.content
        return ""

    @staticmethod
    def _get_last_assistant_message(history: list[ConversationTurn]) -> str:
        """获取最近助手消息"""
        for turn in reversed(history):
            if turn.role == "assistant":
                return turn.content
        return ""

    @staticmethod
    def _extract_subject(message: str) -> str:
        """提取主语"""
        # 简单的主语提取：取句子的前几个名词
        patterns = [
            r"(?:修改|修复|优化|重构|写|创建|生成|实现|开发)\s*[`\"]?(\w+\.?\w*)[`\"]?",
            r"([\w/\\-]+\.\w{1,5})",  # 文件路径
            r"(.+?)(?:的|中|里|上|下)",  # 名词短语
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_recent_files(history: list[ConversationTurn]) -> list[str]:
        """提取最近提到的文件"""
        files: list[str] = []
        pattern = re.compile(r"([\w/\\-]+\.\w{1,5})")
        for turn in reversed(history[-5:]):
            for m in pattern.finditer(turn.content):
                f = m.group(1)
                if f not in files:
                    files.append(f)
        return files

    @staticmethod
    def _get_topic_keywords(topic: str) -> list[str]:
        """获取话题关键词"""
        return TOPIC_KEYWORDS.get(topic, [])

    @staticmethod
    def _filter_history_for_topic(
        history: list[ConversationTurn],
        current_topic: str,
    ) -> list[ConversationTurn]:
        """话题切换时过滤历史，只保留与新话题相关或最近 2 轮"""
        if not history:
            return history
        # 保留最近 2 轮 + 与新话题关键词匹配的轮次
        keywords = set(TOPIC_KEYWORDS.get(current_topic, []))
        relevant: list[ConversationTurn] = []
        for turn in history:
            if any(kw in turn.content for kw in keywords):
                relevant.append(turn)
        # 确保至少保留最近 2 轮
        recent = history[-2:]
        for t in recent:
            if t not in relevant:
                relevant.append(t)
        # 按原始顺序排序
        return sorted(relevant, key=lambda t: history.index(t) if t in history else 0)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_enhancer_instance: ContextEnhancer | None = None


def get_context_enhancer() -> ContextEnhancer:
    """获取全局上下文增强器"""
    global _enhancer_instance
    if _enhancer_instance is None:
        _enhancer_instance = ContextEnhancer()
    return _enhancer_instance