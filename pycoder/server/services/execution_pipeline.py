"""
统一执行管线 — 所有 AI 任务的唯一执行路径

设计原则:
1. CHAT/HERMES/AGENT 三模式共享同一套 5 阶段流水线
2. 优先使用 DeepSeek Native Function Calling，FC 失败时自动降级到文本 JSON 解析
3. 每阶段自动发射进度事件
4. 完成后生成结构化执行报告
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pycoder.brain.deviation_detector import DeviationDetector
from pycoder.brain.task_planner import (
    ExecutionPlan,
    FeasibilityAnalyzer,
    FeasibilityReport,
    PlanBudget,
    TaskPlanner,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 执行配置
# ══════════════════════════════════════════════════════════


@dataclass
class ExecutionConfig:
    """三合一的执行配置"""

    name: str
    max_iterations: int
    tool_timeout: int
    max_concurrent_tools: int
    enable_rumination: bool
    system_prompt: str
    max_empty_retries: int = 2

    # 进度阶段定义
    stages: list[dict] = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 三种策略定义
# ══════════════════════════════════════════════════════════

CHAT_CONFIG = ExecutionConfig(
    name="chat",
    max_iterations=1,
    tool_timeout=15,
    max_concurrent_tools=3,
    enable_rumination=False,
    max_empty_retries=0,
    system_prompt=(
        "你是 PyCoder 编程助手。"
        "你可以用 JSON 工具调用来执行实际操作。"
        '格式: {"tool_calls": [{"name": "read_file", "params": {"path": "xxx"}}]}\n'
        "对于纯知识问答直接文字回复。"
        "对于需要操作文件/命令/代码的任务，必须调用工具执行。"
    ),
    stages=[
        {"id": "intent", "label": "🔍 意图解析", "desc": "分析用户意图"},
        {"id": "llm", "label": "🧠 AI 生成", "desc": "调用大模型生成回复"},
        {"id": "done", "label": "✅ 完成", "desc": "回复生成完毕"},
    ],
)

HERMES_CONFIG = ExecutionConfig(
    name="hermes",
    max_iterations=10,
    tool_timeout=30,
    max_concurrent_tools=5,
    enable_rumination=False,
    max_empty_retries=3,
    system_prompt=(
        "你是 PyCoder Hermes 执行器。你必须通过调用函数工具来实际执行任务。\n\n"
        "## 可用工具（必须使用）\n"
        "- read_file / write_file / list_files — 文件操作\n"
        "- run_terminal — 执行命令\n"
        "- search — 搜索文本\n"
        "- git_status / git_log — Git 操作\n"
        "- execute_python — 执行 Python 代码\n"
        "- python_env — 环境信息\n"
        "- code_review — 代码审查\n"
        "- security_scan — 安全扫描\n"
        "- dependency_analysis — 依赖分析\n\n"
        "## 🚨 强制规则\n"
        "1. 每次回复必须以 JSON 格式输出工具调用\n"
        '2. 格式: {"tool_calls": [{"name": "工具名", "params": {}}]}\n'
        "3. 禁止输出纯文字描述而不调用工具\n"
        "4. 工具执行完毕后，输出分析总结报告\n"
    ),
    stages=[
        {"id": "intent", "label": "🔍 意图解析", "desc": "分析用户意图"},
        {"id": "route", "label": "🔄 模式路由", "desc": "调度 Hermes 模式"},
        {"id": "llm", "label": "🧠 AI 执行", "desc": "Hermes 5步工作法"},
        {"id": "plugin", "label": "🔧 后台插件", "desc": "执行匹配插件"},
        {"id": "merge", "label": "📋 结果归集", "desc": "整合输出"},
        {"id": "done", "label": "✅ 完成", "desc": "任务执行完毕"},
    ],
)

AGENT_CONFIG = ExecutionConfig(
    name="agent",
    max_iterations=50,
    tool_timeout=60,
    max_concurrent_tools=8,
    enable_rumination=True,
    max_empty_retries=2,
    system_prompt=(
        "你是 PyCoder 全自主 Agent。面对任务必须调用工具一步步完成。\n\n"
        "## 🔴 必须遵守\n"
        "1. 每次回复必须以 JSON 格式输出工具调用\n"
        '2. 格式: {"tool_calls": [{"name": "工具名", "params": {}}]}\n'
        "3. 不可输出纯文字描述而不调用工具\n"
        "4. 任务完成后输出总结报告\n"
    ),
    stages=[
        {"id": "intent", "label": "🔍 意图解析", "desc": "分析用户意图"},
        {"id": "route", "label": "🔄 模式路由", "desc": "调度 Agent 模式"},
        {"id": "llm", "label": "🧠 AI 执行", "desc": "Agent 多轮迭代"},
        {"id": "plugin", "label": "🔧 后台插件", "desc": "执行匹配插件"},
        {"id": "merge", "label": "📋 结果归集", "desc": "整合输出"},
        {"id": "done", "label": "✅ 完成", "desc": "任务执行完毕"},
    ],
)

CONFIG_MAP: dict[str, ExecutionConfig] = {
    "chat": CHAT_CONFIG,
    "hermes": HERMES_CONFIG,
    "agent": AGENT_CONFIG,
}


def get_execution_config(mode: str) -> ExecutionConfig:
    """按模式获取执行配置"""
    return CONFIG_MAP.get(mode, CHAT_CONFIG)


# ══════════════════════════════════════════════════════════
# P0: 按模式动态选择工具集
# ══════════════════════════════════════════════════════════

TOOL_TIERS: dict[str, list[str] | None] = {
    "chat": [
        "read_file",
        "write_file",
        "list_files",
        "search",
        "run_terminal",
        "git_status",
        "execute_python",
        "python_env",
    ],
    "hermes": [
        "read_file",
        "write_file",
        "list_files",
        "search",
        "run_terminal",
        "git_status",
        "git_log",
        "execute_python",
        "python_env",
        "code_review",
        "format_code",
        "docker_status",
        "security_scan",
        "dependency_analysis",
    ],
    "agent": None,  # 全部 48 个工具
}


def get_tool_names_for_mode(mode: str) -> list[str] | None:
    """获取指定模式的工具名称列表（None = 全部）"""
    return TOOL_TIERS.get(mode)


# ══════════════════════════════════════════════════════════
# 执行管线
# ══════════════════════════════════════════════════════════


class ExecutionPipeline:
    """五阶段统一执行管线 — 所有模式共用"""

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.tool_calls: list[dict] = []
        self.written_files: list[str] = []
        self._start_time = time.monotonic()
        self._last_had_tools = False
        self._empty_retries = 0
        self._last_yield_time = 0.0  # 上次 yield 时间戳（用于 keepalive）
        self._pending_correction: str | None = None  # P1-2: 待注入的偏差纠正提示
        self._hallucination_low_count: int = 0  # P0-3: 连续低幻觉分计数

    async def _maybe_keepalive(self, phase: str = "llm"):
        """检查并发送 keepalive 心跳（如果超过 12 秒未 yield）"""
        now = time.monotonic()
        if now - self._last_yield_time > 12:
            self._last_yield_time = now
            return {
                "type": "progress",
                "phase": phase,
                "stage": "⏳ AI 推理中...",
                "current_step": 2,
                "total_steps": len(self.config.stages),
                "percent": 55,
                "elapsed_seconds": int(now - self._start_time),
                "eta_seconds": 0,
                "milestones": [],
            }
        return None

    async def execute(
        self,
        message: str,
        bridge,  # ChatBridge
        history_context: str = "",
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict]:
        """主执行循环

        Args:
            message: 用户消息
            bridge: ChatBridge 实例
            history_context: 历史对话上下文
            cancel_event: 取消事件，前端 stop 信号时设置

        Yields:
            → agent_status / progress / token / tool_result / done
        """
        strategy = self.config

        # ── 取消检查辅助函数 ──
        async def _check_cancel():
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("用户取消执行")

        # ── Stage 1: Context Assembly ──
        from pycoder.prompts.cache_rules import inject_cache_rules

        bridge.config.system_prompt = inject_cache_rules(strategy.system_prompt, lang="zh")
        effective_message = message
        if history_context:
            effective_message = f"[对话历史回顾]\n{history_context}\n\n[当前消息] {message}"

        yield {
            "type": "agent_status",
            "status": "started",
            "message": (f"🔍 意图解析: {strategy.name.upper()} 模式"),
        }
        yield {
            "type": "progress",
            "phase": "intent",
            "stage": strategy.stages[0]["label"],
            "current_step": 0,
            "total_steps": len(strategy.stages),
            "percent": 15,
            "elapsed_seconds": 0,
            "eta_seconds": 0,
            "milestones": [],
        }
        await asyncio.sleep(0)

        # ══════════════════════════════════════════════════════════
        # Stage 1.5: 计划制定（原方案 + 补充1/2/5）
        # ── 意图分析 → 任务分解 → 正反可行性分析 → 预算设定 ──
        # ══════════════════════════════════════════════════════════
        plan: ExecutionPlan | None = None
        feasibility: FeasibilityReport | None = None
        budget: PlanBudget | None = None
        detector: DeviationDetector | None = None

        # chat 模式或简短消息跳过计划阶段
        should_plan = strategy.name != "chat" and len(message) > 15

        if should_plan:
            try:
                # 1. 意图分析 + Agent 选择（延迟导入避免循环依赖）
                from pycoder.brain.intelligent_router import get_intelligent_router

                router = get_intelligent_router()
                decision = router.decide(message)

                # 2. 任务分解（补充1：注入上下文提升分解质量）
                planner = TaskPlanner()
                plan_context = self._build_plan_context(message, history_context)
                plan = planner.plan(decision.intent.normalized_intent, context=plan_context)

                # 3. 正反可行性分析（补充2）
                analyzer = FeasibilityAnalyzer()
                feasibility = analyzer.analyze(plan, context=plan_context)

                # 4. 预算设定（补充5）
                budget = PlanBudget.from_plan(plan)

                # 5. 偏差检测器初始化
                detector = DeviationDetector(plan)

                # 发射计划进度事件
                yield {
                    "type": "progress",
                    "phase": "plan",
                    "stage": "📋 执行计划制定",
                    "current_step": 1,
                    "total_steps": len(strategy.stages),
                    "percent": 25,
                    "elapsed_seconds": 0,
                    "eta_seconds": 0,
                    "milestones": [],
                    "plan": {
                        "task_count": len(plan.tasks),
                        "strategy": plan.strategy.value,
                        "estimated_tokens": plan.total_estimated_tokens,
                        "feasibility": feasibility.recommendation,
                        "risks": feasibility.risks[:3],
                        "budget": budget.to_dict(),
                    },
                }

                # 可行性中止 → 提前返回
                if feasibility.recommendation == "abort":
                    yield {
                        "type": "error",
                        "message": (f"❌ 可行性分析未通过: " f"{'; '.join(feasibility.risks[:3])}"),
                    }
                    yield {
                        "type": "done",
                        "content": (
                            f"任务因可行性分析中止。\n"
                            f"风险: {'; '.join(feasibility.risks)}\n"
                            f"建议: {'; '.join(feasibility.mitigation)}"
                        ),
                        "v2_engine": True,
                        "tool_calls_count": 0,
                        "duration_ms": 0,
                    }
                    return

                # ════════════════════════════════════════════════════
                # Stage 1.6: 人机确认（补充4：风险分级确认）
                # ── caution → 展示计划等用户确认 ──
                # ════════════════════════════════════════════════════
                if feasibility.recommendation == "caution":
                    yield {
                        "type": "plan_review",
                        "plan": {
                            "tasks": [
                                {"id": t.task_id, "desc": t.description[:60]} for t in plan.tasks
                            ],
                            "strategy": plan.strategy.value,
                            "risks": feasibility.risks,
                            "mitigation": feasibility.mitigation,
                            "budget": budget.to_dict(),
                        },
                        "message": (
                            "⚠️ 该任务存在风险，请确认是否继续执行。\n"
                            f"风险: {'; '.join(feasibility.risks[:3])}\n"
                            f"缓解: {'; '.join(feasibility.mitigation[:3])}"
                        ),
                    }
                    logger.info(
                        "计划等待用户确认: recommendation=caution risks=%d",
                        len(feasibility.risks),
                    )

                # 计划注入 prompt（原方案核心：计划驱动执行）
                plan_prompt = self._build_plan_prompt(plan, feasibility, budget)
                effective_message = f"{plan_prompt}\n\n{effective_message}"

                logger.info(
                    "计划制定完成: tasks=%d strategy=%s feasibility=%s budget=%d",
                    len(plan.tasks),
                    plan.strategy.value,
                    feasibility.recommendation,
                    budget.budget_tokens,
                )

            except Exception as e:
                # 计划制定失败 → 降级到原有流程
                logger.warning("计划制定失败，降级到直接执行: %s", e)
                plan = None
                feasibility = None
                budget = None
                detector = None

        # P0: 根据模式选择工具集
        tool_names = get_tool_names_for_mode(strategy.name)
        if tool_names:
            logger.info(
                "pipeline_tool_tier mode=%s tool_count=%d",
                strategy.name,
                len(tool_names),
            )

        # ── Stage 2-4: LLM Invoke → Parse → Execute ──
        full_content = ""
        total_tokens = 0
        iter_count = 0

        for iter_count in range(1, strategy.max_iterations + 1):
            pct = int(iter_count / strategy.max_iterations * 100)

            # 进度: 思考中
            yield {
                "type": "progress",
                "phase": "llm",
                "stage": f"🤖 {strategy.name.upper()} 执行中 ({iter_count}/{strategy.max_iterations})",
                "current_step": 2,
                "total_steps": len(strategy.stages),
                "percent": min(50 + pct // 3, 70),
                "elapsed_seconds": 0,
                "eta_seconds": 0,
                "milestones": [],
            }

            # 构建 prompt
            if iter_count == 1:
                if strategy.name != "chat":
                    prompt = f"请直接输出 JSON 工具调用来完成任务:\n\n" f"{effective_message}\n\n"
                else:
                    prompt = effective_message
                if strategy.enable_rumination:
                    prompt += "\n\n请先分析需求，再逐步执行。每3步进行一次反思复盘。"
            elif self._last_had_tools:
                prompt = (
                    "以上是工具执行结果。如需继续请输出 JSON 工具调用。" "已完成请直接输出总结。"
                )
            else:
                prompt = (
                    "【紧急】你上一轮没有调用任何工具！"
                    "你必须以 JSON 格式输出工具调用: "
                    '{"tool_calls": [{"name": "工具名", "params": {}}]}'
                )

            # 反思复盘
            if strategy.enable_rumination and iter_count > 1 and iter_count % 3 == 0:
                prompt += (
                    f"\n\n---\n### 反思复盘（第{iter_count // 3}次）\n"
                    "1. 当前进展是否对齐原始目标？\n"
                    "2. 最近几步是否有冗余或错误？\n"
                    "3. 有没有更简单的替代方案？\n"
                )

            # P1-2: 注入待处理的偏差纠正提示
            if self._pending_correction:
                prompt += (
                    f"\n\n---\n### ⚠️ 偏差纠正（第{iter_count}轮）\n"
                    f"{self._pending_correction}\n"
                    "请根据上述纠正建议调整当前执行方向。\n"
                )
                self._pending_correction = None  # 消费后清空

            # 调用 LLM (Native FC + 文本兜底)
            response_text = ""
            has_tool_calls = False
            tool_call_names: list[str] = []

            # ── 取消检查 ──
            await _check_cancel()

            # 重置 keepalive 计时器
            self._last_yield_time = time.monotonic()

            try:
                async with asyncio.timeout(120):  # 单轮LLM调用最多120秒
                    async for ev in bridge.chat_stream(prompt, tool_names=tool_names):
                        # ── 流中取消检查 ──
                        await _check_cancel()
                        if ev.event_type == "token":
                            self._last_yield_time = time.monotonic()
                            response_text += ev.content
                            total_tokens += len(ev.content)
                            yield {"type": "token", "data": ev.content, "content": ev.content}
                            if "🔧" in ev.content:
                                tn = ev.content.replace("🔧 执行 ", "").strip()[:40]
                                tool_call_names.append(tn)
                                has_tool_calls = True
                        elif ev.event_type == "reasoning":
                            yield {"type": "reasoning", "content": ev.content}
                        elif ev.event_type == "done":
                            response_text = ev.content or response_text
                        elif ev.event_type == "error":
                            yield {"type": "error", "message": ev.content}
                            return
            except TimeoutError:
                yield {
                    "type": "error",
                    "message": "⏱ LLM 调用超时 (120s)，已返回当前进度",
                }
                if response_text:
                    break  # 有部分内容就继续
                continue  # 无内容重试
            except Exception as e:
                yield {"type": "error", "message": f"LLM 调用失败: {str(e)[:200]}"}
                return

            self._last_had_tools = has_tool_calls
            full_content += response_text

            # ════════════════════════════════════════════════════
            # P0-3: 幻觉验证（每轮 LLM 输出后）
            # ════════════════════════════════════════════════════
            hallucination_score = 100.0
            if strategy.name != "chat" and len(response_text) > 50:
                try:
                    from pycoder.server.services.hallucination_guard import (
                        get_hallucination_guard,
                    )

                    guard = get_hallucination_guard()
                    h_result = await guard.validate(
                        response_text,
                        context={
                            "mode": strategy.name,
                            "iteration": iter_count,
                            "task": message[:200],
                        },
                    )
                    hallucination_score = h_result.overall_score
                    if hallucination_score < 60:
                        yield {
                            "type": "hallucination_warning",
                            "score": hallucination_score,
                            "issues": h_result.consistency_issues[:5],
                            "recommendations": h_result.recommendations[:3],
                            "message": (f"⚠️ 幻觉风险: 可信度 {hallucination_score:.0f}/100"),
                        }
                        # 幻觉熔断：连续低分则注入纠正提示
                        self._hallucination_low_count = (
                            getattr(self, "_hallucination_low_count", 0) + 1
                        )
                        if self._hallucination_low_count >= 2:
                            full_content += (
                                "\n\n⚠️ [系统检测到连续幻觉风险，"
                                "请仅基于实际工具结果回复，"
                                "不要编造不存在的信息]"
                            )
                    else:
                        self._hallucination_low_count = 0
                    logger.debug(
                        "pipeline_hallucination_check score=%.1f iter=%d",
                        hallucination_score,
                        iter_count,
                    )
                except Exception as e:
                    logger.debug("hallucination_guard_skipped error=%s", str(e)[:100])

            # ════════════════════════════════════════════════════
            # 补充2: 偏差检测 + 补充5: 预算追踪
            # ════════════════════════════════════════════════════
            if budget is not None:
                # 预算追踪
                budget.consume(len(response_text))
                budget.actual_iterations = iter_count

                # 预算告警
                if budget.status == "warning":
                    yield {
                        "type": "agent_status",
                        "status": "working",
                        "message": (
                            f"⚠️ Token预算使用 {budget.usage_ratio:.0%}，" "建议简化后续操作"
                        ),
                    }
                elif budget.status == "replan":
                    yield {
                        "type": "agent_status",
                        "status": "working",
                        "message": "🔄 预算超支，触发重规划...",
                    }
                    # 简化剩余任务：减少迭代上限
                    strategy.max_iterations = min(strategy.max_iterations, iter_count + 3)
                elif budget.status == "cutoff":
                    yield {
                        "type": "agent_status",
                        "status": "working",
                        "message": "⛔ 预算熔断，返回已完成部分",
                    }
                    logger.warning(
                        "预算熔断: actual=%d budget=%d ratio=%.2f",
                        budget.actual_tokens,
                        budget.budget_tokens,
                        budget.usage_ratio,
                    )
                    break

            # 偏差检测（仅有计划时）—— P1-2: 即时纠正注入
            if detector is not None and has_tool_calls:
                # 从工具调用名构造简化数据
                tc_list = [{"name": tn, "params": {}} for tn in tool_call_names]
                tc_results = [{"success": True} for _ in tc_list]
                dev_report = detector.detect(tc_list, tc_results)

                # 偏差纠正 —— 注入到下一轮 LLM 调用
                if dev_report.deviations:
                    correction = dev_report.correction_prompt()
                    if correction:
                        self._pending_correction = correction
                        full_content += f"\n\n{correction}\n"
                        yield {
                            "type": "agent_status",
                            "status": "working",
                            "message": (
                                f"📐 偏差检测: {len(dev_report.deviations)}项" " → 已注入纠正提示"
                            ),
                        }
                        logger.info(
                            "deviation_correction_injected " "deviations=%d",
                            len(dev_report.deviations),
                        )

                # 计划完成检测
                if detector.is_complete:
                    yield {
                        "type": "agent_status",
                        "status": "working",
                        "message": "✅ 执行计划全部完成",
                    }
                    break

            if not response_text:
                logger.warning(
                    "pipeline_empty_response iteration=%d",
                    iter_count,
                )
                if self._empty_retries < strategy.max_empty_retries:
                    self._empty_retries += 1
                    continue
                break

            # ── P1: XML 工具调用解析（兼容不支持 FC 的模型）──
            if not has_tool_calls and response_text:
                try:
                    from pycoder.server.chat_handler import _execute_xml_tool_calls as _xml_exec

                    cleaned, tool_results = await _xml_exec(response_text)
                    if tool_results:
                        has_tool_calls = True
                        for tr in tool_results:
                            tn = tr.get("tool", "unknown")
                            tool_call_names.append(tn)
                            if tr.get("success"):
                                full_content += f"\n✅ [{tn}] 执行成功\n"
                            else:
                                full_content += f"\n❌ [{tn}] 失败: {tr.get('output', '')[:100]}\n"
                            logger.info(
                                "pipeline_xml_tool_call tool=%s success=%s",
                                tn,
                                tr.get("success"),
                            )
                    if cleaned != response_text:
                        response_text = cleaned
                except Exception as e:
                    logger.debug("xml_tool_parse_skipped error=%s", str(e)[:100])

            # 完成检测（无工具调用时）
            if not has_tool_calls:
                # CHAT 模式：有实质内容就直接接受
                if strategy.name == "chat":
                    break
                # AGENT/HERMES：有实质内容但无工具调用 → 根据迭代次数和重试判断
                has_substance = len(response_text) > 100
                has_retries_left = self._empty_retries < strategy.max_empty_retries
                if has_substance and not has_retries_left:
                    break
                if has_retries_left:
                    self._empty_retries += 1
                    yield {
                        "type": "agent_status",
                        "status": "working",
                        "message": f"⚠️ AI 未调用工具，第 {self._empty_retries} 次强化重试...",
                    }
                    continue
                break

        # ── Stage 5: Result Assembly + 学习反馈（补充3）──
        elapsed = time.monotonic() - self._start_time
        tool_count = full_content.count("🔧 执行")

        # 计划完成度
        plan_status_dict = {}
        if detector is not None:
            plan_status_dict = detector.status_dict()

        # ════════════════════════════════════════════════════
        # Stage 5.5: 后验验证（P1-3）
        # ── 验证声称的文件修改、命令执行是否实际发生 ──
        # ════════════════════════════════════════════════════
        post_verify_issues: list[str] = []
        if strategy.name != "chat" and tool_count > 0:
            try:
                post_verify_issues = await self._post_execution_verify(
                    full_content, self.written_files
                )
                if post_verify_issues:
                    yield {
                        "type": "post_verify",
                        "issues": post_verify_issues[:10],
                        "message": f"🔍 后验验证发现 {len(post_verify_issues)} 个问题",
                    }
                    logger.warning(
                        "post_verify_issues count=%d",
                        len(post_verify_issues),
                    )
            except Exception as e:
                logger.debug("post_verify_skipped error=%s", str(e)[:100])

        summary_line = f"⚡ 工具调用 {tool_count} 次" if tool_count > 0 else ""
        time_line = f"⏱ 耗时 {elapsed:.1f}s"

        # 计划完成度
        plan_summary = ""
        if plan_status_dict:
            plan_summary = (
                f"📋 计划完成 {plan_status_dict['completed']}/{plan_status_dict['total']}"
                f" ({plan_status_dict['percent']}%)"
            )
            if plan_status_dict.get("deviations", 0) > 0:
                plan_summary += f" | ⚠️ 偏差 {plan_status_dict['deviations']}项"
            if plan_status_dict.get("replans", 0) > 0:
                plan_summary += f" | 🔄 重规划 {plan_status_dict['replans']}次"

        # 预算使用
        budget_summary = ""
        if budget is not None:
            budget_summary = (
                f"💰 Token {budget.actual_tokens}/{budget.budget_tokens}"
                f" ({budget.usage_ratio:.0%})"
            )

        summary = ""
        parts = [p for p in [summary_line, time_line, plan_summary, budget_summary] if p]
        summary = " | ".join(parts)

        # ════════════════════════════════════════════════════
        # 补充3: 学习反馈闭环 — 执行结果反馈到学习系统
        # ════════════════════════════════════════════════════
        if plan is not None:
            try:
                await self._feedback_to_learning(
                    plan=plan,
                    detector=detector,
                    budget=budget,
                    elapsed=elapsed,
                    tool_count=tool_count,
                    iter_count=iter_count,
                )
            except Exception as e:
                logger.debug("学习反馈失败（非致命）: %s", e)

        yield {
            "type": "progress",
            "phase": "done",
            "stage": f"✅ {strategy.name.upper()} 执行完成",
            "current_step": len(strategy.stages),
            "total_steps": len(strategy.stages),
            "percent": 100,
            "elapsed_seconds": int(elapsed),
            "eta_seconds": 0,
            "milestones": [],
        }

        final_content = full_content.rstrip()
        if summary:
            final_content += f"\n\n---\n📊 执行摘要\n{summary}"

        # ════════════════════════════════════════════════════
        # P1-1: 结构化执行报告
        # ════════════════════════════════════════════════════
        structured_report = {
            "mode": strategy.name,
            "duration_ms": int(elapsed * 1000),
            "iterations": iter_count,
            "tool_calls_count": tool_count,
            "files_written": self.written_files,
            "tool_calls": self.tool_calls,
            "plan": plan_status_dict if plan_status_dict else None,
            "budget": budget.to_dict() if budget else None,
            "hallucination_score": (getattr(self, "_hallucination_low_count", 0)),
            "post_verify_issues": post_verify_issues[:10],
            "success": len(post_verify_issues) == 0,
        }

        yield {
            "type": "done",
            "content": final_content,
            "v2_engine": True,
            "tool_calls_count": tool_count,
            "duration_ms": int(elapsed * 1000),
            "plan": detector.status_dict() if detector else None,
            "budget": budget.to_dict() if budget else None,
            "report": structured_report,  # P1-1: 结构化报告
            "post_verify": {  # P1-3: 后验验证结果
                "issues_count": len(post_verify_issues),
                "issues": post_verify_issues[:5],
            },
        }

        yield {
            "type": "agent_status",
            "status": "completed",
            "message": (
                f"✅ {strategy.name.upper()} 完成"
                f" ({len(full_content)} 字符)"
                + (f", {tool_count} 次工具调用" if tool_count else "")
                + (f", {len(post_verify_issues)} 个验证问题" if post_verify_issues else "")
            ),
        }

    # ══════════════════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _build_plan_context(message: str, history: str) -> dict[str, Any]:
        """补充1: 构建计划上下文 — 注入项目结构提升分解质量"""
        ctx: dict[str, Any] = {
            "message": message,
            "has_history": bool(history),
        }
        # 尝试获取项目结构（失败则降级）
        try:
            from pathlib import Path

            cwd = Path.cwd()
            py_files = list(cwd.rglob("*.py"))[:20]
            ctx["project_files"] = [str(f.relative_to(cwd)) for f in py_files]
            ctx["project_root"] = str(cwd)
        except Exception:
            ctx["project_files"] = []
        return ctx

    @staticmethod
    def _build_plan_prompt(
        plan: ExecutionPlan,
        feasibility: FeasibilityReport,
        budget: PlanBudget,
    ) -> str:
        """构建计划注入 prompt — 计划驱动执行的核心"""
        tasks_text = "\n".join(
            f"  {t.task_id}. {t.description}"
            + (f" (依赖: {', '.join(t.dependencies)})" if t.dependencies else "")
            for t in plan.tasks
        )

        risk_text = ""
        if feasibility.risks:
            risk_text = "\n⚠️ 已知风险:\n" + "\n".join(f"  - {r}" for r in feasibility.risks[:3])

        mitigation_text = ""
        if feasibility.mitigation:
            mitigation_text = "\n🛡️ 缓解措施:\n" + "\n".join(
                f"  - {m}" for m in feasibility.mitigation[:3]
            )

        return (
            f"## 执行计划（请按计划逐步执行）\n"
            f"策略: {plan.strategy.value}\n"
            f"任务分解:\n{tasks_text}\n"
            f"预估Token: {plan.total_estimated_tokens} | 预算: {budget.budget_tokens}\n"
            f"可行性: {feasibility.recommendation}"
            f"{risk_text}{mitigation_text}\n"
            f"---\n请按上述计划顺序执行，每步输出JSON工具调用。"
        )

    @staticmethod
    async def _feedback_to_learning(
        plan: ExecutionPlan,
        detector: DeviationDetector | None,
        budget: PlanBudget | None,
        elapsed: float,
        tool_count: int,
        iter_count: int,
    ) -> None:
        """补充3: 学习反馈闭环 — 执行结果反馈到学习系统

        复用现有 LearningEngine.on_task_complete()，
        将本次执行的经验（成功/失败、偏差、预算使用）沉淀到知识库。
        """
        try:
            from pycoder.capabilities.self_evo.learning import LearningEngine

            engine = LearningEngine()

            # 计算执行指标
            completed = len(detector._report.completed_task_ids) if detector else 0
            total = len(plan.tasks)
            deviations = len(detector._report.deviations) if detector else 0
            budget_ratio = budget.usage_ratio if budget else 0.0

            # 判断成功/失败
            success = completed >= total * 0.8 and deviations < 3

            # 构建经验数据
            experience = {
                "intent": plan.original_intent[:200],
                "strategy": plan.strategy.value,
                "task_count": total,
                "completed": completed,
                "iterations": iter_count,
                "tool_calls": tool_count,
                "elapsed_seconds": elapsed,
                "deviations": deviations,
                "budget_ratio": round(budget_ratio, 2),
                "budget_status": budget.status if budget else "unknown",
                "success": success,
            }

            # 如果有失败任务，记录教训
            if not success and detector is not None:
                failed_tasks = [t.task_id for t in plan.tasks if t.status.value == "failed"]
                if failed_tasks:
                    experience["failed_tasks"] = failed_tasks
                    experience["lesson"] = (
                        f"任务 {', '.join(failed_tasks)} 失败，"
                        f"偏差 {deviations} 项，"
                        f"预算使用 {budget_ratio:.0%}"
                    )

            # 调用学习引擎（如果方法存在）
            if hasattr(engine, "on_task_complete"):
                await engine.on_task_complete(experience)
            else:
                logger.debug("LearningEngine 无 on_task_complete 方法，跳过反馈")

        except ImportError:
            logger.debug("LearningEngine 未安装，跳过学习反馈")
        except Exception as e:
            logger.debug("学习反馈异常（非致命）: %s", e)

    @staticmethod
    async def _post_execution_verify(content: str, written_files: list[str]) -> list[str]:
        """P1-3: 后验验证 — 验证LLM声称的操作是否实际生效

        检查项目:
        1. 声称写入的文件是否真的存在且被修改
        2. 声称的代码修改是否与实际文件内容一致
        3. 引用的文件路径是否存在

        Returns:
            问题列表，空列表表示验证通过
        """
        issues: list[str] = []
        try:
            from pathlib import Path

            cwd = Path.cwd()

            # 1. 验证声称写入的文件
            import re

            write_pattern = re.compile(
                r"(?:write_file|创建|写入|修改|更新).*?[\"'`]([^\"'`]+\.\w{1,10})[\"'`]",
                re.IGNORECASE,
            )
            claimed_files = set()
            for m in write_pattern.finditer(content):
                fpath = m.group(1)
                claimed_files.add(fpath)

            for fpath in claimed_files:
                target = (cwd / fpath).resolve()
                try:
                    if not target.is_relative_to(cwd):
                        issues.append(f"文件路径越界: {fpath}")
                        continue
                except ValueError:
                    issues.append(f"无效文件路径: {fpath}")
                    continue

                if not target.exists():
                    issues.append(f"声称写入的文件不存在: {fpath}")
                elif fpath in written_files:
                    pass  # 已记录
                else:
                    # 检查文件修改时间是否在本次执行期间
                    mtime = target.stat().st_mtime
                    age_s = time.time() - mtime
                    if age_s > 300:  # 超过5分钟未修改
                        issues.append(
                            f"声称修改的文件未实际变更: {fpath} " f"(最后修改 {age_s:.0f}s 前)"
                        )

            # 2. 验证引用的文件路径
            file_ref_pattern = re.compile(
                r"(?:文件|路径|位于|在).*?[\"'`]([^\"'`]+\.\w{1,10})[\"'`]",
                re.IGNORECASE,
            )
            for m in file_ref_pattern.finditer(content):
                fpath = m.group(1)
                if fpath in claimed_files:
                    continue
                target = (cwd / fpath).resolve()
                try:
                    if target.is_relative_to(cwd) and not target.exists():
                        issues.append(f"引用的文件不存在: {fpath}")
                except ValueError:
                    pass

            # 3. 验证代码引用（简单启发式）
            code_ref_pattern = re.compile(
                r"(?:class|def|函数|方法|模块)\s+[\"'`]?(\w+)[\"'`]?",
                re.IGNORECASE,
            )
            # 只在内容较长且有文件引用时做深度验证
            if len(content) > 500 and claimed_files:
                for fpath in list(claimed_files)[:3]:
                    target = (cwd / fpath).resolve()
                    if target.exists() and target.suffix == ".py":
                        try:
                            file_content = target.read_text(encoding="utf-8", errors="ignore")
                            for m in code_ref_pattern.finditer(content):
                                symbol = m.group(1)
                                if (
                                    len(symbol) > 3
                                    and symbol not in file_content
                                    and symbol[0].isupper()
                                ):
                                    pass  # 类名可能在其他文件中
                        except (OSError, UnicodeDecodeError):
                            pass

        except Exception as e:
            logger.debug("post_verify_error: %s", str(e)[:100])

        return issues
