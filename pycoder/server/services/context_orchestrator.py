"""
ContextOrchestrator — 上下文保持与任务追踪总调度中心

职责：
    集成 TaskTracker、ContextManager、DriftDetector、MemoryAugmentor、
    ContextMetrics 五大组件，提供给 ChatBridge / UnifiedEntryAgent / AgentLoop
    统一的上下文管理接口。

组件协作流程:

    用户消息 → DriftDetector.check() → 偏离? → 生成提醒锚点
              ↓
          TaskTracker → 更新进度 → 生成上下文锚点
              ↓
          MemoryAugmentor.retrieve() → 检索长期记忆
              ↓
          ContextManager → 智能窗口 → 保留关键消息
              ↓
          ContextMetrics → 记录指标

用法:
    orchestrator = ContextOrchestrator(project="pycoder")

    # 1. 新任务
    orchestrator.start_task("创建一个 FastAPI 认证系统")

    # 2. 每轮对话
    anchor = orchestrator.process_user_message("用户的消息")
    # anchor 包含: 任务锚点 + 偏离提醒 + 长期记忆 + 窗口摘要

    # 3. 注入 LLM
    messages.insert(0, {"role": "system", "content": anchor})

    # 4. 对话后
    orchestrator.add_assistant_response("AI 的回复")
    orchestrator.record_anchor_feedback(correctly_used=True)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pycoder.server.services.context_manager import ContextWindowManager
from pycoder.server.services.context_metrics import ContextMetrics
from pycoder.server.services.drift_detector import DriftDetector
from pycoder.server.services.memory_augmentor import MemoryAugmentor
from pycoder.server.services.task_tracker import TaskPhase, TaskTracker

logger = logging.getLogger(__name__)

# ── 模块级单例（供 ChatBridge 等无状态组件访问）──
_orchestrator_instance: ContextOrchestrator | None = None


def get_orchestrator(project: str = "") -> ContextOrchestrator:
    """获取全局 ContextOrchestrator 实例（延迟初始化）"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = ContextOrchestrator(
            project=project,
            max_context_tokens=8000,
        )
    return _orchestrator_instance


def reset_orchestrator() -> None:
    """重置全局实例（新会话时调用）"""
    global _orchestrator_instance
    _orchestrator_instance = None


