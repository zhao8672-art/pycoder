"""
统一 Agent 执行循环 — 一个循环驱动所有策略，集成智能路由

特性:
  - 智能路由: 根据意图分析动态调整执行参数（V2 新增）
  - 读并行/写串行（来自 AgentOrchestrator）
  - 反思机制每3轮（来自 ReActLoop）
  - 内联代码块自动写入（来自 AutonomousPipeline）
  - 完成信号自动检测（来自 AutonomousPipeline）
  - 统一格式解析（JSON/FILE/ReAct/代码块）
  - 反馈学习: 实时收集执行信号（V2 新增）
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pycoder.ai.diagnostic_auto_fix import DiagnosticAutoFixer, get_diagnostic_fixer
from pycoder.brain.context_enhancer import ContextEnhancer, get_context_enhancer
from pycoder.brain.feedback_loop import FeedbackLoop, get_feedback_loop
from pycoder.brain.intelligent_router import (
    IntelligentRouter,
    RoutingDecision,
    get_intelligent_router,
)
from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine
from pycoder.core.services.agent_parser import WRITE_TOOLS as WRITE_SAFE_TOOLS
from pycoder.core.services.agent_parser import parse_response, validate_tool_call
from pycoder.server.services.agent_strategies import AgentStrategy
from pycoder.server.services.agent_tools import execute_agent_tool

logger = logging.getLogger(__name__)

WORKSPACE = Path(
    __import__("os").environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
)


class UnifiedAgentLoop:
    """统一 Agent 执行循环（V2: 集成智能路由和反馈学习）"""

    def __init__(
        self,
        strategy: AgentStrategy,
        workspace: Path = WORKSPACE,
        router: IntelligentRouter | None = None,
        feedback: FeedbackLoop | None = None,
        context_enhancer: ContextEnhancer | None = None,
        enable_intelligent_routing: bool = False,
        diagnostic_fixer: DiagnosticAutoFixer | None = None,
        self_evolution_engine: SelfEvolutionEngine | None = None,
    ):
        self.strategy = strategy
        self.workspace = WORKSPACE
        self._rumination_count = 0
        # FIX(自循环): 移除实例级 _last_iteration_had_tools，改为每次 chat_stream 内的局部变量。
        # 旧实现是实例变量，会跨多次 chat_stream 调用残留状态，
        # 导致新对话起始 prompt 错误地变成"以上是工具执行结果"。

        # V2: 智能路由模块
        self._router = router or get_intelligent_router()
        self._feedback = feedback or get_feedback_loop()
        self._context_enhancer = context_enhancer or get_context_enhancer()
        self._enable_intelligent_routing = enable_intelligent_routing
        self._last_signal: Any = None  # V2: 最近一次执行的信号，用于用户评分关联

        # V2.1: 诊断自动修复器 (Phase 2.2)
        self._diagnostic_fixer = diagnostic_fixer or get_diagnostic_fixer()

        # V2.2: 自进化引擎 (Self-Evolution feedback hook)
        self._self_evo = self_evolution_engine

    async def chat_stream(
        self,
        message: str,
        bridge,  # LLMProvider (BridgeLLMProvider) — 提供 stream()/add_message()/configure()
        context: str = "",
        session_id: str = "",
        *,
        auto_apply_fixes: bool = False,
    ) -> AsyncIterator[dict]:
        """
        统一执行流（V2: 集成智能路由决策）

        Args:
            message: 用户消息
            bridge: LLM 桥接
            context: 上下文
            session_id: 会话 ID
            auto_apply_fixes: 是否在代码生成后自动应用安全 LSP 修复 (Phase 2.2)

        Yields:
            {"type": "status", "status": "analyzing"|"executing"|"thinking",
             "iteration": int, "max": int, "progress_pct": int}
            {"type": "tool_result", "tool_name": str, "result": str, "iteration": int}
            {"type": "agent_result", "status": "done", "summary": str, ...}
            {"type": "error", "message": str}
        """
        strategy = self.strategy
        max_iterations = strategy.max_iterations
        timeout = strategy.tool_timeout
        all_tool_calls: list[dict] = []
        all_results: list[str] = []
        written_files: list[str] = []
        tool_success_count: int = 0  # V2: 追踪成功工具调用数
        tool_failure_count: int = 0  # V2: 追踪失败工具调用数

        # FIX(自循环): 每次对话独立的局部状态
        last_iteration_had_tools: bool = False  # 上一轮是否真正执行了工具
        consecutive_empty_count: int = 0  # 连续空响应计数（>2 即终止）
        consecutive_no_tool_count: int = 0  # 连续无工具调用计数（>3 即终止）
        MAX_CONSECUTIVE_EMPTY = 2  # 连续 2 次空响应直接终止
        MAX_CONSECUTIVE_NO_TOOL = 3  # 连续 3 轮无工具调用直接终止

        start_time = time.monotonic()

        # ═══════════════════════════════════════════════
        # V2: 智能路由决策
        # ═══════════════════════════════════════════════
        decision: RoutingDecision | None = None
        if self._enable_intelligent_routing:
            try:
                # 上下文增强
                enhanced = self._context_enhancer.process_message(message, session_id=session_id)
                if enhanced.resolved_message != message:
                    logger.info(
                        "context_enhanced: original='%s' resolved='%s'",
                        message[:50],
                        enhanced.resolved_message[:50],
                    )

                # 路由决策
                decision = self._router.decide(enhanced.resolved_message)

                # 动态调整执行参数
                max_iterations = decision.execution_config.max_iterations
                timeout = decision.execution_config.tool_timeout

                logger.info(
                    "intelligent_routing: domain=%s type=%s complexity=%s "
                    "agent=%s tools=%d iterations=%d confidence=%.2f",
                    decision.intent.technical_domain,
                    decision.intent.task_type,
                    decision.intent.complexity,
                    decision.agent.primary_agent,
                    decision.tool_plan.estimated_tool_calls,
                    max_iterations,
                    decision.confidence,
                )

                # 直接回答路径（无需 Agent 和工具）
                if (
                    decision.agent.primary_agent == "none"
                    and decision.tool_plan.allow_direct_answer
                ):
                    yield {
                        "type": "status",
                        "status": "analyzing",
                        "iteration": 0,
                        "max": 1,
                        "progress_pct": 50,
                        "routing": {
                            "domain": decision.intent.technical_domain,
                            "task_type": decision.intent.task_type,
                            "complexity": decision.intent.complexity,
                            "agent": "none",
                            "decision_time_ms": decision.decision_time_ms,
                        },
                    }
                    # 直接回答
                    bridge.configure(
                        system_prompt="你是 PyCoder AI 助手。请用中文简洁回答用户问题。",
                        max_tokens=2048,
                    )
                    response_text = ""
                    try:
                        async for event in bridge.stream(message):
                            if event.event_type == "token":
                                response_text += event.content
                            elif event.event_type == "error":
                                yield {"type": "error", "message": event.content}
                                return
                            elif event.event_type == "done":
                                response_text = event.content or response_text
                    except Exception as e:
                        yield {"type": "error", "message": f"LLM 调用失败: {e}"}
                        return

                    self._context_enhancer.record_assistant_response(
                        session_id,
                        response_text[:500],
                        topic=decision.intent.task_type,
                    )
                    yield {
                        "type": "agent_result",
                        "status": "done",
                        "summary": response_text[:2000] if response_text else "已处理完成",
                        "iterations": 1,
                        "tool_count": 0,
                        "files_written": [],
                        "routing": decision.to_dict() if decision else None,
                    }
                    return

                # 需要追问用户
                if decision.intent.needs_clarification:
                    questions = decision.intent.clarification_questions
                    yield {
                        "type": "agent_result",
                        "status": "clarification_needed",
                        "summary": (
                            "为了更好地帮助您，请确认以下信息：\n"
                            + "\n".join(f"- {q}" for q in questions)
                        ),
                        "questions": questions,
                        "ambiguity_notes": decision.intent.ambiguity_notes,
                        "iterations": 0,
                        "tool_count": 0,
                    }
                    return

            except Exception as e:
                logger.warning("intelligent_routing_failed: %s, falling back to default", e)
                decision = None

        # ═══════════════════════════════════════════════
        # 构建系统提示词
        # ═══════════════════════════════════════════════

        # 构建系统提示词（注入缓存优化规则）
        system_prompt = strategy.system_prompt
        from pycoder.prompts.cache_rules import inject_cache_rules

        system_prompt = inject_cache_rules(system_prompt, lang="zh")
        if context:
            system_prompt += f"\n\n## 上下文\n{context}"

        bridge.configure(system_prompt=system_prompt, max_tokens=16384)

        yield {
            "type": "status",
            "status": "analyzing",
            "iteration": 0,
            "max": max_iterations,
            "progress_pct": 0,
        }

        # 构建分析 prompt
        analysis_prompt = (
            f"请直接输出 JSON 工具调用来完成以下任务:\n\n{message}\n\n"
            '格式: {"tool_calls": [{"name": "工具名", "params": {}}]}'
        )
        if strategy.enable_rumination:
            analysis_prompt += "\n\n每完成3步工具调用后，进行反思复盘。"

        response_text = ""

        for iteration in range(1, max_iterations + 1):
            # FIX(自循环): 协作式取消检查点 — 让外部 task.cancel() 能及时生效
            if asyncio.current_task() is not None and asyncio.current_task().cancelled():
                return

            pct = int(iteration / max_iterations * 100)
            yield {
                "type": "status",
                "status": "thinking",
                "iteration": iteration,
                "max": max_iterations,
                "progress_pct": pct,
            }

            # 1. LLM 调用
            if iteration == 1:
                prompt = analysis_prompt
            elif last_iteration_had_tools:
                prompt = (
                    "以上是工具执行结果。如需继续请输出 JSON 工具调用。" "已完成请直接输出总结。"
                )
            else:
                # 上一轮没有工具调用 → 用强制指令
                prompt = (
                    "【紧急】你上一轮没有调用任何工具！"
                    "你必须以 JSON 格式直接输出工具调用，不要输出任何文字。\n"
                    '正确格式: {"tool_calls": [{"name": "list_files", '
                    '"params": {"path": "."}}]}\n'
                    '可以同时调多个: {"tool_calls": [{"name": "A", '
                    '"params": {}}, {"name": "B", "params": {}}]}'
                )

            # V2.1: 注入 LSP 诊断到 prompt (Phase 2.2)
            # 仅在 iteration > 1 且有写入文件时注入诊断
            if iteration > 1 and written_files:
                try:
                    diag_prompt = self._diagnostic_fixer.get_diagnostics_prompt()
                    if diag_prompt:
                        prompt = (
                            f"{prompt}\n\n---\n"
                            f"## 代码诊断反馈\n"
                            f"{diag_prompt}\n"
                            f"请优先修复上述错误，然后继续完成任务。"
                        )
                except Exception as e:
                    logger.debug("diagnostic_inject_failed: %s", e)
            # 每3步添加反思提示
            if strategy.enable_rumination and iteration > 1 and iteration % 3 == 0:
                self._rumination_count += 1
                prompt += (
                    f"\n\n---\n### 反思复盘（第{self._rumination_count}次）\n"
                    "1. 当前进展是否对齐原始目标？\n"
                    "2. 最近几步是否有冗余或错误？\n"
                    "3. 有没有更简单的替代方案？\n"
                    "请基于以上反思继续执行或调整策略。"
                )

            response_text = ""
            try:
                async for event in bridge.stream(prompt):
                    if event.event_type == "token":
                        response_text += event.content
                    elif event.event_type == "error":
                        yield {"type": "error", "message": event.content}
                        return
                    elif event.event_type == "done":
                        response_text = event.content or response_text
            except Exception as e:
                yield {"type": "error", "message": f"LLM 调用失败: {e}"}
                return

            if not response_text:
                # FIX(自循环): 连续空响应计数 + 提前终止，避免无限消耗迭代
                consecutive_empty_count += 1
                # 不再用 assistant 角色注入提示（会污染上下文让 LLM 误以为自己说过）
                logger.warning(
                    "agent_loop_empty_response iteration=%d/%d consecutive=%d",
                    iteration,
                    max_iterations,
                    consecutive_empty_count,
                )
                if consecutive_empty_count >= MAX_CONSECUTIVE_EMPTY:
                    yield {
                        "type": "agent_result",
                        "status": "done",
                        "summary": (
                            "## ⚠️ 任务终止：LLM 连续返回空响应\n"
                            f"已连续 {consecutive_empty_count} 次空响应，"
                            "可能是模型异常或上下文过大。请重试或切换模型。"
                        ),
                        "iterations": iteration,
                        "tool_count": len(all_tool_calls),
                        "files_written": written_files,
                    }
                    return
                # 用 user 角色注入提示，明确告知这是系统消息而非助手自述
                bridge.add_message(
                    "user",
                    "（系统提示：上一轮 LLM 返回了空响应，请尝试用不同方式完成任务或确认是否已完成。）",
                )
                last_iteration_had_tools = False
                continue
            else:
                consecutive_empty_count = 0  # 重置连续空响应计数

            # 2. 统一解析
            parsed = parse_response(response_text)

            # P0/P1: 首轮/次轮无工具调用不得判定为完成
            if not parsed.tool_calls and not parsed.file_blocks:
                if iteration == 1:
                    parsed.completion = False
                    logger.info(
                        "agent_loop_p0_no_tools_and_no_files iteration=1 len=%d", len(response_text)
                    )
                elif iteration == 2:
                    parsed.completion = False
                    logger.info(
                        "agent_loop_p1_no_tools_and_no_files iteration=2 len=%d", len(response_text)
                    )

            # 3. 完成信号检测
            if parsed.completion:
                done_result = {
                    "type": "agent_result",
                    "status": "done",
                    "summary": parsed.summary or response_text[:500],
                    "iterations": iteration,
                    "tool_count": len(all_tool_calls),
                    "files_written": written_files,
                }
                if decision:
                    done_result["routing"] = decision.to_dict()

                # V2: 记录反馈
                self._record_feedback(
                    decision,
                    session_id,
                    completed=True,
                    reason="done",
                    iterations=iteration,
                    tool_calls=len(all_tool_calls),
                    tool_success=tool_success_count,
                    execution_time_ms=(time.monotonic() - start_time) * 1000,
                )

                yield done_result
                return

            # 4. 处理代码块（自动写入文件）
            for fblock in parsed.file_blocks:
                try:
                    target = (self.workspace / fblock["path"]).resolve()
                    if target.is_relative_to(self.workspace):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(fblock["content"], encoding="utf-8")
                        written_files.append(fblock["path"])
                        logger.info(
                            "agent_wrote_file path=%s size=%d",
                            fblock["path"],
                            len(fblock["content"]),
                        )
                except (OSError, ValueError) as e:
                    logger.warning(
                        "agent_write_failed path=%s error=%s",
                        fblock["path"],
                        e,
                    )

            # 4.5. 追踪写入的文件 → 诊断自动修复 (Phase 2.2)
            if written_files:
                try:
                    self._diagnostic_fixer.track_files(written_files)
                except Exception as e:
                    logger.debug("diagnostic_track_failed: %s", e)

            # 4.6. 自动应用安全修复 (Phase 2.2)
            # 仅在 auto_apply_fixes=True 时执行, 且需要已有注册的修复处理器
            if auto_apply_fixes and written_files:
                try:
                    applied = self._diagnostic_fixer.auto_apply_safe_fixes(
                        file_paths=written_files,
                    )
                    if applied:
                        logger.info(
                            "auto_apply_safe_fixes applied=%d",
                            len(applied),
                        )
                        yield {
                            "type": "auto_fix_applied",
                            "count": len(applied),
                            "fixes": applied,
                        }
                except Exception as e:
                    logger.debug("auto_apply_safe_fixes_failed: %s", e)

            # 5. 处理工具调用
            if not parsed.tool_calls:
                # 没有工具调用也没有代码块，检查是否应继续
                if parsed.file_blocks:
                    # 写了文件但没有工具调用，继续下一轮
                    last_iteration_had_tools = False
                    continue
                # FIX(自循环): 连续无工具调用计数
                consecutive_no_tool_count += 1
                # P0: 首轮无工具调用 → 注入强制指令继续循环
                if iteration == 1:
                    p0_msg = (
                        "(系统提示：上一轮输出没有包含任何 JSON 工具调用。"
                        '你必须以 {"tool_calls": [...]} 格式输出工具调用。'
                        "不要用文字描述你要做什么，直接输出 JSON 格式的工具调用。"
                        '例如：{"tool_calls": [{"name": "list_files", "params": {"path": "."}}, '
                        '{"name": "git_status", "params": {}}]}'
                        "这是第一次警告。)"
                    )
                    # FIX(自循环): 用 user 角色注入，避免污染 assistant 上下文
                    bridge.add_message("user", p0_msg)
                    logger.warning("agent_loop_p0_no_json_toolcalls iteration=1")
                    last_iteration_had_tools = False
                    continue
                elif iteration == 2:
                    p1_msg = (
                        "(第二次警告：你仍然没有调用任何工具！"
                        "你被设计为必须使用 JSON 格式调用工具。"
                        "输出格式必须是："
                        '{"tool_calls": [{"name": "工具名", "params": {}}]}'
                        "不要输出任何文字描述，直接输出 JSON。"
                        "如果第三次仍然不调用工具，任务将标记为失败。)"
                    )
                    bridge.add_message("user", p1_msg)
                    logger.warning("agent_loop_p1_no_json_toolcalls iteration=2")
                    last_iteration_had_tools = False
                    continue

                # FIX(自循环): 连续 MAX_CONSECUTIVE_NO_TOOL 轮无工具调用 → 提前终止
                if consecutive_no_tool_count >= MAX_CONSECUTIVE_NO_TOOL:
                    yield {
                        "type": "agent_result",
                        "status": "done",
                        "summary": (
                            "## ⚠️ 任务终止：连续无工具调用\n"
                            f"已连续 {consecutive_no_tool_count} 轮未调用工具，"
                            "判定为对话已偏离 Agent 模式。可重新发起任务或切换模型。"
                        ),
                        "iterations": iteration,
                        "tool_count": len(all_tool_calls),
                        "files_written": written_files,
                    }
                    return

                # 既没有工具也没有代码块，视为完成
                done_result = {
                    "type": "agent_result",
                    "status": "done",
                    "summary": response_text[:500],
                    "iterations": iteration,
                    "tool_count": len(all_tool_calls),
                    "files_written": written_files,
                }
                if decision:
                    done_result["routing"] = decision.to_dict()

                self._record_feedback(
                    decision,
                    session_id,
                    completed=True,
                    reason="done_no_tools",
                    iterations=iteration,
                    tool_calls=len(all_tool_calls),
                    tool_success=tool_success_count,
                    execution_time_ms=(time.monotonic() - start_time) * 1000,
                )

                yield done_result
                return

            # 6. 执行工具
            # FIX(自循环): 改用局部变量，避免跨调用残留状态
            last_iteration_had_tools = bool(parsed.tool_calls)
            consecutive_no_tool_count = 0  # 重置连续无工具调用计数
            yield {
                "type": "status",
                "status": "executing",
                "iteration": iteration,
                "max": max_iterations,
                "progress_pct": int(iteration / max_iterations * 100),
                "tool_calls": [tc["name"] for tc in parsed.tool_calls],
            }

            # 区分读写操作
            writers = [tc for tc in parsed.tool_calls if tc["name"] in WRITE_SAFE_TOOLS]
            readers = [tc for tc in parsed.tool_calls if tc["name"] not in WRITE_SAFE_TOOLS]

            # 写操作：严格串行
            for tc in writers:
                ok, err = validate_tool_call(tc)
                if not ok:
                    yield {"type": "tool_result", "tool_name": tc["name"], "result": f"❌ {err}"}
                    tool_failure_count += 1
                    continue

                all_tool_calls.append(tc)
                try:
                    result = await execute_agent_tool(
                        tc["name"],
                        tc.get("params", {}),
                        self.workspace,
                        timeout=timeout,
                    )
                    all_results.append(str(result))
                    tool_success_count += 1
                    yield {
                        "type": "tool_result",
                        "tool_name": tc["name"],
                        "result": str(result)[:500],
                        "iteration": iteration,
                    }
                    # 更新桥接消息上下文
                    bridge.add_message(
                        "assistant",
                        f"工具 {tc['name']} 结果:\n{str(result)[:1000]}",
                    )
                except Exception as e:
                    err_msg = f"❌ 工具执行失败: {e}"
                    yield {"type": "tool_result", "tool_name": tc["name"], "result": err_msg}
                    bridge.add_message("assistant", err_msg)
                    tool_failure_count += 1

            # 读操作：并行执行
            if readers:

                async def _execute_one(tc: dict) -> tuple[str, str | None, bool]:
                    ok, err = validate_tool_call(tc)
                    if not ok:
                        return tc["name"], f"❌ {err}", False
                    try:
                        r = await execute_agent_tool(
                            tc["name"],
                            tc.get("params", {}),
                            self.workspace,
                            timeout=timeout,
                        )
                        return tc["name"], str(r), True
                    except Exception as e:
                        return tc["name"], f"❌ 工具执行失败: {e}", False

                read_tasks = [_execute_one(tc) for tc in readers]
                for coro in asyncio.as_completed(read_tasks):
                    tool_name, result, success = await coro
                    all_tool_calls.append({"name": tool_name, "params": {}})
                    all_results.append(result or "")
                    if success:
                        tool_success_count += 1
                    else:
                        tool_failure_count += 1
                    # M9: list_agent_configs 等大型列表需要更大的截断上限
                    result_str = result or ""
                    max_preview = 2000 if tool_name == "list_agent_configs" else 500
                    max_context = 5000 if tool_name == "list_agent_configs" else 1000
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result_str[:max_preview],
                        "iteration": iteration,
                    }
                    bridge.add_message(
                        "assistant",
                        f"工具 {tool_name} 结果:\n{result_str[:max_context]}",
                    )

        # 达到最大迭代次数
        max_iter_result = {
            "type": "agent_result",
            "status": "completed",
            "summary": (
                f"## ✅ 任务执行完成\n"
                f"- 迭代次数: {max_iterations}\n"
                f"- 工具调用: {len(all_tool_calls)} 次\n"
                f"- 写入文件: {len(written_files)} 个\n"
                f"\n{response_text[:800] if response_text else '已达最大迭代次数，部分任务可能未完成。'}"
            ),
            "iterations": max_iterations,
            "tool_count": len(all_tool_calls),
            "files_written": written_files,
        }
        if decision:
            max_iter_result["routing"] = decision.to_dict()

        # V2: 记录反馈
        self._record_feedback(
            decision,
            session_id,
            completed=False,
            reason="max_iterations",
            iterations=max_iterations,
            tool_calls=len(all_tool_calls),
            tool_success=tool_success_count,
            execution_time_ms=(time.monotonic() - start_time) * 1000,
        )

        yield max_iter_result

    # ═══════════════════════════════════════════════════
    # V2: 反馈学习辅助方法
    # ═══════════════════════════════════════════════════

    async def chat_stream_with_evolution(
        self,
        message: str,
        bridge,
        context: str = "",
        session_id: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[dict]:
        """包装 chat_stream 并自动记录到 Self-Evolution 引擎

        每次 Agent 执行完成后 (无论成功或失败), 自动调用
        `self_evolution_engine.record_agent_execution()` 记录执行信号。

        Args:
            message: 用户消息
            bridge: LLM 桥接
            context: 上下文
            session_id: 会话 ID
            **kwargs: 透传给 chat_stream

        Yields:
            chat_stream 的事件流
        """
        start_time = time.monotonic()
        tools_used: list[str] = []
        success = False
        error_msg: str | None = None

        try:
            async for event in self.chat_stream(
                message,
                bridge,
                context=context,
                session_id=session_id,
                **kwargs,
            ):
                # 记录工具使用
                if event.get("type") == "tool_result":
                    tool_name = event.get("tool_name")
                    if tool_name and tool_name not in tools_used:
                        tools_used.append(tool_name)
                # 记录最终状态
                if event.get("type") == "agent_result":
                    status = event.get("status", "")
                    success = status in ("done", "completed")
                yield event
        except Exception as e:
            error_msg = str(e)
            logger.warning("chat_stream_with_evolution error: %s", e)
            raise
        finally:
            # 记录到 Self-Evolution 引擎
            if self._self_evo is not None:
                try:
                    duration_ms = (time.monotonic() - start_time) * 1000
                    self._self_evo.record_agent_execution(
                        session_id=session_id or "unknown",
                        success=success,
                        duration_ms=duration_ms,
                        tools_used=tools_used,
                        error=error_msg,
                    )
                except Exception as e:
                    logger.debug("self_evo_record_failed: %s", e)

    def _record_feedback(
        self,
        decision: RoutingDecision | None,
        session_id: str,
        completed: bool,
        reason: str,
        iterations: int,
        tool_calls: int,
        tool_success: int,
        execution_time_ms: float,
    ) -> None:
        """记录执行反馈到反馈学习循环"""
        if not decision or not self._enable_intelligent_routing:
            return

        try:
            signal = self._feedback.start_signal(
                session_id=session_id,
                intent=decision.intent,
                agent=decision.agent,
                tool_plan=decision.tool_plan,
                strategy=decision.execution_config.strategy,
                max_iterations=decision.execution_config.max_iterations,
            )
            self._feedback.end_signal(
                signal,
                completed=completed,
                completion_reason=reason,
                iterations=iterations,
                tool_calls=tool_calls,
                tool_success=tool_success,
                tool_failure=tool_calls - tool_success,
                execution_time_ms=execution_time_ms,
            )
            self._last_signal = signal  # 保存供后续用户评分使用
        except Exception as e:
            logger.debug("feedback_record_failed: %s", e)

    def record_user_rating(
        self,
        rating: int,
        text: str = "",
        reaction: str = "",
        session_id: str = "",
    ) -> None:
        """记录用户反馈评分（关联到最近一次执行）"""
        try:
            signal = self._last_signal
            if signal is None:
                signal = self._feedback.start_signal(session_id=session_id)
            self._feedback.record_user_rating(
                signal=signal,
                rating=rating,
                text=text,
                reaction=reaction,
            )
        except Exception as e:
            logger.debug("user_rating_record_failed: %s", e)

    def get_feedback_stats(self) -> Any:
        """获取反馈统计"""
        return self._feedback.get_stats()

    def get_feedback_recommendations(self) -> list[str]:
        """获取优化建议"""
        return self._feedback.get_recommendations()
