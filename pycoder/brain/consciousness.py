"""
意识引擎 — AI 的持续感知层

让 AI 从"被动响应"升级为"主动感知"。

功能:
- 文件监听: 实时监控工作区变化
- Git 监控: 追踪提交、分支、冲突
- 测试监听: 自动运行相关测试
- LSP 事件: 语法/类型错误实时反馈
- 注意力管理: 优先级评分、事件聚合、上下文切换决策
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


class OperatingMode(str, enum.Enum):
    """AI 运行模式"""
    IDLE = "idle"          # 低功耗监听，仅处理关键事件
    AWARE = "aware"        # 主动感知，分析变化，预判需求
    FOCUSED = "focused"    # 全速运行，执行复杂任务
    REFLECT = "reflect"    # 回顾已完成任务，总结经验


@dataclass
class SystemEvent:
    """系统事件"""
    event_type: str              # 事件类型
    source: str = ""             # 事件来源
    summary: str = ""            # 摘要
    severity: str = "info"       # info / warning / error / critical
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    auto_fixable: bool = False   # 是否可以自动修复


class ConsciousnessEngine:
    """
    意识引擎

    运行模式:
    - IDLE: 后台低功耗监听，只处理 critical 级别事件
    - AWARE: 主动分析项目变化，预判需求并生成建议
    - FOCUSED: 全力执行用户指定的任务
    - REFLECT: 回顾、总结、学习
    """

    def __init__(self):
        self._mode = OperatingMode.IDLE
        self._event_queue: asyncio.Queue[SystemEvent] = asyncio.Queue()
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._attention_thresholds: dict[str, int] = {
            "file_save": 5,       # 5 次保存后合并为一次分析
            "error": 1,           # 错误立即处理
            "warning": 2,         # 警告累积 2 次处理
        }
        self._event_buffers: dict[str, list[SystemEvent]] = defaultdict(list)
        self._last_action_time: float = 0.0

        # 注册默认处理器
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """注册默认事件处理器"""
        self.on("file_changed", self._on_file_changed)
        self.on("git_change", self._on_git_change)
        self.on("test_failure", self._on_test_failure)
        self.on("security_issue", self._on_security_issue)
        self.on("performance_regression", self._on_perf_regression)

    @property
    def mode(self) -> OperatingMode:
        return self._mode

    def set_mode(self, mode: OperatingMode) -> None:
        """切换运行模式"""
        old_mode = self._mode
        self._mode = mode
        logger.info("意识引擎模式: %s → %s", old_mode.value, mode.value)

    def on(self, event_type: str, handler: Callable) -> None:
        """注册事件处理器"""
        self._handlers[event_type].append(handler)

    async def perceive(self, event: SystemEvent) -> None:
        """接收系统事件并触发分析"""
        # IDLE 模式下只处理关键事件
        if self._mode == OperatingMode.IDLE and event.severity != "critical":
            return

        await self._event_queue.put(event)
        await self._process_event(event)

    async def _process_event(self, event: SystemEvent) -> None:
        """处理单个事件"""
        # 事件聚合
        buffer_key = f"{event.event_type}_{event.source}"
        self._event_buffers[buffer_key].append(event)

        threshold = self._attention_thresholds.get(event.event_type, 1)
        if len(self._event_buffers[buffer_key]) >= threshold:
            # 触发处理
            merged = self._merge_events(self._event_buffers[buffer_key])
            self._event_buffers[buffer_key].clear()

            # 调用所有注册的处理器
            for handler in self._handlers.get(merged.event_type, []):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(merged)
                    else:
                        handler(merged)
                except Exception as e:
                    logger.error("事件处理器失败: %s", e, exc_info=True)

    async def _on_file_changed(self, event: SystemEvent) -> None:
        """文件变化处理"""
        if self._mode == OperatingMode.FOCUSED:
            return  # 聚焦模式下不中断当前任务

        logger.debug("检测到文件变化: %s", event.summary)

    async def _on_git_change(self, event: SystemEvent) -> None:
        """Git 变化处理"""
        logger.info("Git 变化: %s", event.summary)

    async def _on_test_failure(self, event: SystemEvent) -> None:
        """测试失败处理"""
        logger.warning("测试失败: %s", event.summary)
        if event.auto_fixable and self._mode in (OperatingMode.AWARE, OperatingMode.FOCUSED):
            logger.info("尝试自动修复测试失败...")

    async def _on_security_issue(self, event: SystemEvent) -> None:
        """安全问题处理"""
        logger.critical("安全问题: %s", event.summary)

    async def _on_perf_regression(self, event: SystemEvent) -> None:
        """性能回归处理"""
        logger.warning("性能回归: %s", event.summary)

    def generate_awareness_report(self) -> dict[str, Any]:
        """生成感知报告"""
        return {
            "mode": self._mode.value,
            "queue_size": self._event_queue.qsize(),
            "buffered_events": {
                k: len(v) for k, v in self._event_buffers.items()
            },
            "last_action_seconds_ago": time.time() - self._last_action_time,
        }

    @staticmethod
    def _merge_events(events: list[SystemEvent]) -> SystemEvent:
        """合并一批同类事件"""
        if len(events) == 1:
            return events[0]

        return SystemEvent(
            event_type=events[0].event_type,
            source=events[0].source,
            summary=f"合并了 {len(events)} 个事件: {events[0].summary}",
            severity=events[0].severity,
        )
