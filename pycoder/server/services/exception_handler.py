"""
异常分级处理引擎 — 对标 Codex L1-L4 四级异常体系

提供:
  - ExceptionClassifier: 根据异常类型/内容自动分级 (L1/L2/L3/L4)
  - ExceptionPipeline: 按等级执行对应处理策略
  - handle_with_retry: 带分级重试的装饰器/工具函数

等级定义:
  L1_BLOCKING: 中断子任务 → 回滚快照 → 重新下发
  L2_MAJOR:    不中断 → 收集缺陷 → 生成补丁 → 迭代修复
  L3_MINOR:    不阻塞 → 记录建议 → 可选优化
  L4_COMM:     自动重试2次 → 失败终止 → 输出报错报告
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from pycoder.server.log import log

# 尝试导入 agent_bus（可能先于 agent_bus 加载）
try:
    from pycoder.server.services.agent_bus import DangerLevel
except ImportError:
    # 回退定义，确保独立可用
    class DangerLevel(Enum):
        L0_NONE = "l0_none"
        L3_MINOR = "l3_minor"
        L2_MAJOR = "l2_major"
        L1_BLOCKING = "l1_blocking"
        L4_COMM = "l4_comm"


T = TypeVar("T")


# ══════════════════════════════════════════════════════════
# 异常分级结果
# ══════════════════════════════════════════════════════════


@dataclass
class ClassificationResult:
    """分级结果"""

    level: DangerLevel
    reason: str
    matched_pattern: str = ""
    suggestion: str = ""


@dataclass
class ExceptionResult:
    """异常处理结果"""

    level: DangerLevel
    handled: bool
    action_taken: str  # rollback / collect / ignore / retry / terminate
    retries_remaining: int = 0
    snapshot_id: str = ""
    message: str = ""


# ══════════════════════════════════════════════════════════
# L1 阻断级匹配规则
# ══════════════════════════════════════════════════════════

# 编译好的正则，避免每次重复编译
_L1_SYNTAX_PATTERNS = [
    re.compile(r, re.IGNORECASE)
    for r in [
        # 编译/语法错误
        r"(?:Syntax|Indentation|Tab)Error",
        r"ModuleNotFoundError.*(?:import|no module)",
        # 高危安全漏洞
        r"hardcoded.*(?:key|secret|password|token|credential)",
        r"SQL\s*(?:injection|拼接|注入)",
        r"(?:os\.system|subprocess\.(?:call|Popen|run).*shell\s*=\s*True)",
        r"(?:exec|eval)\s*\(",
        # 完全偏离需求
        r"(?:偏离|不符合).*(?:需求|requirement)",
        # 密钥明文
        r"(?:api[_-]?key|secret|password)\s*=\s*['\"][^'\"]+['\"]",
    ]
]

_L2_LOGIC_PATTERNS = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"(?:缺少|缺失|missing).*(?:测试|test|校验|validate)",
        r"no.*(?:validation|check|guard)",
        r"(?:空值|None|null).*(?:判断|check|guard)",
        r"AssertionError",
        r"AttributeError.*(?:None|null)",
        r"(?:边界|boundary).*(?:未处理|unhandled)",
    ]
]

_L4_COMM_PATTERNS = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"(?:connection|connect).*(?:refused|timeout|reset|closed)",
        r"timeout.*(?:read|write|connect)",
        r"JSON(?:Decode|Parse)Error",
        r"msg_id.*(?:missing|invalid)",
        r"context_pool.*(?:丢失|missing|truncat)",
    ]
]


# ══════════════════════════════════════════════════════════
# 异常分类器
# ══════════════════════════════════════════════════════════


class ExceptionClassifier:
    """异常分类器 — 根据异常类型和上下文自动分级"""

    @classmethod
    def classify(cls, error: str, context: dict | None = None) -> ClassificationResult:
        """对异常进行分级"""
        ctx = context or {}

        # 1. 检查显式标记的等级
        explicit_level = ctx.get("explicit_danger_level")
        if explicit_level:
            try:
                level = DangerLevel(explicit_level)
                return ClassificationResult(
                    level=level,
                    reason=f"显式指定异常等级: {explicit_level}",
                )
            except (ValueError, TypeError):
                pass

        # 2. 按正则模式匹配
        # L1 阻断级
        for pattern in _L1_SYNTAX_PATTERNS:
            if pattern.search(error):
                return ClassificationResult(
                    level=DangerLevel.L1_BLOCKING,
                    reason=f"匹配 L1 阻断级规则: {pattern.pattern[:60]}",
                    matched_pattern=pattern.pattern,
                    suggestion="立即中断当前子任务，回滚至上一稳定版本快照，重新下发任务",
                )

        # L2 修正级
        for pattern in _L2_LOGIC_PATTERNS:
            if pattern.search(error):
                return ClassificationResult(
                    level=DangerLevel.L2_MAJOR,
                    reason=f"匹配 L2 修正级规则: {pattern.pattern[:60]}",
                    matched_pattern=pattern.pattern,
                    suggestion="不中断流程，统一收集缺陷，生成修复补丁迭代重编码",
                )

        # L4 通信异常
        for pattern in _L4_COMM_PATTERNS:
            if pattern.search(error):
                return ClassificationResult(
                    level=DangerLevel.L4_COMM,
                    reason=f"匹配 L4 通信异常规则: {pattern.pattern[:60]}",
                    matched_pattern=pattern.pattern,
                    suggestion="自动重试 2 次，重试失败后终止全流程并输出完整报错报告",
                )

        # 3. 基于上下文的启发式判断
        severity = ctx.get("severity", "")
        if severity in ("error", "critical", "fatal"):
            return ClassificationResult(
                level=DangerLevel.L2_MAJOR,
                reason="错误级别为 error/critical/fatal，归类为 L2 修正级",
                suggestion="收集缺陷，生成修复补丁",
            )

        # 4. 默认：L3 优化级
        return ClassificationResult(
            level=DangerLevel.L3_MINOR,
            reason="未匹配任何高危规则，归类为 L3 优化级",
            suggestion="记录建议，不阻塞交付",
        )


# ══════════════════════════════════════════════════════════
# 异常流水线处理器
# ══════════════════════════════════════════════════════════

MAX_RETRIES_BY_LEVEL = {
    DangerLevel.L4_COMM: 2,  # 通信异常最多重试 2 次
    DangerLevel.L3_MINOR: 0,  # 优化级不重试
    DangerLevel.L2_MAJOR: 3,  # 修正级最多 3 轮修复
    DangerLevel.L1_BLOCKING: 0,  # 阻断级不重试，直接回滚
    DangerLevel.L0_NONE: 0,
}


class ExceptionPipeline:
    """异常流水线处理器"""

    def __init__(self, snapshot_manager=None):
        self._snapshot_manager = snapshot_manager

    async def handle(
        self,
        level: DangerLevel,
        error: str,
        snapshot_id: str = "",
        run_context: dict | None = None,
    ) -> ExceptionResult:
        """按等级执行对应的处理策略"""
        ctx = run_context or {}

        if level == DangerLevel.L1_BLOCKING:
            return await self._handle_blocking(error, snapshot_id, ctx)

        elif level == DangerLevel.L2_MAJOR:
            return await self._handle_major(error, snapshot_id, ctx)

        elif level == DangerLevel.L3_MINOR:
            return self._handle_minor(error, ctx)

        elif level == DangerLevel.L4_COMM:
            return await self._handle_comm(error, ctx)

        return ExceptionResult(
            level=level,
            handled=True,
            action_taken="ignore",
            message="无异常，无需处理",
        )

    async def _handle_blocking(
        self,
        error: str,
        snapshot_id: str,
        ctx: dict,
    ) -> ExceptionResult:
        """L1 阻断级: 中断 → 回滚 → 重新下发"""
        log.warning("exception_l1_blocking", error=error[:200], snapshot=snapshot_id)

        # 尝试回滚
        rollback_ok = False
        if self._snapshot_manager and snapshot_id:
            try:
                workspace = ctx.get("workspace", "")
                if workspace:
                    result = await self._snapshot_manager.rollback(workspace, snapshot_id)
                    rollback_ok = result.success
            except Exception as e:
                log.error("rollback_failed", error=str(e))

            rollback_msg = f"已回滚快照 {snapshot_id}" if rollback_ok else "回滚失败，流程终止"
            return ExceptionResult(
                level=DangerLevel.L1_BLOCKING,
                handled=rollback_ok,
                action_taken="rollback" if rollback_ok else "terminate",
                snapshot_id=snapshot_id,
                message=f"[L1 阻断] {error[:200]} — {rollback_msg}",
            )

    async def _handle_major(
        self,
        error: str,
        snapshot_id: str,
        ctx: dict,
    ) -> ExceptionResult:
        """L2 修正级: 收集 → 生成补丁 → 迭代修复"""
        log.info("exception_l2_major", error=error[:200])
        return ExceptionResult(
            level=DangerLevel.L2_MAJOR,
            handled=False,
            action_taken="collect_patch",
            retries_remaining=MAX_RETRIES_BY_LEVEL[DangerLevel.L2_MAJOR],
            message=f"[L2 修正] {error[:200]} — 已收集缺陷，等待生成修复补丁",
        )

    def _handle_minor(self, error: str, ctx: dict) -> ExceptionResult:
        """L3 优化级: 记录建议，不阻塞"""
        log.debug("exception_l3_minor", error=error[:200])
        return ExceptionResult(
            level=DangerLevel.L3_MINOR,
            handled=True,
            action_taken="log_only",
            message=f"[L3 优化] {error[:200]} — 已记录，不阻塞交付",
        )

    async def _handle_comm(
        self,
        error: str,
        ctx: dict,
    ) -> ExceptionResult:
        """L4 通信异常: 自动重试 → 失败终止"""
        retries_left = MAX_RETRIES_BY_LEVEL[DangerLevel.L4_COMM]
        for attempt in range(1, MAX_RETRIES_BY_LEVEL[DangerLevel.L4_COMM] + 1):
            log.info("exception_l4_retry", attempt=attempt, error=error[:200])
            retries_left -= 1
            await asyncio.sleep(1 * attempt)  # 递增等待
            # 调用方会判断 retries_remaining > 0 并重试
            break

            comm_msg = "重试失败，流程终止" if retries_left == 0 else f"剩余 {retries_left} 次重试"
            return ExceptionResult(
                level=DangerLevel.L4_COMM,
                handled=retries_left == 0,
                action_taken="terminate" if retries_left == 0 else "retry",
                retries_remaining=retries_left,
                message=f"[L4 通信] {error[:200]} — {comm_msg}",
            )


# ══════════════════════════════════════════════════════════
# 便捷工具函数
# ══════════════════════════════════════════════════════════


def classify_error(error: str, context: dict | None = None) -> DangerLevel:
    """快捷分级 — 直接返回 DangerLevel"""
    return ExceptionClassifier.classify(error, context).level


async def handle_with_retry[T](
    coro_factory: Callable[[], Awaitable[T]],
    error_context: dict | None = None,
    max_retries: int = 2,
    retry_delay: float = 1.0,
) -> tuple[T | None, ExceptionResult | None]:
    """通用带分级重试的执行包装

    用法:
        result, err = await handle_with_retry(
            lambda: some_async_func(),
            error_context={"severity": "error"},
        )
        if err and err.level == DangerLevel.L1_BLOCKING:
            # 立即回滚
            ...
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            result = await coro_factory()
            return result, None
        except Exception as e:
            last_exc = e
            level = classify_error(str(e), error_context)
            if level == DangerLevel.L1_BLOCKING:
                # L1 不重试
                return None, ExceptionResult(
                    level=level,
                    handled=False,
                    action_taken="terminate",
                    message=f"[L1 阻断] 不重试: {e}",
                )
            if level == DangerLevel.L3_MINOR:
                # L3 直接返回成功但带警告
                return None, ExceptionResult(
                    level=level,
                    handled=True,
                    action_taken="ignore",
                    message=f"[L3 优化] {e}",
                )
            if attempt < max_retries:
                log.info("retrying", attempt=attempt + 1, max=max_retries)
                await asyncio.sleep(retry_delay * (attempt + 1))

    return None, ExceptionResult(
        level=classify_error(str(last_exc), error_context),
        handled=False,
        action_taken="failed_after_retry",
        message=f"重试 {max_retries} 次后仍失败: {last_exc}",
    )


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_default_exception_pipeline: ExceptionPipeline | None = None


def get_exception_pipeline() -> ExceptionPipeline:
    """获取全局异常流水线处理实例"""
    global _default_exception_pipeline
    if _default_exception_pipeline is None:
        _default_exception_pipeline = ExceptionPipeline()
    return _default_exception_pipeline