class ContextOrchestrator:
    """上下文保持与任务追踪总调度中心"""

    def __init__(self, project: str = "", max_context_tokens: int = 8000):
        self.project = project
        self.tracker = TaskTracker()
        self.context_mgr = ContextWindowManager(max_context_tokens)
        self.drift = DriftDetector()
        self.memory = MemoryAugmentor()
        self.metrics = ContextMetrics()
        self._last_anchor: str = ""
        self._ws_callback: Callable[[dict], Awaitable[None]] | None = None
        self._review_every_n: int = 10  # 每 N 轮触发回顾
        self._stats: dict = {"tasks_completed": 0, "tasks_failed": 0}

    def set_ws_callback(self, cb: Callable[[dict], Awaitable[None]]) -> None:
        """注册 WebSocket 推送回调（用于实时状态推送）"""
        self._ws_callback = cb

    async def _push_event(self, event: dict) -> None:
        if self._ws_callback:
            try:
                await self._ws_callback(event)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("push_event_callback_failed: %s", e)
                pass

    # ══════════════════════════════════════════════════════
    # 任务生命周期
    # ══════════════════════════════════════════════════════

    def start_task(self, goal: str, parameters: dict | None = None) -> dict:
        """开始新任务: 初始化跟踪器 + 偏离检测器 + 指标"""
        self.tracker.initialize(goal, parameters)
        self.drift.set_goal(goal)
        self.metrics.start_session()
        self.metrics.add_note(f"新任务启动: {goal[:80]}")

        anchor = self.tracker.get_anchor()
        self._last_anchor = anchor.to_prompt()

        # 检索相关长期记忆
        memory_context = self.memory.build_context_prompt(goal, self.project)

        status = self.tracker.get_status()
        return {
            "anchor": self._last_anchor,
            "memory_context": memory_context,
            "status": status,
        }

    def get_anchor(self) -> str:
        """获取当前上下文锚点"""
        anchor = self.tracker.get_anchor()

        # 合并长期记忆
        mem_context = self.memory.build_context_prompt(
            self.tracker._goal or "", self.project, max_memories=2,
        )

        parts = [anchor.to_prompt()]
        if mem_context:
            parts.append(mem_context)

        return "\n\n".join(parts)

    # ══════════════════════════════════════════════════════
    # 每轮对话处理流程
    # ══════════════════════════════════════════════════════

    async def process_user_message(self, message: str) -> dict:
        """处理用户消息 —— 执行完整上下文保持管道

        Returns:
            {
                "anchor": str,              # 注入 LLM 的锚点文本
                "memory_context": str,      # 长期记忆上下文
                "window_summary": str,      # 窗口淘汰摘要
                "drift_report": DriftReport,
                "status": dict,             # 任务状态
                "events": list[dict],       # 需要推送的 WS 事件
            }
        """
        events: list[dict] = []

        # 1. 偏离检测
        drift_report = self.drift.check(message)
        if drift_report.is_drifting:
            self.tracker.add_drift_warning(drift_report.warning)
            self.metrics.record_drift_check(True)
            events.append({
                "type": "drift_warning",
                "warning": drift_report.warning,
                "similarity": drift_report.similarity,
                "suggested_action": drift_report.suggested_action,
            })
        else:
            self.metrics.record_drift_check(False)

        # 2. 更新任务阶段
        if not self.tracker.is_active and len(message.strip()) > 10:
            # 如果之前没有活跃任务，尝试从这个消息初始化
            self.start_task(message)

        # 3. 添加到上下文窗口
        self.context_mgr.add_message({"role": "user", "content": message})
        self.metrics.record_context_injection()

        # 4. 获取窗口消息和淘汰摘要
        effective, summary = self.context_mgr.get_window_messages()

        # 5. 生成完整锚点
        anchor = self.get_anchor()
        self._last_anchor = anchor

        # 6. 定期触发任务回顾
        review_prompt = ""
        review_every = self._review_every_n
        if self.drift._round_count % review_every == 0 and self.drift._round_count > 0:
            review_prompt = self.drift.generate_review_prompt()

        # 7. 推送状态事件
        status = self.tracker.get_status()
        await self._push_event({
            "type": "task_status",
            "status": status,
            "metrics": self.metrics.get_snapshot().__dict__,
        })

        for ev in events:
            await self._push_event(ev)

        # 返回组装结果
        anchor_parts = [anchor]
        if review_prompt:
            anchor_parts.append(review_prompt)

        return {
            "anchor": "\n\n".join(anchor_parts),
            "memory_context": self.memory.build_context_prompt(
                message, self.project,
            ),
            "window_summary": summary,
            "drift_report": drift_report,
            "status": status,
            "events": events,
        }

    def add_assistant_response(self, response: str) -> None:
        """记录 AI 响应到上下文窗口"""
        self.context_mgr.add_message({"role": "assistant", "content": response})
        # 自动提取关键决策持久化
        if self.drift._DECISION_KEYWORDS.search(response):
            self.memory.store(
                project=self.project,
                key=f"decision_{int(__import__('time').time())}",
                content=response[:1000],
                tags=["decision", "auto_captured"],
                importance=0.6,
            )

    # ══════════════════════════════════════════════════════
    # 反馈与评估
    # ══════════════════════════════════════════════════════

    def record_anchor_feedback(self, correctly_used: bool) -> None:
        """记录锚点使用反馈"""
        if correctly_used:
            self.metrics.record_anchor_hit()
        else:
            self.metrics.record_anchor_miss()

    def collect_user_feedback(self, rating: int, comment: str = "") -> None:
        self.metrics.collect_feedback("overall", rating, comment)

    def get_context_health(self) -> dict:
        snapshot = self.metrics.get_snapshot()
        return {
            "continuity_score": snapshot.continuity_score,
            "anchor_hit_rate": snapshot.anchor_hit_rate,
            "drift_rate": snapshot.drift_rate,
            "task_status": self.tracker.get_status(),
            "session_summary": self.context_mgr.get_session_summary(),
        }

    # ══════════════════════════════════════════════════════
    # 会话结束
    # ══════════════════════════════════════════════════════

    async def end_session(self) -> dict:
        """结束当前会话: 归档记忆 + 衰减 + 输出报告"""
        # 持久化关键事实
        for d in self.context_mgr._decision_log[-5:]:
            self.memory.store(
                project=self.project,
                key=f"decision_{int(__import__('time').time())}",
                content=d,
                tags=["decision", "session_archived"],
                importance=0.7,
            )

        # 指标统计
        if self.tracker._phase in (TaskPhase.DONE,):
            self._stats["tasks_completed"] += 1
        elif self.tracker._phase == TaskPhase.FAILED:
            self._stats["tasks_failed"] += 1

        # 衰减
        self.memory.apply_decay()

        report = {
            "metrics": self.metrics.get_snapshot().__dict__,
            "stats": dict(self._stats),
            "summary": self.context_mgr.get_session_summary(),
            "report": self.metrics.get_report(),
        }
        return report
