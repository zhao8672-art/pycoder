"""
自适应执行引擎 — 根据路由决策动态调整执行参数

替代现有的固定循环模式，实现:
  - 动态迭代预算: 根据任务复杂度分配，而非固定轮次
  - 提前终止: 任务完成时自动终止，不浪费轮次
  - 自适应重试: 工具失败时根据错误类型决定是否重试
  - 上下文感知: 每轮执行前注入最新的相关上下文
  - 反馈集成: 与 FeedbackLoop 协作，实时收集执行信号

用法:
    executor = AdaptiveExecutor(router, feedback_loop)
    async for event in executor.execute(message):
        yield event
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycoder.brain.intelligent_router import (
    IntelligentRouter,
    RoutingDecision,
    ExecutionConfig,
    get_intelligent_router,
)
from pycoder.brain.intent_analyzer import IntentAnalysis
from pycoder.brain.agent_selector import AgentSelection
from pycoder.brain.tool_planner import ToolPlan
from pycoder.brain.feedback_loop import FeedbackLoop, ExecutionSignal, get_feedback_loop

logger = logging.getLogger(__name__)

# 写操作工具集合
WRITE_SAFE_TOOLS = {"write_file", "patch_file", "create_file", "overwrite_file"}
WORKSPACE = Path(
    __import__("os").environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class ExecutionContext:
    """执行上下文"""

    session_id: str = ""
    message: str = ""
    decision: RoutingDecision | None = None
    signal: ExecutionSignal | None = None

    # 运行时状态
    iteration: int = 0
    tool_calls_made: int = 0
    tool_success: int = 0
    tool_failure: int = 0
    files_written: list[str] = field(default_factory=list)
    all_results: list[str] = field(default_factory=list)
    last_response: str = ""

    # 性能
    start_time: float = 0.0
    total_tokens: int = 0

    # 终止条件
    should_stop: bool = False
    stop_reason: str = ""

    # 自适应
    consecutive_empty_tool_rounds: int = 0
    consecutive_tool_failures: int = 0


# ══════════════════════════════════════════════════════════
# 工具重试策略
# ══════════════════════════════════════════════════════════

# 错误类型 → 重试策略
ERROR_RETRY_POLICY: dict[str, dict] = {
    "timeout": {"retry": True, "max_retries": 2, "backoff": 2.0, "reason": "超时错误，可重试"},
    "connection": {"retry": True, "max_retries": 3, "backoff": 1.5, "reason": "连接错误，可重试"},
    "rate_limit": {"retry": True, "max_retries": 2, "backoff": 5.0, "reason": "频率限制，等待后重试"},
    "permission": {"retry": False, "max_retries": 0, "backoff": 0, "reason": "权限错误，不应重试"},
    "not_found": {"retry": False, "max_retries": 0, "backoff": 0, "reason": "资源不存在，不应重试"},
    "validation": {"retry": False, "max_retries": 0, "backoff": 0, "reason": "参数验证失败，不应重试"},
    "unknown": {"retry": True, "max_retries": 1, "backoff": 1.0, "reason": "未知错误，尝试重试一次"},
}


def classify_error(error_msg: str) -> str:
    """根据错误消息分类错误类型"""
    msg_lower = error_msg.lower()
    if "timeout" in msg_lower or "超时" in msg_lower:
        return "timeout"
    if "connection" in msg_lower or "connect" in msg_lower or "连接" in msg_lower:
        return "connection"
    if "rate" in msg_lower or "limit" in msg_lower or "频率" in msg_lower:
        return "rate_limit"
    if "permission" in msg_lower or "denied" in msg_lower or "权限" in msg_lower:
        return "permission"
    if "not found" in msg_lower or "不存在" in msg_lower or "no such file" in msg_lower:
        return "not_found"
    if "validation" in msg_lower or "invalid" in msg_lower or "参数" in msg_lower:
        return "validation"
    return "unknown"


# ══════════════════════════════════════════════════════════
# 终止条件检测
# ══════════════════════════════════════════════════════════

COMPLETION_INDICATORS: list[str] = [
    # 中文完成信号
    "任务完成", "已完成", "执行完毕", "全部完成", "操作完成",
    "✅", "✔", "✓",
    # 英文完成信号
    "task completed", "done", "finished", "all done",
    "i have completed", "successfully completed",
]

STUCK_INDICATORS: list[str] = [
    "我不知道", "无法完成", "无法执行", "无法处理",
    "i don't know", "unable to", "cannot", "can't",
    "not possible", "impossible",
]


def is_completion_signal(response: str) -> bool:
    """检测 LLM 响应是否为完成信号"""
    lower = response.lower()
    # 检查是否包含任何完成指示词
    hit = any(indicator.lower() in lower for indicator in COMPLETION_INDICATORS)
    # 排除干扰：如果同时又包含"困惑"类词汇，不算完成
    stuck = any(indicator.lower() in lower for indicator in STUCK_INDICATORS)
    return hit and not stuck


# ══════════════════════════════════════════════════════════
# AdaptiveExecutor
# ══════════════════════════════════════════════════════════


class AdaptiveExecutor:
    """自适应执行引擎

    根据 IntelligentRouter 的路由决策，动态调整执行参数。
    与 FeedbackLoop 协作，实时收集执行信号用于优化。

    用法:
        executor = AdaptiveExecutor()
        async for event in executor.execute("请帮我修复 app.py 的 bug"):
            if event["type"] == "done":
                print(f"完成: {event['summary']}")
    """

    def __init__(
        self,
        router: IntelligentRouter | None = None,
        feedback: FeedbackLoop | None = None,
        workspace: Path = WORKSPACE,
    ) -> None:
        self._router = router or get_intelligent_router()
        self._feedback = feedback or get_feedback_loop()
        self.workspace = workspace

    async def execute(
        self,
        message: str,
        bridge: Any = None,  # LLMProvider
        context: str = "",
        session_id: str = "",
        use_deep_analysis: bool = False,
    ) -> AsyncIterator[dict]:
        """根据路由决策执行任务

        Args:
            message: 用户消息
            bridge: LLM 桥接器（提供 stream/add_message/configure 方法）
            context: 附加上下文
            session_id: 会话 ID
            use_deep_analysis: 是否使用 LLM 深度分析

        Yields:
            {"type": "status", "status": "...", "iteration": N, "max": M, "progress_pct": P}
            {"type": "tool_result", "tool_name": "...", "result": "...", "iteration": N}
            {"type": "done", "status": "completed", "summary": "...", "iterations": N, ...}
            {"type": "error", "message": "..."}
        """
        # 1. 路由决策
        start = time.monotonic()
        if use_deep_analysis:
            decision = await self._router.decide_deep(message)
        else:
            decision = self._router.decide(message)

        yield {
            "type": "status",
            "status": "routing",
            "details": {
                "domain": decision.intent.technical_domain,
                "task_type": decision.intent.task_type,
                "complexity": decision.intent.complexity,
                "agent": decision.agent.primary_agent,
                "estimated_tools": decision.tool_plan.estimated_tool_calls,
                "decision_time_ms": decision.decision_time_ms,
            },
            "iteration": 0,
            "max": decision.execution_config.max_iterations,
            "progress_pct": 0,
        }

        # 2. 开始信号记录
        signal = self._feedback.start_signal(
            session_id=session_id,
            intent=decision.intent,
            agent=decision.agent,
            tool_plan=decision.tool_plan,
            strategy=decision.execution_config.strategy,
            max_iterations=decision.execution_config.max_iterations,
        )

        ctx = ExecutionContext(
            session_id=session_id,
            message=message,
            decision=decision,
            signal=signal,
            start_time=start,
        )

        # 3. 直接回答路径（无需 Agent 和工具）
        if decision.agent.primary_agent == "none" and decision.tool_plan.allow_direct_answer:
            async for event in self._direct_answer(ctx, bridge, context):
                yield event
            return

        # 4. 需要追问用户
        if decision.intent.needs_clarification:
            async for event in self._request_clarification(ctx, bridge):
                yield event
            return

        # 5. 进入自适应执行循环
        async for event in self._adaptive_loop(ctx, bridge, context, decision):
            yield event

        # 6. 结束信号记录
        elapsed = (time.monotonic() - start) * 1000
        self._feedback.end_signal(
            signal,
            completed=not ctx.should_stop or ctx.stop_reason == "done",
            completion_reason=ctx.stop_reason or "done",
            iterations=ctx.iteration,
            tool_calls=ctx.tool_calls_made,
            tool_success=ctx.tool_success,
            tool_failure=ctx.tool_failure,
            execution_time_ms=elapsed,
            total_tokens=ctx.total_tokens,
        )

    # ── 直接回答路径 ───────────────────────────────

    async def _direct_answer(
        self,
        ctx: ExecutionContext,
        bridge: Any,
        context: str,
    ) -> AsyncIterator[dict]:
        """直接回答（无需 Agent 和工具）"""
        max_iter = ctx.decision.execution_config.max_iterations
        yield {
            "type": "status",
            "status": "thinking",
            "iteration": 1,
            "max": max_iter,
            "progress_pct": 50,
        }

        if bridge is None:
            # 无 bridge，返回意图分析结果作为回答
            yield {
                "type": "done",
                "status": "completed",
                "summary": f"已理解您的问题（{ctx.decision.intent.technical_domain}/{ctx.decision.intent.task_type}），"
                          f"但由于未配置 LLM，无法直接回答。",
                "iterations": 1,
                "tool_count": 0,
                "decision_time_ms": ctx.decision.decision_time_ms,
            }
            return

        try:
            system_prompt = f"你是 PyCoder AI 助手。请用中文简洁回答用户问题。\n\n## 上下文\n{context}" if context else "你是 PyCoder AI 助手。请用中文简洁回答用户问题。"
            bridge.configure(system_prompt=system_prompt, max_tokens=2048)

            response_text = ""
            async for event in bridge.stream(ctx.message):
                if event.event_type == "token":
                    response_text += event.content
                elif event.event_type == "error":
                    yield {"type": "error", "message": event.content}
                    return
                elif event.event_type == "done":
                    response_text = event.content or response_text

            yield {
                "type": "done",
                "status": "completed",
                "summary": response_text[:2000] if response_text else "已处理完成",
                "iterations": 1,
                "tool_count": 0,
                "decision_time_ms": ctx.decision.decision_time_ms,
            }
        except Exception as e:
            yield {"type": "error", "message": f"LLM 调用失败: {e}"}

    # ── 追问用户路径 ────────────────────────────────

    async def _request_clarification(
        self,
        ctx: ExecutionContext,
        bridge: Any,
    ) -> AsyncIterator[dict]:
        """请求用户澄清意图"""
        questions = ctx.decision.intent.clarification_questions
        yield {
            "type": "clarification_needed",
            "questions": questions,
            "ambiguity_notes": ctx.decision.intent.ambiguity_notes,
            "summary": f"为了更好地帮助您，请确认以下信息：\n" + "\n".join(f"- {q}" for q in questions),
        }

    # ── 自适应执行循环 ─────────────────────────────

    async def _adaptive_loop(
        self,
        ctx: ExecutionContext,
        bridge: Any,
        context: str,
        decision: RoutingDecision,
    ) -> AsyncIterator[dict]:
        """自适应执行循环"""
        config = decision.execution_config
        max_iterations = config.max_iterations

        if bridge is None:
            yield {
                "type": "error",
                "message": "未配置 LLM 桥接器，无法执行 Agent 任务",
            }
            return

        # 构建系统提示词
        system_prompt = self._build_system_prompt(decision, context)
        bridge.configure(
            system_prompt=system_prompt,
            max_tokens=config.max_tokens,
        )

        yield {
            "type": "status",
            "status": "analyzing",
            "iteration": 0,
            "max": max_iterations,
            "progress_pct": 0,
        }

        for iteration in range(1, max_iterations + 1):
            ctx.iteration = iteration
            pct = int(iteration / max_iterations * 100)

            yield {
                "type": "status",
                "status": "thinking",
                "iteration": iteration,
                "max": max_iterations,
                "progress_pct": pct,
            }

            # 构建当前轮 prompt
            prompt = self._build_iteration_prompt(ctx, decision, iteration)

            # 反思注入
            if config.enable_rumination and iteration > 1 and iteration % 3 == 0:
                prompt += (
                    f"\n\n---\n### 反思复盘（第{iteration // 3}次）\n"
                    "1. 当前进展是否对齐原始目标？\n"
                    "2. 最近几步是否有冗余或错误？\n"
                    "3. 有没有更简单的替代方案？\n"
                    "请基于以上反思继续执行或调整策略。"
                )

            # LLM 调用
            response_text = ""
            try:
                async for event in bridge.stream(prompt):
                    if event.event_type == "token":
                        response_text += event.content
                    elif event.event_type == "error":
                        yield {"type": "error", "message": event.content}
                        ctx.stop_reason = "error"
                        return
                    elif event.event_type == "done":
                        response_text = event.content or response_text
            except Exception as e:
                yield {"type": "error", "message": f"LLM 调用失败: {e}"}
                ctx.stop_reason = "error"
                return

            ctx.last_response = response_text

            if not response_text:
                ctx.consecutive_empty_tool_rounds += 1
                if ctx.consecutive_empty_tool_rounds >= 3:
                    ctx.stop_reason = "max_empty_rounds"
                    yield {
                        "type": "done",
                        "status": "completed",
                        "summary": "LLM 连续多轮返回空响应，任务终止",
                        "iterations": iteration,
                        "tool_count": ctx.tool_calls_made,
                    }
                    return
                continue

            ctx.consecutive_empty_tool_rounds = 0

            # 解析响应
            parsed = self._parse_response(response_text)

            # 完成信号检测
            if parsed.get("completion") or is_completion_signal(response_text):
                ctx.stop_reason = "done"
                yield {
                    "type": "done",
                    "status": "completed",
                    "summary": parsed.get("summary") or response_text[:500],
                    "iterations": iteration,
                    "tool_count": ctx.tool_calls_made,
                    "files_written": ctx.files_written,
                }
                return

            # 处理工具调用
            tool_calls = parsed.get("tool_calls", [])
            file_blocks = parsed.get("file_blocks", [])

            # 处理文件块
            for fblock in file_blocks:
                try:
                    target = (self.workspace / fblock["path"]).resolve()
                    if target.is_relative_to(self.workspace):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(fblock["content"], encoding="utf-8")
                        ctx.files_written.append(fblock["path"])
                except (OSError, ValueError) as e:
                    logger.warning("file_write_failed: %s", e)

            if not tool_calls:
                if ctx.tool_calls_made > 0:
                    # 已经执行过工具，可能是完成了
                    ctx.stop_reason = "done"
                    yield {
                        "type": "done",
                        "status": "completed",
                        "summary": response_text[:500],
                        "iterations": iteration,
                        "tool_count": ctx.tool_calls_made,
                        "files_written": ctx.files_written,
                    }
                    return
                else:
                    # 还没有工具调用，但 LLM 没有给出工具调用格式
                    # 注入提示继续
                    bridge.add_message(
                        "assistant",
                        "(系统提示：请使用 JSON 格式的工具调用来完成任务。"
                        '格式: {"tool_calls": [{"name": "工具名", "params": {}}]}'
                        "如果任务已完成，请直接输出总结。)",
                    )
                    continue

            # 执行工具
            yield {
                "type": "status",
                "status": "executing",
                "iteration": iteration,
                "max": max_iterations,
                "progress_pct": pct,
                "tool_calls": [tc["name"] for tc in tool_calls],
            }

            # 区分读写
            writers = [tc for tc in tool_calls if tc["name"] in WRITE_SAFE_TOOLS]
            readers = [tc for tc in tool_calls if tc["name"] not in WRITE_SAFE_TOOLS]

            # 写操作串行
            for tc in writers:
                result = await self._execute_tool_with_retry(tc, bridge)
                ctx.tool_calls_made += 1
                if result["success"]:
                    ctx.tool_success += 1
                else:
                    ctx.tool_failure += 1
                yield {
                    "type": "tool_result",
                    "tool_name": tc["name"],
                    "result": result["output"][:500],
                    "success": result["success"],
                    "iteration": iteration,
                }

            # 读操作并行
            if readers:
                tasks = [self._execute_tool_with_retry(tc, bridge) for tc in readers]
                results = await asyncio.gather(*tasks)
                for tc, result in zip(readers, results):
                    ctx.tool_calls_made += 1
                    if result["success"]:
                        ctx.tool_success += 1
                    else:
                        ctx.tool_failure += 1
                    yield {
                        "type": "tool_result",
                        "tool_name": tc["name"],
                        "result": result["output"][:500],
                        "success": result["success"],
                        "iteration": iteration,
                    }

            # 检查连续失败
            if ctx.tool_failure > 0 and ctx.tool_success == 0:
                ctx.consecutive_tool_failures += 1
            else:
                ctx.consecutive_tool_failures = 0

            if ctx.consecutive_tool_failures >= 5:
                ctx.stop_reason = "too_many_failures"
                yield {
                    "type": "error",
                    "message": "连续工具调用失败过多，任务终止",
                }
                return

        # 达到最大迭代
        ctx.stop_reason = "max_iterations"
        yield {
            "type": "done",
            "status": "completed",
            "summary": (
                f"## 任务执行完成\n"
                f"- 迭代次数: {max_iterations}\n"
                f"- 工具调用: {ctx.tool_calls_made} 次\n"
                f"- 写入文件: {len(ctx.files_written)} 个\n"
                f"\n{ctx.last_response[:800] if ctx.last_response else '已达最大迭代次数，部分任务可能未完成。'}"
            ),
            "iterations": max_iterations,
            "tool_count": ctx.tool_calls_made,
            "files_written": ctx.files_written,
        }

    # ── 工具执行（含重试） ──────────────────────────

    async def _execute_tool_with_retry(
        self,
        tc: dict,
        bridge: Any,
    ) -> dict:
        """执行工具，支持自适应重试"""
        max_retries = self._feedback.weights.tool_retry_max
        tool_name = tc.get("name", "unknown")
        params = tc.get("params", {})

        for attempt in range(max_retries + 1):
            try:
                from pycoder.server.services.agent_tools import execute_agent_tool
                result = await execute_agent_tool(
                    tool_name,
                    params,
                    self.workspace,
                    timeout=30,
                )
                output = str(result)

                # 检测结果中是否包含错误
                if "❌" in output or "error" in output.lower()[:50]:
                    error_type = classify_error(output)
                    policy = ERROR_RETRY_POLICY.get(error_type, ERROR_RETRY_POLICY["unknown"])
                    if policy["retry"] and attempt < policy["max_retries"]:
                        await asyncio.sleep(policy["backoff"])
                        continue

                return {"success": True, "output": output, "attempts": attempt + 1}

            except Exception as e:
                error_msg = f"❌ 工具执行失败: {e}"
                error_type = classify_error(str(e))
                policy = ERROR_RETRY_POLICY.get(error_type, ERROR_RETRY_POLICY["unknown"])

                if policy["retry"] and attempt < policy["max_retries"]:
                    await asyncio.sleep(policy["backoff"])
                    continue

                return {"success": False, "output": error_msg, "attempts": attempt + 1}

        return {"success": False, "output": f"❌ 工具 {tool_name} 重试 {max_retries} 次后仍失败", "attempts": max_retries + 1}

    # ── Prompt 构建 ────────────────────────────────

    def _build_system_prompt(self, decision: RoutingDecision, context: str) -> str:
        """根据决策构建系统提示词"""
        intent = decision.intent
        agent = decision.agent
        tool_plan = decision.tool_plan

        lines = [
            "你是 PyCoder 智能 AI 编程助手，运行在用户的本地开发环境中。",
            "",
            f"## 当前任务分析",
            f"- 技术领域: {intent.technical_domain}",
            f"- 任务类型: {intent.task_type}",
            f"- 复杂度: {intent.complexity} (评分: {intent.complexity_score}/100)",
            f"- Agent 角色: {agent.primary_agent}",
            f"- 预估工具调用: {tool_plan.estimated_tool_calls} 次",
            "",
        ]

        # 工具调用指引
        if tool_plan.allow_direct_answer:
            lines.append("## 回答方式")
            lines.append("你可以直接回答，无需调用工具。")
            lines.append("如果问题需要工具操作，请使用 JSON 格式调用工具。")
        else:
            lines.append("## 工具调用要求")
            lines.append("请使用 JSON 格式调用工具完成任务。")
            lines.append(f"预计需要 {tool_plan.estimated_tool_calls}-{tool_plan.max_tool_calls} 次工具调用。")
            lines.append(f"推荐工具类别: {', '.join(tool_plan.tool_categories)}")
            if tool_plan.preferred_tools:
                lines.append(f"推荐工具: {', '.join(tool_plan.preferred_tools[:8])}")

        lines.append("")
        lines.append("## 工具调用格式")
        lines.append('多工具并行: {"tool_calls": [{"name": "工具名", "params": {}}, ...]}')
        lines.append('单工具: {"name": "工具名", "params": {}}')
        lines.append("")
        lines.append("## 工作流程")
        lines.append("1. 分析任务，输出 JSON 工具调用")
        lines.append("2. 等待工具结果")
        lines.append("3. 基于结果继续或输出总结")
        lines.append("4. 任务完成后输出总结报告")

        if context:
            lines.append("")
            lines.append(f"## 上下文\n{context}")

        if agent.agent_confidence < 0.6:
            lines.append("")
            lines.append("## 注意")
            lines.append("当前 Agent 匹配置信度较低，如果发现角色不匹配，请尽量自行调整策略。")

        return "\n".join(lines)

    def _build_iteration_prompt(
        self,
        ctx: ExecutionContext,
        decision: RoutingDecision,
        iteration: int,
    ) -> str:
        """构建每轮 prompt"""
        if iteration == 1:
            return (
                f"请根据以下任务开始执行:\n\n{ctx.message}\n\n"
                f"请使用 JSON 格式的工具调用。"
                if not decision.tool_plan.allow_direct_answer
                else f"请回答以下问题:\n\n{ctx.message}\n\n如需工具操作，请使用 JSON 格式调用。"
            )

        return "以上是工具执行结果。如需继续请输出 JSON 工具调用。已完成请直接输出总结。"

    # ── 响应解析 ───────────────────────────────────

    @staticmethod
    def _parse_response(response_text: str) -> dict:
        """解析 LLM 响应"""
        import json
        import re

        result: dict = {
            "tool_calls": [],
            "file_blocks": [],
            "completion": False,
            "summary": "",
        }

        text = response_text.strip()

        # 尝试提取 JSON 工具调用
        # 优先匹配 tool_calls 格式
        tc_pattern = re.compile(r'"tool_calls"\s*:\s*\[(.*?)\]', re.DOTALL)
        match = tc_pattern.search(text)
        if match:
            try:
                calls = json.loads("[" + match.group(1) + "]")
                result["tool_calls"] = calls
            except json.JSONDecodeError:
                pass

        # 匹配单个工具调用
        if not result["tool_calls"]:
            single_pattern = re.compile(r'\{"name"\s*:\s*"(\w+)"\s*,\s*"params"\s*:\s*(\{[^}]+\})\}')
            for m in single_pattern.finditer(text):
                try:
                    result["tool_calls"].append({
                        "name": m.group(1),
                        "params": json.loads(m.group(2)),
                    })
                except json.JSONDecodeError:
                    pass

        # 提取代码块（可能包含文件路径）
        code_pattern = re.compile(
            r'```(?:\w+)?\s*(?:\n|\r\n?)(.*?)(?:\n|\r\n?)```', re.DOTALL
        )
        for m in code_pattern.finditer(text):
            content = m.group(1).strip()
            if content:
                # 尝试从上下文推断文件路径
                path_hint = re.search(
                    r'(?:path|file|文件|写入|保存到)[\s:：]*[`"\']?([^\s`"\'\n]+\.\w+)',
                    text, re.IGNORECASE,
                )
                path = path_hint.group(1) if path_hint else "output.txt"
                result["file_blocks"].append({"path": path, "content": content})

        # 检测完成信号
        if is_completion_signal(text) and not result["tool_calls"]:
            result["completion"] = True
            result["summary"] = text[:500]

        return result


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_executor_instance: AdaptiveExecutor | None = None


def get_adaptive_executor() -> AdaptiveExecutor:
    """获取全局自适应执行引擎"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = AdaptiveExecutor()
    return _executor_instance