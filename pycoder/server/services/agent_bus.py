"""
AgentBus — Agent 消息总线

基于 asyncio.Queue 的发布/订阅系统，支持:
    - 点对点消息 (PM → Architect)
    - 广播消息 (PM → *)
    - 请求/回复模式 (问 → 答)
    - 消息历史记录

用于 AutonomousPipeline 中 Agent 间通信。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    QUESTION = "question"
    ANSWER = "answer"
    REVIEW = "review"
    REVIEW_FIX = "review_fix"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    INFO = "info"
    PATCH = "patch"  # A5 修复补丁推送
    DELIVER = "deliver"  # 整合交付
    TERMINATE = "terminate"  # 流程终止


class DangerLevel(Enum):
    """异常等级 — 对标 Codex L1-L4 四级异常体系"""

    L0_NONE = "l0_none"  # 无异常
    L3_MINOR = "l3_minor"  # 优化级: 代码冗余/命名不规范（不阻塞交付）
    L2_MAJOR = "l2_major"  # 修正级: 功能缺失/无测试/缺校验（收集补丁迭代）
    L1_BLOCKING = "l1_blocking"  # 阻断级: 高危漏洞/完全偏离需求/无法编译（中断回滚）
    L4_COMM = "l4_comm"  # 通信异常: 消息格式错乱/上下文丢失（自动重试）


class FlowStage(Enum):
    """流程阶段 — 标识当前处于闭环的哪个阶段"""

    REQUIREMENT = "requirement"  # 需求拆解
    ARCHITECT = "architect"  # 架构设计
    CODING = "coding"  # 编码产出
    REVIEWING = "reviewing"  # 并行校验
    FIXING = "fixing"  # 缺陷修复
    DELIVERING = "delivering"  # 整合交付


@dataclass
class BusMessage:
    """总线消息 — 扩展版，对标 Codex 统一 JSON 协议模板"""

    # ── 基础字段（原有，保持向后兼容） ──
    id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:6]}")
    msg_type: MessageType = MessageType.INFO
    from_agent: str = ""
    to_agent: str = "*"
    content: str = ""
    context: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""

    # ── 新增字段（对标 Codex 协议，全部有默认值） ──
    flow_stage: FlowStage = FlowStage.REQUIREMENT
    danger_level: DangerLevel = DangerLevel.L0_NONE
    context_pool: dict = field(
        default_factory=lambda: {
            "user_origin_command": "",
            "pre_all_output": [],
            "code_version_snapshot": "",
        }
    )
    attach_list: list[dict] = field(default_factory=list)
    exception_info: dict = field(
        default_factory=lambda: {
            "is_exception": False,
            "exception_desc": "",
            "rollback_snapshot_id": "",
        }
    )
    finish_flag: bool = False
    task_content: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.msg_type.value,
            "from": self.from_agent,
            "to": self.to_agent,
            "content": self.content[:500] if self.content else "",
            "flow_stage": self.flow_stage.value,
            "danger_level": self.danger_level.value,
            "finish_flag": self.finish_flag,
            "timestamp": self.timestamp,
        }

    def to_dict_full(self) -> dict:
        """完整序列化（含所有字段，用于调试/审计）"""
        return {
            "id": self.id,
            "type": self.msg_type.value,
            "from": self.from_agent,
            "to": self.to_agent,
            "flow_stage": self.flow_stage.value,
            "danger_level": self.danger_level.value,
            "content": self.content[:500] if self.content else "",
            "task_content": self.task_content[:500] if self.task_content else "",
            "context": dict(self.context),
            "context_pool": {
                k: v if isinstance(v, str) else v[:2] if isinstance(v, list) else v
                for k, v in self.context_pool.items()
            },
            "attach_count": len(self.attach_list),
            "exception_info": self.exception_info,
            "finish_flag": self.finish_flag,
            "reply_to": self.reply_to,
            "timestamp": self.timestamp,
        }


MessageHandler = Callable[[BusMessage], Awaitable[None]]


class AgentBus:
    """Agent 消息总线"""

    MAX_HISTORY = 200

    def __init__(self):
        self._queues: dict[str, asyncio.Queue[BusMessage]] = {}
        self._handlers: dict[str, MessageHandler] = {}
        self._message_log: list[BusMessage] = []
        self._reply_futures: dict[str, asyncio.Future] = {}
        self._running = False
        self._dispatch_task: asyncio.Task | None = None

    # ── 注册 ────────────────────────────────────────────

    def register(self, agent_id: str, handler: MessageHandler | None = None):
        """注册 Agent 到总线"""
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()
        if handler:
            self._handlers[agent_id] = handler

    def unregister(self, agent_id: str):
        """从总线注销"""
        self._queues.pop(agent_id, None)
        self._handlers.pop(agent_id, None)

    @property
    def agents(self) -> list[str]:
        return list(self._queues.keys())

    # ── 发送 ────────────────────────────────────────────

    async def send(self, msg: BusMessage):
        """发送消息到指定 Agent 或广播"""
        self._message_log.append(msg)
        if len(self._message_log) > self.MAX_HISTORY:
            self._message_log = self._message_log[-self.MAX_HISTORY :]

        if msg.to_agent == "*":
            # 广播
            for q in self._queues.values():
                await q.put(msg)
        elif msg.to_agent in self._queues:
            await self._queues[msg.to_agent].put(msg)

        # 请求/回复匹配
        if msg.reply_to and msg.reply_to in self._reply_futures:
            future = self._reply_futures.pop(msg.reply_to)
            if not future.done():
                future.set_result(msg)

    async def broadcast(
        self,
        from_agent: str,
        content: str,
        msg_type: MessageType = MessageType.INFO,
        flow_stage: FlowStage = FlowStage.REQUIREMENT,
        danger_level: DangerLevel = DangerLevel.L0_NONE,
        finish_flag: bool = False,
    ):
        """快捷广播（支持扩展字段）"""
        await self.send(
            BusMessage(
                from_agent=from_agent,
                to_agent="*",
                msg_type=msg_type,
                content=content,
                flow_stage=flow_stage,
                danger_level=danger_level,
                finish_flag=finish_flag,
            )
        )

    # ── 接收 ────────────────────────────────────────────

    async def receive(
        self,
        agent_id: str,
        timeout: float = 60.0,
    ) -> BusMessage | None:
        """阻塞等待一条消息"""
        if agent_id not in self._queues:
            self.register(agent_id)
        try:
            return await asyncio.wait_for(
                self._queues[agent_id].get(),
                timeout=timeout,
            )
        except TimeoutError:
            return None

    # ── 请求/回复 ───────────────────────────────────────

    async def request(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        msg_type: MessageType = MessageType.QUESTION,
        timeout: float = 120.0,
        flow_stage: FlowStage = FlowStage.REQUIREMENT,
    ) -> BusMessage | None:
        """发送请求并等待回复"""
        msg = BusMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            msg_type=msg_type,
            content=content,
            flow_stage=flow_stage,
        )
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._reply_futures[msg.id] = future
        await self.send(msg)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._reply_futures.pop(msg.id, None)
            return None

    async def reply(self, to_msg: BusMessage, content: str):
        """回复一条消息"""
        await self.send(
            BusMessage(
                from_agent=to_msg.to_agent,
                to_agent=to_msg.from_agent,
                msg_type=MessageType.ANSWER,
                content=content,
                reply_to=to_msg.id,
                flow_stage=to_msg.flow_stage,
            )
        )

    # ── 查询 ────────────────────────────────────────────

    def get_history(self, limit: int = 50) -> list[dict]:
        return [m.to_dict() for m in self._message_log[-limit:]]

    def get_messages_for(self, agent_id: str, limit: int = 20) -> list[dict]:
        relevant = [
            m
            for m in self._message_log
            if m.to_agent in ("*", agent_id) or m.from_agent == agent_id
        ]
        return [m.to_dict() for m in relevant[-limit:]]

    # ── 事件流 ──────────────────────────────────────────

    async def events(self) -> AsyncIterator[BusMessage]:
        """监听所有消息（用于前端展示）"""
        self._running = True
        q: asyncio.Queue[BusMessage] = asyncio.Queue()
        orig_send = self.send

        async def _intercept(msg: BusMessage):
            await orig_send(msg)
            await q.put(msg)

        self.send = _intercept  # type: ignore
        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=5.0)
                    yield msg
                except TimeoutError:
                    continue
        finally:
            self.send = orig_send
            self._running = False

    def stop(self):
        """停止事件流"""
        self._running = False
