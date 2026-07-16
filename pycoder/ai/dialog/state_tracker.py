"""对话状态追踪引擎 — 弥补与 Hermes -5.5 的多轮对话差距

功能:
  1. 多轮意图追踪: 保持跨轮次意图一致性
  2. 上下文消歧: 利用历史对话消解模糊引用 (它/这个/那里)
  3. 状态转换: 跟踪对话状态 (等待输入/等待确认/执行中)
  4. 实体累积: 累加跨轮次提及的实体和文件
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class DialogState:
    """对话状态"""

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.current_intent: str = ""
        self.previous_intent: str = ""
        self.confidence: float = 0.0
        self.entities: dict[str, list[str]] = {}
        self.mentioned_files: list[str] = []
        self.recent_errors: list[str] = []
        self.turn_count: int = 0
        self.is_waiting_for_input: bool = False
        self.is_waiting_for_confirmation: bool = False
        self.active_task: str = ""
        self.task_history: list[dict] = []
        self.last_model: str = ""
        self.context_snapshot: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "current_intent": self.current_intent,
            "previous_intent": self.previous_intent,
            "confidence": self.confidence,
            "entities": self.entities,
            "mentioned_files": self.mentioned_files,
            "turn_count": self.turn_count,
            "is_waiting_for_input": self.is_waiting_for_input,
            "is_waiting_for_confirmation": self.is_waiting_for_confirmation,
            "active_task": self.active_task,
        }


class DialogStateTracker:
    """对话状态追踪器

    管理对话历史，保持跨轮次上下文一致。
    每次理解新消息前加载当前状态，理解后更新状态。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, DialogState] = {}

    def get_or_create(self, session_id: str) -> DialogState:
        """获取或创建会话状态"""
        if session_id not in self._sessions:
            self._sessions[session_id] = DialogState(session_id)
        return self._sessions[session_id]

    def update_intent(
        self, session_id: str, intent: str, confidence: float
    ) -> None:
        """更新意图，自动处理前/当前意图切换"""
        state = self.get_or_create(session_id)
        state.previous_intent = state.current_intent
        state.current_intent = intent
        state.confidence = confidence
        state.turn_count += 1

    def add_entity(self, session_id: str, category: str, value: str) -> None:
        """添加实体"""
        state = self.get_or_create(session_id)
        if category not in state.entities:
            state.entities[category] = []
        if value not in state.entities[category]:
            state.entities[category].append(value)

    def add_file(self, session_id: str, file_path: str) -> None:
        """添加提及的文件"""
        state = self.get_or_create(session_id)
        if file_path not in state.mentioned_files:
            state.mentioned_files.append(file_path)

    def set_active_task(self, session_id: str, task: str) -> None:
        """设置活跃任务"""
        state = self.get_or_create(session_id)
        if state.active_task and state.active_task != task:
            state.task_history.append({
                "task": state.active_task,
                "completed": False,
                "timestamp": time.time(),
            })
        state.active_task = task

    def complete_active_task(self, session_id: str) -> None:
        """标记活跃任务完成"""
        state = self.get_or_create(session_id)
        if state.active_task:
            state.task_history.append({
                "task": state.active_task,
                "completed": True,
                "timestamp": time.time(),
            })
            state.active_task = ""

    def resolve_anaphora(self, session_id: str, text: str) -> str:
        """消解回指 (它/这个/那里 → 实际对象)

        Args:
            session_id: 会话 ID
            text: 用户输入文本
        Returns:
            消解后的文本 (替换引用为具体名称)
        """
        state = self.get_or_create(session_id)

        # 如果没有前文，直接返回
        if state.turn_count <= 1:
            return text

        # 回指词 → 替换为活跃实体
        resolved = text

        # "它" → 上一个意图的对象
        if "它" in text or "这个" in text:
            if state.entities:
                # 找到最近添加的实体
                for category, values in reversed(list(state.entities.items())):
                    if values:
                        resolved = resolved.replace("它", values[-1])
                        resolved = resolved.replace("这个", values[-1])
                        break

        # "那里" → 上一个文件路径
        if "那里" in text and state.mentioned_files:
            resolved = resolved.replace("那里", state.mentioned_files[-1])

        # "上文" / "刚才" → 上一个任务
        if "上文" in text or "刚才" in text:
            prev = state.previous_intent
            if prev:
                resolved = resolved.replace("上文", f"'{prev}'")
                resolved = resolved.replace("刚才", f"'{prev}'")

        # "这个文件" → 最近提到的文件
        if "这个文件" in text and state.mentioned_files:
            resolved = resolved.replace("这个文件", state.mentioned_files[-1])

        if resolved != text:
            logger.info("回指消解: '%s' → '%s'", text, resolved)

        return resolved

    def get_context(self, session_id: str) -> dict:
        """获取上下文摘要 (用于注入 LLM prompt)"""
        state = self.get_or_create(session_id)
        return {
            "previous_intent": state.previous_intent,
            "current_intent": state.current_intent,
            "active_task": state.active_task,
            "turn_count": state.turn_count,
            "recent_entities": {
                k: v[-3:] for k, v in state.entities.items()
            },
            "recent_files": state.mentioned_files[-5:],
            "recent_errors": state.recent_errors[-3:],
        }

    def get_context_prompt(self, session_id: str) -> str:
        """获取上下文 prompt 片段"""
        ctx = self.get_context(session_id)
        parts = []

        if ctx["active_task"]:
            parts.append(f"当前任务: {ctx['active_task']}")

        if ctx["current_intent"]:
            parts.append(f"当前意图: {ctx['current_intent']}")

        if ctx["recent_files"]:
            files = ", ".join(ctx["recent_files"])
            parts.append(f"涉及文件: {files}")

        if ctx["recent_errors"]:
            parts.append(f"近期错误: {'; '.join(ctx['recent_errors'])}")

        return "\n".join(parts) if parts else ""

    def remove_session(self, session_id: str) -> None:
        """删除会话"""
        self._sessions.pop(session_id, None)

    def stats(self) -> dict:
        """统计"""
        return {
            "active_sessions": len(self._sessions),
            "total_turns": sum(s.turn_count for s in self._sessions.values()),
        }


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_tracker: DialogStateTracker | None = None


def get_tracker() -> DialogStateTracker:
    """获取追踪器单例"""
    global _tracker
    if _tracker is None:
        _tracker = DialogStateTracker()
    return _tracker
